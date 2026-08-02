# HumanOS 字段定义、Prompt 设计与系统框架

## 0. 本文档目的

本文档的目的不是总结会议，也不是直接列功能需求，而是先把 HumanOS 的底层变量定义清楚：

1. 系统到底有哪些基本字段。
2. `task`、`static profile`、`dynamic profile` 分别指什么。
3. 每个字段在什么时候收集。
4. 每个字段是否参与调度、是否进入 memory、是否进入 prompt。
5. prompt 应该如何拼接。
6. 整个系统框架如何围绕这些字段运行。

核心原则：

> 用户不应该先把“几点做什么”排好再交给系统。用户应该提供任务约束，HumanOS 根据 DDL、预计时长、可用时间、当前状态和历史记忆完成调度。

## 1. 总体变量分层

HumanOS 的变量分为五层：

| 层级 | 名称 | 作用 | 更新频率 |
| --- | --- | --- | --- |
| L1 | Static Profile | 用户长期画像 | 初次使用 / 用户主动修改 |
| L2 | Dynamic Profile | 用户当前状态和短期状态 | 每天 / 每次任务前后 |
| L3 | Task Object | 待调度任务对象 | 用户新增 / AI 解析 |
| L4 | Execution Feedback | 执行、中断、完成反馈 | 任务进行中 / 任务结束 |
| L5 | System Memory | 系统沉淀的历史经验 | 自动更新 |

这五层共同进入调度：

```text
Static Profile
      +
Dynamic Profile
      +
Task Object
      +
Execution Feedback / Memory
      ↓
Prompt Assembly
      ↓
Scheduling + Constraint Validation
      ↓
User Confirmation
      ↓
Calendar + Memory Update
```

## 2. Task Object 字段定义

### 2.1 Task 的定义

`Task` 是 HumanOS 的基本调度对象，对应计算机调度中的 job / process。

一个 task 不等于一个已经排好的日程。  
一个 task 应该是一个带有约束的待调度对象。

### 2.2 Task 类型

| 类型 | 定义 | 是否由系统调度 |
| --- | --- | --- |
| Flexible Task | 用户需要完成，但没有固定开始时间的任务 | 是 |
| Fixed Event | 已经有固定时间的事件，例如会议、课程、访谈 | 否，只作为约束 |

不单独设置 `Recovery Task`。被中断后的任务仍然是原来的 Task，只是进入 `paused` 状态，并通过 `context_dump`, `remaining_duration`, `recovery_cue`, `next_step` 支持恢复。

### 2.3 Flexible Task 字段

| 字段名 | 中文名 | 类型 | 是否必填 | 来源 | 调度用途 |
| --- | --- | --- | --- | --- | --- |
| `task_id` | 任务 ID | string | 系统生成 | 系统 | 唯一标识 |
| `title` | 任务名称 | string | 必填 | 用户 / AI 解析 | 展示和语义检索 |
| `task_type` | 任务类型 | enum | 推荐 | AI 解析 / 用户选择 | 判断任务负荷 |
| `deadline` | 截止期 / DDL | datetime/text | 必填 | 用户 | 优先级排序核心依据 |
| `estimated_duration` | 预计总时长 | minutes | 必填 | 用户 | 切分 session |
| `context` | 任务上下文 | text | 推荐 | 用户 / 对话 | 支持恢复 |
| `goal` | 任务目标 | text | 推荐 | 用户 | 判断完成标准 |
| `expected_difficulty` | 用户预期难度 | 1-7 / low-mid-high | 可选 | 用户 | 作为认知负荷估计输入之一 |
| `cognitive_load` | 任务认知负荷 | low/mid/high | 系统推断 | AI | 与当前状态匹配，调整 session 长度 |
| `clarity` | 任务清晰度 | low/mid/high | 系统推断 / 用户修正 | AI / 用户 | 低清晰度任务先澄清 |
| `splittable` | 是否可拆分 | boolean | 推荐 | 用户 / AI | 决定是否拆成多个 session |
| `remaining_duration` | 剩余时长 | minutes | 系统维护 | 执行反馈 | 任务暂停后继续使用同一个 task |
| `materials_needed` | 所需材料 | text/list | 可选 | 用户 | 判断是否 blocked |
| `status` | 当前状态 | enum | 系统维护 | 系统 | 队列状态 |

### 2.4 Fixed Event 字段

| 字段名 | 中文名 | 类型 | 是否必填 | 调度用途 |
| --- | --- | --- | --- | --- |
| `event_id` | 固定事件 ID | string | 系统生成 | 唯一标识 |
| `title` | 事件名称 | string | 必填 | 展示 |
| `start_time` | 开始时间 | datetime | 必填 | 占用日历 |
| `end_time` | 结束时间 | datetime | 必填 | 占用日历 |
| `event_type` | 事件类型 | enum | 推荐 | 会议 / 课程 / 访谈 / 外出 |
| `location` | 地点 | string | 可选 | 判断切换成本 |
| `buffer_needed` | 是否需要缓冲 | boolean/minutes | 可选 | 前后留时间 |

### 2.5 Task 状态

| 状态 | 含义 | OS 映射 |
| --- | --- | --- |
| `incomplete_info` | 缺少 DDL / 预计时长 / 可用时间 | Waiting / Blocked |
| `ready` | 信息完整，可以进入调度队列 | Ready Queue |
| `scheduled` | 已生成计划但未开始 | Dispatcher 后 |
| `running` | 当前正在执行 | Running on CPU |
| `paused` | 被中断，等待恢复 | Interrupt / Context Switch |
| `completed` | 已完成 | Terminated |

### 2.6 Task 的最低输入门槛

Flexible Task 最低只需要：

1. `title`
2. `deadline`
3. `estimated_duration`

不应强制要求：

1. 具体开始时间
2. 具体结束时间
3. 手动高/中/低优先级

原因：如果用户已经给了具体开始结束时间，用户实际上已经完成了调度，系统没有发挥调度作用。

### 2.7 用户难度与 AI 认知负荷

`expected_difficulty` 和 `cognitive_load` 不能混用：

- `expected_difficulty` 是用户认为这个任务有多难。
- `cognitive_load` 是系统用于调度的估计认知负荷。

Task Dimension Agent 应使用以下输入估计 `cognitive_load`：

```text
expected_difficulty
+ task_type
+ 任务动作特征，例如阅读、写作、代码、复现、总结
+ clarity
+ estimated_duration
+ collaboration_required / dependency_status
+ 历史 feedback 中的 perceived_difficulty / actual_duration / interruption_reason
→ cognitive_load
```

调度时使用的是 `cognitive_load` 与当前 `focus / energy / stress` 的匹配，而不是直接使用用户填写的 difficulty。

执行后再用用户反馈校准：

```text
perceived_difficulty
+ actual_duration
+ completion_status
+ interruption_reason
→ 校准同类任务的 cognitive_load / estimated_duration / recovery_cost
```

### 2.8 中断恢复仍属于原 Task

HumanOS 不应把“恢复任务”建成新 task。状态迁移应是：

```text
ready / scheduled / running
→ paused
→ scheduled / running
→ completed
```

这样可以保留同一个 task 的剩余时长、上下文窗口、材料、开放问题、执行反馈和 memory 链路。

## 3. Static Profile 字段定义

### 3.1 Static Profile 的定义

`Static Profile` 是用户长期相对稳定的信息，用来提供个性化调度的边界条件。

它不是每次调度都变化，也不应该因为一次行为或一次失败就被直接改写。单次行为只进入 `Episodic Memory`。只有当证据稳定后，才可以升级为 `Learned Pattern` 并更新 Static Profile。

证据稳定可以通过两种方式判断：

1. 系统观察到同类问题重复出现，例如同一 blocker / 同一时段失败 / 同一任务类型恢复困难出现 3-5 次。
2. 用户明确确认：“这确实是我的一个常见问题 / 常见模式”。

因此 HumanOS 的长期个性化应分成：

- `Episodic Memory`：单次事件记录，例如“今天 14:00 阅读任务因为精力低中断”。
- `Learned Pattern`：多次证据或用户确认后的稳定规律，例如“用户通常在 14:00-15:30 不适合高负荷阅读”。
- `Static Profile`：由用户长期身份、学习场景、偏好和 learned pattern 组成的稳定画像。

Static Profile 不应全量进入每次调度 prompt。调度只读取必要字段，例如 `learning_context`, `preferred_session_length`, `deep_work_window`, `common_blockers`, `control_preference`。`planning_tools` 这类字段只在解释工具差异或研究分析时使用，不默认进入 Scheduler prompt。

### 3.2 Static Profile 字段

| 字段名 | 中文名 | 类型 | 收集时机 | 调度用途 | 是否入 prompt | 是否入 memory |
| --- | --- | --- | --- | --- | --- | --- |
| `user_role` | 用户身份 | enum | 初次使用 | 区分本科 / 硕士 / 自主研究者 | 是 | 是 |
| `learning_context` | 学习场景 | enum/list | 初次使用 | 区分课程、论文、项目、考试 | 是 | 是 |
| `preferred_session_length` | 偏好专注时长 | minutes | 初次使用 | 任务切块 | 是 | 是 |
| `low_energy_window` | 低精力时间段 | time range | 初次使用 | 避免高负荷任务 | 是 | 是 |
| `deep_work_window` | 深度工作偏好时间 | time range | 初次使用 | 优先安排高负荷任务 | 是 | 是 |
| `planning_tools` | 常用计划工具 | list | 初次使用 | 解释工具差异 / 研究分析 | 否，除非任务相关 | 是 |
| `common_blockers` | 常见卡点 | list | 初次使用 | 生成风险提醒 | 是 | 是 |
| `control_preference` | 控制偏好 | enum | 初次使用 | 是否自动调整 / 是否确认 | 是 | 是 |

### 3.3 Static Profile 页面字段顺序

Profile 页面应按调度使用优先级排序：

1. 学习 / 研究场景：`learning_context`
2. 偏好专注时长：`preferred_session_length`
3. 低精力时间：`low_energy_window`
4. 深度工作时间：`deep_work_window`
5. 常见卡点：`common_blockers`
6. 控制偏好：`control_preference`
7. 常用计划工具：`planning_tools`

本周可用时间不属于 Static Profile，应放入 Weekly Context。

## 4. Dynamic Profile 字段定义

### 4.1 Dynamic Profile 的定义

`Dynamic Profile` 是用户短期上下文和当前状态，对应计算机调度中的当前可用资源与本周约束。

Static Profile 描述“这个人通常怎样”，Dynamic Profile 描述“这一周 / 这一刻怎样”。

Dynamic Profile 分成两个内部块：

1. `Weekly Context`：本周重建一次，描述这一周的任务环境和临时约束。
2. `Momentary State`：随时更新，描述用户此刻的资源状态。

### 4.2 Weekly Context 字段

| 字段名 | 中文名 | 类型 | 收集方式 | 更新频率 | 调度用途 |
| --- | --- | --- | --- | --- | --- |
| `weekly_available_windows` | 本周可用时间 | weekly schedule | 用户输入 / 日历同步 | 每周 | 决定 flexible task 可排位置 |
| `fixed_events` | 固定事件 | calendar events | 用户输入 / 日历同步 | 每周 / 实时 | 先占据日历，不可随意移动 |
| `weekly_goal` | 本周目标 | text/list | 用户输入 | 每周 | 决定任务优先级和解释重点 |
| `temporary_constraints` | 临时约束 | text/list | 用户输入 | 每周 / 每天 | 例如出行、考试周、临时会议 |
| `important_deadlines` | 重要截止日期 | list | 用户输入 / 任务抽取 | 每周 / 实时 | DDL 优先排序 |
| `weekly_note` | 本周备注 | text | 用户输入 | 每周 | 提供本周背景，不进入每个 agent 的全量 prompt |

### 4.3 Momentary State 字段

| 字段名 | 中文名 | 类型 | 收集方式 | 收集时机 | 调度用途 |
| --- | --- | --- | --- | --- | --- |
| `focus` | 当前专注度 | 1-7 slider | 用户自评 | 当前状态面板 / 任务前 | 判断是否适合深度任务 |
| `energy` | 当前精力 | 1-7 slider | 用户自评 | 当前状态面板 / 任务前 | 调整 session 长度 |
| `stress` | 当前压力 | 1-7 slider | 用户自评 | 当前状态面板 / 任务前 | 决定是否需要拆分 / 确认 |
| `emotion` | 当前情绪 | emoji / 1-5 | 用户自评 | 每日 / 任务前后 | 调整提示语气 |
| `readiness` | 任务准备度 | 1-7 Likert | 用户自评 | 任务开始前 | 判断是否进入 running |
| `attention_residue` | 注意力残留 | 1-7 Likert / 问答 | 用户自评 / AI 推断 | 任务切换时 | 判断恢复成本 |
| `confidence_to_complete` | 完成信心 | 0-1 / 1-7 | 用户自评 / AI 推断 | 计划确认时 / 任务开始前 | 判断计划是否需要改 |
| `daily_note` | 今日自我描述 | text | 用户输入 | 每天第一次进入 | 提供当天上下文 |

### 4.4 Dynamic Profile 与滑动条

当前 prototype 中已有：

- focus
- energy
- stress

这三个滑动条不能只用于前端展示，必须进入：

1. 调度 prompt
2. 约束验证
3. 调度解释
4. memory 检索 query

### 4.5 Dynamic Profile 更新频率

| 场景 | 应更新字段 |
| --- | --- |
| 每周第一次打开系统 | `weekly_available_windows`, `fixed_events`, `weekly_goal`, `temporary_constraints`, `important_deadlines`, `weekly_note` |
| 每天第一次打开系统 | `daily_note`, `emotion`, `focus`, `energy`, `stress` |
| 用户确认计划 / 准备开始任务 | `confidence_to_complete`, `readiness`, `focus`, `energy`, `stress` |
| 用户切换任务 | `attention_residue`, `emotion`, `stress` |
| 用户完成任务 | `emotion`, `actual_duration`, `perceived_difficulty`, `system_helpfulness` |

`confidence_to_complete` 不应在任务结束后收集。任务结束后应收集的是实际执行评价，例如完成度、实际难度、耗时和系统建议是否有用。

## 5. Execution Feedback 字段定义

### 5.1 Execution Feedback 的定义

`Execution Feedback` 是任务执行中或执行后产生的数据，用于更新 Task Model、Momentary State、系统建议质量和长期 memory。

它是 HumanOS 区别于普通计划工具的关键：系统不只记录任务是否存在，还记录用户如何中断、如何恢复、为什么没按计划执行。

### 5.2 反馈分层

Execution Feedback 应拆成三类：

1. `Task Feedback`：评价刚才这个任务，用来更新 Task Model。
2. `State Feedback`：评价当前状态，用来决定接下来继续、休息、切换或重排。
3. `System Feedback`：评价 HumanOS 的建议质量，用来评估推荐是否有帮助。

### 5.3 Task Feedback 字段

| 字段名 | 中文名 | 类型 | 触发时机 | 用途 |
| --- | --- | --- | --- | --- |
| `completion_status` | 完成状态 | completed / partial / failed | 任务结束 | 判断是否需要重排 |
| `actual_duration` | 实际耗时 | minutes | 任务结束 | 校准预计时长 |
| `progress_summary` | 当前进展 | text | 中断 / 完成 | 恢复任务 |
| `open_questions` | 未解决问题 | text/list | 中断 / 完成 | 恢复任务 |
| `next_step` | 回来第一步 | text | 中断 / 完成 | 降低恢复成本 |
| `interruption_reason` | 中断原因 | enum/text | 中断发生 | 更新 blocker 模式 |
| `perceived_difficulty` | 主观难度 | 1-7 | 任务结束 | 更新认知负荷估计 |
| `remaining_duration` | 剩余时长 | minutes | 中断 / 部分完成 | 保持原任务连续性 |

### 5.4 State Feedback 字段

| 字段名 | 中文名 | 类型 | 触发时机 | 用途 |
| --- | --- | --- | --- | --- |
| `post_focus` | 任务后专注度 | 1-7 | 任务结束 / 中断 | 判断是否继续深度任务 |
| `post_energy` | 任务后精力 | 1-7 | 任务结束 / 中断 | 判断是否休息 |
| `post_stress` | 任务后压力 | 1-7 | 任务结束 / 中断 | 判断是否重排 |
| `attention_residue` | 注意力残留 | 1-7 / text | 切换任务时 | 判断恢复成本 |
| `next_action_preference` | 下一步偏好 | continue / rest / switch / reschedule | 任务结束 | 决定下一步策略 |

### 5.5 System Feedback 字段

| 字段名 | 中文名 | 类型 | 触发时机 | 用途 |
| --- | --- | --- | --- | --- |
| `schedule_helpfulness` | 安排是否有帮助 | 1-7 | 任务结束 / 计划确认后 | 评估调度建议 |
| `explanation_clarity` | 解释是否清楚 | 1-7 | 用户查看建议后 | 评估解释质量 |
| `timing_fit` | 时间是否合适 | 1-7 | 任务结束 | 评估时间块质量 |
| `control_feeling` | 用户控制感 | 1-7 | 计划确认 / 任务后 | 判断 human-in-the-loop 是否有效 |
| `user_override` | 用户是否手动覆盖建议 | boolean/text | 用户拖拽 / 编辑 / 拒绝时 | 学习系统哪里判断不准 |

## 6. System Memory 字段定义

### 6.1 System Memory 的定义

`System Memory` 是由 profile、task、runtime state、feedback 和 chat turn 生成的可检索历史记录。

它不直接等于数据库表，而是调度前可被 embedding search 检索出来的经验片段。

### 6.2 Memory 来源

| 来源 | 例子 | 用途 |
| --- | --- | --- |
| Profile | 用户通常下午低精力 | 调度避开低精力时段 |
| Runtime State | 今天 energy=3, stress=6 | 当前计划拆小 |
| Task | 阅读论文预计 180 分钟 | 任务切块 |
| Chat Turn | 用户说“开始不了” | 识别卡点 |
| Context Dump | 上次停在 related work gap | 恢复任务 |
| Completion Feedback | 实际耗时比预期多 60 分钟 | 校准估时 |

### 6.3 Memory 进入 prompt 的方式

Memory 不应直接全部塞入 prompt，而应：

1. 用当前任务 + 当前状态 + 用户输入构造 query。
2. 通过 embedding search 检索最相似的历史片段。
3. 只把 top-k 片段放进 prompt。
4. 在用户界面中用自然语言解释，不暴露 embedding / vector 等术语。

## 7. Prompt 设计

### 7.1 Prompt 总体结构

每次调度 prompt 应由 7 个部分组成：

```text
System Role
Static Profile
Weekly Context
Dynamic Profile
Task Objects
Calendar Constraints
Retrieved Memory
Output Schema
```

### 7.2 System Prompt

目标：定义 HumanOS 的角色和边界。

```text
你是 HumanOS 的学习任务调度 agent。
你的目标不是简单复述用户输入，而是根据任务 DDL、预计时长、用户可用时间、当前状态和历史记忆生成可执行计划。
不要要求用户直接给出每个任务的开始时间，除非该任务是固定事件。
所有计划必须等待用户确认后才能写入日历。
输出必须是 JSON。
```

### 7.3 Static Profile Prompt

应包含：

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

不默认包含：

```json
{
  "planning_tools": ["Calendar", "Notion"]
}
```

除非当前任务是在比较工具、解释用户已有计划方式，或做研究分析，否则 `planning_tools` 不进入 Scheduler prompt。

### 7.3.1 Weekly Context Prompt

应包含：

```json
{
  "weekly_available_windows": "周一/三 19:00-21:00，周六 09:00-12:00",
  "fixed_events": ["周二 10:00 组会"],
  "weekly_goal": "读完 planning 相关论文并整理 gap",
  "temporary_constraints": ["周四外出"],
  "important_deadlines": ["周五前发给队友"],
  "weekly_note": "这周主要压力来自 presentation。"
}
```

### 7.4 Dynamic Profile Prompt

应包含：

```json
{
  "focus": 5,
  "energy": 4,
  "stress": 5,
  "emotion": "neutral",
  "confidence_to_complete": 5,
  "readiness": 4,
  "attention_residue": 3,
  "daily_note": "今天上午状态一般，但下午有较完整时间。"
}
```

### 7.5 Task Prompt

Flexible Task 示例：

```json
{
  "task_id": "task_001",
  "task_type": "flexible_task",
  "title": "阅读 AI planning 相关论文",
  "deadline": "2026-08-05 18:00",
  "estimated_duration": 180,
  "expected_difficulty": 5,
  "context": "需要总结这些论文如何 planning、gap 是什么、功能是什么",
  "splittable": true,
  "cognitive_load": "high",
  "status": "ready"
}
```

Fixed Event 示例：

```json
{
  "event_id": "event_001",
  "task_type": "fixed_event",
  "title": "组会",
  "start_time": "2026-08-02 10:00",
  "end_time": "2026-08-02 11:00"
}
```

### 7.6 Constraint Prompt

约束应显式写入：

```json
{
  "constraints": [
    "fixed_event 不可移动",
    "flexible_task 必须在 deadline 前完成",
    "优先安排 DDL 更近的任务",
    "高 cognitive_load 任务优先放入 deep_work_window",
    "energy <= 3 时单个 session 不超过 30 分钟",
    "stress >= 6 时需要用户确认后再调整",
    "计划不得与 fixed_event 重叠"
  ]
}
```

### 7.7 Output Schema

```json
{
  "ready_queue": [
    {
      "task_id": "task_001",
      "priority_reason": "DDL 最近，且预计耗时较长"
    }
  ],
  "plan": [
    {
      "task_id": "task_001",
      "start": "2026-08-02 09:00",
      "end": "2026-08-02 09:45",
      "mode": "deep_work",
      "reason": "放在用户深度工作窗口内"
    }
  ],
  "constraint_check": {
    "valid": true,
    "violations": [],
    "adjustments": []
  },
  "confidence": 0.82,
  "questions": [],
  "requires_confirmation": true,
  "user_facing_explanation": "我先把 DDL 最近且负荷较高的论文阅读放到上午深度工作窗口，并拆成 45 分钟的小段。"
}
```

## 8. 调度逻辑

### 8.1 Ready Queue 进入条件

Flexible Task 进入 ready queue 需要：

1. 有任务名称。
2. 有 DDL。
3. 有预计时长。
4. 用户有本周可用时间，来自当前输入或 Weekly Context。

缺任何一个字段则进入 `incomplete_info`。

### 8.2 排序规则

当前阶段使用简单透明规则：

1. DDL 越近，越优先。
2. Fixed Event 不进入 ready queue，而是先占据日历。
3. 预计时长越长，越需要提前拆分，但不直接覆盖 DDL。
4. 高认知负荷任务优先放入 deep work window。
5. 当前 energy 低或 stress 高时，单个 session 缩短。

### 8.3 约束验证

系统生成初始计划后必须验证：

| 约束 | 检查问题 |
| --- | --- |
| DDL | 是否能在截止期前完成 |
| fixed event | 是否与固定事件冲突 |
| availability | 是否落在用户可用时间 |
| session length | 是否超过偏好专注时长 |
| low energy | 高负荷任务是否落在低精力时间 |
| dynamic state | 当前状态是否适合计划长度 |

## 9. 系统框架

### 9.1 模块结构

```text
User Input
  ↓
Input Parser
  ├─ Flexible Task Extractor
  ├─ Fixed Event Extractor
  └─ Missing Field Detector
  ↓
Profile Manager
  ├─ Static Profile
  └─ Dynamic Profile
  ↓
Memory Retriever
  ├─ Task Memory
  ├─ Runtime Memory
  ├─ Feedback Memory
  └─ Chat Memory
  ↓
Scheduler
  ├─ Ready Queue Builder
  ├─ DDL Sorter
  ├─ Session Splitter
  └─ Calendar Allocator
  ↓
Constraint Validator
  ↓
Explanation / Confidence Agent
  ↓
User Confirmation
  ↓
Calendar Commit
  ↓
Execution Feedback
  ↓
Memory Update
```

### 9.2 与 OS 调度映射

| OS 调度概念 | HumanOS 字段 / 模块 |
| --- | --- |
| Job Arrival | 用户输入 Flexible Task / Fixed Event |
| Process Control Block | Task Object |
| Ready Queue | DDL、预计时长、可用时间完整的 Flexible Task |
| CPU Scheduler | Scheduler：DDL Sorter + Session Splitter |
| Dispatcher | 用户确认后 Calendar Commit |
| Running | 当前执行中的 Task |
| Interrupt | 外部打断 / 用户切换任务 |
| Context Switch | Context Dump：progress / open questions / next step |
| Waiting / Blocked | incomplete_info / 缺材料 / 缺 DDL |
| Terminated | completed + Execution Feedback |

## 10. 字段优先级总结

当前最重要的字段不是所有字段，而是这 12 个：

| 优先级 | 字段 | 所属层级 | 原因 |
| --- | --- | --- | --- |
| P0 | `title` | Task | 没有任务名无法调度 |
| P0 | `deadline` | Task | DDL 是优先级核心 |
| P0 | `estimated_duration` | Task | 决定切块 |
| P0 | `weekly_available_windows` | Weekly Context | 决定本周可排时间 |
| P0 | `focus` | Dynamic Profile | 判断当前可用认知资源 |
| P0 | `energy` | Dynamic Profile | 判断 session 长度 |
| P0 | `stress` | Dynamic Profile | 判断是否需要确认 / 拆分 |
| P1 | `preferred_session_length` | Static Profile | 个性化切块 |
| P1 | `low_energy_window` | Static Profile | 避开高负荷任务 |
| P1 | `context` | Task | 支持恢复 |
| P1 | `next_step` | Feedback | 支持中断后继续 |
| P1 | `actual_duration` | Feedback | 校准后续估时 |

## 11. 下一步修改方向

基于这些字段，后续代码修改应按这个顺序：

1. 修改任务输入：Flexible Task 只要求 DDL + 预计时长，不要求开始时间。
2. 增加 Fixed Event 类型：固定事件作为 calendar constraint。
3. 重排 Profile 页面：把调度字段放在前面。
4. 确认 focus / energy / stress 进入调度 prompt。
5. 增加 Dynamic Profile 的 emotion / readiness / attention residue。
6. 增加约束验证层。
7. 增加 Execution Feedback 到 memory 的闭环。

## 12. 一句话定义

HumanOS 的核心不是“帮用户画日历”，而是：

> 把用户的任务、DDL、预计时长、可用时间、当前状态和历史执行经验组织成可调度变量，再通过约束验证和用户确认生成可执行计划，并在中断与完成后持续更新用户模型。
