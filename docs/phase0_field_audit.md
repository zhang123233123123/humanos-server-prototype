# Phase 0 Field Audit

本文件记录当前 prototype 的字段、代码入口和缺口。目的不是总结会议，而是为后续逐步改代码提供可执行基线。

## 1. 当前代码入口

### 前端

- `frontend/index.html`
  - 登录 / 注册
  - 初次 Profile wizard
  - 当前状态滑动条
  - AI 对话框
  - 日历视图
  - 手动新增任务弹窗

- `frontend/app.js`
  - Profile 表单保存：`saveWizardProfile`
  - 当前状态保存：`saveRuntimeStateToBackend`
  - 对话发送和任务解析：`sendChatMessage`
  - 待确认调度生成：`requestTentativeSchedule`
  - 日历渲染：`renderCalendar`
  - 任务详情渲染：`renderTaskDetail`
  - 任务字段校验：`missingTimeConfirmationFields`

### 后端

- `backend/humanos_server.py`
  - 数据库 schema
  - 用户登录注册
  - Profile 保存与读取
  - Task CRUD
  - chat turn 解析
  - embedding memory 写入与检索
  - 调度 API

- `backend/humanos_graph.py`
  - LangGraph 编排节点
  - Profile / Task / Memory 读取
  - scheduler node
  - explanation node
  - confirmation policy node
  - LLM refinement node

## 2. 当前 Task 字段

数据库 `tasks` 表当前字段：

| 字段 | 当前含义 | 当前问题 |
|---|---|---|
| `id` | task id | 可保留 |
| `user_id` | 所属用户 | 可保留 |
| `title` | 任务标题 | 可保留 |
| `type` | 粗略任务类型，如 reading / writing / coding | 不是任务调度类型，不能区分 flexible task 和 fixed event |
| `due` | 目标时间 / 开始时间混用 | 当前最大问题：DDL、开始时间、自然语言时间混在一起 |
| `duration` | 预计分钟数 | 应明确为 `estimated_duration` |
| `priority` | 高 / 中 / 低 | 当前 scheduler 主要按它排序，但我们现在要求优先看 DDL |
| `status` | queued / scheduled / paused 等 | 可保留，但需要统一状态流转 |
| `context` | 任务背景 | 可保留 |
| `context_window_json` | 进展、下一步、开放问题等 | 可保留，应作为恢复任务的核心字段 |
| `cognitive_load` | high / medium / low | 可保留，但现在多靠默认推断 |
| `ambiguity` | high / medium / low | 应改名或映射到 `clarity` |
| `switch_cost` | 切换成本 | 可保留 |
| `reentry_cost` | 回到任务的成本 | 可保留 |
| `slot_json` | 日历安排 | 可保留 |
| `checkpoints_json` | 检查点 | 当前使用较弱 |
| `created_at` / `updated_at` | 时间戳 | 可保留 |

## 3. 目标 Task 字段差距

当前缺少或需要明确的字段：

| 目标字段 | 当前状态 | 修改方向 |
|---|---|---|
| `task_type` | 当前 `type` 含义不对 | 新增或派生：`flexible_task` / `fixed_event` / `recovery_task` |
| `deadline` | 被混在 `due` 里 | 从 `due` 中拆出，Flexible Task 主要依赖 DDL |
| `estimated_duration` | 当前叫 `duration` | 保持兼容，但接口语义改成预计时长 |
| `start_time` / `end_time` | 当前混在 `due` 或 `slot_json` | 只用于 Fixed Event 或已确认日历 slot |
| `goal` | 没有独立字段 | 可先放入 `context_window_json.goal` |
| `clarity` | 当前接近 `ambiguity` | 建议用 `clarity`，保留 `ambiguity` 兼容 |
| `splittable` | 没有 | 用于判断能否切块 |
| `dependency_status` | 没有 | 判断是否被材料、队友反馈、外部条件卡住 |
| `collaboration_required` | 没有 | 判断是否需要等待他人 |
| `emotional_resistance` | 没有 | 用于识别拖延和压力相关任务 |
| `flexibility` | 没有 | 判断是否可移动 |
| `buffer_needed` | 没有 | Fixed Event 前后缓冲 |
| `location` | 没有 | Fixed Event 字段 |

## 4. 当前 Profile 字段

数据库 `profiles` 表当前字段：

| 字段 | 当前含义 | 当前问题 |
|---|---|---|
| `role` | 学习者身份 | 可保留 |
| `deep_work_window` | 深度工作时间 | 可保留 |
| `low_energy_window` | 低能量时间 | 可保留 |
| `control_preference` | 用户是否希望确认后调整 | 可保留 |
| `blocker_patterns` | 常见卡点 | 可保留 |
| `task_preferences` | JSON，包含很多 profile 字段 | 调度关键字段藏在 JSON 里，scheduler 使用不足 |

`task_preferences` 当前包含：

- `available_windows`
- `preferred_session_minutes`
- `learning_mode`
- `current_courses`
- `near_deadlines`
- `planning_tools`
- `planning_gap`
- `short_term_goal`
- `support_need`
- `recovery_preference`

## 5. 目标 Profile 字段差距

Profile 当前不是主要问题，主要问题是“保存了但没有充分进入调度”。

需要优先排序的 Profile 字段：

1. `available_windows`
2. `preferred_session_length`
3. `low_energy_window`
4. `deep_work_window`
5. `learning_context`
6. `common_blockers`
7. `control_preference`
8. `planning_tools`

当前 gap：

- `available_windows` 在 JSON 里，但 scheduler 没有按它约束排程。
- `preferred_session_minutes` 在 JSON 里，但 scheduler 没有稳定按它切块。
- `near_deadlines` 只是 profile 文本，不等于任务级 DDL。
- `planning_gap` / `support_need` 更适合给 explanation / recovery agent，不应该直接塞给 scheduler。

## 6. 当前 Dynamic Profile 字段

前端当前有三个滑动条：

- `focus`
- `energy`
- `stress`

后端 `runtime_states` 表支持：

- `focus`
- `energy`
- `stress`
- `mood`
- `attention_residue`

当前 gap：

- 前端只发送 `focus / energy / stress`。
- `mood / attention_residue` 后端支持但前端没有输入。
- scheduler 主要使用 `energy`，对 `focus / stress` 的使用偏弱。
- 当前状态没有进入任务字段推断，例如没有根据状态调整 `cognitive_load`、`splittable`、`reentry_cost`。

## 7. 当前 Prompt / Agent 输入

### Task Parser Agent

位置：`backend/humanos_server.py` 的 `parse_tasks_from_text`

当前输入：

- 用户原始文本
- today
- conversation_context
- schema：`title / due / duration / priority / context`

当前输出：

- tasks 列表
- 每个 task 含 `title / due / duration / priority / context`

当前 gap：

- 输出 schema 还没有 `task_type / deadline / estimated_duration / fixed_event / missing_fields / task_dimensions`。
- 多任务解析已有强化，但后续时间补全仍容易把“3点到4点”理解成新增任务，而不是补全上一条缺失字段。

### Scheduler Graph

位置：`backend/humanos_graph.py`

当前节点：

1. `load_profile`
2. `load_task_state`
3. `retrieve_memory`
4. `schedule`
5. `explain`
6. `confirm`
7. `refine`

当前 scheduler 行为：

- 读取 tasks
- 按 `priority` 排序
- 如果 `due` 里有具体时间，则直接用作开始时间
- 否则从 9:00 往后排
- energy 低且 cognitive load high 时缩短时长

当前 gap：

- 没有 DDL-first ready queue。
- 没有 fixed event 先占位。
- 没有 available windows 约束。
- 没有 preferred session length 切块。
- 没有独立 Constraint Validator。
- `due` 同时承担 DDL 和开始时间，导致用户只给 DDL 时系统行为不稳定。

### Explanation / Refinement

位置：

- `backend/humanos_graph.py`
- `backend/humanos_server.py` 的 `refine_schedule_decision`

当前输入：

- profile
- runtime_state
- tasks 前 6 个
- memory evidence 前 3 个
- current_decision

当前 gap：

- explanation 已经存在，但和真正调度约束没有完全对齐。
- 目前更像“对 deterministic schedule 的解释和润色”，不是严格的多 agent 协商。

## 8. 当前最需要修正的 8 个问题

1. `missingTimeConfirmationFields` 仍然把“可调度任务”当成“必须有具体开始时间”的日历项。
2. `due` 混用了 DDL、开始时间、自然语言目标时间。
3. scheduler 主要按 `priority` 排，而不是按 DDL 和任务维度。
4. Flexible Task 和 Fixed Event 没有分开建模。
5. Profile 的 `available_windows` 和 `preferred_session_minutes` 保存了，但调度使用不足。
6. Dynamic Profile 的 `focus / energy / stress` 没有充分参与任务选择和解释。
7. 缺少 Constraint Validator Agent，计划冲突或缺字段时容易直接进入待确认。
8. 任务维度没有独立 prompt，导致所有任务默认 60 分钟、中优先级、模糊 context 的情况仍会出现。

## 9. 下一步代码修改顺序

下一步不应直接重写 UI，而应先改最小可验证链条：

### Step 1：改任务字段判断

目标：

- Flexible Task 最低要求从“具体几点”改为：
  - `title`
  - `deadline`
  - `estimated_duration`

- Fixed Event 最低要求为：
  - `title`
  - `start_time`
  - `end_time` 或 `duration`

涉及文件：

- `frontend/app.js`
  - `missingTimeConfirmationFields`
  - `requestTentativeSchedule`
- `backend/humanos_server.py`
  - `parse_tasks_from_text`
  - `parse_time_followup_for_recent_tasks`

### Step 2：改 Task Parser schema

目标：

- 输出 `task_type`
- 输出 `deadline`
- 输出 `estimated_duration`
- 输出 `fixed_start_time / fixed_end_time`
- 输出 `missing_fields`
- 输出初步任务维度

涉及文件：

- `backend/humanos_server.py`

### Step 3：改 Scheduler 排序

目标：

- fixed event 先占位
- flexible task 按 DDL 排 ready queue
- 再考虑 duration、deep work、low energy、dynamic state

涉及文件：

- `backend/humanos_graph.py`

### Step 4：改 Profile 调度输入

目标：

- scheduler 明确读取：
  - `available_windows`
  - `preferred_session_minutes`
  - `deep_work_window`
  - `low_energy_window`

涉及文件：

- `backend/humanos_server.py`
- `backend/humanos_graph.py`

### Step 5：改 Prompt 分层

目标：

- Task Parser 只负责抽字段。
- Task Dimension Agent 只负责补任务维度。
- Scheduler Agent 只负责排程。
- Validator Agent 只负责检查约束。
- Explanation Agent 只负责用户可读解释。

涉及文件：

- `backend/humanos_server.py`
- `backend/humanos_graph.py`

## 10. Phase 0 结论

当前 prototype 已经有：

- 登录注册
- Profile 保存
- 当前状态滑动条
- 多任务解析
- embedding memory
- LangGraph 调度骨架
- 用户确认后写入日历

但它还没有完全变成“计算机调度原理映射”：

- 现在的 task 更像日历事件，不是 ready queue 里的可调度对象。
- scheduler 还不是 DDL-first + constraint-aware。
- Profile 和 Dynamic Profile 已经收集，但没有充分进入调度决策。
- agent 名义上存在多个节点，但核心字段边界和输入输出还需要收紧。

因此下一步应先改 Task 字段和调度准入规则，再改 scheduler。UI 优化要在字段链路稳定之后进行。
