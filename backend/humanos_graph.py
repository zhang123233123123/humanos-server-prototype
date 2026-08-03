"""LangGraph orchestration for HumanOS scheduling.

The graph is dependency-tolerant: when `langgraph` is installed, HumanOS uses a
real StateGraph. Without it, the same nodes run sequentially so the MVP remains
usable on a clean machine.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, TypedDict


class HumanOSState(TypedDict, total=False):
    user_id: str
    payload: dict[str, Any]
    profile: dict[str, Any]
    tasks: list[dict[str, Any]]
    runtime_state: dict[str, Any]
    query: str
    memories: list[dict[str, Any]]
    plan_patch: list[dict[str, Any]]
    joint_state: dict[str, Any]
    candidate_actions: list[dict[str, Any]]
    parallel_suggestions: list[dict[str, Any]]
    explanation: str
    confidence: str | dict[str, Any]
    requires_confirmation: bool
    reasons: list[str]
    decision: dict[str, Any]
    constraint_summary: dict[str, Any]
    unscheduled_tasks: list[dict[str, Any]]
    low_confidence_demand: list[dict[str, Any]]
    ai_task_analysis: dict[str, Any]
    candidate_plans: list[dict[str, Any]]
    validation: dict[str, Any]
    repair_suggestions: list[dict[str, Any]]


def load_profile_node(store: Any):
    def node(state: HumanOSState) -> HumanOSState:
        return {"profile": store.ensure_profile(state["user_id"])}

    return node


def load_task_state_node(store: Any):
    def node(state: HumanOSState) -> HumanOSState:
        payload = state.get("payload", {})
        user_id = state["user_id"]
        tasks = payload.get("tasks") or store.list_tasks(user_id)
        runtime_state = payload.get("runtime_state") or store.latest_runtime_state(user_id)
        query = payload.get("query") or store.build_schedule_query(tasks, runtime_state)
        return {"tasks": tasks, "runtime_state": runtime_state, "query": query}

    return node


def retrieve_memory_node(store: Any):
    def node(state: HumanOSState) -> HumanOSState:
        memories = store.search_memories(state["user_id"], state.get("query", ""), top_k=4)
        return {"memories": memories}

    return node


def analyze_inputs_node(store: Any):
    def node(state: HumanOSState) -> HumanOSState:
        analysis = store.analyze_schedule_inputs(state)
        return {"ai_task_analysis": analysis}

    return node


def parse_due_start_hour(due: str | None) -> float | None:
    text = str(due or "")
    colon_match = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if colon_match:
        hour = int(colon_match.group(1))
        minute = int(colon_match.group(2))
        if re.search(r"下午|晚上", text) and hour < 12:
            hour += 12
        if "中午" in text and hour < 11:
            hour += 12
        return hour + minute / 60
    hour_match = re.search(r"(早上|上午|中午|下午|晚上)?\s*(\d{1,2})\s*(点|时)", text)
    if not hour_match:
        return None
    period = hour_match.group(1) or ""
    hour = int(hour_match.group(2))
    if period in {"下午", "晚上"} and hour < 12:
        hour += 12
    if period == "中午" and hour < 11:
        hour += 12
    return float(hour)


WEEKDAY_INDEX = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def day_index_from_due(due: str | None) -> int | None:
    match = re.search(r"(?:周|星期)([一二三四五六日天])", str(due or ""))
    return WEEKDAY_INDEX.get(match.group(1)) if match else None


def segment_covers_day(segment: str, target_day: int) -> bool:
    range_match = re.search(r"周([一二三四五六日天])\s*(?:至|到|-)\s*周?([一二三四五六日天])", segment)
    if range_match:
        return WEEKDAY_INDEX[range_match.group(1)] <= target_day <= WEEKDAY_INDEX[range_match.group(2)]
    return any(WEEKDAY_INDEX[day] == target_day for day in re.findall(r"(?:周|星期)([一二三四五六日天])", segment))


def day_indices_from_text(text: str | None) -> list[int]:
    clean = str(text or "")
    indices: set[int] = set()
    if re.search(r"每天|每日", clean):
        indices.update(range(7))
    if "工作日" in clean:
        indices.update(range(5))
    if "周末" in clean:
        indices.update({5, 6})
    for start_text, end_text in re.findall(r"周([一二三四五六日天])\s*(?:至|到|[-–—])\s*周?([一二三四五六日天])", clean):
        start, end = WEEKDAY_INDEX[start_text], WEEKDAY_INDEX[end_text]
        indices.update(range(start, end + 1))
    indices.update(WEEKDAY_INDEX[day] for day in re.findall(r"(?:周|星期)([一二三四五六日天])", clean))
    return sorted(indices)


def parse_clock_token(token: str, context: str = "") -> float | None:
    match = re.search(r"(\d{1,2})(?:[:：](\d{2}))?", token)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    token_period = re.search(r"早上|上午|中午|下午|晚上", token)
    fallback_period = re.search(r"早上|上午|中午|下午|晚上", context)
    period = token_period.group(0) if token_period else fallback_period.group(0) if fallback_period else ""
    if period in {"下午", "晚上"} and hour < 12:
        hour += 12
    if period == "中午" and hour < 11:
        hour += 12
    return hour + minute / 60


def time_range_from_text(text: str | None) -> dict[str, Any] | None:
    clean = str(text or "")
    match = re.search(r"((?:(?:早上|上午|中午|下午|晚上)\s*)?\d{1,2}(?:[:：]\d{2})?)\s*(?:至|到|[-–—])\s*((?:(?:早上|上午|中午|下午|晚上)\s*)?\d{1,2}(?:[:：]\d{2})?)", clean)
    if match:
        start_period_match = re.search(r"早上|上午|中午|下午|晚上", match.group(1))
        start_period = start_period_match.group(0) if start_period_match else ""
        start = parse_clock_token(match.group(1))
        end = parse_clock_token(match.group(2), start_period)
        if start is not None and end is not None and end > start:
            return {"start": start, "end": end, "explicit_end": True}
    if re.search(r"上午|早上", clean):
        return {"start": 8.0, "end": 12.0, "explicit_end": True}
    if "中午" in clean:
        return {"start": 11.5, "end": 13.5, "explicit_end": True}
    if "下午" in clean:
        return {"start": 12.0, "end": 18.0, "explicit_end": True}
    if "晚上" in clean:
        return {"start": 18.0, "end": 23.0, "explicit_end": True}
    single = parse_due_start_hour(clean)
    return None if single is None else {"start": single, "end": None, "explicit_end": False}


def classify_weekly_activity(text: str) -> str:
    if re.search(r"^\s*日常", text):
        return "recurring_routine"
    if re.search(r"^\s*可移动", text):
        return "flexible_activity"
    if re.search(r"^\s*固定", text):
        return "fixed_event"
    if re.search(r"午饭|晚饭|早餐|通勤|睡眠|接送|日常", text):
        return "recurring_routine"
    if re.search(r"健身|运动|洗衣|购物|打扫|散步", text):
        return "flexible_activity"
    return "fixed_event"


def list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in re.split(r"[,，、/；;\n]", str(value or "")) if item.strip()]


def parse_available_windows(profile: dict[str, Any]) -> list[dict[str, Any]]:
    raw = str(profile.get("weekly_context", {}).get("weekly_available_windows") or "")
    windows: list[dict[str, Any]] = []
    for segment in [item.strip() for item in re.split(r"[；;\n]", raw) if item.strip()]:
        days = day_indices_from_text(segment)
        time_range = time_range_from_text(segment)
        if not days or not time_range or not time_range["explicit_end"]:
            continue
        for day in days:
            windows.append({"day_index": day, "start": time_range["start"], "end": time_range["end"], "source": segment})
    return windows


def hard_constraint_intervals(profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    weekly = profile.get("weekly_context", {})
    items: list[dict[str, Any]] = []
    for text in list_value(weekly.get("fixed_events")):
        activity_type = classify_weekly_activity(text)
        if activity_type != "flexible_activity":
            items.append({"text": text, "type": activity_type, "days": day_indices_from_text(text), "range": time_range_from_text(text)})
    for text in list_value(weekly.get("temporary_constraints")):
        items.append({"text": text, "type": "temporary_constraint", "days": day_indices_from_text(text), "range": time_range_from_text(text)})
    for text in list_value(weekly.get("other_commitments") or weekly.get("important_deadlines")):
        items.append({"text": text, "type": "other_commitment", "days": day_indices_from_text(text), "range": time_range_from_text(text)})

    intervals: list[dict[str, Any]] = []
    uncertain: list[str] = []
    for item in items:
        if not item["days"] or not item["range"]:
            uncertain.append(item["text"])
            continue
        if item["range"]["end"] is None and item["type"] not in {"recurring_routine", "other_commitment"}:
            uncertain.append(item["text"])
            continue
        for day in item["days"]:
            end = item["range"]["end"]
            if end is None:
                end = item["range"]["start"] + (1 if item["type"] == "recurring_routine" else 0.5)
            intervals.append({
                "day_index": day,
                "start": item["range"]["start"],
                "end": min(end, 24.0),
                "label": item["text"],
                "source_type": item["type"],
                "inferred": item["range"]["end"] is None,
                "confidence": "medium" if item["range"]["end"] is None else "high",
            })
    return intervals, uncertain


def flexible_activity_duration_minutes(text: str) -> int:
    explicit = re.search(r"(?:时长|持续)\s*(\d+)\s*(分钟|min|小时|h)", text, re.IGNORECASE)
    if explicit:
        amount = int(explicit.group(1))
        return amount * 60 if re.search(r"小时|h", explicit.group(2), re.IGNORECASE) else amount
    if re.search(r"午饭|晚饭|早餐|吃饭|用餐", text):
        return 60
    if re.search(r"通勤|接送", text):
        return 45
    if re.search(r"健身|运动|购物", text):
        return 60
    return 45


def flexible_activity_intervals(profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    weekly = profile.get("weekly_context", {})
    intervals: list[dict[str, Any]] = []
    uncertain: list[str] = []
    for text in list_value(weekly.get("fixed_events")):
        if classify_weekly_activity(text) != "flexible_activity":
            continue
        days = day_indices_from_text(text)
        activity_range = time_range_from_text(text)
        if not days or not activity_range or not activity_range.get("explicit_end"):
            uncertain.append(f"{text}（AI 安排需要一个可发生范围）")
            continue
        window_start = float(activity_range["start"])
        window_end = float(activity_range["end"])
        duration_minutes = min(flexible_activity_duration_minutes(text), max(round((window_end - window_start) * 60), 15))
        preferred_start = 12.0 if re.search(r"午饭|吃午饭", text) else 18.0 if "晚饭" in text else 8.0 if "早餐" in text else window_start
        selected_start = max(window_start, min(preferred_start, window_end - duration_minutes / 60))
        for day in days:
            intervals.append({
                "day_index": day,
                "start": selected_start,
                "end": selected_start + duration_minutes / 60,
                "label": text,
                "source_type": "flexible_activity",
                "availability_window": {"start": window_start, "end": window_end},
                "inferred": True,
                "confidence": "medium",
            })
    return intervals, uncertain


def subtract_interval(window: dict[str, Any], busy: dict[str, Any]) -> list[dict[str, Any]]:
    if busy["end"] <= window["start"] or busy["start"] >= window["end"]:
        return [window]
    parts = []
    if busy["start"] > window["start"]:
        parts.append({**window, "end": min(busy["start"], window["end"])})
    if busy["end"] < window["end"]:
        parts.append({**window, "start": max(busy["end"], window["start"])})
    return [part for part in parts if part["end"] - part["start"] >= 0.25]


def build_scheduling_context(profile: dict[str, Any]) -> dict[str, Any]:
    weekly = profile.get("weekly_context", {})
    rest_minutes = int(profile.get("task_preferences", {}).get("rest_between_tasks_minutes") or 10)
    intervals, uncertain = hard_constraint_intervals(profile)
    flexible_blocks, flexible_uncertain = flexible_activity_intervals(profile)
    windows = parse_available_windows(profile)
    for busy in [*intervals, *flexible_blocks]:
        windows = [part for window in windows for part in (subtract_interval(window, busy) if window["day_index"] == busy["day_index"] else [window])]
    keep_buffer = weekly.get("keep_buffer") is not False
    buffer_blocks: list[dict[str, Any]] = []
    if keep_buffer:
        buffered: list[dict[str, Any]] = []
        for day in range(7):
            day_windows = sorted((window for window in windows if window["day_index"] == day), key=lambda item: item["start"])
            total_minutes = sum((window["end"] - window["start"]) * 60 for window in day_windows)
            reserve_left = max(rest_minutes, round(total_minutes * 0.15)) if total_minutes else 0
            adjusted = [{**window, "reserved_buffer_minutes": 0} for window in day_windows]
            for window in reversed(adjusted):
                available = max((window["end"] - window["start"]) * 60 - 15, 0)
                take = min(reserve_left, available)
                if take <= 0:
                    continue
                buffer_start = window["end"] - take / 60
                buffer_blocks.append({
                    "day_index": day,
                    "start": buffer_start,
                    "end": window["end"],
                    "label": "可调整 Buffer",
                    "source_type": "buffer",
                })
                window["end"] = buffer_start
                window["reserved_buffer_minutes"] += round(take)
                reserve_left -= take
            buffered.extend(window for window in adjusted if window["end"] - window["start"] >= 0.25)
        windows = buffered
    return {
        "windows": windows,
        "hard_constraints": intervals,
        "flexible_activity_blocks": flexible_blocks,
        "buffer_blocks": buffer_blocks,
        "uncertain_constraints": [*uncertain, *flexible_uncertain],
        "keep_buffer": keep_buffer,
        "rest_minutes": rest_minutes,
    }


def task_demand_hypothesis(task: dict[str, Any]) -> dict[str, Any]:
    raw_expected = task.get("expected_difficulty") or task.get("task_demand", {}).get("expected_difficulty")
    expected = int(raw_expected) if str(raw_expected or "").isdigit() else None
    if expected is not None:
        return {
            "level": "high" if expected >= 6 else "low" if expected <= 2 else "medium",
            "expected_difficulty": expected,
            "evidence": task.get("task_demand", {}).get("evidence") or [f"user expected_difficulty={expected}/7"],
            "confidence": task.get("task_demand", {}).get("confidence_level") or "high",
        }
    text = f"{task.get('title', '')} {task.get('context', '')}"
    high = bool(re.search(r"论文|写作|编程|代码|分析|研究|设计|复杂|初稿|proposal", text, re.I))
    low = bool(re.search(r"邮件|整理|预约|打印|提交|行政|纪要", text, re.I))
    label = "费力" if high else "轻松" if low else "一般"
    return {"level": "high" if high else "low" if low else "medium", "expected_difficulty": None, "evidence": [f"AI 根据任务名称与描述初步估计：{label}"], "confidence": "low"}


def scheduler_node(_: Any):
    def node(state: HumanOSState) -> HumanOSState:
        tasks = state.get("tasks", [])
        runtime_state = state.get("runtime_state", {})
        profile = state.get("profile", {})
        ai_analysis = state.get("ai_task_analysis", {}) or {}
        energy = int(runtime_state.get("energy", 4))
        focus = int(runtime_state.get("focus", 4))
        stress = int(runtime_state.get("stress", 4))
        context = build_scheduling_context(profile)
        rest_minutes = context["rest_minutes"]
        preferred_session_minutes = min(max(int(profile.get("task_preferences", {}).get("preferred_session_minutes") or 45), 15), 180)
        now = datetime.now()
        today_index = now.weekday()
        current_hour = now.hour + now.minute / 60
        next_quarter_hour = min(24.0, round((current_hour + 0.2499) * 4) / 4)
        palette = ["blue", "green", "violet", "gold"]
        priority_rank = {"高": 0, "中": 1, "低": 2}
        deep_work_start = parse_due_start_hour(profile.get("deep_work_window")) or 9.0
        low_energy_start = parse_due_start_hour(profile.get("low_energy_window")) or 14.0
        needs_clarification: list[dict[str, Any]] = []
        blocked_tasks: list[dict[str, Any]] = []
        ready_tasks: list[dict[str, Any]] = []
        low_confidence_demand: list[dict[str, Any]] = []

        for task in tasks:
            if task.get("status") in {"completed", "terminated", "paused"}:
                continue
            if task.get("status") == "blocked":
                blocked_tasks.append(task)
                continue
            missing = [key for key in ("due", "duration") if not task.get(key) or task.get(key) == "未设置"]
            if missing:
                needs_clarification.append({"task_id": task.get("id"), "missing": missing})
                continue
            ready_tasks.append(task)

        ai_demands = {
            str(item.get("task_id")): item
            for item in ai_analysis.get("task_demands", [])
            if isinstance(item, dict) and item.get("task_id")
        }
        dependencies = [item for item in ai_analysis.get("dependencies", []) if isinstance(item, dict)]

        def demand_for(task: dict[str, Any]) -> dict[str, Any]:
            fallback = task_demand_hypothesis(task)
            hypothesis = ai_demands.get(str(task.get("id")))
            if not hypothesis:
                return fallback
            level = hypothesis.get("level") if hypothesis.get("level") in {"low", "medium", "high"} else fallback["level"]
            evidence = [str(item) for item in hypothesis.get("evidence", []) if str(item).strip()] or fallback["evidence"]
            return {
                "level": level,
                "expected_difficulty": fallback.get("expected_difficulty"),
                "evidence": evidence,
                "confidence": hypothesis.get("confidence_level") or fallback["confidence"],
            }

        for task in ready_tasks:
            demand = demand_for(task)
            if demand["confidence"] == "low":
                low_confidence_demand.append({"task_id": task.get("id"), "title": task.get("title"), "evidence": demand["evidence"]})

        def task_kind(task: dict[str, Any]) -> str:
            return str(task.get("task_type") or task.get("contextWindow", {}).get("taskType") or task.get("context_window", {}).get("taskType") or "flexible_task")

        def dependency_rank(task_id: str) -> int:
            rank = 0
            changed = True
            while changed and rank < len(ready_tasks):
                changed = False
                for edge in dependencies:
                    before = str(edge.get("before_task_id") or edge.get("predecessor_task_id") or "")
                    after = str(edge.get("after_task_id") or edge.get("successor_task_id") or "")
                    if after == task_id and before:
                        before_rank = dependency_rank.cache.get(before, 0)
                        if before_rank + 1 > rank:
                            rank = before_rank + 1
                            changed = True
                dependency_rank.cache[task_id] = rank
            return rank

        dependency_rank.cache = {}  # type: ignore[attr-defined]
        for task in ready_tasks:
            dependency_rank(str(task.get("id")))

        def ordered_tasks(strategy: str) -> list[dict[str, Any]]:
            def key(task: dict[str, Any]) -> tuple[Any, ...]:
                due_day = day_index_from_due(task.get("due"))
                dependency = dependency_rank.cache.get(str(task.get("id")), 0)  # type: ignore[attr-defined]
                high_load = 0 if demand_for(task)["level"] == "high" else 1
                if strategy == "energy_fit":
                    return (dependency, due_day if due_day is not None else 7, high_load, priority_rank.get(task.get("priority"), 1))
                if strategy == "balanced":
                    return (dependency, priority_rank.get(task.get("priority"), 1), due_day if due_day is not None else 7, high_load)
                return (dependency, due_day if due_day is not None else 7, priority_rank.get(task.get("priority"), 1), high_load)

            return sorted(ready_tasks, key=key)

        def initial_windows() -> list[dict[str, Any]]:
            usable = []
            for window in context["windows"]:
                if window["day_index"] < today_index:
                    continue
                candidate = {**window}
                if candidate["day_index"] == today_index:
                    candidate["start"] = max(candidate["start"], next_quarter_hour)
                if candidate["end"] - candidate["start"] >= 0.25:
                    usable.append(candidate)
            return usable

        def subtract_busy(windows: list[dict[str, Any]], block: dict[str, Any], include_rest: bool = True) -> list[dict[str, Any]]:
            busy = {
                "start": block["start"],
                "end": block["end"] + (rest_minutes / 60 if include_rest else 0),
            }
            return [
                part
                for window in windows
                for part in (subtract_interval(window, busy) if window["day_index"] == block["day_index"] else [window])
            ]

        def fixed_task_blocks(strategy: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            blocks: list[dict[str, Any]] = []
            windows = initial_windows()
            for index, task in enumerate(ordered_tasks(strategy)):
                if task_kind(task) != "fixed_event":
                    continue
                day = day_index_from_due(task.get("due"))
                start = parse_due_start_hour(task.get("due"))
                if day is None or start is None:
                    continue
                minutes = max(int(task.get("duration") or 30), 5)
                block = {
                    "block_id": f"{task['id']}-fixed",
                    "task_id": task["id"],
                    "day_index": day,
                    "deadline_day_index": day,
                    "start": start,
                    "end": start + minutes / 60,
                    "color": "context",
                    "kind": "fixed_event",
                    "mode": "fixed",
                    "session_minutes": minutes,
                    "total_task_minutes": minutes,
                    "remaining_after_block_minutes": 0,
                    "constraint_evidence": ["用户提供的固定开始时间"],
                    "state_scope": "fixed_context",
                }
                blocks.append(block)
                windows = subtract_busy(windows, block, include_rest=False)
            return blocks, windows

        def candidate_score(window: dict[str, Any], start: float, task: dict[str, Any], strategy: str, daily_load: dict[int, int]) -> float:
            demand = demand_for(task)
            preferred_start = low_energy_start if demand["level"] == "low" else deep_work_start
            day_distance = max(window["day_index"] - today_index, 0)
            energy_penalty = abs(start - preferred_start) * (6 if strategy == "energy_fit" else 2)
            balance_penalty = daily_load.get(window["day_index"], 0) / (12 if strategy == "balanced" else 40)
            urgency_penalty = day_distance * (45 if strategy == "deadline_first" else 12)
            return energy_penalty + balance_penalty + urgency_penalty + start / 48

        def select_slot(
            windows: list[dict[str, Any]],
            task: dict[str, Any],
            requested_minutes: int,
            strategy: str,
            daily_load: dict[int, int],
        ) -> dict[str, Any] | None:
            deadline_day = day_index_from_due(task.get("due"))
            if deadline_day is None:
                return None
            parsed_deadline_hour = parse_due_start_hour(task.get("due"))
            deadline_hour = parsed_deadline_hour if parsed_deadline_hour is not None else 24.0
            demand = demand_for(task)
            preferred_start = low_energy_start if demand["level"] == "low" else deep_work_start
            candidates: list[dict[str, Any]] = []
            for window in windows:
                if window["day_index"] > deadline_day:
                    continue
                effective_end = min(window["end"], deadline_hour) if window["day_index"] == deadline_day else window["end"]
                available_minutes = max(int(round((effective_end - window["start"]) * 60)), 0)
                if available_minutes < min(requested_minutes, 5):
                    continue
                session_minutes = min(requested_minutes, available_minutes)
                if session_minutes < requested_minutes and available_minutes < 15 and requested_minutes > 15:
                    continue
                duration = session_minutes / 60
                starts = [window["start"]]
                preferred = min(max(preferred_start, window["start"]), max(window["start"], effective_end - duration))
                if abs(preferred - starts[0]) > 0.01:
                    starts.append(preferred)
                for start in starts:
                    if start + duration <= effective_end + 0.001:
                        candidates.append({
                            "window": window,
                            "start": start,
                            "end": start + duration,
                            "session_minutes": session_minutes,
                            "score": candidate_score(window, start, task, strategy, daily_load),
                        })
            return min(candidates, key=lambda item: item["score"]) if candidates else None

        def validate_plan(blocks: list[dict[str, Any]], windows: list[dict[str, Any]]) -> dict[str, Any]:
            violations: list[dict[str, Any]] = []
            flexible_blocks = [block for block in blocks if block.get("kind") != "fixed_event"]
            for block in flexible_blocks:
                if block["day_index"] == today_index and block["start"] < next_quarter_hour - 0.001:
                    violations.append({"type": "past_time", "block_id": block["block_id"], "task_id": block["task_id"]})
                inside = any(
                    window["day_index"] == block["day_index"]
                    and block["start"] >= window["start"] - 0.001
                    and block["end"] <= window["end"] + 0.001
                    for window in context["windows"]
                )
                if not inside:
                    violations.append({"type": "outside_available_window", "block_id": block["block_id"], "task_id": block["task_id"]})
            for day in range(7):
                ordered = sorted((block for block in blocks if block["day_index"] == day), key=lambda item: item["start"])
                for previous, current in zip(ordered, ordered[1:]):
                    if current["start"] < previous["end"] - 0.001:
                        violations.append({"type": "overlap", "block_ids": [previous["block_id"], current["block_id"]]})
            return {"valid": not violations, "violations": violations}

        def generate_candidate(strategy: str, label: str) -> dict[str, Any]:
            blocks, free_windows = fixed_task_blocks(strategy)
            daily_load: dict[int, int] = {}
            unscheduled: list[dict[str, Any]] = []
            low_capacity = energy <= 3 or focus <= 3 or stress >= 6
            today_state_used = False
            session_counter: dict[str, int] = {}
            flexible_tasks = [task for task in ordered_tasks(strategy) if task_kind(task) != "fixed_event"]
            for task_index, task in enumerate(flexible_tasks):
                total_minutes = max(int(task.get("execution", {}).get("remaining_duration_minutes") or task.get("duration", 60)), 5)
                remaining = total_minutes
                deadline_day = day_index_from_due(task.get("due"))
                if deadline_day is None:
                    unscheduled.append({"task_id": task.get("id"), "remaining_minutes": remaining, "reason": "无法识别完成期限"})
                    continue
                demand = demand_for(task)
                safety = 0
                while remaining > 0 and safety < 100:
                    safety += 1
                    requested = min(preferred_session_minutes, remaining)
                    selected = select_slot(free_windows, task, requested, strategy, daily_load)
                    if not selected:
                        break
                    session_minutes = selected["session_minutes"]
                    if (
                        not today_state_used
                        and selected["window"]["day_index"] == today_index
                        and low_capacity
                        and demand["level"] == "high"
                        and session_minutes > 25
                    ):
                        session_minutes = 25
                        selected["end"] = selected["start"] + session_minutes / 60
                        today_state_used = True
                        state_scope = "today_first_task_adjustment"
                    else:
                        state_scope = "weekly_skeleton"
                    session_counter[str(task["id"])] = session_counter.get(str(task["id"]), 0) + 1
                    remaining = max(remaining - session_minutes, 0)
                    dependency_evidence = [
                        str(edge.get("reason"))
                        for edge in dependencies
                        if str(edge.get("after_task_id") or edge.get("successor_task_id") or "") == str(task.get("id")) and edge.get("reason")
                    ]
                    block = {
                        "block_id": f"{task['id']}-{strategy}-{session_counter[str(task['id'])]}",
                        "task_id": task["id"],
                        "day_index": selected["window"]["day_index"],
                        "deadline_day_index": deadline_day,
                        "start": selected["start"],
                        "end": selected["end"],
                        "color": palette[task_index % len(palette)],
                        "kind": "task_session",
                        "mode": "execution",
                        "session_index": session_counter[str(task["id"])],
                        "session_minutes": session_minutes,
                        "total_task_minutes": total_minutes,
                        "remaining_after_block_minutes": remaining,
                        "constraint_evidence": [
                            f"可用窗口：{selected['window']['source']}",
                            f"Deadline：{task.get('due')}",
                            f"单次专注偏好：{preferred_session_minutes} 分钟",
                            *demand["evidence"],
                            *dependency_evidence,
                        ],
                        "state_scope": state_scope,
                    }
                    blocks.append(block)
                    daily_load[block["day_index"]] = daily_load.get(block["day_index"], 0) + session_minutes
                    free_windows = subtract_busy(free_windows, block)
                if remaining > 0:
                    unscheduled.append({
                        "task_id": task.get("id"),
                        "remaining_minutes": remaining,
                        "scheduled_minutes": total_minutes - remaining,
                        "reason": "Deadline 前的可用时间不足，尚有部分时长未安排",
                    })

            counts: dict[str, int] = {}
            for block in blocks:
                if block.get("kind") == "task_session":
                    counts[str(block["task_id"])] = counts.get(str(block["task_id"]), 0) + 1
            for block in blocks:
                if block.get("kind") == "task_session":
                    block["session_count"] = counts[str(block["task_id"])]

            validation = validate_plan(blocks, context["windows"])
            scheduled_minutes = sum(block.get("session_minutes", 0) for block in blocks if block.get("kind") == "task_session")
            day_loads = [daily_load.get(day, 0) for day in range(today_index, 7)] or [0]
            load_spread = max(day_loads) - min(day_loads)
            return {
                "id": strategy,
                "label": label,
                "plan_patch": blocks,
                "unscheduled_tasks": unscheduled,
                "validation": validation,
                "metrics": {
                    "scheduled_minutes": scheduled_minutes,
                    "remaining_minutes": sum(item.get("remaining_minutes", 0) for item in unscheduled),
                    "session_count": len([block for block in blocks if block.get("kind") == "task_session"]),
                    "load_spread_minutes": load_spread,
                    "hard_violation_count": len(validation["violations"]),
                },
            }

        candidate_plans = [
            generate_candidate("energy_fit", "优先匹配深度工作与任务需求"),
            generate_candidate("deadline_first", "优先尽早满足 Deadline"),
            generate_candidate("balanced", "优先平衡每天负荷"),
        ]
        candidate_plans.sort(
            key=lambda candidate: (
                candidate["metrics"]["hard_violation_count"],
                candidate["metrics"]["remaining_minutes"],
                candidate["metrics"]["load_spread_minutes"],
            )
        )
        selected_candidate = candidate_plans[0]
        unscheduled_tasks = selected_candidate["unscheduled_tasks"]
        repair_suggestions: list[dict[str, Any]] = []
        for item in unscheduled_tasks:
            task = next((candidate for candidate in ready_tasks if candidate.get("id") == item.get("task_id")), {})
            repair_suggestions.append({
                "task_id": item.get("task_id"),
                "title": task.get("title") or "任务",
                "remaining_minutes": item.get("remaining_minutes", 0),
                "options": [
                    "在 Deadline 前增加一个可用时间窗口",
                    "延后 Deadline，并重新生成候选计划",
                    "减少本周目标范围或把剩余部分移入下周",
                    "在用户确认后减少 Buffer，但不占用 Fixed Events",
                ],
            })

        joint_state = {
            "task_environment_state": {
                "weekly_context": profile.get("weekly_context", {}),
                "parsed_constraints": context,
                "ready_task_ids": [task.get("id") for task in ready_tasks],
                "blocked_task_ids": [task.get("id") for task in blocked_tasks],
                "needs_clarification": needs_clarification,
                "ai_task_analysis": ai_analysis,
            },
            "user_state": {
                "momentary_state": runtime_state,
                "relevant_static_profile": {
                    "deep_work_window": profile.get("deep_work_window"),
                    "low_energy_window": profile.get("low_energy_window"),
                    "preferred_session_minutes": preferred_session_minutes,
                    "rest_between_tasks_minutes": rest_minutes,
                },
                "learned_patterns": profile.get("learned_patterns", []),
            },
        }

        candidate_actions = [
            {
                "action": "accept_feasible_candidate",
                "predicted_next_state": "所有已安排 Session 均在可用窗口和固定约束之外",
                "fit": "high" if not unscheduled_tasks else "medium",
                "uncertainty": "low" if not unscheduled_tasks else "medium",
            },
            {
                "action": "repair_partial_schedule",
                "predicted_next_state": "保留可行 Session，并针对剩余分钟调整可用时间、范围或 Deadline",
                "fit": "high" if unscheduled_tasks else "low",
                "uncertainty": "medium",
            },
        ]

        return {
            "plan_patch": selected_candidate["plan_patch"],
            "candidate_plans": candidate_plans,
            "validation": selected_candidate["validation"],
            "joint_state": joint_state,
            "candidate_actions": candidate_actions,
            "parallel_suggestions": [],
            "constraint_summary": context,
            "unscheduled_tasks": unscheduled_tasks,
            "repair_suggestions": repair_suggestions,
            "low_confidence_demand": low_confidence_demand,
        }

    return node


def explanation_node(store: Any):
    def node(state: HumanOSState) -> HumanOSState:
        profile = state.get("profile", {})
        runtime_state = state.get("runtime_state", {})
        memories = state.get("memories", [])
        explanation = "整周骨架由 Weekly Context、长期节奏和任务需求生成；当前状态只调整今天的第一个执行块。"
        reasons = [
            f"profile={profile.get('role')}, deep_work={profile.get('deep_work_window')}",
            (
                f"today-only state focus={runtime_state.get('focus')}, "
                f"energy={runtime_state.get('energy')}, stress={runtime_state.get('stress')}"
            ),
        ]
        if memories:
            reasons.append(f"retrieved {len(memories)} personalized memories")
        return {"explanation": explanation, "reasons": reasons}

    return node


def confirmation_policy_node(_: Any):
    def node(state: HumanOSState) -> HumanOSState:
        runtime_state = state.get("runtime_state", {})
        candidate_actions = state.get("candidate_actions", [])
        selected_action = max(candidate_actions, key=lambda item: {"low": 0, "medium": 1, "high": 2}.get(item.get("fit"), 0)) if candidate_actions else {}
        state_confidence = runtime_state.get("confidence_level", "high" if runtime_state.get("source") == "self_report" else "medium")
        impact = "high" if selected_action.get("action") in {"rest", "switch_to_lighter_task"} else "low"
        ask_user_before_adjustment = impact == "high" or state_confidence == "low"
        requires_confirmation = True  # every generated plan remains user-editable and user-confirmed
        decision = {
            "action": "suggest_plan",
            "selected_adjustment": selected_action,
            "candidate_actions": candidate_actions,
            "plan_patch": state.get("plan_patch", []),
            "candidate_plans": state.get("candidate_plans", []),
            "selected_candidate_id": (state.get("candidate_plans") or [{}])[0].get("id"),
            "validation": state.get("validation", {}),
            "explanation": state.get("explanation", ""),
            "confidence": {
                "level": state_confidence,
                "evidence": ["available windows", "fixed events", "temporary constraints", "deadlines", "buffer", "task demand", "momentary state scoped to today's first task"],
                "missing_or_conflicting": state.get("joint_state", {}).get("task_environment_state", {}).get("needs_clarification", []),
                "mental_state_is_hypothesis": True,
            },
            "requires_confirmation": requires_confirmation,
            "ask_user_before_adjustment": ask_user_before_adjustment,
            "control_mode": "ai_proposed_user_editable",
            "joint_state": state.get("joint_state", {}),
            "parallel_suggestions": state.get("parallel_suggestions", []),
            "constraint_summary": state.get("constraint_summary", {}),
            "unscheduled_tasks": state.get("unscheduled_tasks", []),
            "repair_suggestions": state.get("repair_suggestions", []),
            "low_confidence_demand": state.get("low_confidence_demand", []),
            "ai_task_analysis": state.get("ai_task_analysis", {}),
            "memory_evidence": state.get("memories", []),
            "reasons": state.get("reasons", []),
            "orchestration": "langgraph",
        }
        return {
            "confidence": state_confidence,
            "requires_confirmation": requires_confirmation,
            "decision": decision,
        }

    return node


def llm_refinement_node(store: Any):
    def node(state: HumanOSState) -> HumanOSState:
        decision = state.get("decision", {})
        refined = store.refine_schedule_decision(state, decision)
        return {"decision": refined}

    return node


def run_schedule_graph(store: Any, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    initial_state: HumanOSState = {"user_id": user_id, "payload": payload}

    try:
        from langgraph.graph import END, START, StateGraph

        builder = StateGraph(HumanOSState)
        builder.add_node("load_profile", load_profile_node(store))
        builder.add_node("load_task_state", load_task_state_node(store))
        builder.add_node("retrieve_memory", retrieve_memory_node(store))
        builder.add_node("analyze_inputs", analyze_inputs_node(store))
        builder.add_node("schedule", scheduler_node(store))
        builder.add_node("explain", explanation_node(store))
        builder.add_node("confirmation_policy", confirmation_policy_node(store))
        builder.add_node("llm_refine", llm_refinement_node(store))
        builder.add_edge(START, "load_profile")
        builder.add_edge("load_profile", "load_task_state")
        builder.add_edge("load_task_state", "retrieve_memory")
        builder.add_edge("retrieve_memory", "analyze_inputs")
        builder.add_edge("analyze_inputs", "schedule")
        builder.add_edge("schedule", "explain")
        builder.add_edge("explain", "confirmation_policy")
        builder.add_edge("confirmation_policy", "llm_refine")
        builder.add_edge("llm_refine", END)
        graph = builder.compile()
        result = graph.invoke(initial_state)
        decision = result["decision"]
        decision["orchestration"] = "langgraph"
        return decision
    except ImportError:
        state: HumanOSState = initial_state
        for node_factory in (
            load_profile_node,
            load_task_state_node,
            retrieve_memory_node,
            analyze_inputs_node,
            scheduler_node,
            explanation_node,
            confirmation_policy_node,
            llm_refinement_node,
        ):
            state.update(node_factory(store)(state))
        decision = state["decision"]
        decision["orchestration"] = "sequential_fallback"
        return decision
