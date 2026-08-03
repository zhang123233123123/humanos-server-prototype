#!/usr/bin/env python3
"""HumanOS MVP backend.

Standard-library HTTP API with SQLite persistence and a lightweight local
embedding index. This is intentionally dependency-free so the prototype can be
run on a clean machine, then later replaced by FastAPI + pgvector/Chroma.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.environ.get("HUMANOS_DB_PATH", "").strip()) if os.environ.get("HUMANOS_DB_PATH", "").strip() else DATA_DIR / "humanos.db"
VECTOR_DIMS = 64
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"


def load_local_env() -> None:
    """Load backend/.env without adding a dotenv dependency."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())
    return words or ["empty"]


def embed_text(text: str) -> list[float]:
    vec = [0.0] * VECTOR_DIMS
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "big") % VECTOR_DIMS
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def as_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def from_json(value: str | None, fallback: object) -> object:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def infer_duration_minutes(text: str) -> int | None:
    chinese_amounts = {
        "半": 0.5,
        "一": 1,
        "一个": 1,
        "两": 2,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
    }
    chinese_match = re.search(r"(半|一个|一|两|二|三|四|五)\s*(小时|分钟)", text)
    if chinese_match:
        amount = chinese_amounts[chinese_match.group(1)]
        return int(amount * 60) if chinese_match.group(2) == "小时" else int(amount)
    match = re.search(r"(\d+)\s*(个)?\s*(分钟|min|小时|h)", text, re.I)
    if not match:
        return None
    amount = int(match.group(1))
    return amount * 60 if match.group(3).lower() in {"小时", "h"} else amount


def chat_completion(messages: list[dict], temperature: float = 0.2) -> object | None:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None

    payload = {
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    request = Request(
        DEEPSEEK_API_URL,
        data=as_json(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as exc:
        print(f"DeepSeek unavailable, fallback to local rules: {type(exc).__name__}: {exc}")
        return None


def safe_duration_minutes(value: object, fallback: int = 60) -> int:
    if isinstance(value, (int, float)):
        return max(int(value), 15)
    parsed = infer_duration_minutes(str(value or ""))
    return max(parsed or fallback, 15)


def parse_clock_hour(value: str, inherited_period: str = "") -> float | None:
    text = re.sub(r"\s+", "", str(value or ""))
    period_match = re.search(r"(早上|上午|中午|下午|晚上)", text)
    period = period_match.group(1) if period_match else inherited_period
    colon_match = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if colon_match:
        hour = int(colon_match.group(1))
        minute = int(colon_match.group(2))
    else:
        hour_match = re.search(r"(\d{1,2})(点|时)", text)
        if not hour_match:
            return None
        hour = int(hour_match.group(1))
        minute = 0
    if period in {"下午", "晚上"} and hour < 12:
        hour += 12
    if period == "中午" and hour < 11:
        hour += 12
    return hour + minute / 60


def format_clock_hour(hour: float) -> str:
    whole_hour = int(hour)
    minute = int(round((hour - whole_hour) * 60))
    if minute == 60:
        whole_hour += 1
        minute = 0
    return f"{whole_hour:02d}:{minute:02d}"


def parse_clock_range(value: str, inherited_period: str = "") -> tuple[float, float] | None:
    clock = r"((?:早上|上午|中午|下午|晚上)?\s*\d{1,2}\s*(?:[:：]\s*\d{2}|点|时))"
    match = re.search(rf"{clock}\s*(?:-|–|—|~|至|到)\s*{clock}", str(value or ""))
    if not match:
        return None
    start_text = match.group(1)
    end_text = match.group(2)
    period_match = re.search(r"(早上|上午|中午|下午|晚上)", start_text)
    inherited = period_match.group(1) if period_match else inherited_period
    start = parse_clock_hour(start_text, inherited)
    end = parse_clock_hour(end_text, inherited)
    if start is None or end is None:
        return None

    explicit_period = re.search(r"(早上|上午|中午|下午|晚上)", f"{start_text}{end_text}")
    if not explicit_period and start < 8 and end <= 8:
        start += 12
        end += 12
    elif end <= start and end < 12:
        end += 12
    return start, end


def today_label() -> str:
    return time.strftime("%Y-%m-%d")


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                  user_id TEXT PRIMARY KEY,
                  role TEXT NOT NULL,
                  deep_work_window TEXT NOT NULL,
                  low_energy_window TEXT NOT NULL,
                  control_preference TEXT NOT NULL,
                  blocker_patterns TEXT NOT NULL,
                  task_preferences TEXT NOT NULL,
                  weekly_context_json TEXT NOT NULL DEFAULT '{}',
                  learned_patterns_json TEXT NOT NULL DEFAULT '[]',
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                  id TEXT PRIMARY KEY,
                  email TEXT UNIQUE NOT NULL,
                  name TEXT NOT NULL,
                  password_hash TEXT NOT NULL,
                  salt TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  last_login_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  title TEXT NOT NULL,
                  type TEXT NOT NULL,
                  due TEXT,
                  duration INTEGER NOT NULL,
                  priority TEXT NOT NULL,
                  status TEXT NOT NULL,
                  context TEXT NOT NULL,
                  context_window_json TEXT NOT NULL DEFAULT '{}',
                  cognitive_load TEXT NOT NULL,
                  ambiguity TEXT NOT NULL,
                  switch_cost TEXT NOT NULL,
                  reentry_cost TEXT NOT NULL,
                  slot_json TEXT,
                  checkpoints_json TEXT NOT NULL,
                  demand_json TEXT NOT NULL DEFAULT '{}',
                  execution_json TEXT NOT NULL DEFAULT '{}',
                  resource_modality_json TEXT NOT NULL DEFAULT '[]',
                  parallelizable INTEGER NOT NULL DEFAULT 0,
                  expected_difficulty INTEGER,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runtime_states (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  focus INTEGER NOT NULL,
                  energy INTEGER NOT NULL,
                  stress INTEGER NOT NULL,
                  mood INTEGER,
                  attention_residue TEXT,
                  emotion TEXT,
                  readiness TEXT,
                  daily_note TEXT,
                  created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS context_dumps (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  task_id TEXT NOT NULL,
                  progress TEXT NOT NULL,
                  open_questions TEXT NOT NULL,
                  next_action TEXT NOT NULL,
                  stop_reason TEXT NOT NULL,
                  materials TEXT NOT NULL,
                  created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memories (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  source_type TEXT NOT NULL,
                  source_id TEXT NOT NULL,
                  task_id TEXT,
                  text TEXT NOT NULL,
                  metadata_json TEXT NOT NULL,
                  embedding_json TEXT NOT NULL,
                  created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  type TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_turns (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  user_text TEXT NOT NULL,
                  assistant_reply TEXT NOT NULL,
                  intent TEXT NOT NULL,
                  features_json TEXT NOT NULL,
                  task_ids_json TEXT NOT NULL,
                  created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS execution_feedback (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  task_id TEXT NOT NULL,
                  trigger TEXT NOT NULL,
                  task_evaluation_json TEXT NOT NULL,
                  state_evaluation_json TEXT NOT NULL,
                  recommendation_evaluation_json TEXT NOT NULL,
                  created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS state_transitions (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  task_id TEXT,
                  before_state_json TEXT NOT NULL,
                  action_json TEXT NOT NULL,
                  predicted_state_json TEXT NOT NULL,
                  actual_state_json TEXT NOT NULL,
                  outcome_json TEXT NOT NULL,
                  created_at INTEGER NOT NULL
                );
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "context_window_json" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN context_window_json TEXT NOT NULL DEFAULT '{}'")
            task_migrations = {
                "demand_json": "TEXT NOT NULL DEFAULT '{}'",
                "execution_json": "TEXT NOT NULL DEFAULT '{}'",
                "resource_modality_json": "TEXT NOT NULL DEFAULT '[]'",
                "parallelizable": "INTEGER NOT NULL DEFAULT 0",
                "expected_difficulty": "INTEGER",
            }
            for name, definition in task_migrations.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {definition}")
            profile_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(profiles)").fetchall()
            }
            profile_migrations = {
                "weekly_context_json": "TEXT NOT NULL DEFAULT '{}'",
                "learned_patterns_json": "TEXT NOT NULL DEFAULT '[]'",
            }
            for name, definition in profile_migrations.items():
                if name not in profile_columns:
                    conn.execute(f"ALTER TABLE profiles ADD COLUMN {name} {definition}")
            runtime_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(runtime_states)").fetchall()
            }
            runtime_migrations = {"emotion": "TEXT", "readiness": "TEXT", "daily_note": "TEXT"}
            for name, definition in runtime_migrations.items():
                if name not in runtime_columns:
                    conn.execute(f"ALTER TABLE runtime_states ADD COLUMN {name} {definition}")

    def password_hash(self, password: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()

    def public_user(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "created_at": row["created_at"],
            "last_login_at": row["last_login_at"],
        }

    def create_user(self, email: str, password: str, name: str = "") -> dict:
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValueError("valid email is required")
        if len(password) < 6:
            raise ValueError("password must be at least 6 characters")
        user_id = new_id("user")
        salt = uuid.uuid4().hex
        timestamp = now_ms()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (id, email, name, password_hash, salt, created_at, last_login_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    email,
                    name.strip() or email.split("@")[0],
                    self.password_hash(password, salt),
                    salt,
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        profile = self.ensure_profile(user_id)
        self.log_event(user_id, "user_registered", {"email": email})
        return {"user": self.public_user(row), "profile": profile}

    def authenticate_user(self, email: str, password: str) -> dict:
        email = email.strip().lower()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if not row or self.password_hash(password, row["salt"]) != row["password_hash"]:
                raise PermissionError("invalid email or password")
            conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now_ms(), row["id"]))
            row = conn.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
        profile = self.ensure_profile(row["id"])
        self.log_event(row["id"], "user_logged_in", {"email": email})
        return {"user": self.public_user(row), "profile": profile}

    def ensure_profile(self, user_id: str) -> dict:
        existing = self.get_profile(user_id)
        if existing:
            return existing
        profile = {
            "user_id": user_id,
            "role": "硕士生",
            "deep_work_window": "09:00-11:30",
            "low_energy_window": "14:00-15:30",
            "control_preference": "ai_proposed_user_editable",
            "blocker_patterns": ["task_ambiguity", "fatigue", "context_loss"],
            "weekly_context": {
                "week_of": today_label(),
                "weekly_available_windows": "",
                "fixed_events": [],
                "weekly_goal": "",
                "current_tasks": "",
                "temporary_constraints": [],
                "other_commitments": [],
                "task_deadlines": [],
                "weekly_note": "",
                "keep_buffer": True,
                "buffer_preference": "保留可调整时间与无任务时段",
            },
            "learned_patterns": [],
            "task_preferences": {
                "writing": "morning_deep_work",
                "admin": "low_energy_slots",
                "reading": "moderate_energy",
                "onboarding_completed": False,
                "planning_gap": "",
                "common_blockers": [],
                "preferred_session_minutes": 45,
                "rest_between_tasks_minutes": 10,
                "day_rhythm": {
                    "morning_energy": 6,
                    "afternoon_energy": 4,
                    "evening_energy": 5,
                },
                "learning_mode": "reading_writing",
                "current_courses": "",
                "near_deadlines": "",
                "short_term_goal": "",
                "support_need": "clarify_next_action",
            },
        }
        self.upsert_profile(profile)
        self.add_memory(
            user_id=user_id,
            source_type="profile",
            source_id=user_id,
            task_id=None,
            text=(
                f"User is a {profile['role']}. Deep work window: "
                f"{profile['deep_work_window']}. Low energy window: "
                f"{profile['low_energy_window']}. Control preference: "
                f"{profile['control_preference']}."
            ),
            metadata={"kind": "initial_profile"},
        )
        return self.get_profile(user_id) or profile

    def get_profile(self, user_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return None
        return {
            "user_id": row["user_id"],
            "role": row["role"],
            "deep_work_window": row["deep_work_window"],
            "low_energy_window": row["low_energy_window"],
            "control_preference": row["control_preference"],
            "blocker_patterns": from_json(row["blocker_patterns"], []),
            "task_preferences": from_json(row["task_preferences"], {}),
            "weekly_context": from_json(row["weekly_context_json"], {}),
            "learned_patterns": from_json(row["learned_patterns_json"], []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def upsert_profile(self, profile: dict) -> dict:
        user_id = profile.get("user_id", "demo")
        current = self.get_profile(user_id)
        timestamp = now_ms()
        data = {
            "role": profile.get("role", current.get("role") if current else "研究型学生"),
            "deep_work_window": profile.get(
                "deep_work_window", current.get("deep_work_window") if current else "09:00-11:30"
            ),
            "low_energy_window": profile.get(
                "low_energy_window", current.get("low_energy_window") if current else "14:00-15:30"
            ),
            "control_preference": profile.get(
                "control_preference",
                current.get("control_preference") if current else "ai_proposed_user_editable",
            ),
            "blocker_patterns": profile.get(
                "blocker_patterns", current.get("blocker_patterns") if current else []
            ),
            "task_preferences": profile.get(
                "task_preferences", current.get("task_preferences") if current else {}
            ),
            "weekly_context": profile.get(
                "weekly_context", current.get("weekly_context") if current else {}
            ),
            "learned_patterns": profile.get(
                "learned_patterns", current.get("learned_patterns") if current else []
            ),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO profiles (
                  user_id, role, deep_work_window, low_energy_window,
                  control_preference, blocker_patterns, task_preferences,
                  weekly_context_json, learned_patterns_json,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                  role=excluded.role,
                  deep_work_window=excluded.deep_work_window,
                  low_energy_window=excluded.low_energy_window,
                  control_preference=excluded.control_preference,
                  blocker_patterns=excluded.blocker_patterns,
                  task_preferences=excluded.task_preferences,
                  weekly_context_json=excluded.weekly_context_json,
                  learned_patterns_json=excluded.learned_patterns_json,
                  updated_at=excluded.updated_at
                """,
                (
                    user_id,
                    data["role"],
                    data["deep_work_window"],
                    data["low_energy_window"],
                    data["control_preference"],
                    as_json(data["blocker_patterns"]),
                    as_json(data["task_preferences"]),
                    as_json(data["weekly_context"]),
                    as_json(data["learned_patterns"]),
                    current["created_at"] if current else timestamp,
                    timestamp,
                ),
            )
        self.log_event(user_id, "profile_upserted", data)
        profile_summary = (
            f"Profile update. Role: {data['role']}. Deep work: {data['deep_work_window']}. "
            f"Low energy: {data['low_energy_window']}. Control: {data['control_preference']}. "
            f"Blockers: {', '.join(data['blocker_patterns'])}. "
            f"Preferences: {as_json(data['task_preferences'])}."
        )
        self.add_memory(
            user_id=user_id,
            source_type="profile",
            source_id=user_id,
            task_id=None,
            text=profile_summary,
            metadata={"kind": "profile_update"},
        )
        return self.ensure_profile(user_id)

    def infer_task_type(self, title: str, context: str = "") -> str:
        text = f"{title} {context}".lower()
        if any(word in text for word in ["write", "写", "proposal", "related", "论文"]):
            return "writing"
        if any(word in text for word in ["read", "看", "文献", "paper"]):
            return "reading"
        if any(word in text for word in ["email", "邮件", "admin", "会议纪要"]):
            return "admin"
        if any(word in text for word in ["code", "代码", "prototype", "原型"]):
            return "coding"
        return "general"

    def infer_task_demand(self, payload: dict, task_type: str) -> dict:
        """Estimate task demand as an inspectable hypothesis, not a measurement."""
        expected = payload.get("expected_difficulty")
        expected = int(expected) if str(expected or "").isdigit() else None
        features = payload.get("task_features") or {}
        evidence = []
        score = 1
        if task_type in {"writing", "coding", "research"}:
            score += 2
            evidence.append(f"task_type={task_type}")
        elif task_type == "reading":
            score += 1
            evidence.append("reading requires sustained attention")
        if expected is not None:
            score += 2 if expected >= 6 else 1 if expected >= 4 else 0
            evidence.append(f"user expected_difficulty={expected}/7")
        for key in ("uncertainty", "error_cost", "precision_requirement", "external_dependency", "substeps"):
            value = features.get(key)
            if value in {"high", True} or (isinstance(value, int) and value >= 4):
                score += 1
                evidence.append(f"{key}={value}")
        level = "high" if score >= 4 else "medium" if score >= 2 else "low"
        confidence = "medium" if expected is None else "high"
        return {
            "estimated_cognitive_load": level,
            "expected_difficulty": expected,
            "task_features": features,
            "evidence": evidence or ["limited task description"],
            "confidence_level": confidence,
            "source": "user_self_report" if expected is not None else "ai_inference",
            "user_confirmed": expected is not None,
        }

    def create_task(self, user_id: str, payload: dict) -> dict:
        task_id = payload.get("id") or new_id("task")
        title = payload.get("title", "未命名任务")
        context = payload.get("context", "")
        task_type = payload.get("type") or self.infer_task_type(title, context)
        priority = payload.get("priority", "中")
        duration = infer_duration_minutes(f"{title} {context}") or int(payload.get("duration", 60))
        status = payload.get("status", "queued")
        demand = payload.get("task_demand") or self.infer_task_demand(payload, task_type)
        cognitive_load = payload.get("cognitive_load") or demand["estimated_cognitive_load"]
        ambiguity = payload.get("ambiguity", "medium" if task_type in {"writing", "research"} else "low")
        switch_cost = payload.get("switch_cost", "high" if cognitive_load == "high" else "medium")
        reentry_cost = payload.get("reentry_cost", switch_cost)
        timestamp = now_ms()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                  id, user_id, title, type, due, duration, priority, status,
                  context, context_window_json, cognitive_load, ambiguity, switch_cost, reentry_cost,
                  slot_json, checkpoints_json, demand_json, execution_json,
                  resource_modality_json, parallelizable, expected_difficulty,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    user_id,
                    title,
                    task_type,
                    payload.get("due"),
                    duration,
                    priority,
                    status,
                    context,
                    as_json(payload.get("contextWindow") or payload.get("context_window") or {}),
                    cognitive_load,
                    ambiguity,
                    switch_cost,
                    reentry_cost,
                    as_json(payload.get("slot")),
                    as_json(payload.get("checkpoints", [])),
                    as_json(demand),
                    as_json(payload.get("execution") or {
                        "original_estimate_minutes": duration,
                        "accumulated_actual_minutes": 0,
                        "remaining_duration_minutes": duration,
                        "progress_percent": 0,
                        "sessions": [],
                    }),
                    as_json(payload.get("resource_modality", [])),
                    int(bool(payload.get("parallelizable", False))),
                    demand.get("expected_difficulty"),
                    timestamp,
                    timestamp,
                ),
            )
        self.add_memory(
            user_id=user_id,
            source_type="task",
            source_id=task_id,
            task_id=task_id,
            text=f"Task: {title}. Type: {task_type}. Context: {context}. Priority: {priority}.",
            metadata={"task_type": task_type, "priority": priority, "status": status},
        )
        self.log_event(user_id, "task_created", {"task_id": task_id, "title": title})
        return self.get_task(task_id) or {}

    def parse_tasks_from_text(self, user_id: str, text: str, chat_context: dict | None = None) -> list[dict]:
        clean = text.strip()
        if not clean:
            raise ValueError("task text is required")
        explicit_schedule_tasks = self.parse_explicit_schedule_lines(user_id, clean)
        if explicit_schedule_tasks:
            return explicit_schedule_tasks
        if self.looks_like_compact_multi_task_list(clean):
            return self.local_parse_tasks_from_text(user_id, clean)
        llm_result = chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 HumanOS 的任务解析 agent。只输出 JSON。"
                        "从用户中文输入中提取所有学习任务。"
                        "如果一句话包含多个时间点或多个动作，必须拆成多个任务。不要输出解释。"
                    ),
                },
                {
                    "role": "user",
                    "content": as_json(
                        {
                            "text": clean,
                            "today": today_label(),
                            "conversation_context": chat_context or {},
                            "schema": {
                                "tasks": [
                                    {
                                        "title": "任务标题，不要包含其他任务",
                                        "due": "目标时间；如果用户说今天/明天/周几，需要保留相对日期和具体时间",
                                        "duration": "预计分钟数，数字；没有说时默认 60",
                                        "priority": "高/中/低",
                                        "context": "只保留该任务相关背景",
                                    }
                                ]
                            },
                        }
                    ),
                },
            ]
        )
        if llm_result:
            if isinstance(llm_result, list):
                raw_tasks = llm_result
            elif isinstance(llm_result, dict):
                raw_tasks = llm_result.get("tasks") if isinstance(llm_result.get("tasks"), list) else [llm_result]
            else:
                raw_tasks = []
            tasks = []
            for item in raw_tasks[:8]:
                if not isinstance(item, dict):
                    continue
                payload = {
                    "title": item.get("title") or clean[:60],
                    "due": item.get("due") or "未设置",
                    "duration": safe_duration_minutes(item.get("duration"), 60),
                    "priority": item.get("priority") if item.get("priority") in {"高", "中", "低"} else "中",
                    "context": item.get("context") or clean,
                }
                payload["parser"] = "deepseek"
                tasks.append(self.create_task(user_id, payload))
            if tasks:
                return tasks

        return self.local_parse_tasks_from_text(user_id, clean)

    def looks_like_compact_multi_task_list(self, text: str) -> bool:
        parts = [
            part.strip(" ，,。；;、")
            for part in re.split(r"(?:，|,|。|；|;|、|然后|再|接着|最后)", text)
            if part.strip(" ，,。；;、")
        ]
        if len(parts) < 2:
            return False
        action_count = sum(
            1
            for part in parts
            if re.search(r"(复习|学习|写|读|阅读|总结|整理|完善|完成|处理|准备|提交|看|做|备战|开会|会议|讨论)", part)
        )
        followup_markers = re.search(r"第[一二三四五六七八九\d]+|这个|那个|都是|每个", text)
        return action_count >= 2 and not followup_markers

    def parse_explicit_schedule_lines(self, user_id: str, text: str) -> list[dict]:
        clock = r"(?:(?:早上|上午|中午|下午|晚上)\s*)?\d{1,2}\s*(?:[:：]\s*\d{2}|点|时)"
        range_pattern = re.compile(
            rf"^\s*(?:[-*•]|\d+[.、)]?)?\s*(?P<title>.+?)\s*[：:]\s*"
            rf"(?P<start>{clock})\s*(?:-|–|—|~|至|到)\s*(?P<end>{clock})\s*$"
        )
        day_pattern = re.compile(r"(今天|今晚|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天])")
        tasks = []
        for line in re.split(r"[\n\r]+", text):
            clean_line = line.strip(" \t，,。；;")
            if not clean_line:
                continue
            match = range_pattern.match(clean_line)
            if not match:
                continue
            title = re.sub(r"^\s*(?:[-*•]|\d+[.、)]?)\s*", "", match.group("title")).strip(" ，,。；;：:")
            if not title:
                continue
            day_match = day_pattern.search(title) or day_pattern.search(text)
            day = day_match.group(1) if day_match else "今天"
            title = day_pattern.sub("", title).strip(" ，,。；;：:") or match.group("title").strip()
            start_text = match.group("start")
            end_text = match.group("end")
            period_match = re.search(r"(早上|上午|中午|下午|晚上)", start_text)
            inherited_period = period_match.group(1) if period_match else ""
            start = parse_clock_hour(start_text)
            end = parse_clock_hour(end_text, inherited_period)
            if start is None or end is None:
                continue
            if end <= start and end < 12:
                end += 12
            duration = max(int(round((end - start) * 60)), 15)
            tasks.append(
                self.create_task(
                    user_id,
                    {
                        "title": title[:42],
                        "due": f"{day} {format_clock_hour(start)}",
                        "duration": duration,
                        "priority": "高" if any(word in title for word in ["重要", "紧急", "ddl", "deadline"]) else "中",
                        "context": clean_line,
                    },
                )
            )
        for task in tasks:
            task["parser"] = "explicit_schedule_lines"
        return tasks

    def local_parse_tasks_from_text(self, user_id: str, text: str) -> list[dict]:
        clean = text.strip()
        time_word = r"(((早上|上午|中午|下午|晚上)\s*)?\d{1,2}\s*(点|时)|\d{1,2}[:：]\d{2})"
        relative_day = r"(今天|今晚|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天])"
        connector_segments = [
            part.strip(" ，,。；;、")
            for part in re.split(r"(?:然后|最后|再|接着|之后|，|,|。|；|;)", clean)
            if part.strip(" ，,。；;、")
        ]
        segment_pattern = re.compile(rf"((?:{relative_day})?\s*(?:{time_word})?[^，。；;、]*(?:会议|开会|学习|复习|写|读|整理|完成|处理|准备|提交|看|做)[^，。；;]*)")
        segments = [match.group(1).strip(" ，,。；;、") for match in segment_pattern.finditer(clean)]
        if len(connector_segments) > len(segments):
            segments = connector_segments
        if not segments:
            segments = [clean]

        tasks = []
        last_day = ""
        last_period = ""
        for segment in segments[:8]:
            day_match = re.search(relative_day, segment)
            if day_match:
                last_day = day_match.group(0)
            period_match = re.search(r"(早上|上午|中午|下午|晚上)", segment)
            if period_match:
                last_period = period_match.group(0)
            due_match = re.search(rf"({relative_day}\s*{time_word}|{time_word}|{relative_day})", segment)
            due = due_match.group(0) if due_match else "未设置"
            separate_time_match = re.search(time_word, segment)
            if due != "未设置" and day_match and separate_time_match and not re.search(time_word, due):
                due = f"{day_match.group(0)}{separate_time_match.group(0)}"
            if due != "未设置" and last_day and not re.search(relative_day, due):
                due = f"{last_day}{due}"
            if due != "未设置" and last_period and re.search(r"\d{1,2}\s*(点|时)", due) and not re.search(r"(早上|上午|中午|下午|晚上)", due):
                due = re.sub(r"(\d{1,2}\s*(点|时))", rf"{last_period}\1", due, count=1)
            if due == "未设置" and last_day and period_match:
                due = f"{last_day}{period_match.group(0)}"
            duration = infer_duration_minutes(segment) or 60
            priority = "高" if (
                any(word in segment for word in ["紧急", "重要", "ddl", "deadline", "优先级高", "高优先级"])
                or re.search(r"优先级\s*[:：]?\s*高", segment)
            ) else "中"
            title_text = re.sub(rf"({relative_day}|{time_word}|然后|最后|先|需要|进行|我们的|我们|这个|的)", "", segment)
            title_text = re.sub(r"\s+", "", title_text).strip("，,。；;、") or segment
            task = self.create_task(
                user_id,
                {
                    "title": title_text[:42],
                    "due": due,
                    "duration": duration,
                    "priority": priority,
                    "context": segment,
                },
            )
            task["parser"] = "local_fallback"
            tasks.append(task)
        return tasks

    def parse_task_from_text(self, user_id: str, text: str) -> dict:
        tasks = self.parse_tasks_from_text(user_id, text)
        if not tasks:
            raise ValueError("no task parsed")
        return tasks[0]

    def extract_behavior_features(self, user_id: str, text: str, chat_context: dict | None = None) -> dict:
        clean = text.strip()
        llm_result = chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 HumanOS 的行为语言特征提取 agent。只输出 JSON。"
                        "从学生输入中提取任务管理相关行为特征，不要输出诊断结论。"
                    ),
                },
                {
                    "role": "user",
                    "content": as_json(
                        {
                            "text": clean,
                            "conversation_context": chat_context or {},
                            "schema": {
                                "intent": "add_task/reschedule/progress_update/interruption/report_state/other",
                                "planning_behavior": ["会计划", "反复改计划", "开始困难", "切换困难"],
                                "blockers": ["任务不清楚", "疲劳", "焦虑", "外部打断", "上下文丢失"],
                                "control_language": "用户表达控制感/失控感的短语",
                                "affect": "neutral/stressed/anxious/tired/confident",
                                "needs_follow_up": "true/false",
                            },
                        }
                    ),
                },
            ]
        )
        if not isinstance(llm_result, dict):
            blockers = []
            if any(word in clean for word in ["不知道", "不清楚", "模糊", "从哪"]):
                blockers.append("任务不清楚")
            if any(word in clean for word in ["累", "困", "没精力"]):
                blockers.append("疲劳")
            if any(word in clean for word in ["焦虑", "压力", "慌"]):
                blockers.append("焦虑")
            if any(word in clean for word in ["打断", "开会", "消息", "临时"]):
                blockers.append("外部打断")
            if any(word in clean for word in ["回不来", "忘了", "上下文"]):
                blockers.append("上下文丢失")
            if any(word in clean for word in ["进展", "完成", "写完", "做完"]):
                intent = "progress_update"
            elif any(word in clean for word in ["安排", "排", "计划", "日历"]):
                intent = "add_task"
            elif any(word in clean for word in ["中断", "暂停", "切换"]):
                intent = "interruption"
            else:
                intent = "other"
            llm_result = {
                "intent": intent,
                "planning_behavior": [],
                "blockers": blockers,
                "control_language": "",
                "affect": "stressed" if "压力" in clean else "neutral",
                "needs_follow_up": bool(blockers),
            }
        self.add_memory(
            user_id=user_id,
            source_type="behavior_language",
            source_id=new_id("chat"),
            task_id=None,
            text=f"User said: {clean}. Features: {as_json(llm_result)}",
            metadata={"kind": "behavior_language_features", "features": llm_result},
        )
        self.log_event(user_id, "behavior_language_features", {"text": clean, "features": llm_result})
        return llm_result

    def chat_turn(self, user_id: str, payload: dict) -> dict:
        text = payload.get("text", "").strip()
        if not text:
            raise ValueError("text is required")
        chat_context = self.build_chat_context(user_id, text)
        features = self.extract_behavior_features(user_id, text, chat_context)
        intent = features.get("intent", "other")
        response = {
            "intent": intent,
            "features": features,
            "reply": "我已经记录了这条信息，会用它更新后续安排判断。",
            "tasks": [],
            "context": {
                "recent_task_count": len(chat_context.get("recent_tasks", [])),
                "memory_count": len(chat_context.get("retrieved_memories", [])),
                "embedding_model": "humanos-local-hash-embedding-v1",
            },
        }
        followup_tasks = self.parse_time_followup_for_recent_tasks(user_id, text, chat_context)
        if followup_tasks:
            response["tasks"] = followup_tasks
            response["reply"] = f"我已把时间补充到上一轮 {len(followup_tasks)} 个任务上，并在右侧生成待确认安排。"
            intent = "reschedule"
            response["intent"] = intent
        should_parse_tasks = any(
            word in text
            for word in [
                "任务",
                "写",
                "读",
                "阅读",
                "整理",
                "完成",
                "复习",
                "学习",
                "开会",
                "会议",
                "取",
                "拿",
                "办",
                "买",
                "发",
                "看",
                "做",
                "分钟",
                "小时",
                "点",
                "时",
                "明天",
                "今天",
                "周",
            ]
        ) and (intent in {"add_task", "reschedule", "other"} or self.looks_like_compact_multi_task_list(text))
        if should_parse_tasks and not response["tasks"]:
            intent = "add_task" if intent == "progress_update" else intent
            response["intent"] = intent
            response["tasks"] = self.parse_tasks_from_text(user_id, text, chat_context)
            response["reply"] = (
                f"我先把它解析成 {len(response['tasks'])} 个任务，并在右侧生成待确认安排。"
                if len(response["tasks"]) > 1
                else "我先把它解析成一个任务，并在右侧生成待确认安排。"
            )
        elif intent == "progress_update":
            response["reply"] = "收到进展。你可以继续补充下一步，或让我根据当前状态重新安排。"
        elif intent == "interruption":
            response["reply"] = "收到。这是暂停触发信号，不等同于系统已经判断你的状态下降。请用最小中断记录补充原因、进展和回来后的第一步。"
            response["event_trigger"] = "open_pause_checkin"
        self.save_chat_turn(
            user_id=user_id,
            user_text=text,
            assistant_reply=response["reply"],
            intent=intent,
            features=features,
            task_ids=[task["id"] for task in response["tasks"]],
        )
        return response

    def save_chat_turn(
        self,
        user_id: str,
        user_text: str,
        assistant_reply: str,
        intent: str,
        features: dict,
        task_ids: list[str],
    ) -> dict:
        turn = {
            "id": new_id("turn"),
            "user_id": user_id,
            "user_text": user_text,
            "assistant_reply": assistant_reply,
            "intent": intent,
            "features": features,
            "task_ids": task_ids,
            "created_at": now_ms(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_turns (
                  id, user_id, user_text, assistant_reply, intent,
                  features_json, task_ids_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn["id"],
                    user_id,
                    user_text,
                    assistant_reply,
                    intent,
                    as_json(features),
                    as_json(task_ids),
                    turn["created_at"],
                ),
            )
        self.log_event(user_id, "chat_turn_saved", {"turn_id": turn["id"], "intent": intent, "task_ids": task_ids})
        return turn

    def list_chat_turns(self, user_id: str, limit: int = 20) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_turns WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "user_text": row["user_text"],
                "assistant_reply": row["assistant_reply"],
                "intent": row["intent"],
                "features": from_json(row["features_json"], {}),
                "task_ids": from_json(row["task_ids_json"], []),
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]

    def latest_task_turn_tasks(self, user_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT task_ids_json FROM chat_turns WHERE user_id=? ORDER BY created_at DESC LIMIT 6",
                (user_id,),
            ).fetchall()
        for row in rows:
            task_ids = from_json(row["task_ids_json"], [])
            tasks = [self.get_task(task_id) for task_id in task_ids if task_id]
            tasks = [task for task in tasks if task and task.get("status") not in {"completed", "terminated"}]
            if tasks:
                return tasks
        return []

    def parse_time_followup_for_recent_tasks(self, user_id: str, text: str, chat_context: dict | None = None) -> list[dict]:
        recent_tasks = (chat_context or {}).get("recent_tasks") or self.latest_task_turn_tasks(user_id)
        if not recent_tasks:
            return []
        has_time = re.search(r"\d{1,2}\s*(点|时)|\d{1,2}[:：]\d{2}", text)
        if not has_time:
            return []
        has_reference_marker = re.search(r"(第[一二三四五六七八九\d]+|这个|那个|开始|在|都是|每个)", text)
        has_time_range = parse_clock_range(text) is not None
        if not has_reference_marker and not has_time_range and len(recent_tasks) != 1:
            return []

        day_match = re.search(r"(今天|今晚|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天])", text)
        day = day_match.group(1) if day_match else "今天"
        default_duration = infer_duration_minutes(text) or None
        assignments: list[tuple[int, str, float, int]] = []
        used_indexes: set[int] = set()
        ordinal_map = {
            "一": 0,
            "1": 0,
            "二": 1,
            "两": 1,
            "2": 1,
            "三": 2,
            "3": 2,
            "四": 3,
            "4": 3,
            "五": 4,
            "5": 4,
        }

        parts = [
            part.strip(" ，,。；;、")
            for part in re.split(r"(?:，|,|。|；|;|然后|再|接着|最后)", text)
            if part.strip(" ，,。；;、")
        ]
        last_period = ""
        for part in parts:
            period_match = re.search(r"(早上|上午|中午|下午|晚上)", part)
            if period_match:
                last_period = period_match.group(1)
            clock_range = parse_clock_range(part, last_period)
            if clock_range:
                start, end = clock_range
                duration_from_range = max(int(round((end - start) * 60)), 15)
            else:
                start = parse_clock_hour(part, last_period)
                duration_from_range = None
            if start is None:
                continue
            target_index = None
            ordinal = re.search(r"第\s*([一二两三四五\d])\s*个?", part)
            if ordinal:
                target_index = ordinal_map.get(ordinal.group(1))
            if target_index is None:
                for index, task in enumerate(recent_tasks):
                    if index in used_indexes:
                        continue
                    title = str(task.get("title", ""))
                    title_tokens = [token for token in re.findall(r"[A-Za-z0-9]+", title) if len(token) >= 2]
                    chinese_title = "".join(re.findall(r"[\u4e00-\u9fff]", title))
                    title_tokens.extend(
                        chinese_title[offset : offset + 2]
                        for offset in range(max(len(chinese_title) - 1, 0))
                    )
                    if title and (title in part or any(token in part for token in title_tokens)):
                        target_index = index
                        break
            if target_index is None:
                for index, task in enumerate(recent_tasks):
                    if index in used_indexes:
                        continue
                    due_text = str(task.get("due") or "")
                    if not re.search(r"\d{1,2}\s*(点|时)|\d{1,2}[:：]\d{2}", due_text):
                        target_index = index
                        break
            if target_index is None:
                for index in range(len(recent_tasks)):
                    if index not in used_indexes:
                        target_index = index
                        break
            if target_index is None or target_index >= len(recent_tasks):
                continue
            used_indexes.add(target_index)
            duration = duration_from_range or infer_duration_minutes(part) or default_duration or recent_tasks[target_index].get("duration", 60) or 60
            assignments.append((target_index, part, start, int(duration)))

        if not assignments:
            return []

        updated_tasks = []
        for target_index, part, start, duration in assignments[: len(recent_tasks)]:
            task = recent_tasks[target_index]
            updated = self.patch_task(
                task["id"],
                {
                    "due": f"{day} {format_clock_hour(start)}",
                    "duration": duration,
                    "context": f"{task.get('context') or task.get('title')}；时间补充：{part}",
                },
            )
            updated["parser"] = "time_followup"
            updated_tasks.append(updated)
        return updated_tasks

    def get_task(self, task_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self.task_row(row) if row else None

    def list_tasks(self, user_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE user_id=? ORDER BY created_at ASC", (user_id,)
            ).fetchall()
        return [self.task_row(row) for row in rows]

    def build_chat_context(self, user_id: str, text: str) -> dict:
        turns = self.list_chat_turns(user_id, limit=6)
        active_tasks = [
            task for task in self.list_tasks(user_id)
            if task.get("status") not in {"completed", "terminated"}
        ]
        latest_chain = self.latest_task_turn_tasks(user_id)
        recent_tasks = latest_chain or active_tasks[-5:]
        query = " ".join(
            [
                text,
                " ".join(task.get("title", "") for task in recent_tasks),
                " ".join(turn.get("user_text", "") for turn in turns[-3:]),
            ]
        )
        memories = self.search_memories(user_id, query, top_k=5)
        context = {
            "recent_turns": [
                {
                    "user_text": turn.get("user_text"),
                    "assistant_reply": turn.get("assistant_reply"),
                    "intent": turn.get("intent"),
                    "task_ids": turn.get("task_ids", []),
                }
                for turn in turns[-4:]
            ],
            "recent_tasks": [
                {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "due": task.get("due"),
                    "duration": task.get("duration"),
                    "status": task.get("status"),
                    "context": task.get("context"),
                }
                for task in recent_tasks
            ],
            "active_task_titles": [task.get("title") for task in active_tasks[-8:]],
            "retrieved_memories": [
                {
                    "source_type": memory.get("source_type"),
                    "task_id": memory.get("task_id"),
                    "text": memory.get("text"),
                    "score": memory.get("score"),
                }
                for memory in memories
            ],
        }
        self.log_event(
            user_id,
            "chat_context_built",
            {
                "recent_task_ids": [task.get("id") for task in recent_tasks],
                "memory_ids": [memory.get("memory_id") for memory in memories],
                "embedding_model": "humanos-local-hash-embedding-v1",
            },
        )
        return context

    def task_row(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "title": row["title"],
            "type": row["type"],
            "due": row["due"],
            "duration": infer_duration_minutes(f"{row['title']} {row['context']}") or row["duration"],
            "priority": row["priority"],
            "status": row["status"],
            "context": row["context"],
            "contextWindow": from_json(row["context_window_json"], {}),
            "cognitive_load": row["cognitive_load"],
            "task_demand": from_json(row["demand_json"], {}),
            "execution": from_json(row["execution_json"], {}),
            "resource_modality": from_json(row["resource_modality_json"], []),
            "parallelizable": bool(row["parallelizable"]),
            "expected_difficulty": row["expected_difficulty"],
            "ambiguity": row["ambiguity"],
            "switch_cost": row["switch_cost"],
            "reentry_cost": row["reentry_cost"],
            "slot": from_json(row["slot_json"], None),
            "checkpoints": from_json(row["checkpoints_json"], []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def patch_task(self, task_id: str, patch: dict) -> dict:
        current = self.get_task(task_id)
        if not current:
            raise KeyError(task_id)
        allowed = {
            "title",
            "type",
            "due",
            "duration",
            "priority",
            "status",
            "context",
            "cognitive_load",
            "ambiguity",
            "switch_cost",
            "reentry_cost",
            "expected_difficulty",
        }
        updates: dict[str, object] = {k: v for k, v in patch.items() if k in allowed}
        if "expected_difficulty" in patch and "task_demand" not in patch:
            refreshed_payload = {
                **current,
                **patch,
                "task_features": (current.get("task_demand") or {}).get("task_features", {}),
            }
            refreshed_demand = self.infer_task_demand(
                refreshed_payload,
                str(patch.get("type") or current.get("type") or "general"),
            )
            updates["demand_json"] = as_json(refreshed_demand)
            updates["cognitive_load"] = refreshed_demand["estimated_cognitive_load"]
        if "slot" in patch:
            updates["slot_json"] = as_json(patch["slot"])
        if "checkpoints" in patch:
            updates["checkpoints_json"] = as_json(patch["checkpoints"])
        if "contextWindow" in patch:
            updates["context_window_json"] = as_json(patch["contextWindow"])
        if "context_window" in patch:
            updates["context_window_json"] = as_json(patch["context_window"])
        if "task_demand" in patch:
            updates["demand_json"] = as_json(patch["task_demand"])
        if "execution" in patch:
            updates["execution_json"] = as_json(patch["execution"])
        if "resource_modality" in patch:
            updates["resource_modality_json"] = as_json(patch["resource_modality"])
        if "parallelizable" in patch:
            updates["parallelizable"] = int(bool(patch["parallelizable"]))
        updates["updated_at"] = now_ms()
        assignments = ", ".join(f"{key}=?" for key in updates)
        values = list(updates.values()) + [task_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE tasks SET {assignments} WHERE id=?", values)
        self.log_event(current["user_id"], "task_updated", {"task_id": task_id, "patch": patch})
        return self.get_task(task_id) or {}

    def delete_task(self, task_id: str) -> dict:
        current = self.get_task(task_id)
        if not current:
            raise KeyError(task_id)
        with self.connect() as conn:
            conn.execute("DELETE FROM context_dumps WHERE task_id=?", (task_id,))
            conn.execute("DELETE FROM memories WHERE task_id=? OR source_id=?", (task_id, task_id))
            conn.execute("DELETE FROM events WHERE payload_json LIKE ?", (f"%{task_id}%",))
            conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.log_event(current["user_id"], "task_deleted", {"task_id": task_id, "title": current["title"]})
        return {"id": task_id, "deleted": True}

    def save_runtime_state(self, user_id: str, payload: dict) -> dict:
        state_id = new_id("state")
        state = {
            "id": state_id,
            "user_id": user_id,
            "focus": int(payload.get("focus", 4)),
            "energy": int(payload.get("energy", 4)),
            "stress": int(payload.get("stress", 4)),
            "mood": payload.get("mood"),
            "attention_residue": payload.get("attention_residue", ""),
            "emotion": payload.get("emotion", "neutral"),
            "readiness": payload.get("readiness", "unsure"),
            "daily_note": payload.get("daily_note", ""),
            "source": "self_report",
            "confidence_level": "high",
            "created_at": now_ms(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_states (
                  id, user_id, focus, energy, stress, mood,
                  attention_residue, emotion, readiness, daily_note, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state["id"],
                    user_id,
                    state["focus"],
                    state["energy"],
                    state["stress"],
                    state["mood"],
                    state["attention_residue"],
                    state["emotion"],
                    state["readiness"],
                    state["daily_note"],
                    state["created_at"],
                ),
            )
        self.log_event(user_id, "runtime_state_saved", state)
        return state

    def latest_runtime_state(self, user_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM runtime_states WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if not row:
            return {
                "focus": 5, "energy": 4, "stress": 5, "attention_residue": "",
                "emotion": "neutral", "readiness": "unsure", "source": "default",
                "confidence_level": "low",
            }
        state = dict(row)
        state.update({"source": "self_report", "confidence_level": "high"})
        return state

    def save_context_dump(self, user_id: str, payload: dict) -> dict:
        dump_id = new_id("dump")
        task_id = payload["task_id"]
        dump = {
            "id": dump_id,
            "user_id": user_id,
            "task_id": task_id,
            "progress": payload.get("progress", ""),
            "open_questions": payload.get("open_questions", []),
            "next_action": payload.get("next_action", ""),
            "stop_reason": payload.get("stop_reason", "unknown"),
            "materials": payload.get("materials", []),
            "created_at": now_ms(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO context_dumps (
                  id, user_id, task_id, progress, open_questions,
                  next_action, stop_reason, materials, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dump_id,
                    user_id,
                    task_id,
                    dump["progress"],
                    as_json(dump["open_questions"]),
                    dump["next_action"],
                    dump["stop_reason"],
                    as_json(dump["materials"]),
                    dump["created_at"],
                ),
            )
        checkpoints = [
            {"label": "暂停原因", "text": dump["stop_reason"]},
            {"label": "当前进展", "text": dump["progress"] or "未补充"},
            {"label": "下一步", "text": dump["next_action"] or "恢复时先确认一个小步骤。"},
        ]
        task = self.get_task(task_id) or {}
        execution = task.get("execution") or {}
        execution["remaining_duration_minutes"] = int(
            payload.get("remaining_duration_minutes")
            or execution.get("remaining_duration_minutes")
            or task.get("duration", 60)
        )
        execution["progress_percent"] = int(payload.get("progress_percent") or execution.get("progress_percent") or 0)
        execution["last_stop_reason"] = dump["stop_reason"]
        next_status = "blocked" if dump["stop_reason"] == "blocked" else "paused"
        self.patch_task(
            task_id,
            {
                "status": next_status,
                "checkpoints": checkpoints,
                "execution": execution,
                "contextWindow": {
                    "progress": dump["progress"],
                    "nextStep": dump["next_action"],
                    "openQuestions": "；".join(dump["open_questions"]),
                },
            },
        )
        memory_text = (
            f"Context dump for task {task_id}. Progress: {dump['progress']}. "
            f"Open questions: {', '.join(dump['open_questions'])}. "
            f"Next action: {dump['next_action']}. Stop reason: {dump['stop_reason']}."
        )
        self.add_memory(
            user_id=user_id,
            source_type="context_dump",
            source_id=dump_id,
            task_id=task_id,
            text=memory_text,
            metadata={"stop_reason": dump["stop_reason"], "task_id": task_id},
        )
        self.log_event(user_id, "context_dump_saved", dump)
        return dump

    def save_execution_feedback(self, user_id: str, payload: dict) -> dict:
        """Store three feedback targets separately and preserve the same task identity."""
        task_id = payload["task_id"]
        task = self.get_task(task_id)
        if not task:
            raise KeyError(task_id)
        feedback = {
            "id": new_id("feedback"),
            "user_id": user_id,
            "task_id": task_id,
            "trigger": payload.get("trigger", "task_completed"),
            "task_evaluation": payload.get("task_evaluation") or {},
            "state_evaluation": payload.get("state_evaluation") or {},
            "recommendation_evaluation": payload.get("recommendation_evaluation") or {},
            "created_at": now_ms(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO execution_feedback (
                  id, user_id, task_id, trigger, task_evaluation_json,
                  state_evaluation_json, recommendation_evaluation_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback["id"], user_id, task_id, feedback["trigger"],
                    as_json(feedback["task_evaluation"]),
                    as_json(feedback["state_evaluation"]),
                    as_json(feedback["recommendation_evaluation"]),
                    feedback["created_at"],
                ),
            )
        execution = task.get("execution") or {}
        task_eval = feedback["task_evaluation"]
        actual = int(task_eval.get("actual_minutes") or 0)
        execution["accumulated_actual_minutes"] = int(execution.get("accumulated_actual_minutes") or 0) + actual
        if task_eval.get("remaining_duration_minutes") is not None:
            execution["remaining_duration_minutes"] = int(task_eval["remaining_duration_minutes"])
        if task_eval.get("completion") == "completed":
            execution["remaining_duration_minutes"] = 0
        execution["last_perceived_difficulty"] = task_eval.get("perceived_difficulty")
        execution.setdefault("sessions", []).append({
            "feedback_id": feedback["id"],
            "actual_minutes": actual,
            "completion": task_eval.get("completion", "partial"),
            "perceived_difficulty": task_eval.get("perceived_difficulty"),
        })
        demand = task.get("task_demand") or {}
        if task_eval.get("perceived_difficulty") is not None:
            demand.setdefault("calibration_history", []).append({
                "feedback_id": feedback["id"],
                "expected_difficulty": task.get("expected_difficulty"),
                "perceived_difficulty": task_eval.get("perceived_difficulty"),
            })
            demand["last_calibrated_at"] = feedback["created_at"]
        patch = {"execution": execution, "task_demand": demand}
        if task_eval.get("completion") == "completed":
            patch["status"] = "completed"
        self.patch_task(task_id, patch)
        self.add_memory(
            user_id=user_id,
            source_type="episodic_memory",
            source_id=feedback["id"],
            task_id=task_id,
            text=(
                f"Task episode {task['title']}. Trigger: {feedback['trigger']}. "
                f"Task evaluation: {as_json(task_eval)}. State after: "
                f"{as_json(feedback['state_evaluation'])}."
            ),
            metadata={
                "kind": "execution_episode",
                "eligible_for_pattern": True,
                "pattern_label": payload.get("pattern_label") or feedback["trigger"],
            },
        )
        self.log_event(user_id, "execution_feedback_saved", feedback)
        return feedback

    def record_state_transition(self, user_id: str, payload: dict) -> dict:
        transition = {
            "id": new_id("transition"),
            "user_id": user_id,
            "task_id": payload.get("task_id"),
            "before_state": payload.get("before_state") or {},
            "action": payload.get("action") or {},
            "predicted_state": payload.get("predicted_state") or {},
            "actual_state": payload.get("actual_state") or {},
            "outcome": payload.get("outcome") or {},
            "created_at": now_ms(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO state_transitions (
                  id, user_id, task_id, before_state_json, action_json,
                  predicted_state_json, actual_state_json, outcome_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transition["id"], user_id, transition["task_id"],
                    as_json(transition["before_state"]), as_json(transition["action"]),
                    as_json(transition["predicted_state"]), as_json(transition["actual_state"]),
                    as_json(transition["outcome"]), transition["created_at"],
                ),
            )
        self.log_event(user_id, "state_transition_recorded", transition)
        return transition

    def pattern_candidates(self, user_id: str) -> list[dict]:
        """Three similar episodes create a candidate; static profile still needs confirmation."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT metadata_json, created_at FROM memories WHERE user_id=? AND source_type='episodic_memory'",
                (user_id,),
            ).fetchall()
        groups: dict[str, list[int]] = {}
        for row in rows:
            metadata = from_json(row["metadata_json"], {})
            label = metadata.get("pattern_label") or metadata.get("stop_reason")
            if label:
                groups.setdefault(str(label), []).append(row["created_at"])
        return [
            {
                "pattern_label": label,
                "episode_count": len(dates),
                "status": "candidate" if len(dates) >= 3 else "insufficient_evidence",
                "can_suggest_update": len(set(time.strftime("%Y-%m-%d", time.localtime(date / 1000)) for date in dates)) >= 5,
                "requires_user_confirmation": True,
            }
            for label, dates in groups.items()
        ]

    def promote_pattern(self, user_id: str, payload: dict) -> dict:
        if not payload.get("user_confirmed"):
            raise ValueError("user confirmation is required before updating static profile")
        label = str(payload.get("pattern_label") or "").strip()
        if not label:
            raise ValueError("pattern_label is required")
        profile = self.ensure_profile(user_id)
        patterns = list(profile.get("learned_patterns") or [])
        if not any(item.get("pattern_label") == label for item in patterns):
            patterns.append({
                "pattern_label": label,
                "evidence_count": int(payload.get("evidence_count") or 1),
                "user_confirmed": True,
                "confirmed_at": now_ms(),
            })
        profile["learned_patterns"] = patterns
        updated = self.upsert_profile(profile)
        return {"learned_patterns": updated.get("learned_patterns", [])}

    def add_memory(
        self,
        user_id: str,
        source_type: str,
        source_id: str,
        task_id: str | None,
        text: str,
        metadata: dict,
    ) -> dict:
        memory_id = new_id("mem")
        memory = {
            "id": memory_id,
            "user_id": user_id,
            "source_type": source_type,
            "source_id": source_id,
            "task_id": task_id,
            "text": text,
            "metadata": metadata,
            "embedding_model": "humanos-local-hash-embedding-v1",
            "created_at": now_ms(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memories (
                  id, user_id, source_type, source_id, task_id, text,
                  metadata_json, embedding_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    user_id,
                    source_type,
                    source_id,
                    task_id,
                    text,
                    as_json(metadata | {"embedding_model": memory["embedding_model"]}),
                    as_json(embed_text(text)),
                    memory["created_at"],
                ),
            )
        return memory

    def search_memories(self, user_id: str, query: str, top_k: int = 5) -> list[dict]:
        query_vec = embed_text(query)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE user_id=? ORDER BY created_at DESC LIMIT 200",
                (user_id,),
            ).fetchall()
        scored = []
        for row in rows:
            vec = from_json(row["embedding_json"], [])
            score = cosine(query_vec, vec) if isinstance(vec, list) else 0.0
            scored.append(
                {
                    "memory_id": row["id"],
                    "source_type": row["source_type"],
                    "source_id": row["source_id"],
                    "task_id": row["task_id"],
                    "text": row["text"],
                    "metadata": from_json(row["metadata_json"], {}),
                    "score": round(score, 4),
                    "created_at": row["created_at"],
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def analyze_schedule_inputs(self, state: dict) -> dict:
        tasks = state.get("tasks", [])
        profile = state.get("profile", {})
        fallback_demands = []
        for task in tasks:
            expected = task.get("expected_difficulty") or task.get("task_demand", {}).get("expected_difficulty")
            try:
                expected_value = int(expected) if expected is not None else None
            except (TypeError, ValueError):
                expected_value = None
            level = "high" if expected_value and expected_value >= 6 else "low" if expected_value and expected_value <= 2 else "medium"
            fallback_demands.append({
                "task_id": task.get("id"),
                "level": level,
                "evidence": task.get("task_demand", {}).get("evidence") or ["来自用户难度输入或本地任务需求规则"],
                "confidence_level": task.get("task_demand", {}).get("confidence_level") or ("high" if expected_value else "low"),
            })

        llm_result = chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 HumanOS 的任务分析 agent。只输出 JSON。"
                        "分析 Task Demand 与任务之间的先后依赖，不生成具体开始时间。"
                        "用户已经确认的难度是高优先级证据，不能无依据覆盖。"
                        "依赖只能引用输入中的 task_id；不确定时不要虚构。"
                        "runtime_state 只能影响今天第一个执行块，不能用于判断整周所有任务。"
                        "将证据与推断分开：每个判断都给出具体 evidence 和 calibrated confidence。"
                        "固定时间和习惯时段是硬边界；AI 安排活动只在用户给出的可发生范围内选择，不把整个范围视为占用。"
                    ),
                },
                {
                    "role": "user",
                    "content": as_json({
                        "profile": {
                            "role": profile.get("role"),
                            "deep_work_window": profile.get("deep_work_window"),
                            "low_energy_window": profile.get("low_energy_window"),
                            "weekly_goal": profile.get("weekly_context", {}).get("weekly_goal"),
                        },
                        "tasks": [
                            {
                                "id": task.get("id"),
                                "title": task.get("title"),
                                "deadline": task.get("due"),
                                "duration": task.get("duration"),
                                "priority": task.get("priority"),
                                "context": task.get("context"),
                                "user_difficulty": task.get("expected_difficulty"),
                                "task_demand": task.get("task_demand", {}),
                            }
                            for task in tasks[:12]
                        ],
                        "required_schema": {
                            "task_demands": [{
                                "task_id": "existing task id",
                                "level": "low/medium/high",
                                "evidence": ["specific evidence"],
                                "confidence_level": "low/medium/high",
                            }],
                            "dependencies": [{
                                "before_task_id": "existing task id",
                                "after_task_id": "existing task id",
                                "reason": "why the first task must precede the second",
                                "confidence_level": "low/medium/high",
                            }],
                            "evidence": ["cross-task evidence used"],
                            "confidence_level": "low/medium/high",
                        },
                    }),
                },
            ]
        )
        if not isinstance(llm_result, dict):
            return {
                "provider": "local_fallback",
                "model": None,
                "prompt_version": "task-demand-dependency-v2",
                "task_demands": fallback_demands,
                "dependencies": [],
                "evidence": ["DeepSeek 不可用，使用用户难度与本地规则"],
                "confidence_level": "low",
            }

        valid_ids = {str(task.get("id")) for task in tasks}
        task_demands = [
            item for item in (llm_result.get("task_demands") or [])
            if isinstance(item, dict) and str(item.get("task_id")) in valid_ids
        ]
        dependencies = [
            item for item in (llm_result.get("dependencies") or [])
            if isinstance(item, dict)
            and str(item.get("before_task_id")) in valid_ids
            and str(item.get("after_task_id")) in valid_ids
            and str(item.get("before_task_id")) != str(item.get("after_task_id"))
        ]
        return {
            "provider": "deepseek",
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            "prompt_version": "task-demand-dependency-v2",
            "task_demands": task_demands or fallback_demands,
            "dependencies": dependencies,
            "evidence": llm_result.get("evidence") or [],
            "confidence_level": llm_result.get("confidence_level") or "medium",
        }

    def decide_schedule(self, user_id: str, payload: dict) -> dict:
        from humanos_graph import run_schedule_graph

        decision = run_schedule_graph(self, user_id, payload)
        self.log_event(user_id, "schedule_decision", decision)
        return decision

    def build_schedule_query(self, tasks: list[dict], state: dict) -> str:
        task_text = "; ".join(f"{t.get('title')} {t.get('type')} {t.get('status')}" for t in tasks[:6])
        return (
            f"Schedule tasks under focus {state.get('focus')} energy {state.get('energy')} "
            f"stress {state.get('stress')}. Tasks: {task_text}"
        )

    def schedule_explanation(self, state: dict, memories: list[dict]) -> str:
        energy = int(state.get("energy", 4))
        stress = int(state.get("stress", 4))
        base = ""
        if energy <= 3:
            base += "你现在的精力偏低，建议先从一个更小的步骤开始，而不是直接进入长时间高强度任务。"
        elif stress >= 6:
            base += "你现在压力偏高，我会先给出建议，等你确认后再调整计划。"
        else:
            base += "你当前状态可以支持一个较完整的学习时间段。"
        if memories:
            base += f" 我也参考了你过去 {len(memories)} 次相似情况。"
        return base

    def refine_schedule_decision(self, state: dict, decision: dict) -> dict:
        profile = self.ensure_profile(state.get("user_id", "demo"))
        tasks = state.get("tasks", [])
        runtime_state = state.get("runtime_state", {})
        memories = state.get("memories", [])
        candidate_summaries = []
        for candidate in decision.get("candidate_plans", []):
            candidate_summaries.append({
                "id": candidate.get("id"),
                "label": candidate.get("label"),
                "metrics": candidate.get("metrics", {}),
                "validation": candidate.get("validation", {}),
                "unscheduled_tasks": candidate.get("unscheduled_tasks", []),
                "blocks": [
                    {
                        "task_id": block.get("task_id"),
                        "day_index": block.get("day_index"),
                        "start": block.get("start"),
                        "end": block.get("end"),
                        "session_minutes": block.get("session_minutes"),
                        "remaining_after_block_minutes": block.get("remaining_after_block_minutes"),
                    }
                    for block in candidate.get("plan_patch", [])[:80]
                ],
            })
        llm_result = chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 HumanOS 的候选计划比较 agent。只输出 JSON。"
                        "不要说你在收集数据、沉淀画像、使用 embedding 或后端。"
                        "Deadline 是最晚完成时间，绝不能作为开始时间。"
                        "runtime_state 只允许解释或调整今天的第一个任务，不能用于解释整周安排。"
                        "只能在 candidate_plans 中选择，不能发明新的时间块。"
                        "有 hard violation 的方案不能被选择；优先减少 remaining_minutes，再考虑认知匹配、依赖和负荷平衡。"
                        "固定时间/习惯时段必须避开；AI 安排活动已经由约束引擎在可发生范围内预留，不得与其重叠。"
                        "必须引用输入证据；证据不足时降低 confidence 并写入 warnings，不得补造用户偏好。"
                        "解释要面向学生，简短、具体、可操作。"
                    ),
                },
                {
                    "role": "user",
                    "content": as_json(
                        {
                            "relevant_profile": {
                                "deep_work_window": profile.get("deep_work_window"),
                                "low_energy_window": profile.get("low_energy_window"),
                                "preferred_session_minutes": profile.get("task_preferences", {}).get("preferred_session_minutes"),
                                "weekly_context": profile.get("weekly_context", {}),
                                "learned_patterns": profile.get("learned_patterns", []),
                            },
                            "runtime_state": runtime_state,
                            "tasks": tasks[:6],
                            "memory_evidence": memories[:3],
                            "input_analysis": state.get("ai_task_analysis", {}),
                            "candidate_plans": candidate_summaries,
                            "deterministic_repair_suggestions": decision.get("repair_suggestions", []),
                            "required_schema": {
                                "explanation": "一句中文安排理由",
                                "first_action": "用户现在可以立刻开始的一步",
                                "risk": "可能卡住的原因",
                                "selected_candidate_id": "candidate_plans 中的 id",
                                "constraint_interpretation": ["对可用时间、固定事项和临时限制的简短理解"],
                                "task_demand_review": ["任务需求判断及依据，包含 task_id"],
                                "task_dependencies": ["任务依赖及依据，包含 before_task_id/after_task_id"],
                                "repair_suggestions": ["无法完整安排时的可操作修复建议"],
                                "evidence": ["为什么选择该候选计划"],
                                "confidence_level": "low/medium/high",
                                "warnings": ["输入中的冲突、歧义或需要确认的地方"],
                            },
                        }
                    ),
                },
            ]
        )
        if not isinstance(llm_result, dict):
            decision["llm_provider"] = "local_fallback"
            decision["ai_provenance"] = {
                "provider": state.get("ai_task_analysis", {}).get("provider", "local_fallback"),
                "model": state.get("ai_task_analysis", {}).get("model"),
                "calls": ["task_demand_and_dependency_analysis"],
                "candidate_comparison": "local_fallback",
                "evidence": state.get("ai_task_analysis", {}).get("evidence", []),
                "confidence_level": state.get("ai_task_analysis", {}).get("confidence_level", "low"),
                "prompt_versions": {
                    "task_analysis": state.get("ai_task_analysis", {}).get("prompt_version", "task-demand-dependency-v2"),
                    "candidate_comparison": "candidate-comparison-v2",
                },
            }
            return decision
        selected_id = llm_result.get("selected_candidate_id")
        selected_candidate = next(
            (
                candidate for candidate in decision.get("candidate_plans", [])
                if candidate.get("id") == selected_id and candidate.get("validation", {}).get("valid", False)
            ),
            None,
        )
        if selected_candidate:
            decision["selected_candidate_id"] = selected_candidate.get("id")
            decision["plan_patch"] = selected_candidate.get("plan_patch", [])
            decision["validation"] = selected_candidate.get("validation", {})
            decision["unscheduled_tasks"] = selected_candidate.get("unscheduled_tasks", [])
        decision["explanation"] = llm_result.get("explanation") or decision.get("explanation", "")
        decision["first_action"] = llm_result.get("first_action", "")
        decision["risk"] = llm_result.get("risk", "")
        decision["ai_analysis"] = {
            "constraint_interpretation": llm_result.get("constraint_interpretation") or [],
            "task_demand_review": llm_result.get("task_demand_review") or [],
            "task_dependencies": llm_result.get("task_dependencies") or state.get("ai_task_analysis", {}).get("dependencies", []),
            "candidate_comparison_evidence": llm_result.get("evidence") or [],
            "confidence_level": llm_result.get("confidence_level") or "medium",
            "prompt_versions": {
                "task_analysis": state.get("ai_task_analysis", {}).get("prompt_version", "task-demand-dependency-v2"),
                "candidate_comparison": "candidate-comparison-v2",
            },
            "warnings": llm_result.get("warnings") or [],
        }
        if llm_result.get("repair_suggestions"):
            decision["repair_suggestions"] = [
                *decision.get("repair_suggestions", []),
                {"source": "deepseek", "options": llm_result.get("repair_suggestions")},
            ]
        decision["ai_provenance"] = {
            "provider": "deepseek",
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            "calls": ["task_demand_and_dependency_analysis", "candidate_plan_comparison"],
            "selected_candidate_id": decision.get("selected_candidate_id"),
            "evidence": llm_result.get("evidence") or [],
            "confidence_level": llm_result.get("confidence_level") or "medium",
            "prompt_versions": {
                "task_analysis": state.get("ai_task_analysis", {}).get("prompt_version", "task-demand-dependency-v2"),
                "candidate_comparison": "candidate-comparison-v2",
            },
        }
        decision["llm_provider"] = "deepseek"
        return decision

    def reentry_prompt(self, user_id: str, payload: dict) -> dict:
        task_id = payload["task_id"]
        task = self.get_task(task_id)
        if not task:
            raise KeyError(task_id)
        state = payload.get("runtime_state") or payload.get("current_runtime_state") or self.latest_runtime_state(user_id)
        query = f"Resume task {task['title']} with energy {state.get('energy')} stress {state.get('stress')}"
        memories = self.search_memories(user_id, query, top_k=4)
        latest_dump = None
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM context_dumps
                WHERE user_id=? AND task_id=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, task_id),
            ).fetchone()
        if row:
            latest_dump = {
                "progress": row["progress"],
                "open_questions": from_json(row["open_questions"], []),
                "next_action": row["next_action"],
                "stop_reason": row["stop_reason"],
            }
        first_step = (
            latest_dump["next_action"]
            if latest_dump and latest_dump["next_action"]
            else "先用 10 分钟重新确认当前进展和下一步。"
        )
        prompt = (
            f"恢复任务：{task['title']}。"
            f"{'上次进展：' + latest_dump['progress'] + '。' if latest_dump else ''}"
            f"第一步：{first_step}"
        )
        response = {
            "task_id": task_id,
            "prompt": prompt,
            "first_step": first_step,
            "suggested_block_minutes": 25 if int(state.get("energy", 4)) <= 3 else 45,
            "memory_evidence": memories,
        }
        self.log_event(user_id, "reentry_prompt", response)
        return response

    def log_event(self, user_id: str, event_type: str, payload: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO events (id, user_id, type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("evt"), user_id, event_type, as_json(payload), now_ms()),
            )


store = Store(DB_PATH)


class Handler(BaseHTTPRequestHandler):
    server_version = "HumanOSBackend/0.1"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self) -> None:
        self.route()

    def do_POST(self) -> None:
        self.route()

    def do_PUT(self) -> None:
        self.route()

    def do_PATCH(self) -> None:
        self.route()

    def do_DELETE(self) -> None:
        self.route()

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, data: object, status: int = 200) -> None:
        raw = as_json(data).encode("utf-8")
        self.send_response(status)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def route(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        method = self.command
        try:
            if method == "GET" and path == "/api/health":
                ai_enabled = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
                self.send_json({
                    "ok": True,
                    "db": str(DB_PATH),
                    "embedding_model": "humanos-local-hash-embedding-v1",
                    "ai_enabled": ai_enabled,
                    "ai_provider": "deepseek" if ai_enabled else None,
                    "ai_model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat") if ai_enabled else None,
                    "scheduling_mode": "constraint_engine_plus_llm" if ai_enabled else "constraint_engine_only",
                })
                return

            if path == "/api/auth/register" and method == "POST":
                payload = self.read_json()
                result = store.create_user(
                    email=payload.get("email", ""),
                    password=payload.get("password", ""),
                    name=payload.get("name", ""),
                )
                self.send_json(result, status=201)
                return

            if path == "/api/auth/login" and method == "POST":
                payload = self.read_json()
                result = store.authenticate_user(
                    email=payload.get("email", ""),
                    password=payload.get("password", ""),
                )
                self.send_json(result)
                return

            if path == "/api/profile":
                user_id = query.get("user_id", ["demo"])[0]
                if method == "GET":
                    self.send_json({"profile": store.ensure_profile(user_id)})
                    return
                if method == "PUT":
                    payload = self.read_json()
                    payload["user_id"] = payload.get("user_id", user_id)
                    self.send_json({"profile": store.upsert_profile(payload)})
                    return

            if path == "/api/tasks":
                user_id = query.get("user_id", ["demo"])[0]
                if method == "GET":
                    store.ensure_profile(user_id)
                    self.send_json({"tasks": store.list_tasks(user_id)})
                    return
                if method == "POST":
                    payload = self.read_json()
                    user_id = payload.get("user_id", user_id)
                    store.ensure_profile(user_id)
                    self.send_json({"task": store.create_task(user_id, payload)}, status=201)
                    return

            if path == "/api/tasks/parse" and method == "POST":
                payload = self.read_json()
                user_id = payload.get("user_id", "demo")
                store.ensure_profile(user_id)
                task = store.parse_task_from_text(user_id, payload.get("text", ""))
                self.send_json({"tasks": [task]}, status=201)
                return

            if path == "/api/chat/turn" and method == "POST":
                payload = self.read_json()
                user_id = payload.get("user_id", "demo")
                store.ensure_profile(user_id)
                self.send_json({"turn": store.chat_turn(user_id, payload)}, status=201)
                return

            if path == "/api/chat/turns" and method == "GET":
                user_id = query.get("user_id", ["demo"])[0]
                limit = int(query.get("limit", ["20"])[0])
                store.ensure_profile(user_id)
                self.send_json({"turns": store.list_chat_turns(user_id, limit=limit)})
                return

            if path.startswith("/api/tasks/") and method == "PATCH":
                task_id = path.split("/")[-1]
                self.send_json({"task": store.patch_task(task_id, self.read_json())})
                return

            if path.startswith("/api/tasks/") and method == "DELETE":
                task_id = path.split("/")[-1]
                self.send_json({"task": store.delete_task(task_id)})
                return

            if path == "/api/state-checkins" and method == "POST":
                payload = self.read_json()
                user_id = payload.get("user_id", "demo")
                store.ensure_profile(user_id)
                self.send_json({"runtime_state": store.save_runtime_state(user_id, payload)}, status=201)
                return

            if path == "/api/context-dumps" and method == "POST":
                payload = self.read_json()
                user_id = payload.get("user_id", "demo")
                store.ensure_profile(user_id)
                self.send_json({"context_dump": store.save_context_dump(user_id, payload)}, status=201)
                return

            if path == "/api/execution-feedback" and method == "POST":
                payload = self.read_json()
                user_id = payload.get("user_id", "demo")
                store.ensure_profile(user_id)
                self.send_json({"feedback": store.save_execution_feedback(user_id, payload)}, status=201)
                return

            if path == "/api/state-transitions" and method == "POST":
                payload = self.read_json()
                user_id = payload.get("user_id", "demo")
                store.ensure_profile(user_id)
                self.send_json({"transition": store.record_state_transition(user_id, payload)}, status=201)
                return

            if path == "/api/patterns/candidates" and method == "GET":
                user_id = query.get("user_id", ["demo"])[0]
                store.ensure_profile(user_id)
                self.send_json({"patterns": store.pattern_candidates(user_id)})
                return

            if path == "/api/patterns/promote" and method == "POST":
                payload = self.read_json()
                user_id = payload.get("user_id", "demo")
                store.ensure_profile(user_id)
                self.send_json(store.promote_pattern(user_id, payload))
                return

            if path == "/api/schedules/decide" and method == "POST":
                payload = self.read_json()
                user_id = payload.get("user_id", "demo")
                store.ensure_profile(user_id)
                self.send_json({"decision": store.decide_schedule(user_id, payload)})
                return

            if path == "/api/reentry" and method == "POST":
                payload = self.read_json()
                user_id = payload.get("user_id", "demo")
                store.ensure_profile(user_id)
                self.send_json({"reentry": store.reentry_prompt(user_id, payload)})
                return

            if path == "/api/memories/search" and method == "GET":
                user_id = query.get("user_id", ["demo"])[0]
                q = query.get("q", [""])[0]
                top_k = int(query.get("top_k", ["5"])[0])
                store.ensure_profile(user_id)
                self.send_json({"memories": store.search_memories(user_id, q, top_k=top_k)})
                return

            self.send_json({"error": "not_found", "path": path}, status=404)
        except KeyError as exc:
            self.send_json({"error": "not_found", "id": str(exc)}, status=404)
        except PermissionError as exc:
            self.send_json({"error": "unauthorized", "message": str(exc)}, status=401)
        except ValueError as exc:
            self.send_json({"error": "bad_request", "message": str(exc)}, status=400)
        except sqlite3.IntegrityError:
            self.send_json({"error": "conflict", "message": "email already registered"}, status=409)
        except Exception as exc:
            self.send_json({"error": type(exc).__name__, "message": str(exc)}, status=500)


def main() -> None:
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "8787"))
    print(f"HumanOS backend listening on http://127.0.0.1:{port}")
    print(f"External access uses http://<server-ip>:{port}")
    print(f"SQLite database: {DB_PATH}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
