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
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "humanos.db"
VECTOR_DIMS = 64
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
CHAT_CONTEXT_TURN_LIMIT = 50


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()


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
    match = re.search(r"(\d+)\s*(?:个\s*)?(?:-|–|—)?\s*(分钟|minutes?|mins?|min|小时|hours?|hrs?|h)", text, re.I)
    if not match:
        return None
    amount = int(match.group(1))
    return amount * 60 if match.group(2).lower() in {"小时", "hour", "hours", "hr", "hrs", "h"} else amount


ENGLISH_WEEKDAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
ENGLISH_RELATIVE_DAY = rf"(?:today|tonight|tomorrow|tmr|tmrw|{ENGLISH_WEEKDAY})"
ENGLISH_TIME_WORD = r"(?:morning|afternoon|evening|night|noon|\d{1,2}(?::\d{2})\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm))"
ENGLISH_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
CHINESE_WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def english_day_time_in_text(text: str) -> str:
    clean = str(text or "")
    day = re.search(ENGLISH_RELATIVE_DAY, clean, re.I)
    time_match = re.search(ENGLISH_TIME_WORD, clean, re.I)
    if day and time_match:
        if day.start() <= time_match.start():
            return f"{day.group(0)} {time_match.group(0)}"
        return f"{time_match.group(0)} {day.group(0)}"
    if day:
        return day.group(0)
    if re.search(r"\bevery\s+(morning|afternoon|evening|night|day)\b", clean, re.I):
        every = re.search(r"\bevery\s+(morning|afternoon|evening|night|day)\b", clean, re.I)
        return every.group(0) if every else "every day"
    if time_match and re.search(r"\b(am|pm|morning|afternoon|evening|night|noon)\b", time_match.group(0), re.I):
        return time_match.group(0)
    return ""


def chinese_day_time_in_text(text: str) -> str:
    clean = str(text or "")
    day = r"(今天|今晚|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天])"
    clock = r"((?:早上|上午|中午|下午|晚上)?\s*\d{1,2}\s*(?:[:：]\s*\d{2}|点|时))"
    day_clock = re.search(rf"{day}\s*{clock}", clean)
    if day_clock:
        return re.sub(r"\s+", "", day_clock.group(0))
    clock_day = re.search(rf"{clock}\s*{day}", clean)
    if clock_day:
        return re.sub(r"\s+", "", clock_day.group(0))
    day_period = re.search(rf"{day}\s*(早上|上午|中午|下午|晚上)", clean)
    if day_period:
        return re.sub(r"\s+", "", day_period.group(0))
    recurring = re.search(r"每天\s*(早上|上午|中午|下午|晚上)", clean)
    if recurring:
        return recurring.group(0)
    return ""


def recurring_due_values(segment: str, due: str) -> list[str]:
    text = str(segment or "")
    due_text = str(due or "")
    english = re.search(r"\bevery\s+(morning|afternoon|evening|night|day)\b", f"{text} {due_text}", re.I)
    chinese = re.search(r"每天\s*(早上|上午|中午|下午|晚上)?", f"{text} {due_text}")
    if not english and not chinese:
        return [due]

    if english:
        period = english.group(1).lower()
        if period == "day":
            period = "afternoon"
        day_names = ENGLISH_WEEKDAY_NAMES
        period_time = period
    else:
        period = chinese.group(1) if chinese and chinese.group(1) else "下午"
        day_names = CHINESE_WEEKDAY_NAMES
        period_time = {
            "早上": "09:00",
            "上午": "09:00",
            "中午": "12:00",
            "下午": "14:00",
            "晚上": "19:00",
        }.get(period, "14:00")

    today = date.today()
    values = []
    for offset in range(7):
        current = today + timedelta(days=offset)
        values.append(f"{day_names[current.weekday()]} {period_time}")
    return values


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
    raw = str(value or "")
    text = re.sub(r"\s+", "", raw)
    period_match = re.search(r"(早上|上午|中午|下午|晚上)", text)
    english_period_match = re.search(r"\b(morning|afternoon|evening|night|noon)\b", raw, re.I)
    period = period_match.group(1) if period_match else (english_period_match.group(1).lower() if english_period_match else inherited_period)
    colon_match = re.search(r"(\d{1,2})[:：](\d{2})(am|pm)?", text, re.I)
    if colon_match:
        hour = int(colon_match.group(1))
        minute = int(colon_match.group(2))
        meridiem = (colon_match.group(3) or "").lower()
    else:
        hour_match = re.search(r"(\d{1,2})(点|时|am|pm)", text, re.I)
        if not hour_match:
            if period == "noon":
                return 12.0
            if period in {"morning"}:
                return 9.0
            if period in {"afternoon"}:
                return 14.0
            if period in {"evening", "night"}:
                return 19.0
            return None
        hour = int(hour_match.group(1))
        minute = 0
        meridiem = (hour_match.group(2) or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if period in {"下午", "晚上", "afternoon", "evening", "night"} and hour < 12:
        hour += 12
    if period in {"中午", "noon"} and hour < 11:
        hour += 12
    return hour + minute / 60


def normalize_calendar_hour(hour: float, duration_minutes: int = 60) -> float:
    duration = max(duration_minutes, 15) / 60
    if hour >= 24:
        return max(0.0, 24.0 - duration)
    return max(0.0, hour)


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
        DATA_DIR.mkdir(parents=True, exist_ok=True)
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
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "context_window_json" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN context_window_json TEXT NOT NULL DEFAULT '{}'")

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
            "role": "研究型学生",
            "deep_work_window": "09:00-11:30",
            "low_energy_window": "14:00-15:30",
            "control_preference": "confirm_before_reschedule",
            "blocker_patterns": ["task_ambiguity", "fatigue", "context_loss"],
            "task_preferences": {
                "writing": "morning_deep_work",
                "admin": "low_energy_slots",
                "reading": "moderate_energy",
                "onboarding_completed": False,
                "planning_tools": [],
                "planning_gap": "",
                "common_blockers": [],
                "recovery_preference": "",
                "available_windows": "",
                "preferred_session_minutes": 45,
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
                current.get("control_preference") if current else "confirm_before_reschedule",
            ),
            "blocker_patterns": profile.get(
                "blocker_patterns", current.get("blocker_patterns") if current else []
            ),
            "task_preferences": profile.get(
                "task_preferences", current.get("task_preferences") if current else {}
            ),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO profiles (
                  user_id, role, deep_work_window, low_energy_window,
                  control_preference, blocker_patterns, task_preferences,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                  role=excluded.role,
                  deep_work_window=excluded.deep_work_window,
                  low_energy_window=excluded.low_energy_window,
                  control_preference=excluded.control_preference,
                  blocker_patterns=excluded.blocker_patterns,
                  task_preferences=excluded.task_preferences,
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

    def infer_schedule_task_type(self, payload: dict) -> str:
        explicit = payload.get("task_type") or payload.get("taskType")
        due = str(payload.get("due") or payload.get("deadline") or "")
        context = str(payload.get("context") or "")
        text = f"{due} {context}"
        has_clock = re.search(r"\d{1,2}\s*(点|时)|\d{1,2}[:：]\d{2}", text)
        fixed_words = re.search(r"(会议|开会|开.*会|组会|上课|面试|吃饭|午饭|午餐|晚饭|早餐|appointment|meeting|lunch|dinner|breakfast|meal|exam|examination)", text, re.I)
        deadline_words = re.search(r"(截止|ddl|deadline|之前|前|due|\bby\b|before)", text, re.I)
        if explicit in {"flexible_task", "fixed_event", "recovery_task"}:
            if explicit == "fixed_event" and deadline_words and not fixed_words:
                return "flexible_task"
            return explicit
        if has_clock and (fixed_words or not deadline_words):
            return "fixed_event"
        return "flexible_task"

    def local_task_dimensions(self, task: dict, chat_context: dict | None = None) -> dict:
        text = f"{task.get('title', '')} {task.get('context', '')}".lower()
        explicit_load = task.get("cognitive_load")
        explicit_ambiguity = task.get("ambiguity")
        high_load_terms = ["论文", "写", "coding", "代码", "研究", "阅读", "planning", "复现", "实验", "分析"]
        low_load_terms = ["取", "拿", "买", "发邮件", "报销", "预约", "整理文件"]
        dependency_terms = ["等", "等待", "反馈", "队友", "老师", "导师", "审批", "回复", "确认"]
        collaboration_terms = ["会议", "开会", "组会", "讨论", "队友", "同学", "老师", "导师", "team", "meeting"]
        unclear_terms = ["看看", "处理", "搞一下", "弄", "完善", "研究一下", "不清楚", "卡住", "想想"]
        resistance_terms = ["不想", "拖延", "焦虑", "压力", "烦", "累", "害怕", "开始不了"]

        if explicit_load in {"high", "medium", "low"}:
            cognitive_load = explicit_load
        elif any(term in text for term in high_load_terms):
            cognitive_load = "high"
        elif any(term in text for term in low_load_terms):
            cognitive_load = "low"
        else:
            cognitive_load = "medium"

        if explicit_ambiguity in {"high", "medium", "low"}:
            ambiguity = explicit_ambiguity
        elif any(term in text for term in unclear_terms):
            ambiguity = "high"
        elif len(str(task.get("title", ""))) <= 4:
            ambiguity = "medium"
        else:
            ambiguity = "low"

        dependency_status = "waiting_external" if any(term in text for term in dependency_terms) else "self_contained"
        collaboration_required = any(term in text for term in collaboration_terms)
        emotional_resistance = "high" if any(term in text for term in resistance_terms) else "medium" if ambiguity == "high" else "low"
        duration = safe_duration_minutes(task.get("estimated_duration") or task.get("duration"), 60)
        splittable = cognitive_load == "high" or duration >= 90
        clarity = "low" if ambiguity == "high" else "medium" if ambiguity == "medium" else "high"
        recovery_cost = "high" if cognitive_load == "high" or ambiguity == "high" else "medium" if collaboration_required else "low"

        return {
            "cognitive_load": cognitive_load,
            "ambiguity": ambiguity,
            "clarity": clarity,
            "splittable": splittable,
            "recovery_cost": recovery_cost,
            "dependency_status": dependency_status,
            "collaboration_required": collaboration_required,
            "emotional_resistance": emotional_resistance,
            "confidence": 0.68 if ambiguity == "high" else 0.78,
            "source": "local_rules",
        }

    def task_dimension_agent(self, task: dict, chat_context: dict | None = None) -> dict:
        fallback = self.local_task_dimensions(task, chat_context)
        llm_result = chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 HumanOS 的 Task Dimension Agent。只输出 JSON。"
                        "判断任务用于调度的认知维度，不要输出面向用户的话。"
                        "不要改变任务标题、时间和截止日期。"
                    ),
                },
                {
                    "role": "user",
                    "content": as_json(
                        {
                            "task": {
                                "title": task.get("title"),
                                "context": task.get("context"),
                                "task_type": task.get("task_type") or task.get("taskType"),
                                "deadline": task.get("deadline") or task.get("due"),
                                "estimated_duration": task.get("estimated_duration") or task.get("duration"),
                            },
                            "recent_context": chat_context or {},
                            "schema": {
                                "cognitive_load": "high/medium/low",
                                "ambiguity": "high/medium/low",
                                "clarity": "high/medium/low",
                                "splittable": "true/false",
                                "recovery_cost": "high/medium/low",
                                "dependency_status": "self_contained/waiting_external/blocked_by_unknown",
                                "collaboration_required": "true/false",
                                "emotional_resistance": "high/medium/low",
                                "confidence": "0.0-1.0",
                            },
                        }
                    ),
                },
            ]
        )
        if not isinstance(llm_result, dict):
            return fallback
        dimensions = {**fallback}
        allowed_levels = {"high", "medium", "low"}
        for key in ["cognitive_load", "ambiguity", "clarity", "recovery_cost", "emotional_resistance"]:
            value = str(llm_result.get(key) or "")
            if value in allowed_levels:
                dimensions[key] = value
        dependency = str(llm_result.get("dependency_status") or "")
        if dependency in {"self_contained", "waiting_external", "blocked_by_unknown"}:
            dimensions["dependency_status"] = dependency
        for key in ["splittable", "collaboration_required"]:
            if key in llm_result:
                dimensions[key] = bool(llm_result[key])
        try:
            dimensions["confidence"] = round(float(llm_result.get("confidence", dimensions["confidence"])), 2)
        except (TypeError, ValueError):
            pass
        dimensions["source"] = "deepseek"
        return dimensions

    def create_task(self, user_id: str, payload: dict) -> dict:
        title = payload.get("title", "未命名任务")
        context = payload.get("context", "")
        task_type = payload.get("type") or self.infer_task_type(title, context)
        schedule_task_type = self.infer_schedule_task_type(payload)
        deadline = payload.get("deadline") or payload.get("due")
        if not payload.get("id"):
            normalized_title = re.sub(r"\s+", " ", str(title)).strip().lower()
            normalized_due = re.sub(r"\s+", " ", str(payload.get("due") or deadline or "")).strip().lower()
            with self.connect() as conn:
                duplicate = conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE user_id=? AND lower(trim(title))=? AND lower(trim(coalesce(due, '')))=?
                      AND status NOT IN ('completed', 'terminated')
                    ORDER BY
                      CASE WHEN slot_json IS NOT NULL AND slot_json != 'null' THEN 0 ELSE 1 END,
                      updated_at DESC
                    LIMIT 1
                    """,
                    (user_id, normalized_title, normalized_due),
                ).fetchone()
            if duplicate:
                self.log_event(user_id, "task_deduplicated", {"task_id": duplicate["id"], "title": title})
                return self.task_row(duplicate)
        task_id = payload.get("id") or new_id("task")
        priority = payload.get("priority", "中")
        duration = infer_duration_minutes(f"{title} {context}") or int(
            payload.get("estimated_duration") or payload.get("duration", 60)
        )
        status = payload.get("status", "queued")
        dimensions = self.task_dimension_agent(
            {
                **payload,
                "title": title,
                "context": context,
                "type": task_type,
                "task_type": schedule_task_type,
                "deadline": deadline,
                "estimated_duration": duration,
            },
            payload.get("chat_context"),
        )
        cognitive_load = dimensions.get(
            "cognitive_load",
            payload.get("cognitive_load") or ("high" if task_type in {"writing", "coding"} else "medium"),
        )
        ambiguity = dimensions.get(
            "ambiguity",
            payload.get("ambiguity") or ("medium" if task_type in {"writing", "research"} else "low"),
        )
        switch_cost = payload.get("switch_cost", "high" if cognitive_load == "high" else "medium")
        reentry_cost = payload.get("reentry_cost") or dimensions.get("recovery_cost") or switch_cost
        context_window = payload.get("contextWindow") or payload.get("context_window") or {}
        if not isinstance(context_window, dict):
            context_window = {}
        context_window = {
            **context_window,
            "taskType": schedule_task_type,
            "deadline": deadline,
            "estimatedDuration": duration,
            "dimensions": dimensions,
        }
        timestamp = now_ms()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                  id, user_id, title, type, due, duration, priority, status,
                  context, context_window_json, cognitive_load, ambiguity, switch_cost, reentry_cost,
                  slot_json, checkpoints_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    user_id,
                    title,
                    task_type,
                    payload.get("due") or deadline,
                    duration,
                    priority,
                    status,
                    context,
                    as_json(context_window),
                    cognitive_load,
                    ambiguity,
                    switch_cost,
                    reentry_cost,
                    as_json(payload.get("slot")),
                    as_json(payload.get("checkpoints", [])),
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
            metadata={
                "task_type": task_type,
                "schedule_task_type": schedule_task_type,
                "deadline": deadline,
                "priority": priority,
                "status": status,
                "dimensions": dimensions,
            },
        )
        self.log_event(user_id, "task_created", {"task_id": task_id, "title": title})
        return self.get_task(task_id, user_id=user_id) or {}

    def parse_tasks_from_text(self, user_id: str, text: str, chat_context: dict | None = None) -> list[dict]:
        clean = text.strip()
        if not clean:
            raise ValueError("task text is required")
        expected_count = self.estimated_task_count(clean)
        explicit_schedule_tasks = self.parse_explicit_schedule_lines(user_id, clean)
        if explicit_schedule_tasks:
            return explicit_schedule_tasks
        if self.looks_like_compact_multi_task_list(clean) or self.english_task_segments(clean):
            return self.local_parse_tasks_from_text(user_id, clean)
        llm_result = chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 HumanOS 的任务解析 agent。只输出 JSON。"
                        "从用户中文或英文输入中提取所有学习任务、固定事件和生活安排。"
                        "任务标题和 context 必须使用用户输入的主要语言；英文输入保留英文，不要翻译成中文。"
                        "如果一句话包含多个时间点或多个动作，必须拆成多个任务。"
                        "区分 flexible_task 和 fixed_event："
                        "有固定会议、上课、吃饭、考试、明确开始时间且必须按时发生的是 fixed_event；"
                        "只需要在截止日前完成、可由系统安排执行窗口的是 flexible_task。"
                        "不要输出解释。"
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
                                        "task_type": "flexible_task/fixed_event/recovery_task",
                                        "deadline": "flexible_task 的截止日期或目标日期；如果用户说今天/明天/周几，需要保留相对日期",
                                        "due": "兼容字段；fixed_event 写开始时间，flexible_task 写 deadline",
                                        "estimated_duration": "预计分钟数，数字；没有说时默认 60",
                                        "duration": "兼容字段，等同 estimated_duration",
                                        "priority": "高/中/低",
                                        "cognitive_load": "high/medium/low",
                                        "ambiguity": "high/medium/low",
                                        "splittable": "true/false",
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
            payloads = []
            for item in raw_tasks[:8]:
                if not isinstance(item, dict):
                    continue
                explicit_duration = infer_duration_minutes(clean) if len(raw_tasks) == 1 else None
                parsed_duration = safe_duration_minutes(
                    item.get("estimated_duration") or item.get("duration"), explicit_duration or 60
                )
                if explicit_duration and parsed_duration == 60:
                    parsed_duration = explicit_duration
                payload = {
                    "title": item.get("title") or clean[:60],
                    "task_type": item.get("task_type") or item.get("taskType"),
                    "deadline": item.get("deadline") or item.get("due") or "未设置",
                    "due": item.get("due") or item.get("deadline") or "未设置",
                    "estimated_duration": parsed_duration,
                    "duration": parsed_duration,
                    "priority": item.get("priority") if item.get("priority") in {"高", "中", "低"} else "中",
                    "cognitive_load": item.get("cognitive_load") if item.get("cognitive_load") in {"high", "medium", "low"} else None,
                    "ambiguity": item.get("ambiguity") if item.get("ambiguity") in {"high", "medium", "low"} else None,
                    "context": item.get("context") or clean,
                }
                payload = {key: value for key, value in payload.items() if value is not None}
                payload["parser"] = "deepseek"
                payloads.append(payload)
            explicit_duration = infer_duration_minutes(clean)
            if explicit_duration and len(payloads) == 1:
                payloads[0]["estimated_duration"] = explicit_duration
                payloads[0]["duration"] = explicit_duration
            if expected_count > 1 and len(payloads) < expected_count:
                self.log_event(
                    user_id,
                    "task_parse_fallback",
                    {
                        "reason": "llm_under_split",
                        "expected_count": expected_count,
                        "llm_count": len(payloads),
                        "text": clean[:500],
                    },
                )
                return self.local_parse_tasks_from_text(user_id, clean)
            if payloads:
                tasks = [self.create_task(user_id, payload) for payload in payloads]
                return tasks

        return self.local_parse_tasks_from_text(user_id, clean)

    def estimated_task_count(self, text: str) -> int:
        compact = re.sub(r"\s+", "", text)
        readable = re.sub(r"\s+", " ", text).strip()
        if not compact:
            return 0
        clock_count = len(re.findall(r"(?:早上|上午|中午|下午|晚上)?\d{1,2}(?:[:：]\d{2}|点|时)|\d{1,2}(?::\d{2})?\s*(?:am|pm)", readable, re.I))
        action_segments = [
            part.strip("，,。；;、")
            for part in re.split(r"(?:然后|最后|再|接着|之后|，|,|。|；|;|、|\b(?:i\s+)?also\s+need\s+to\b|\band\s+(?=I\s+need\s+to|I\s+also\s+need\s+to|review|read|write|finish|complete|prepare|go|study|submit)\b)", readable, flags=re.I)
            if part.strip("，,。；;、")
        ]
        action_count = sum(
            1
            for part in action_segments
            if re.search(
                r"(复习|学习|写|读|阅读|总结|整理|完善|完成|处理|准备|提交|看|做|备战|开会|会议|组会|讨论|取|拿|办|买|发|"
                r"\b(finish|complete|write|read|review|study|prepare|design|eat|meet|meeting|submit)\b)",
                part,
                re.I,
            )
        )
        serial_count = len(re.findall(r"第[一二两三四五六七八九\d]+个", compact))
        return max(clock_count, action_count, serial_count, 1)

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
            if re.search(
                r"(复习|学习|写|读|阅读|总结|整理|完善|完成|处理|准备|提交|看|做|备战|开会|会议|组会|讨论|取|拿|办|买|发|"
                r"\b(finish|complete|write|read|review|study|prepare|design|eat|meet|meeting|submit)\b)",
                part,
                re.I,
            )
        )
        followup_markers = re.search(r"第[一二三四五六七八九\d]+|这个|那个|都是|每个", text)
        return action_count >= 2 and not followup_markers

    def english_task_segments(self, text: str) -> list[str]:
        if not re.search(r"[A-Za-z]", text):
            return []
        normalized = re.sub(r"\s+", " ", text).strip()
        normalized = re.sub(r"^\s*this week\s+", "", normalized, flags=re.I)
        normalized = re.sub(r"\bI also need to\b", "||", normalized, flags=re.I)
        normalized = re.sub(r"\bI need to\b", "||", normalized, flags=re.I)
        normalized = re.sub(r"\bI have to\b", "||", normalized, flags=re.I)
        normalized = re.sub(r"\bI plan to\b", "||", normalized, flags=re.I)
        normalized = re.sub(
            r"\band\s+(?=(?:I\s+)?(?:also\s+)?(?:need|have|plan)\s+to\b|review\b|read\b|write\b|finish\b|complete\b|prepare\b|go\b|study\b|submit\b)",
            "||",
            normalized,
            flags=re.I,
        )
        normalized = re.sub(
            r",\s*(?=(?:review|read|write|finish|complete|prepare|go|study|submit)\b)",
            "||",
            normalized,
            flags=re.I,
        )
        parts = [re.sub(r"^\s*to\s+", "", part.strip(" .,!;:"), flags=re.I) for part in normalized.split("||") if part.strip(" .,!;:")]
        return parts if len(parts) > 1 else []

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
                        "task_type": "fixed_event",
                        "deadline": f"{day} {format_clock_hour(start)}",
                        "due": f"{day} {format_clock_hour(start)}",
                        "estimated_duration": duration,
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
        time_word = rf"(((早上|上午|中午|下午|晚上)\s*)?\d{{1,2}}\s*(点|时)|\d{{1,2}}[:：]\d{{2}}\s*(?:am|pm)?|\d{{1,2}}\s*(?:am|pm)|morning|afternoon|evening|night|noon)"
        relative_day = rf"(今天|今晚|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天]|today|tonight|tomorrow|tmr|tmrw|{ENGLISH_WEEKDAY}|every\s+(?:morning|afternoon|evening|night|day))"
        english_segments = self.english_task_segments(clean)
        connector_segments = english_segments or [
            part.strip(" ，,。；;、")
            for part in re.split(r"(?:然后|最后|再|接着|之后|，|,|。|；|;)", clean)
            if part.strip(" ，,。；;、")
        ]
        action_pattern = (
            r"(会议|开会|开.*会|组会|学习|复习|写|读|阅读|总结|整理|完善|完成|处理|准备|提交|看|做|备战|取|拿|办|买|发|"
            r"\b(?:finish|complete|write|read|review|study|prepare|design|eat|meet|meeting|submit)\b)"
        )
        merged_segments: list[str] = []
        for part in connector_segments:
            has_action = re.search(action_pattern, part)
            has_date_or_clock = re.search(relative_day, part, re.I) or re.search(time_word, part, re.I)
            has_duration_only = infer_duration_minutes(part) and not has_action and not has_date_or_clock
            if has_duration_only and merged_segments:
                merged_segments[-1] = f"{merged_segments[-1]}，{part}"
            else:
                merged_segments.append(part)
        connector_segments = merged_segments
        segment_pattern = re.compile(rf"((?:{relative_day})?\s*(?:{time_word})?[^，。；;、]*(?:{action_pattern})[^，。；;]*)")
        segments = [match.group(1).strip(" ，,。；;、") for match in segment_pattern.finditer(clean)]
        if connector_segments and len(connector_segments) >= len(segments):
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
            english_due = english_day_time_in_text(segment)
            chinese_due = chinese_day_time_in_text(segment)
            due_match = re.search(rf"({relative_day}\s*{time_word}|{time_word}\s*{relative_day}|{time_word}|{relative_day})", segment, re.I)
            due = english_due or chinese_due or (due_match.group(0) if due_match else "未设置")
            separate_time_match = re.search(time_word, segment)
            if due != "未设置" and day_match and separate_time_match and not re.search(time_word, due):
                due = f"{day_match.group(0)}{separate_time_match.group(0)}"
            if due != "未设置" and last_day and not english_due and not re.search(relative_day, due, re.I):
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
            title_text = re.sub(rf"({relative_day}|{time_word}|然后|最后|先|需要|进行|我们的|我们|这个|的|吧|之前|以前|前)", "", segment)
            title_text = re.sub(r"(这周|本周|我需要|我要|我在|我|在|并且|而且|以及)", "", title_text)
            title_text = re.sub(
                r"\b(i|we|the|a|an|to|at|on|by|before|after|need|needs|have|has|plan|planned|want|"
                r"finish|complete|do|work|work on|eat)\b",
                " ",
                title_text,
                flags=re.I,
            )
            title_text = re.sub(
                r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
                r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b\s*\d{1,2}",
                " ",
                title_text,
                flags=re.I,
            )
            title_text = re.sub(r"\d+\s*(个)?(?:-|–|—)?\s*(分钟|minutes?|mins?|min|小时|hours?|hrs?|h)", "", title_text, flags=re.I)
            title_text = re.sub(r"(大概|大约|预计|左右)", "", title_text)
            if re.search(r"[A-Za-z]", title_text):
                title_text = re.sub(r"\s+", " ", title_text).strip(" ，,。；;、") or segment
            else:
                title_text = re.sub(r"\s+", "", title_text).strip("，,。；;、") or segment
            if re.search(r"[A-Za-z]", title_text):
                title_text = re.sub(r"\b(?:this week|by|before|after|for|every|today|tonight|tomorrow|tmr|tmrw|monday|tuesday|wednesday|thursday|friday|saturday|sunday|morning|afternoon|evening|night|noon)\b", " ", title_text, flags=re.I)
                title_text = re.sub(r"\d{1,2}(?::\d{2})?\s*(?:am|pm)|\d{1,2}[:：]\d{2}", " ", title_text, flags=re.I)
                title_text = re.sub(r"\b(?:am|pm|minutes?|mins?|hours?|hrs?)\b", " ", title_text, flags=re.I)
                title_text = re.sub(r"\s+", " ", title_text).strip(" .,!;:") or segment
            for due_value in recurring_due_values(segment, due):
                is_recurring_time = due_value != due
                task = self.create_task(
                    user_id,
                    {
                        "title": title_text[:42],
                        "task_type": "fixed_event" if is_recurring_time else self.infer_schedule_task_type({"due": due_value, "context": segment}),
                        "deadline": due_value,
                        "due": due_value,
                        "estimated_duration": duration,
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

    def chat_turn_confidence(self, response: dict, chat_context: dict) -> float:
        confidence = 0.55
        features = response.get("features") or {}
        intent = response.get("intent") or features.get("intent")
        tasks = response.get("tasks") or []
        if intent and intent != "other":
            confidence += 0.12
        if tasks:
            confidence += 0.14
            missing_penalty = 0.0
            for task in tasks:
                due = str(task.get("deadline") or task.get("due") or "")
                duration = int(task.get("estimated_duration") or task.get("duration") or 0)
                if due in {"", "未设置"}:
                    missing_penalty += 0.08
                if duration <= 0:
                    missing_penalty += 0.08
            confidence -= min(missing_penalty, 0.18)
        if chat_context.get("retrieved_memories"):
            confidence += 0.06
        if features.get("needs_follow_up"):
            confidence -= 0.06
        if response.get("intent") == "reschedule":
            confidence += 0.04
        return round(max(0.05, min(confidence, 0.95)), 2)

    def text_mentions_task(self, text: str, task: dict) -> bool:
        lower_text = text.lower()
        alias_pairs = [
            ("system design", "系统设计"),
            ("lunch", "午饭"),
            ("breakfast", "早饭"),
            ("dinner", "晚饭"),
            ("final examination", "期末考试"),
            ("final exam", "期末考试"),
            ("exam", "考试"),
        ]
        searchable_text = lower_text
        for english, chinese in alias_pairs:
            if english in lower_text:
                searchable_text += f" {chinese}"
            if chinese in text:
                searchable_text += f" {english}"
        title = str(task.get("title") or "").strip()
        context_text = " ".join(str(task.get(key) or "") for key in ["context", "due", "deadline"]).strip()
        searchable = " ".join([title, context_text]).strip()
        if not title and not context_text:
            return False
        lower_title = title.lower()
        if lower_title and lower_title in searchable_text:
            return True
        stop_words = {
            "the", "and", "for", "with", "need", "needs", "have", "has", "plan",
            "finish", "complete", "task", "today", "tomorrow", "august",
            "move", "reschedule", "put", "schedule", "change", "set", "start", "shift",
        }
        title_tokens = [
            token for token in re.findall(r"[A-Za-z0-9]+", lower_title)
            if len(token) >= 3 and token not in stop_words
        ]
        title_hits = [token for token in title_tokens if token in searchable_text]
        if len(title_tokens) == 1 and title_hits:
            return True
        if len(title_hits) >= 2:
            return True
        context_tokens = [
            token for token in re.findall(r"[A-Za-z0-9]+", context_text.lower())
            if len(token) >= 3 and token not in stop_words
        ]
        context_hits = [token for token in context_tokens if token in searchable_text]
        if len(context_hits) >= 2:
            return True
        chinese_title = "".join(re.findall(r"[\u4e00-\u9fff]", searchable))
        if len(chinese_title) >= 2:
            fragments = {
                chinese_title[offset : offset + 2]
                for offset in range(len(chinese_title) - 1)
            }
            if any(fragment in searchable_text for fragment in fragments):
                return True
        return False

    def resolve_task_reference_context(self, text: str, chat_context: dict) -> dict:
        recent_tasks = (chat_context or {}).get("recent_tasks") or []
        active_tasks = (chat_context or {}).get("active_tasks") or []
        candidate_tasks = recent_tasks + [
            task for task in active_tasks
            if task.get("id") not in {recent.get("id") for recent in recent_tasks}
        ]
        lower_text = text.lower()
        has_time = re.search(r"\d{1,2}\s*(点|时)|\d{1,2}[:：]\d{2}", text)
        has_time_range = parse_clock_range(text) is not None
        explicit_reference = re.search(
            r"(这个|那个|它|该任务|上一条|上一个|刚刚|刚才|第\s*[一二两三四五六七八九\d]\s*个?|"
            r"\b(it|this|that|that task|the task|previous|last one|same task|first one|second one)\b)",
            lower_text,
            re.I,
        )
        edit_action = re.search(
            r"(改到|放到|安排到|移到|移动到|调整到|提前|推迟|换到|开始|"
            r"\b(move|reschedule|put|schedule|change|set|start|shift)\b)",
            lower_text,
            re.I,
        )
        new_topic = re.search(
            r"\b(i\s+also\s+have|also\s+have|i\s+have|i\s+plan\s+to|plan\s+to|need\s+to|have\s+to|"
            r"eat|lunch|breakfast|dinner|meal|final\s+exam|examination|exam|deadline|due|by)\b",
            lower_text,
        )
        title_matches = [task for task in candidate_tasks if self.text_mentions_task(text, task)]
        evidence = {
            "has_time": bool(has_time),
            "has_time_range": bool(has_time_range),
            "explicit_reference": bool(explicit_reference),
            "edit_action": bool(edit_action),
            "new_topic": bool(new_topic),
            "title_matches": [task.get("id") for task in title_matches],
        }
        if self.looks_like_compact_multi_task_list(text):
            return {"mode": "new_task", "confidence": 0.84, "target_tasks": [], "evidence": evidence}
        if new_topic and not explicit_reference and not title_matches:
            return {"mode": "new_task", "confidence": 0.82, "target_tasks": [], "evidence": evidence}
        if title_matches and (has_time or has_time_range or edit_action):
            return {"mode": "follow_up", "confidence": 0.86, "target_tasks": title_matches, "evidence": evidence}
        if explicit_reference and (has_time or has_time_range or edit_action) and recent_tasks:
            return {"mode": "follow_up", "confidence": 0.78, "target_tasks": recent_tasks, "evidence": evidence}
        if edit_action and has_time:
            return {"mode": "ambiguous", "confidence": 0.42, "target_tasks": [], "evidence": evidence}
        if has_time and recent_tasks and not explicit_reference and not title_matches and not edit_action:
            compact = re.sub(r"\d{1,2}\s*(点|时)|\d{1,2}[:：]\d{2}|at|to|on|今天|明天|周[一二三四五六日天]", "", lower_text)
            compact = re.sub(r"[\s,，。；;:：-]+", "", compact)
            if len(compact) <= 8:
                return {"mode": "ambiguous", "confidence": 0.38, "target_tasks": [], "evidence": evidence}
        return {"mode": "new_task", "confidence": 0.72, "target_tasks": [], "evidence": evidence}

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
        reference_context = self.resolve_task_reference_context(text, chat_context)
        response["context"]["reference_resolution"] = reference_context
        if reference_context["mode"] == "ambiguous":
            if reference_context.get("evidence", {}).get("edit_action"):
                response["reply"] = "我识别到你想调整时间，但没能确定要修改哪一个已有任务。请补充任务名称，或说“把上一条改到这个时间”。"
            else:
                response["reply"] = "这条只包含时间，我不确定是要修改上一条任务，还是新建一个事件。请补一句任务名称或说“把上一条改到这个时间”。"
            response["intent"] = "other"
            response["confidence"] = reference_context["confidence"]
            features = {**features, "confidence": response["confidence"], "reference_resolution": reference_context}
            response["features"] = features
            self.save_chat_turn(
                user_id=user_id,
                user_text=text,
                assistant_reply=response["reply"],
                intent=response["intent"],
                features=features,
                task_ids=[],
            )
            return response
        if reference_context["mode"] == "follow_up":
            followup_tasks = self.parse_time_followup_for_recent_tasks(
                user_id,
                text,
                chat_context,
                reference_context.get("target_tasks") or [],
            )
            if followup_tasks:
                response["tasks"] = followup_tasks
                response["reply"] = f"我已根据上下文把时间更新到 {len(followup_tasks)} 个已有任务上，并在右侧生成待确认安排。"
                intent = "reschedule"
                response["intent"] = intent
        lower_text = text.lower()
        task_keywords = [
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
            "组会",
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
            "need to",
            "todo",
            "task",
            "finish",
            "complete",
            "write",
            "read",
            "review",
            "study",
            "prepare",
            "exam",
            "examination",
            "plan to",
            "eat",
            "lunch",
            "breakfast",
            "dinner",
            "meal",
            "design",
            "deadline",
            "due",
            "today",
            "tomorrow",
            "august",
            "agust",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        should_parse_tasks = (
            intent in {"add_task", "reschedule"}
            or any(word in lower_text for word in task_keywords)
            or self.looks_like_compact_multi_task_list(text)
        ) and intent in {"add_task", "reschedule", "other", "progress_update"}
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
            response["reply"] = "收到中断情况。请补一句回来后第一步，我会把它作为恢复线索。"
        response["confidence"] = self.chat_turn_confidence(response, chat_context)
        features = {**features, "confidence": response["confidence"]}
        response["features"] = features
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

    def list_chat_turns(self, user_id: str, limit: int = CHAT_CONTEXT_TURN_LIMIT) -> list[dict]:
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
            tasks = [self.get_task(task_id, user_id=user_id) for task_id in task_ids if task_id]
            tasks = [task for task in tasks if task and task.get("status") not in {"completed", "terminated"}]
            if tasks:
                return tasks
        return []

    def parse_time_followup_for_recent_tasks(
        self,
        user_id: str,
        text: str,
        chat_context: dict | None = None,
        target_tasks: list[dict] | None = None,
    ) -> list[dict]:
        recent_tasks = target_tasks or []
        if not recent_tasks:
            return []
        if self.looks_like_compact_multi_task_list(text):
            return []
        has_time = re.search(r"\d{1,2}\s*(点|时)|\d{1,2}[:：]\d{2}", text)
        if not has_time:
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
            if target_index is None and len(recent_tasks) == 1:
                target_index = 0
            if target_index is None and re.search(r"(都是|每个|all|each|every)", text, re.I):
                for index, task in enumerate(recent_tasks):
                    if index in used_indexes:
                        continue
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
            start = normalize_calendar_hour(start, duration)
            updated = self.patch_task(
                task["id"],
                {
                    "task_type": "fixed_event",
                    "deadline": f"{day} {format_clock_hour(start)}",
                    "due": f"{day} {format_clock_hour(start)}",
                    "estimated_duration": duration,
                    "duration": duration,
                    "context": f"{task.get('context') or task.get('title')}；时间补充：{part}",
                },
                user_id=user_id,
            )
            updated["parser"] = "time_followup"
            updated_tasks.append(updated)
        return updated_tasks

    def get_task(self, task_id: str, user_id: str | None = None) -> dict | None:
        with self.connect() as conn:
            if user_id:
                row = conn.execute("SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)).fetchone()
            else:
                row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self.task_row(row) if row else None

    def list_tasks(self, user_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE user_id=? ORDER BY created_at ASC", (user_id,)
            ).fetchall()
        return [self.task_row(row) for row in rows]

    def build_chat_context(self, user_id: str, text: str) -> dict:
        turns = self.list_chat_turns(user_id, limit=CHAT_CONTEXT_TURN_LIMIT)
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
                " ".join(turn.get("user_text", "") for turn in turns[-10:]),
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
                for turn in turns[-CHAT_CONTEXT_TURN_LIMIT:]
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
            "active_tasks": [
                {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "due": task.get("due"),
                    "duration": task.get("duration"),
                    "status": task.get("status"),
                    "context": task.get("context"),
                }
                for task in active_tasks[-12:]
            ],
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
        context_window = from_json(row["context_window_json"], {})
        deadline = context_window.get("deadline") or row["due"]
        estimated_duration = context_window.get("estimatedDuration") or row["duration"]
        schedule_task_type = context_window.get("taskType") or self.infer_schedule_task_type(
            {"due": row["due"], "context": row["context"]}
        )
        dimensions = context_window.get("dimensions")
        if not isinstance(dimensions, dict):
            dimensions = self.local_task_dimensions(
                {
                    "title": row["title"],
                    "context": row["context"],
                    "task_type": schedule_task_type,
                    "deadline": deadline,
                    "estimated_duration": estimated_duration,
                    "cognitive_load": row["cognitive_load"],
                    "ambiguity": row["ambiguity"],
                }
            )
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "title": row["title"],
            "type": row["type"],
            "task_type": schedule_task_type,
            "due": row["due"],
            "deadline": deadline,
            "duration": infer_duration_minutes(f"{row['title']} {row['context']}") or row["duration"],
            "estimated_duration": estimated_duration,
            "priority": row["priority"],
            "status": row["status"],
            "context": row["context"],
            "contextWindow": context_window,
            "dimensions": dimensions,
            "cognitive_load": row["cognitive_load"],
            "ambiguity": row["ambiguity"],
            "switch_cost": row["switch_cost"],
            "reentry_cost": row["reentry_cost"],
            "slot": from_json(row["slot_json"], None),
            "checkpoints": from_json(row["checkpoints_json"], []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def patch_task(self, task_id: str, patch: dict, user_id: str | None = None) -> dict:
        current = self.get_task(task_id, user_id=user_id)
        if not current:
            raise KeyError(task_id)
        if "deadline" in patch and "due" not in patch:
            patch["due"] = patch["deadline"]
        if "estimated_duration" in patch and "duration" not in patch:
            patch["duration"] = patch["estimated_duration"]
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
        }
        updates: dict[str, object] = {k: v for k, v in patch.items() if k in allowed}
        if "slot" in patch:
            updates["slot_json"] = as_json(patch["slot"])
        if "checkpoints" in patch:
            updates["checkpoints_json"] = as_json(patch["checkpoints"])
        if "contextWindow" in patch or "context_window" in patch:
            current_window = current.get("contextWindow") or {}
            incoming_window = patch.get("contextWindow") or patch.get("context_window") or {}
            if not isinstance(current_window, dict):
                current_window = {}
            if not isinstance(incoming_window, dict):
                incoming_window = {}
            updates["context_window_json"] = as_json({**current_window, **incoming_window})
        if any(key in patch for key in ["deadline", "estimated_duration", "task_type", "taskType"]):
            context_window = dict(
                {
                    **(current.get("contextWindow") or {}),
                    **(patch.get("contextWindow") or patch.get("context_window") or {}),
                }
            )
            if "deadline" in patch:
                context_window["deadline"] = patch["deadline"]
            if "estimated_duration" in patch:
                context_window["estimatedDuration"] = patch["estimated_duration"]
            if "task_type" in patch or "taskType" in patch:
                context_window["taskType"] = patch.get("task_type") or patch.get("taskType")
            updates["context_window_json"] = as_json(context_window)
        updates["updated_at"] = now_ms()
        assignments = ", ".join(f"{key}=?" for key in updates)
        values = list(updates.values())
        with self.connect() as conn:
            if user_id:
                values.extend([task_id, user_id])
                conn.execute(f"UPDATE tasks SET {assignments} WHERE id=? AND user_id=?", values)
            else:
                values.append(task_id)
                conn.execute(f"UPDATE tasks SET {assignments} WHERE id=?", values)
        self.log_event(current["user_id"], "task_updated", {"task_id": task_id, "patch": patch})
        return self.get_task(task_id, user_id=user_id) or {}

    def delete_task(self, task_id: str, user_id: str | None = None) -> dict:
        current = self.get_task(task_id, user_id=user_id)
        if not current:
            raise KeyError(task_id)
        with self.connect() as conn:
            if user_id:
                conn.execute("DELETE FROM context_dumps WHERE task_id=? AND user_id=?", (task_id, user_id))
                conn.execute("DELETE FROM memories WHERE user_id=? AND (task_id=? OR source_id=?)", (user_id, task_id, task_id))
                conn.execute("DELETE FROM events WHERE user_id=? AND payload_json LIKE ?", (user_id, f"%{task_id}%"))
                conn.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
            else:
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
            "created_at": now_ms(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_states (
                  id, user_id, focus, energy, stress, mood,
                  attention_residue, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state["id"],
                    user_id,
                    state["focus"],
                    state["energy"],
                    state["stress"],
                    state["mood"],
                    state["attention_residue"],
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
            return {"focus": 5, "energy": 4, "stress": 5, "attention_residue": ""}
        return dict(row)

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
            {"label": "当前进展", "text": dump["progress"]},
            {"label": "未解决问题", "text": "；".join(dump["open_questions"]) or "暂无"},
            {"label": "下一步", "text": dump["next_action"] or "恢复时先重新确认下一步。"},
        ]
        self.patch_task(task_id, {"status": "paused", "checkpoints": checkpoints}, user_id=user_id)
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

    def decide_schedule(self, user_id: str, payload: dict) -> dict:
        from humanos_graph import run_schedule_graph

        decision = run_schedule_graph(self, user_id, payload)
        self.log_event(user_id, "schedule_decision", decision)
        return decision

    def build_schedule_query(self, tasks: list[dict], state: dict) -> str:
        task_text = "; ".join(
            (
                f"{t.get('title')} {t.get('task_type') or t.get('type')} "
                f"deadline={t.get('deadline') or t.get('due')} "
                f"duration={t.get('estimated_duration') or t.get('duration')} "
                f"status={t.get('status')}"
            )
            for t in tasks[:8]
        )
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
        llm_result = chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 HumanOS 的调度解释 agent。只输出 JSON。"
                        "不要说你在收集数据、沉淀画像、使用 embedding 或后端。"
                        "解释要面向学生，简短、具体、可操作。"
                    ),
                },
                {
                    "role": "user",
                    "content": as_json(
                        {
                            "profile": profile,
                            "runtime_state": runtime_state,
                            "tasks": tasks[:6],
                            "memory_evidence": memories[:3],
                            "current_decision": decision,
                            "required_schema": {
                                "explanation": "一句中文安排理由",
                                "first_action": "用户现在可以立刻开始的一步",
                                "risk": "可能卡住的原因",
                            },
                        }
                    ),
                },
            ]
        )
        if not isinstance(llm_result, dict):
            decision["llm_provider"] = "local_fallback"
            return decision
        decision["explanation"] = llm_result.get("explanation") or decision.get("explanation", "")
        decision["first_action"] = llm_result.get("first_action", "")
        decision["risk"] = llm_result.get("risk", "")
        decision["llm_provider"] = "deepseek"
        return decision

    def reentry_prompt(self, user_id: str, payload: dict) -> dict:
        task_id = payload["task_id"]
        task = self.get_task(task_id, user_id=user_id)
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
                self.send_json({"ok": True, "db": str(DB_PATH), "embedding_model": "humanos-local-hash-embedding-v1"})
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
                tasks = store.parse_tasks_from_text(user_id, payload.get("text", ""))
                self.send_json({"tasks": tasks}, status=201)
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
                payload = self.read_json()
                user_id = payload.get("user_id") or query.get("user_id", [""])[0]
                if not user_id:
                    self.send_json({"error": "user_id is required"}, status=400)
                    return
                store.ensure_profile(user_id)
                self.send_json({"task": store.patch_task(task_id, payload, user_id=user_id)})
                return

            if path.startswith("/api/tasks/") and method == "DELETE":
                task_id = path.split("/")[-1]
                user_id = query.get("user_id", [""])[0]
                if not user_id:
                    self.send_json({"error": "user_id is required"}, status=400)
                    return
                store.ensure_profile(user_id)
                self.send_json({"task": store.delete_task(task_id, user_id=user_id)})
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
    port = 8787
    print(f"HumanOS backend listening on http://127.0.0.1:{port}")
    print(f"External access uses http://<server-ip>:{port}")
    print(f"SQLite database: {DB_PATH}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
