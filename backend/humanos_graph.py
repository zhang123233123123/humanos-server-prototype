"""LangGraph orchestration for HumanOS scheduling.

The graph is dependency-tolerant: when `langgraph` is installed, HumanOS uses a
real StateGraph. Without it, the same nodes run sequentially so the MVP remains
usable on a clean machine.
"""

from __future__ import annotations

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


def scheduler_node(_: Any):
    def node(state: HumanOSState) -> HumanOSState:
        tasks = state.get("tasks", [])
        runtime_state = state.get("runtime_state", {})
        energy = int(runtime_state.get("energy", 4))
        palette = ["blue", "green", "violet", "gold"]
        priority_rank = {"高": 0, "中": 1, "低": 2}
        cursor = 9.0
        plan_patch = []

        for index, task in enumerate(sorted(tasks, key=lambda t: priority_rank.get(t.get("priority"), 1))):
            if task.get("status") == "paused":
                continue
            duration = max(int(task.get("duration", 60)), 15) / 60
            if energy <= 3 and task.get("cognitive_load") == "high":
                duration = min(duration, 0.5)
            explicit_start = parse_due_start_hour(task.get("due"))
            start = explicit_start if explicit_start is not None else cursor
            plan_patch.append(
                {
                    "task_id": task["id"],
                    "start": start,
                    "end": start + duration,
                    "color": palette[index % len(palette)],
                    "mode": "reentry" if energy <= 3 and task.get("cognitive_load") == "high" else "execution",
                }
            )
            if explicit_start is None:
                cursor += duration + 0.5

        return {"plan_patch": plan_patch}

    return node


def explanation_node(store: Any):
    def node(state: HumanOSState) -> HumanOSState:
        profile = state.get("profile", {})
        runtime_state = state.get("runtime_state", {})
        memories = state.get("memories", [])
        explanation = store.schedule_explanation(runtime_state, memories)
        reasons = [
            f"profile={profile.get('role')}, deep_work={profile.get('deep_work_window')}",
            (
                f"state focus={runtime_state.get('focus')}, "
                f"energy={runtime_state.get('energy')}, stress={runtime_state.get('stress')}"
            ),
        ]
        if memories:
            reasons.append(f"retrieved {len(memories)} personalized memories")
        return {"explanation": explanation, "reasons": reasons}

    return node


def confirmation_policy_node(_: Any):
    def node(state: HumanOSState) -> HumanOSState:
        profile = state.get("profile", {})
        runtime_state = state.get("runtime_state", {})
        energy = int(runtime_state.get("energy", 4))
        stress = int(runtime_state.get("stress", 4))
        requires_confirmation = (
            profile.get("control_preference") == "confirm_before_reschedule"
            or energy <= 3
            or stress >= 6
        )
        confidence = 0.62 if requires_confirmation else 0.78
        decision = {
            "action": "suggest_plan",
            "plan_patch": state.get("plan_patch", []),
            "explanation": state.get("explanation", ""),
            "confidence": confidence,
            "requires_confirmation": requires_confirmation,
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
        builder.add_node("explain", explanation_node(store))
        builder.add_node("confirmation_policy", confirmation_policy_node(store))
        builder.add_node("llm_refine", llm_refinement_node(store))
        builder.add_edge(START, "load_profile")
        builder.add_edge("load_profile", "load_task_state")
        builder.add_edge("load_task_state", "retrieve_memory")
        builder.add_edge("retrieve_memory", "schedule")
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
            scheduler_node,
            explanation_node,
            confirmation_policy_node,
            llm_refinement_node,
        ):
            state.update(node_factory(store)(state))
        decision = state["decision"]
        decision["orchestration"] = "sequential_fallback"
        return decision
