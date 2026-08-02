# HumanOS Prototype 分阶段修改计划

## 目标

把当前 prototype 从“用户说明几点做什么，系统画到日历”改成：

> 用户提供任务约束、Profile、当前状态；系统解析字段、生成调度、验证约束、等待确认、写入日历，并在执行后更新 memory。

本计划要求一部分一部分修改，每一步都要能单独验证。

## 工作原则

1. 每次只改一个模块，不做大范围重构。
2. 每个阶段都要有明确验收标准。
3. 先字段，再 prompt，再调度，再 UI。
4. 不把所有字段无差别塞给一个 agent。
5. 保持用户可控：计划写入日历前必须确认。

## Phase 0：现有字段与代码入口审计

### 目标

先搞清楚现有代码里已有字段、缺失字段、字段是否进入后端和 prompt。

### 检查文件

- `frontend/index.html`
- `frontend/app.js`
- `backend/humanos_server.py`
- `backend/humanos_graph.py`

### 输出

- 现有 Task 字段表
- 现有 Profile 字段表
- 现有 Dynamic Profile 字段表
- 现有 Prompt / Agent 输入表
- 缺口列表

### 验收

- 能明确指出哪些字段只是 UI 展示。
- 能明确指出哪些字段进入了后端。
- 能明确指出哪些字段进入了调度 prompt。

## Phase 1：Task 字段重构

### 目标

把 task 从简单日历项改成可调度对象。

### 当前实现状态

已完成第一轮最小实现：

- 前端 `missingTimeConfirmationFields` 已按 `flexible_task / fixed_event` 区分缺失字段。
- Flexible Task 不再要求具体开始时间，只要求标题、截止日期、预计时长。
- Fixed Event 仍要求日期和开始时间。
- 后端 parser schema 已增加 `task_type / deadline / estimated_duration`。
- 后端不改数据库表，通过 `contextWindow` 兼容保存 `taskType / deadline / estimatedDuration`。
- 后端任务返回值已暴露 `task_type / deadline / estimated_duration`。
- scheduler 已按 fixed event 优先、DDL 日期优先、priority 次优先排序。
- scheduler 已避免 flexible task 与 fixed event 时间块重叠。

尚未完成：

- 还没有单独的 Task Dimension Agent。
- `clarity / splittable / dependency_status / emotional_resistance` 还没有完整进入 parser 和 scheduler。
- 还没有完整 Constraint Validator Agent，只做了最小非重叠约束。

### 新增 / 明确字段

Flexible Task：

- `task_id`
- `task_type = flexible_task`
- `title`
- `deadline`
- `estimated_duration`
- `context`
- `goal`
- `cognitive_load`
- `clarity`
- `splittable`
- `recovery_cost`
- `dependency_status`
- `collaboration_required`
- `emotional_resistance`
- `flexibility`
- `status`

Fixed Event：

- `event_id`
- `task_type = fixed_event`
- `title`
- `start_time`
- `end_time`
- `event_type`
- `location`
- `buffer_needed`

### 行为变化

- Flexible Task 不要求具体开始时间。
- Flexible Task 最低门槛是 `title + deadline + estimated_duration`。
- Fixed Event 才要求固定开始/结束时间。

### 验收

- 输入“周五前读完 planning 论文，大概 3 小时”能生成 flexible task。
- 输入“明天上午 10 点组会 1 小时”能生成 fixed event。
- 缺 DDL 时追问 DDL。
- 缺预计时长时追问预计时长。
- 不再优先追问“几点开始”。

## Phase 2：Profile 字段重排与持久化

### 目标

让 Profile 变成调度可用字段，而不是背景问卷。

### 当前实现状态

已完成第一轮调度接入，但这是 legacy implementation，需要在 Phase 8 中拆分：

- scheduler 会读取 `task_preferences.available_windows`。
- scheduler 会读取 `task_preferences.preferred_session_minutes`。
- scheduler 会读取 `deep_work_window`。
- scheduler 会读取 `low_energy_window`。
- `available_windows` 作为调度候选窗口使用。
- 高负荷任务优先尝试落在 `deep_work_window` 与 `available_windows` 的交集里。
- 高负荷任务会尽量避开 `low_energy_window`。
- 低负荷任务可以填入低能量时段，避免高负荷任务被挤到不合适的位置。

新的目标模型中，`available_windows` 不再属于 Static Profile，而应迁移为 Weekly Context 的 `weekly_available_windows`。

尚未完成：

- Profile 页面字段顺序还没有最终视觉重排。
- `available_windows` 目前只解析时间段，还没有严格解析“周一/周三”这类星期条件。
- 字段仍保存在 `profiles.task_preferences` JSON 中，尚未 migration 成独立列。

### 目标字段顺序

Static Profile：

1. `learning_context`
2. `preferred_session_length`
3. `low_energy_window`
4. `deep_work_window`
5. `common_blockers`
6. `control_preference`
7. `planning_tools`

Weekly Context：

1. `weekly_available_windows`
2. `fixed_events`
3. `weekly_goal`
4. `temporary_constraints`
5. `important_deadlines`
6. `weekly_note`

### 验收

- Profile 页面按调度用途排序。
- 保存后后端 profile 可以读到字段。
- 调度 API 可以拿到这些字段。

## Phase 3：Dynamic Profile 接入调度

### 目标

确保当前状态滑动条不是只在前端展示，而是真正参与调度。

### 当前实现状态

已完成第一轮调度接入：

- scheduler 会读取 `focus / energy / stress`。
- `energy <= 3` 或 `focus <= 3` 时，普通任务块会缩短到最多 30 分钟。
- `stress >= 6` 且任务为高负荷任务时，任务块会缩短到最多 45 分钟。
- `energy / stress` 仍会影响是否需要用户确认。
- 调度解释会说明：是否按用户偏好的 session length、可用时间、低能量窗口进行安排。

尚未完成：

- 前端还没有输入 `mood / attention_residue`。
- `focus / energy / stress` 还没有进入 Task Dimension Agent。
- 还没有把动态状态变化写成长期 profile 更新规则。

### 字段

先接入：

- `focus`
- `energy`
- `stress`

后续再接入：

- `emotion`
- `readiness`
- `attention_residue`

### 验收

- 调度请求 payload 包含 `runtime_state`。
- 后端调度 context 包含 `focus / energy / stress`。
- energy 低时 session 变短。
- stress 高时更倾向要求确认。

## Phase 4：Prompt 与 Agent 输入重构

### 目标

按 agent 拆 prompt，不把所有字段塞给一个模型。

### 当前实现状态

已完成第一轮最小实现：

- `Task Parser Agent` 继续负责从用户输入中抽取任务、任务类型、截止日期和预计时长。
- 新增 `Task Dimension Agent`：
  - 输入单个 task 与最近上下文。
  - 输出 `cognitive_load / ambiguity / clarity / splittable / recovery_cost / dependency_status / collaboration_required / emotional_resistance / confidence`。
  - 有 DeepSeek 时尝试模型判断；失败时使用本地规则兜底。
  - 输出保存在后端 `contextWindow.dimensions`，前端默认不直接展示内部字段。
- `Scheduler Agent` 只接收任务、Profile、动态状态和检索记忆，不接收完整聊天历史。
- 新增 `Constraint Validator Agent`：
  - 在调度草案之后单独检查固定事件冲突、可用时间、低能量窗口、缺失字段和低清晰度任务。
  - 输出 `violations`，由前端映射成中文解释，不暴露内部枚举名。
- `Explanation Agent` 继续负责把调度理由转成用户可读文本，并避免出现 embedding、后端、沉淀等内部表述。

尚未完成：

- Task Dimension Agent 还没有独立 API 调试端点。
- Validator 目前只做规则校验，还没有自动回写调整建议。
- 前端任务详情页还没有做“用户可读的任务维度摘要”。

### Agent Prompt 映射

Task Parser Agent：

- 输入：`raw_user_input`, `recent_turns`, `task_schema`
- 输出：`tasks`, `fixed_events`, `missing_fields`

Task Dimension Agent：

- 输入：`task`, `task_context`
- 输出：`cognitive_load`, `clarity`, `splittable`, `recovery_cost`, `dependency_status`

Scheduler Agent：

- 输入：`ready_tasks`, `fixed_events`, `static_profile`, `dynamic_profile`, `retrieved_memories`
- 输出：`schedule_draft`, `ready_queue`, `confidence`, `reasons`

Constraint Validator Agent：

- 输入：`schedule_draft`, `fixed_events`, `deadlines`, `weekly_available_windows`, `preferred_session_length`, `low_energy_window`, `momentary_state`
- 输出：`valid`, `violations`, `adjustments`, `validated_plan`

Explanation Agent：

- 输入：`validated_plan`, `key_reasons`, `dynamic_profile`, `retrieved_memory_summary`, `confidence`
- 输出：`user_facing_explanation`, `first_action`, `risk`, `requires_confirmation`

### 验收

- 每个 prompt 输入 JSON 可单独打印或记录。
- Scheduler 不接收完整聊天历史。
- Explanation 不暴露 embedding / backend 术语。

## Phase 5：DDL 优先调度

### 目标

把排序逻辑从手动高/中/低优先级改成 DDL + 任务维度 + 用户状态。

### 排序规则

1. Fixed Event 先占据日历。
2. Flexible Task 按 DDL 进入 ready queue。
3. 预计时长决定切块。
4. 高 cognitive load 优先放 deep work window。
5. low energy window 避开高负荷任务。
6. energy 低则缩短 session。
7. stress 高则要求确认。

### 验收

- DDL 近的任务优先。
- 没有 DDL 的任务不进入 ready queue。
- Fixed Event 不会被移动。
- 高负荷任务优先进入 deep work window。

## Phase 6：约束验证层

### 目标

计划生成后先系统自检，再交给用户确认。

### Validator 输出

```json
{
  "valid": true,
  "violations": [],
  "adjustments": [],
  "requires_confirmation": true
}
```

### 检查约束

- DDL 是否可达
- 是否与 fixed event 冲突
- 是否在 available windows 内
- 是否超过 preferred session length
- 高负荷任务是否落在 low energy window
- 当前 energy / stress 是否适合该计划

### 验收

- 冲突计划不会直接写入日历。
- Validator 能输出原因。
- 用户看到的是可读解释，不是内部字段。

## Phase 7：Execution Feedback 与 Memory 闭环

### 目标

让任务完成、中断、切换后的数据进入 memory，下一轮调度能用上。

### 设计修正

Profile 更新必须区分三层：

- `Episodic Memory`：单次行为或单次失败，只记录，不直接改 Static Profile。
- `Learned Pattern`：同类证据重复出现 3-5 次，或用户明确确认后形成稳定模式。
- `Static Profile`：只由稳定模式或用户确认更新。

Dynamic Profile 拆成：

- `Weekly Context`：每周重建，包括 `weekly_available_windows`, `fixed_events`, `weekly_goal`, `temporary_constraints`, `important_deadlines`, `weekly_note`。
- `Momentary State`：随时更新，包括 `focus`, `energy`, `stress`, `emotion`, `readiness`, `daily_note`, `attention_residue`。

`confidence_to_complete` 应在计划确认时或任务开始前收集，不在任务结束后收集。

中断任务不新建 `recovery_task`。原任务进入 `paused`，通过 `context_dump`, `remaining_duration`, `recovery_cue` 恢复。

### 字段

Task Feedback：

- `completion_status`
- `actual_duration`
- `perceived_difficulty`
- `progress_summary`
- `open_questions`
- `next_step`
- `interruption_reason`
- `remaining_duration`

State Feedback：

- `post_focus`
- `post_energy`
- `post_stress`
- `attention_residue`
- `next_action_preference`

System Feedback：

- `schedule_helpfulness`
- `explanation_clarity`
- `timing_fit`
- `control_feeling`
- `user_override`

### 验收

- 完成任务后生成 memory。
- 中断任务后生成 context dump。
- 下一次类似任务可以检索到相关 memory。
- Explanation 能引用历史经验的摘要。
- 单次失败不会直接更新 Static Profile。
- 同类问题重复出现或用户确认后，才生成 Learned Pattern。

## Phase 8：Profile / Context 数据模型修正

### 目标

把当前 Static Profile 中混入的短期字段拆出去，避免 Scheduler prompt 收到无关字段。

### 修改项

- 从 Static Profile 的调度输入中移除 `available_windows`。
- 新增 Weekly Context 保存和读取路径。
- Scheduler Agent 使用 `weekly_available_windows`，不是 Static Profile 的 `available_windows`。
- `planning_tools` 不默认进入 Scheduler prompt。
- Task Dimension Agent 使用 `expected_difficulty + task features` 推断 `cognitive_load`。
- Execution feedback 用 `perceived_difficulty` 校准后续 cognitive load。

### 验收

- 每周可用时间可以单独更新，不污染 Static Profile。
- Scheduler prompt 中没有默认 `planning_tools`。
- 单次行为只生成 Episodic Memory。
- 3-5 次重复或用户确认后才建议更新 Static Profile。

## 推荐执行顺序

本轮先执行：

1. Phase 0：字段与代码入口审计。
2. Phase 1：Task 字段重构。

完成后再进入：

3. Phase 2：Profile 字段重排。
4. Phase 3：Dynamic Profile 接入调度。

## 每阶段提交策略

每个 Phase 单独提交：

- `docs: add implementation plan`
- `audit: document current field flow`
- `task: add flexible task and fixed event fields`
- `profile: reorder scheduling fields`
- `state: route runtime sliders into scheduling`
- `agent: split prompt inputs by agent`
- `schedule: prioritize tasks by deadline`
- `validator: add schedule constraint checks`
- `memory: persist execution feedback`
