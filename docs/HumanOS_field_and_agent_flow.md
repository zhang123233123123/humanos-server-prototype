# HumanOS 字段流转与 Agent 传输关系

## 1. 文档目的

本文档定义 HumanOS 中字段如何在系统中流动，以及不同 agent 之间如何传递信息。

前一份文档定义“有哪些字段”。本文档回答：

1. 字段从哪里来。
2. 字段先进入哪个模块。
3. 字段是否进入 prompt。
4. 字段是否进入 memory。
5. 字段在 agent 之间如何传输。
6. 哪些字段不应该跨 agent 乱传。

核心原则：

> 字段不是越多越好。每个 agent 只接收完成自己任务所必需的字段，并输出结构化结果给下一个 agent。

## 2. 字段总体流转图

```text
User Input / UI Form
  ↓
Input Normalization
  ↓
Task Parser Agent ────────────────┐
  ↓                               │
Task Object                       │
  ↓                               │
Missing Field Detector            │
  ↓                               │
Ready Queue Builder               │
  ↓                               │
Scheduler Agent                   │
  ↓                               │
Constraint Validator Agent        │
  ↓                               │
Explanation Agent                 │
  ↓                               │
User Confirmation                 │
  ↓                               │
Calendar Commit                   │
  ↓                               │
Execution Feedback Agent          │
  ↓                               │
Memory Update Agent ──────────────┘
  ↓
System Memory / Retrieved Memory
```

Profile、Weekly Context 和 Momentary State 是横向输入：

```text
Static Profile ──────┐
Weekly Context ──────┼──→ Scheduler / Validator / Explanation / Recovery
Momentary State ─────┤
Retrieved Memory ────┘
```

## 3. 字段来源

| 字段组 | 来源 | 进入系统的入口 |
| --- | --- | --- |
| Task fields | 用户聊天输入 / 新增任务表单 | Task Parser Agent |
| Static Profile fields | 初始 profile / 个人主页 | Profile Builder Agent |
| Dynamic Profile fields | 滑动条 / emoji / daily check-in | Dynamic State Agent |
| Fixed Event fields | 用户输入 / 日历导入 | Fixed Event Parser |
| Execution Feedback fields | 任务完成 / 中断 / 切换反馈 | Feedback Agent |
| Memory fields | 系统自动生成 | Memory Update Agent |

## 4. 字段流转总表

| 字段组 | 主要字段 | 首次生成模块 | 下游接收方 | 是否入 prompt | 是否入 memory |
| --- | --- | --- | --- | --- | --- |
| Task Core | `title`, `deadline`, `estimated_duration` | Task Parser | Scheduler, Validator, Explanation | 是 | 是 |
| Task Dimensions | `cognitive_load`, `clarity`, `splittable`, `recovery_cost`, `dependency_status` | Task Parser / Task Dimension Agent | Scheduler, Validator, Recovery | 是 | 是 |
| Fixed Event | `start_time`, `end_time`, `event_type` | Fixed Event Parser | Scheduler, Validator | 是 | 可选 |
| Static Profile | `preferred_session_length`, `low_energy_window`, `deep_work_window`, `common_blockers`, `control_preference` | Profile Builder / Learned Pattern | Scheduler, Validator, Explanation | 部分 | 是 |
| Weekly Context | `weekly_available_windows`, `fixed_events`, `weekly_goal`, `temporary_constraints`, `important_deadlines`, `weekly_note` | Weekly Context Builder | Scheduler, Validator, Explanation | 是 | 是 |
| User Background | `user_role`, `learning_context`, `planning_tools` | Profile Builder | Explanation | 部分；`planning_tools` 不默认进 Scheduler | 是 |
| Momentary State | `focus`, `energy`, `stress`, `emotion`, `readiness`, `attention_residue`, `confidence_to_complete` | Dynamic State Agent | Scheduler, Validator, Recovery | 是 | 是 |
| Execution Feedback | `actual_duration`, `completion_status`, `progress_summary`, `next_step` | Feedback Agent | Memory Update, Recovery | 部分 | 是 |
| Retrieved Memory | 相似历史记录 | Memory Retriever | Scheduler, Explanation, Recovery | 是 | 否 |
| Constraint Check | `violations`, `adjustments`, `confidence` | Validator | Explanation, User Confirmation | 是 | 是 |

## 5. Task 字段流转

### 5.1 输入阶段

用户可能输入：

```text
这周要读完 AI planning 相关论文，周五前总结 gap，大概需要 3 小时。
```

Task Parser Agent 输出：

```json
{
  "task_id": "task_001",
  "task_type": "flexible_task",
  "title": "阅读 AI planning 相关论文并总结 gap",
  "deadline": "周五",
  "estimated_duration": 180,
  "context": "需要总结 gap",
  "missing_fields": [],
  "status": "ready"
}
```

### 5.2 任务维度补全

Task Dimension Agent 或 Task Parser Agent 继续补全：

```json
{
  "task_id": "task_001",
  "dimensions": {
    "cognitive_load": "high",
    "clarity": "medium",
    "splittable": true,
    "recovery_cost": "medium",
    "dependency_status": "ready",
    "collaboration_required": false,
    "emotional_resistance": "unknown",
    "flexibility": "movable"
  }
}
```

### 5.3 传给 Scheduler

Scheduler Agent 接收的 task 版本应该是压缩后的调度对象：

```json
{
  "task_id": "task_001",
  "title": "阅读 AI planning 相关论文并总结 gap",
  "deadline": "周五",
  "estimated_duration": 180,
  "dimensions": {
    "cognitive_load": "high",
    "splittable": true,
    "recovery_cost": "medium"
  },
  "status": "ready"
}
```

Scheduler 不需要完整对话原文。

## 6. Profile 字段流转

### 6.1 Static Profile

Static Profile 由 Profile Builder Agent 生成：

```json
{
  "user_role": "研究型学生",
  "learning_context": ["论文阅读", "代码复现"],
  "preferred_session_length": 45,
  "low_energy_window": "14:00-15:30",
  "deep_work_window": "09:00-11:30",
  "common_blockers": ["任务不清楚", "切换后回不来"],
  "control_preference": "confirm_before_reschedule"
}
```

Static Profile 只保存稳定画像，不由单次行为直接改写。一次失败、一次拖拽、一次中断只进入 `Episodic Memory`。当同类证据重复出现 3-5 次，或用户明确确认后，Memory Update Agent 才能把它升级为 `Learned Pattern`，再建议更新 Static Profile。

```text
single event → Episodic Memory
repeated evidence / user confirmation → Learned Pattern
stable pattern → Static Profile update proposal
```

本周可用时间不属于 Static Profile，应放入 Weekly Context。

### 6.1.1 Weekly Context

Weekly Context 每周重建一次，用于描述这一周的短期约束：

```json
{
  "weekly_available_windows": "周一/三 19:00-21:00，周六 09:00-12:00",
  "fixed_events": ["周二 10:00 组会", "周五 16:00 presentation"],
  "weekly_goal": "读完 planning 相关论文并整理 gap",
  "temporary_constraints": ["周四外出", "本周考试复习"],
  "important_deadlines": ["周五前发给队友"],
  "weekly_note": "这周主要压力来自 presentation 和论文总结。"
}
```

### 6.2 Profile 传输规则

| 接收方 | 需要哪些 profile 字段 | 不需要哪些字段 |
| --- | --- | --- |
| Scheduler Agent | `preferred_session_length`, `low_energy_window`, `deep_work_window`, `common_blockers` + Weekly Context 中的 `weekly_available_windows`, `fixed_events`, `important_deadlines` | `planning_tools`, 用户背景长文本 |
| Constraint Validator Agent | Weekly Context 的可用时间 / fixed events / deadlines，Static Profile 的 `preferred_session_length`, `low_energy_window`, `control_preference` | `planning_tools`, 用户背景长文本 |
| Explanation Agent | `user_role`, `learning_context`, `common_blockers`, 关键调度字段 | 全量历史 profile |
| Recovery Agent | `common_blockers`, `preferred_session_length`, `control_preference` | 完整可用时间表 |
| Memory Update Agent | Episodic Memory, Learned Pattern, 用户确认记录 | 不直接把单次行为写入 Static Profile |

## 7. Dynamic Profile 字段流转

### 7.1 Dynamic Profile 输入

Dynamic State Agent 接收：

```json
{
  "focus": 5,
  "energy": 4,
  "stress": 5,
  "emotion": "neutral",
  "daily_note": "今天上午状态一般，但下午有较完整时间。"
}
```

任务开始前可能增加：

```json
{
  "confidence_to_complete": 5,
  "readiness": 4,
  "attention_residue": 3
}
```

### 7.2 Dynamic Profile 传输规则

| 字段 | Scheduler | Validator | Explanation | Recovery | Memory |
| --- | --- | --- | --- | --- | --- |
| `focus` | 是 | 是 | 是 | 可选 | 是 |
| `energy` | 是 | 是 | 是 | 是 | 是 |
| `stress` | 是 | 是 | 是 | 是 | 是 |
| `emotion` | 可选 | 可选 | 是 | 是 | 是 |
| `readiness` | 是 | 是 | 是 | 是 | 是 |
| `attention_residue` | 可选 | 是 | 是 | 是 | 是 |
| `confidence_to_complete` | 是 | 是 | 是 | 可选 | 是 |
| `daily_note` | 可选摘要 | 可选 | 是 | 可选 | 是 |

## 8. Memory 字段流转

### 8.1 Memory 生成

Memory Update Agent 从以下信息生成 memory：

```json
{
  "source_type": "completion_feedback",
  "task_id": "task_001",
  "text": "用户在下午 14:00-15:00 的高负荷阅读任务中未完成，反馈为精力低、任务目标不清楚。",
  "metadata": {
    "actual_duration": 45,
    "completion_status": "partial",
    "blocker": "任务不清楚",
    "energy": 3,
    "stress": 6
  }
}
```

### 8.2 Memory 检索

Memory Retriever 接收 query：

```json
{
  "current_task": "阅读 AI planning 相关论文",
  "task_dimensions": {
    "cognitive_load": "high",
    "clarity": "medium"
  },
  "dynamic_profile": {
    "focus": 5,
    "energy": 4,
    "stress": 5
  }
}
```

输出：

```json
{
  "retrieved_memories": [
    {
      "text": "用户过去在下午高负荷阅读任务中容易延期，拆成 45 分钟更合适。",
      "score": 0.82,
      "source_type": "completion_feedback"
    }
  ]
}
```

### 8.3 Memory 传输规则

Memory 只传摘要，不传完整历史。

| 接收方 | 使用方式 |
| --- | --- |
| Scheduler Agent | 调整 session 长度和时间窗口 |
| Constraint Validator Agent | 判断计划是否与历史失败模式冲突 |
| Explanation Agent | 生成“参考过往情况”的用户可读解释 |
| Recovery Agent | 提示用户从哪里继续 |

## 9. Agent 之间的传输关系

## 9.1 Agent 列表

| Agent | 职责 | 输入 | 输出 |
| --- | --- | --- | --- |
| Input Normalizer | 清理用户输入，识别输入类型 | raw input | normalized input |
| Task Parser Agent | 抽取 task / fixed event | normalized input, recent turns | task objects, missing fields |
| Task Dimension Agent | 判断任务维度 | task objects, context | task dimensions |
| Profile Builder Agent | 建立 static profile | onboarding answers | static profile |
| Dynamic State Agent | 建立 dynamic profile | sliders, emoji, daily note | dynamic profile |
| Memory Retriever | 检索历史相似情况 | task + profile query | retrieved memories |
| Scheduler Agent | 生成初始计划 | ready tasks, profile, memory | schedule draft |
| Constraint Validator Agent | 检查计划约束 | schedule draft, constraints | validated plan, violations |
| Explanation Agent | 生成用户可读解释 | validated plan, reasons, confidence | explanation |
| Confirmation Agent | 处理用户确认 / 拒绝 | validated plan, user action | calendar commit / revise request |
| Recovery Agent | 中断后恢复任务 | active task, context dump, state | recovery prompt |
| Feedback Agent | 收集执行反馈 | completion / interruption input | execution feedback |
| Memory Update Agent | 更新 memory | feedback, task, profile | new memory records |

## 9.2 Agent 流程图

```text
Input Normalizer
  ↓
Task Parser Agent
  ↓
Task Dimension Agent
  ↓
Missing Field Detector
  ├─ missing → Fixed Question Agent → User
  └─ complete
       ↓
Ready Queue Builder
       ↓
Memory Retriever
       ↓
Scheduler Agent
       ↓
Constraint Validator Agent
       ↓
Explanation Agent
       ↓
Confirmation Agent
       ├─ confirm → Calendar Commit
       └─ reject / revise → Scheduler Agent
```

执行阶段：

```text
Calendar Commit
  ↓
Task Running
  ├─ interruption → Recovery Agent → Context Dump → Memory Update Agent
  └─ completion → Feedback Agent → Memory Update Agent
```

## 10. 每个 Agent 的 Prompt 字段映射

### 10.1 Task Parser Agent

输入字段：

```json
{
  "raw_user_input": "...",
  "recent_turns": [],
  "task_schema": {},
  "today": "2026-08-01"
}
```

输出字段：

```json
{
  "tasks": [],
  "fixed_events": [],
  "missing_fields": []
}
```

不需要：

- 完整 static profile
- 完整 memory
- calendar plan

### 10.2 Task Dimension Agent

输入字段：

```json
{
  "task": {},
  "task_context": "...",
  "user_clarification": "..."
}
```

输出字段：

```json
{
  "cognitive_load": "high",
  "clarity": "medium",
  "splittable": true,
  "recovery_cost": "medium",
  "dependency_status": "ready",
  "emotional_resistance": "unknown",
  "flexibility": "movable"
}
```

### 10.3 Scheduler Agent

输入字段：

```json
{
  "ready_tasks": [],
  "fixed_events": [],
  "static_profile": {
    "preferred_session_length": 45,
    "low_energy_window": "...",
    "deep_work_window": "..."
  },
  "weekly_context": {
    "weekly_available_windows": "...",
    "fixed_events": [],
    "important_deadlines": []
  },
  "dynamic_profile": {
    "focus": 5,
    "energy": 4,
    "stress": 5
  },
  "retrieved_memories": []
}
```

输出字段：

```json
{
  "schedule_draft": [],
  "ready_queue": [],
  "confidence": 0.82,
  "reasons": []
}
```

### 10.4 Constraint Validator Agent

输入字段：

```json
{
  "schedule_draft": [],
  "fixed_events": [],
  "deadlines": [],
  "weekly_available_windows": [],
  "preferred_session_length": 45,
  "low_energy_window": "...",
  "dynamic_profile": {}
}
```

输出字段：

```json
{
  "valid": true,
  "violations": [],
  "adjustments": [],
  "validated_plan": []
}
```

### 10.5 Explanation Agent

输入字段：

```json
{
  "validated_plan": [],
  "key_reasons": [],
  "dynamic_profile": {},
  "retrieved_memory_summary": [],
  "confidence": 0.82
}
```

输出字段：

```json
{
  "user_facing_explanation": "...",
  "first_action": "...",
  "risk": "...",
  "requires_confirmation": true
}
```

### 10.6 Recovery Agent

输入字段：

```json
{
  "active_task": {},
  "context_window": {
    "progress_summary": "...",
    "open_questions": "...",
    "next_step": "..."
  },
  "dynamic_profile": {
    "attention_residue": 4,
    "energy": 3
  },
  "retrieved_memories": []
}
```

输出字段：

```json
{
  "recovery_prompt": "...",
  "first_step": "...",
  "suggested_session_length": 25
}
```

### 10.7 Memory Update Agent

输入字段：

```json
{
  "task": {},
  "execution_feedback": {},
  "dynamic_profile": {},
  "previous_estimate": {}
}
```

输出字段：

```json
{
  "memory_records": [],
  "profile_updates": {},
  "duration_calibration": {}
}
```

## 11. 字段传输限制

为了避免 prompt 混乱，应限制字段流动：

| 字段 | 不应传给 | 原因 |
| --- | --- | --- |
| 完整聊天历史 | Scheduler Agent | 噪声太多，只传摘要 / retrieved memory |
| 完整用户背景 | Constraint Validator | 验证只需要约束字段 |
| 内部 embedding score | 用户解释 | 用户不需要看到内部技术 |
| 所有 memory 原文 | Explanation Agent | 只需要少量关键证据 |
| calendar UI 状态 | Task Parser Agent | 解析任务不需要 UI 细节 |

## 12. 最终系统传输关系总结

HumanOS 的字段传输可以概括为：

```text
用户输入 → task 字段
初始问卷 → static profile 字段
滑动条 / emoji / daily note → dynamic profile 字段
任务执行结果 → feedback 字段
feedback + profile + task → memory 字段
task + profile + dynamic state + memory → scheduler prompt
scheduler output + constraints → validator prompt
validated plan + reasons → explanation prompt
user confirmation → calendar commit
calendar execution → feedback loop
```

Agent 传输可以概括为：

## 13. 当前 Prototype 代码落点

截至当前实现，agent 不是全部独立服务，而是在后端函数和 LangGraph 节点中落地：

| Agent | 当前代码位置 | 当前输出 |
|---|---|---|
| Task Parser Agent | `backend/humanos_server.py::parse_tasks_from_text`, `local_parse_tasks_from_text`, `parse_time_followup_for_recent_tasks` | `tasks`, `task_type`, `deadline`, `estimated_duration`, `confidence` |
| Task Dimension Agent | `backend/humanos_server.py::task_dimension_agent`, `local_task_dimensions` | `contextWindow.dimensions` |
| Scheduler Agent | `backend/humanos_graph.py::scheduler_node` | `plan_patch`, `scheduled_minutes`, `remaining_minutes` |
| Constraint Validator Agent | `backend/humanos_graph.py::constraint_validator_node`, `find_plan_violations` | `violations` |
| Explanation Agent | `backend/humanos_graph.py::explanation_node`, `backend/humanos_server.py::refine_schedule_decision` | `explanation`, `first_action`, `risk` |
| Confirmation Agent | `backend/humanos_graph.py::confirmation_policy_node`, `frontend/app.js::confirmScheduleBtn` | `requires_confirmation`, calendar commit |
| Memory Update | `backend/humanos_server.py::add_memory`, `save_chat_turn`, `save_context_dump` | `memories`, `chat_turns`, `context_dumps` |

当前字段保存策略：

- `task_type / deadline / estimated_duration` 写入 `tasks` 表兼容字段，并同步进入 `contextWindow`。
- 任务维度写入 `contextWindow.dimensions`，不新增数据库列。
- `focus / energy / stress` 写入 `runtime_states`，调度时进入 `Scheduler Agent` 和 `Constraint Validator Agent`。
- `confidence` 保存到 `chat_turns.features_json`，调度 confidence 作为 decision 字段返回。
- 前端只显示中文解释，不显示 `embedding_model`, `dependency_status`, `low_task_clarity` 等内部字段名。

```text
Parser → Dimension → Scheduler → Validator → Explanation → Confirmation → Commit → Feedback → Memory
```

其中，`Static Profile`、`Weekly Context`、`Momentary State` 和 `Retrieved Memory` 是横向上下文，会在 Scheduler、Validator、Explanation、Recovery 中按需注入，而不是无差别传给所有 agent。
