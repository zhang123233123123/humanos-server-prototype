"""LangGraph orchestration for HumanOS scheduling.

The graph is dependency-tolerant: when `langgraph` is installed, HumanOS uses a
real StateGraph. Without it, the same nodes run sequentially so the MVP remains
usable on a clean machine.
"""

from __future__ import annotations

from datetime import date
import re
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
    explanation: str
    confidence: float
    requires_confirmation: bool
    reasons: list[str]
    violations: list[dict[str, Any]]
    decision: dict[str, Any]


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


def parse_time_range(text: str | None) -> tuple[float, float] | None:
    clean = str(text or "")
    range_match = re.search(
        r"((?:早上|上午|中午|下午|晚上)?\s*\d{1,2}(?::\d{2}|：\d{2}|点|时)?)\s*(?:-|–|—|~|至|到)\s*((?:早上|上午|中午|下午|晚上)?\s*\d{1,2}(?::\d{2}|：\d{2}|点|时)?)",
        clean,
    )
    if not range_match:
        return None
    start = parse_due_start_hour(range_match.group(1))
    end = parse_due_start_hour(range_match.group(2))
    if start is None or end is None:
        return None
    if end <= start and end < 12:
        end += 12
    return (start, end) if end > start else None


def parse_time_ranges(text: str | None) -> list[tuple[float, float]]:
    clean = str(text or "")
    ranges = []
    for match in re.finditer(
        r"((?:早上|上午|中午|下午|晚上)?\s*\d{1,2}(?::\d{2}|：\d{2}|点|时)?)\s*(?:-|–|—|~|至|到)\s*((?:早上|上午|中午|下午|晚上)?\s*\d{1,2}(?::\d{2}|：\d{2}|点|时)?)",
        clean,
    ):
        parsed = parse_time_range(match.group(0))
        if parsed:
            ranges.append(parsed)
    return ranges


def due_day_rank(due: str | None) -> int:
    text = str(due or "")
    if re.search(r"今天|今晚", text):
        return 0
    if "明天" in text:
        return 1
    if "后天" in text:
        return 2
    iso_match = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if iso_match:
        try:
            target = date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
            return max((target - date.today()).days, 0)
        except ValueError:
            return 99
    md_match = re.search(r"(\d{1,2})[/-](\d{1,2})", text)
    if md_match:
        today = date.today()
        try:
            target = date(today.year, int(md_match.group(1)), int(md_match.group(2)))
            if target < today:
                target = date(today.year + 1, target.month, target.day)
            return max((target - today).days, 0)
        except ValueError:
            return 99
    week_match = re.search(r"(?:周|星期)([一二三四五六日天])", text)
    if week_match:
        week_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
        target = week_map[week_match.group(1)]
        today_index = date.today().weekday()
        return (target - today_index) % 7
    return 99


def schedule_task_type(task: dict[str, Any]) -> str:
    explicit = task.get("task_type") or task.get("taskType") or (task.get("contextWindow") or {}).get("taskType")
    if explicit:
        return str(explicit)
    due = str(task.get("due") or "")
    if parse_due_start_hour(due) is not None:
        return "fixed_event"
    return "flexible_task"


def first_non_overlapping_start(start: float, duration: float, occupied: list[tuple[float, float]]) -> float:
    candidate = start
    for block_start, block_end in sorted(occupied):
        if candidate + duration <= block_start:
            return candidate
        if candidate < block_end and candidate + duration > block_start:
            candidate = block_end + 0.25
    return candidate


def overlaps(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    return a_start < b_end and a_end > b_start


def task_is_high_load(task: dict[str, Any]) -> bool:
    dimensions = task.get("dimensions") or (task.get("contextWindow") or {}).get("dimensions") or {}
    return (
        dimensions.get("cognitive_load") == "high"
        or task.get("cognitive_load") == "high"
        or task.get("type") in {"writing", "coding", "research"}
    )


def task_is_ambiguous(task: dict[str, Any]) -> bool:
    dimensions = task.get("dimensions") or (task.get("contextWindow") or {}).get("dimensions") or {}
    return dimensions.get("clarity") == "low" or dimensions.get("ambiguity") == "high" or task.get("ambiguity") == "high"


def first_start_in_windows(
    duration: float,
    windows: list[tuple[float, float]],
    occupied: list[tuple[float, float]],
    cursor: float,
    avoid_windows: list[tuple[float, float]] | None = None,
) -> float:
    avoid_windows = avoid_windows or []
    fallback_start = max(cursor, windows[0][0]) if windows else max(cursor, 9.0)
    for window_start, window_end in sorted(windows):
        candidate = max(cursor, window_start)
        while candidate + duration <= window_end:
            adjusted = first_non_overlapping_start(candidate, duration, occupied)
            if adjusted != candidate:
                candidate = adjusted
                continue
            conflicting_avoid = next(
                ((avoid_start, avoid_end) for avoid_start, avoid_end in avoid_windows if overlaps(candidate, candidate + duration, avoid_start, avoid_end)),
                None,
            )
            if conflicting_avoid:
                candidate = conflicting_avoid[1] + 0.25
                continue
            return candidate
        cursor = fallback_start
    return first_non_overlapping_start(fallback_start, duration, occupied)


def profile_windows(profile: dict[str, Any], key: str) -> list[tuple[float, float]]:
    preferences = profile.get("task_preferences") or {}
    value = profile.get(key) or preferences.get(key) or ""
    return parse_time_ranges(value)


def intersect_windows(
    primary: list[tuple[float, float]],
    constraint: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    intersections: list[tuple[float, float]] = []
    for start_a, end_a in primary:
        for start_b, end_b in constraint:
            start = max(start_a, start_b)
            end = min(end_a, end_b)
            if end > start:
                intersections.append((start, end))
    return intersections


def subtract_windows(
    windows: list[tuple[float, float]],
    blocked: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for start, end in windows:
        fragments = [(start, end)]
        for block_start, block_end in blocked:
            next_fragments: list[tuple[float, float]] = []
            for frag_start, frag_end in fragments:
                if not overlaps(frag_start, frag_end, block_start, block_end):
                    next_fragments.append((frag_start, frag_end))
                    continue
                if frag_start < block_start:
                    next_fragments.append((frag_start, min(block_start, frag_end)))
                if block_end < frag_end:
                    next_fragments.append((max(block_end, frag_start), frag_end))
            fragments = next_fragments
        result.extend((frag_start, frag_end) for frag_start, frag_end in fragments if frag_end > frag_start)
    return result


def block_inside_any_window(block: dict[str, Any], windows: list[tuple[float, float]]) -> bool:
    if not windows:
        return True
    return any(block["start"] >= start and block["end"] <= end for start, end in windows)


def find_plan_violations(
    plan_patch: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    profile = profile or {}
    preferences = profile.get("task_preferences") or {}
    available_windows = parse_time_ranges(preferences.get("available_windows")) or [(0.0, 24.0)]
    low_energy_windows = profile_windows(profile, "low_energy_window")
    task_by_id = {task.get("id"): task for task in tasks}
    violations: list[dict[str, Any]] = []
    for task in tasks:
        task_kind = schedule_task_type(task)
        deadline = str(task.get("deadline") or task.get("due") or "")
        duration = int(task.get("estimated_duration") or task.get("duration") or 0)
        if task_kind != "fixed_event" and deadline in {"", "未设置"}:
            violations.append({"type": "missing_deadline", "task_id": task.get("id")})
        if duration <= 0:
            violations.append({"type": "missing_duration", "task_id": task.get("id")})
        if task_is_ambiguous(task):
            violations.append({"type": "low_task_clarity", "task_id": task.get("id")})
    for index, block in enumerate(plan_patch):
        task = task_by_id.get(block.get("task_id"), {})
        if block.get("task_type") != "fixed_event" and not block_inside_any_window(block, available_windows):
            violations.append(
                {
                    "type": "outside_available_window",
                    "task_id": block.get("task_id"),
                    "start": block.get("start"),
                    "end": block.get("end"),
                }
            )
        if task_is_high_load(task):
            for low_start, low_end in low_energy_windows:
                if overlaps(block["start"], block["end"], low_start, low_end):
                    violations.append(
                        {
                            "type": "high_load_in_low_energy_window",
                            "task_id": block.get("task_id"),
                            "start": max(block["start"], low_start),
                            "end": min(block["end"], low_end),
                        }
                    )
        for other in plan_patch[index + 1 :]:
            if not overlaps(block["start"], block["end"], other["start"], other["end"]):
                continue
            if block.get("task_type") == "fixed_event" and other.get("task_type") == "fixed_event":
                violations.append(
                    {
                        "type": "fixed_event_conflict",
                        "task_ids": [block.get("task_id"), other.get("task_id")],
                        "start": max(block["start"], other["start"]),
                        "end": min(block["end"], other["end"]),
                    }
                )
    return violations


def constraint_validator_node(_: Any):
    def node(state: HumanOSState) -> HumanOSState:
        violations = find_plan_violations(
            state.get("plan_patch", []),
            state.get("tasks", []),
            state.get("profile", {}),
        )
        return {"violations": violations}

    return node


def scheduler_node(_: Any):
    def node(state: HumanOSState) -> HumanOSState:
        tasks = state.get("tasks", [])
        profile = state.get("profile", {})
        preferences = profile.get("task_preferences") or {}
        runtime_state = state.get("runtime_state", {})
        focus = int(runtime_state.get("focus", 4))
        energy = int(runtime_state.get("energy", 4))
        stress = int(runtime_state.get("stress", 4))
        palette = ["blue", "green", "violet", "gold"]
        priority_rank = {"高": 0, "中": 1, "低": 2}
        available_windows = parse_time_ranges(preferences.get("available_windows")) or [(0.0, 24.0)]
        deep_work_windows = profile_windows(profile, "deep_work_window")
        low_energy_windows = profile_windows(profile, "low_energy_window")
        preferred_minutes = int(preferences.get("preferred_session_minutes") or 60)
        preferred_minutes = min(max(preferred_minutes, 15), 180)
        cursor = available_windows[0][0]
        plan_patch = []
        occupied: list[tuple[float, float]] = []

        def sort_key(task: dict[str, Any]) -> tuple[int, int, int, int, int]:
            task_kind = schedule_task_type(task)
            fixed_rank = 0 if task_kind == "fixed_event" else 1
            due_text = task.get("deadline") or task.get("due")
            start_hour = parse_due_start_hour(due_text)
            hour_rank = int((start_hour if start_hour is not None else 24) * 60)
            load_rank = 0 if task_is_high_load(task) else 1
            return (
                fixed_rank,
                due_day_rank(due_text),
                priority_rank.get(task.get("priority"), 1),
                load_rank,
                hour_rank,
            )

        for index, task in enumerate(sorted(tasks, key=sort_key)):
            if task.get("status") == "paused":
                continue
            raw_duration_minutes = max(int(task.get("estimated_duration") or task.get("duration", 60)), 15)
            task_kind = schedule_task_type(task)
            if task_kind == "fixed_event":
                duration_minutes = raw_duration_minutes
            else:
                duration_minutes = min(raw_duration_minutes, preferred_minutes)
                if energy <= 3 or focus <= 3:
                    duration_minutes = min(duration_minutes, 30)
                if stress >= 6 and task_is_high_load(task):
                    duration_minutes = min(duration_minutes, 45)
            duration = max(duration_minutes, 15) / 60
            explicit_start = parse_due_start_hour(task.get("due")) if task_kind == "fixed_event" else None
            if explicit_start is not None:
                start = explicit_start
            else:
                deep_available = intersect_windows(deep_work_windows, available_windows)
                non_deep_available = subtract_windows(available_windows, deep_available)
                if task_is_high_load(task) and deep_available:
                    candidate_windows = deep_available
                elif not task_is_high_load(task) and non_deep_available:
                    candidate_windows = non_deep_available
                else:
                    candidate_windows = available_windows
                avoid_windows = low_energy_windows if task_is_high_load(task) else []
                start = first_start_in_windows(duration, candidate_windows, occupied, cursor, avoid_windows)
            end = start + duration
            plan_patch.append(
                {
                    "task_id": task["id"],
                    "start": start,
                    "end": end,
                    "color": palette[index % len(palette)],
                    "mode": "reentry" if energy <= 3 and task.get("cognitive_load") == "high" else "execution",
                    "task_type": task_kind,
                    "scheduled_minutes": int(round(duration * 60)),
                    "remaining_minutes": max(raw_duration_minutes - int(round(duration * 60)), 0),
                }
            )
            occupied.append((start, end))
            if explicit_start is None:
                cursor = end + 0.5

        return {"plan_patch": plan_patch}

    return node


def explanation_node(store: Any):
    def node(state: HumanOSState) -> HumanOSState:
        profile = state.get("profile", {})
        preferences = profile.get("task_preferences") or {}
        runtime_state = state.get("runtime_state", {})
        memories = state.get("memories", [])
        explanation = store.schedule_explanation(runtime_state, memories)
        preferred_minutes = preferences.get("preferred_session_minutes")
        if preferred_minutes:
            explanation += f" 我会先按你偏好的 {preferred_minutes} 分钟左右学习块来安排。"
        if preferences.get("available_windows"):
            explanation += " 安排会优先落在你填写的可用时间里。"
        if profile.get("low_energy_window"):
            explanation += " 高负荷任务会尽量避开你通常精力较低的时段。"
        violations = state.get("violations", [])
        if any(item.get("type") == "fixed_event_conflict" for item in violations):
            explanation += " 但有固定事件时间冲突，需要你先确认或手动调整。"
        if any(item.get("type") == "high_load_in_low_energy_window" for item in violations):
            explanation += " 其中有高负荷任务落在低能量时段，我会先等你确认。"
        if any(item.get("type") == "low_task_clarity" for item in violations):
            explanation += " 有些任务目标还不够清楚，建议确认下一步后再开始。"
        reasons = [
            f"profile={profile.get('role')}, deep_work={profile.get('deep_work_window')}",
            (
                f"state focus={runtime_state.get('focus')}, "
                f"energy={runtime_state.get('energy')}, stress={runtime_state.get('stress')}"
            ),
            f"available_windows={preferences.get('available_windows')}",
            f"preferred_session_minutes={preferred_minutes}",
            f"low_energy_window={profile.get('low_energy_window')}",
        ]
        if memories:
            reasons.append(f"retrieved {len(memories)} personalized memories")
        if violations:
            reasons.append(f"violations={violations}")
        return {"explanation": explanation, "reasons": reasons}

    return node


def confirmation_policy_node(_: Any):
    def node(state: HumanOSState) -> HumanOSState:
        profile = state.get("profile", {})
        runtime_state = state.get("runtime_state", {})
        energy = int(runtime_state.get("energy", 4))
        stress = int(runtime_state.get("stress", 4))
        violations = state.get("violations", [])
        requires_confirmation = (
            profile.get("control_preference") == "confirm_before_reschedule"
            or energy <= 3
            or stress >= 6
            or bool(violations)
        )
        confidence = 0.5 if violations else 0.62 if requires_confirmation else 0.78
        decision = {
            "action": "suggest_plan",
            "plan_patch": state.get("plan_patch", []),
            "explanation": state.get("explanation", ""),
            "confidence": confidence,
            "requires_confirmation": requires_confirmation,
            "violations": violations,
            "memory_evidence": state.get("memories", []),
            "reasons": state.get("reasons", []),
            "orchestration": "langgraph",
        }
        return {
            "confidence": confidence,
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
        builder.add_node("schedule", scheduler_node(store))
        builder.add_node("validate_constraints", constraint_validator_node(store))
        builder.add_node("explain", explanation_node(store))
        builder.add_node("confirmation_policy", confirmation_policy_node(store))
        builder.add_node("llm_refine", llm_refinement_node(store))
        builder.add_edge(START, "load_profile")
        builder.add_edge("load_profile", "load_task_state")
        builder.add_edge("load_task_state", "retrieve_memory")
        builder.add_edge("retrieve_memory", "schedule")
        builder.add_edge("schedule", "validate_constraints")
        builder.add_edge("validate_constraints", "explain")
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
            scheduler_node,
            constraint_validator_node,
            explanation_node,
            confirmation_policy_node,
            llm_refinement_node,
        ):
            state.update(node_factory(store)(state))
        decision = state["decision"]
        decision["orchestration"] = "sequential_fallback"
        return decision
