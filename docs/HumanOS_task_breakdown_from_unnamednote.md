# HumanOS 任务划分：基于 Unnamednote 手写草图

来源：`source_materials/Unnamednote(1)_0_1785513663148.pdf`

说明：该 PDF 是 5 页手写草图，无法直接提取文本。以下内容基于页面视觉读取整理，重点不是逐字转写，而是把草图中的系统模块转化为可执行的 prototype 任务划分。

## 1. 草图中的核心结构

草图大致把 HumanOS 分成五类模块：

1. User context：用户背景、个人信息、偏好、状态。
2. Tasks：固定任务输入，包括 DDL、预计时间、优先级、每周目标、固定开始时间等。
3. Self-report：用户每天或任务切换时的主观状态报告，主要通过滑动条、Likert、emoji 等方式收集。
4. Switch / completion：任务切换、任务完成后的反馈，包括完成情况、当前状态、灵活性问题。
5. Dynamic / memory：通过 embedding search 检索历史数据、对话数据和行为数据，辅助 DeepSeek / LLM 生成计划与解释。

## 2. 一级任务划分

| 编号 | 模块 | 目标 | 优先级 |
| --- | --- | --- | --- |
| T1 | User Context / Profile | 明确用户画像字段及其调度用途 | 高 |
| T2 | Task Input | 重新定义任务输入字段，降低用户必须给具体时间的门槛 | 高 |
| T3 | Self-report | 设计用户状态自评入口，收集 focus / energy / stress / emotion | 高 |
| T4 | Scheduling Logic | 根据 DDL、预计时长、可用时间、状态和 profile 自动排程 | 高 |
| T5 | Switch / Completion Feedback | 在任务切换和完成时收集恢复相关信息 | 高 |
| T6 | Memory / Embedding Search | 把 profile、任务、对话、自评、完成反馈写入可检索 memory | 中 |
| T7 | LLM Prompt / Confidence | 让 DeepSeek 使用结构化上下文，并输出置信度和解释 | 中 |
| T8 | Fixed Questions / Flexibility | 设计固定问题和弹性追问机制 | 中 |
| T9 | Environment / Fixed Tasks | 支持固定事件、外部约束和环境条件 | 低到中 |

## 3. T1：User Context / Profile

### 3.1 草图依据

第一页写到：

- User
- Context
- 初始 profile / 偏好
- 个人信息
- 本科、硕士、自由学习者
- 用户模型
- 问卷结合经验
- 每天早上自我描述
- 不同时间状态偏好规律
- 1-7 Likert

### 3.2 需要实现的任务

| 子任务 | 内容 | 输出 |
| --- | --- | --- |
| T1.1 | 整理 Profile 字段 | 字段清单 |
| T1.2 | 区分长期字段和即时字段 | long-term profile / runtime state |
| T1.3 | 明确每个字段进入哪个调度环节 | 字段-调度映射表 |
| T1.4 | 重新排序 Profile 页面 | 按调度使用顺序展示 |
| T1.5 | 增加“每日早上自我描述”入口 | daily check-in |

### 3.3 推荐字段

| 字段 | 类型 | 调度用途 |
| --- | --- | --- |
| 用户身份 | 长期 profile | 决定默认任务类型和解释语言 |
| 学习阶段 | 长期 profile | 区分本科 / 硕士 / 自主研究任务 |
| 可用时间 | 长期或每周 profile | 决定任务可放入哪些窗口 |
| 偏好专注时长 | 长期 profile | 决定任务切块大小 |
| 低精力时间 | 长期 profile | 避开高负荷任务 |
| 常见卡点 | 长期 profile | 生成风险提醒和恢复提示 |
| 每日自我描述 | runtime state | 估计当天状态 |
| focus / energy / stress | runtime state | 调整 session 长度和确认策略 |
| emotion / mood | runtime state | 影响提示语气和任务拆分 |

## 4. T2：Task Input

### 4.1 草图依据

第一页底部写到 Tasks：

- DDL
- 预计时间
- 优先级
- every week
- motivation / goal
- fixed meeting batch
- 固定开始时间

第五页也提到：

- 常规任务
- 固定时间条件
- 事件
- environment
- fixed tasks

### 4.2 任务输入应分两类

#### A. Flexible Task：可调度任务

这类任务由系统安排时间。

必填：

- 任务名称
- DDL
- 预计时长

可选：

- 任务上下文
- motivation / goal
- 任务难度
- 是否需要深度工作
- 是否可以拆分

#### B. Fixed Task：固定事件

这类任务已经有明确时间，系统不应重新调度，只作为约束。

必填：

- 事件名称
- 固定开始时间
- 固定结束时间或持续时长

示例：

- meeting
- seminar
- class
- 已经确定的实验 / 访谈 / 组会

### 4.3 需要实现的任务

| 子任务 | 内容 | 输出 |
| --- | --- | --- |
| T2.1 | 把任务分成 Flexible Task 和 Fixed Task | task type 字段 |
| T2.2 | Flexible Task 不再要求开始时间 | 输入规则 |
| T2.3 | Fixed Task 作为 calendar constraint | 约束事件 |
| T2.4 | DDL 成为优先级主依据 | 排序规则 |
| T2.5 | 预计时长用于切块 | session plan |

## 5. T3：Self-report

### 5.1 草图依据

第一页和第二页多次出现：

- self-report
- 滑动
- 每天早上自我描述
- emotion
- 1-7 Likert
- 你现在精力如何
- 你刚刚感觉好吗
- 你现在状态如何
- emoji

### 5.2 自评入口分三种

| 入口 | 触发时机 | 问什么 |
| --- | --- | --- |
| Daily check-in | 每天第一次进入系统 | 今天状态、情绪、可用时间变化 |
| Pre-task check-in | 任务开始前 | 是否准备好、当前精力、是否还有注意力残留 |
| Post-task check-in | 任务结束 / 切换时 | 完成情况、实际耗时、困难、下一步 |

### 5.3 自评字段

| 字段 | 推荐控件 | 说明 |
| --- | --- | --- |
| focus | 1-7 slider | 当前专注度 |
| energy | 1-7 slider | 当前精力 |
| stress | 1-7 slider | 当前压力 |
| emotion | emoji / 1-5 | 当前情绪 |
| task readiness | 1-7 Likert | 是否准备好进入任务 |
| attention residue | 简短问题或 Likert | 是否还在想着上一个任务 |
| completion confidence | 0-1 或 1-7 | 对完成当前计划的信心 |

### 5.4 需要实现的任务

| 子任务 | 内容 | 输出 |
| --- | --- | --- |
| T3.1 | 保留 focus / energy / stress 滑动条 | runtime state |
| T3.2 | 增加 emotion emoji 输入 | mood field |
| T3.3 | 增加 daily self-report | daily check-in |
| T3.4 | 增加任务开始前 readiness 问题 | pre-task prompt |
| T3.5 | 增加任务结束后 completion feedback | post-task prompt |

## 6. T4：Scheduling Logic

### 6.1 草图依据

草图多次出现：

- DeepSeek
- dynamic
- result + confidence
- confidence > 0.75
- fixed question
- flexibility
- API key every day
- 运动数据 / 对话数据

这说明调度不应只是简单规则，而应有：

1. 规则层：DDL、预计时长、可用时间、固定事件。
2. 状态层：focus、energy、stress、emotion。
3. 记忆层：历史行为、对话、完成反馈。
4. LLM 层：生成解释、置信度、建议。

### 6.2 排程优先级

当前阶段建议：

1. DDL 最近的 Flexible Task 优先。
2. Fixed Task 先放入日历，作为不可移动约束。
3. 根据可用时间寻找空位。
4. 根据预计时长切分为多个 session。
5. 根据 energy / stress 调整 session 长度。
6. 根据 low energy window 避免高负荷任务。
7. 生成计划后进入约束验证。

### 6.3 需要实现的任务

| 子任务 | 内容 | 输出 |
| --- | --- | --- |
| T4.1 | Fixed Task 先占据日历 | calendar constraints |
| T4.2 | Flexible Task 按 DDL 排队 | ready queue |
| T4.3 | 根据预计时长切 session | session list |
| T4.4 | 根据可用时间放入空位 | schedule plan |
| T4.5 | 根据状态缩短或拆分任务 | state-aware plan |
| T4.6 | 输出 confidence | plan confidence |
| T4.7 | confidence 低于阈值时追问 | fixed question / clarification |

## 7. T5：Switch / Completion Feedback

### 7.1 草图依据

第二页写到：

- Switch Tasks / completion
- self report
- 完成情况
- fixed question
- flexibility
- 你现在精力如何
- 你刚刚感觉好吗
- 你现在状态如何
- a-b → AI 作答

第三、四页也强调：

- result + confidence
- 对话数据
- confidence
- relaxing tips
- Battery
- 记电 / confidence

### 7.2 反馈类型

| 场景 | 需要记录 |
| --- | --- |
| 任务完成 | 是否完成、实际耗时、主观难度、满意度 |
| 任务中断 | 中断原因、当前进展、回来第一步 |
| 任务切换 | 是否还有注意力残留、是否需要恢复提示 |
| 任务失败 / 延期 | 原因、是否需要重新估时、是否要拆分 |

### 7.3 需要实现的任务

| 子任务 | 内容 | 输出 |
| --- | --- | --- |
| T5.1 | 任务完成后弹出反馈 | completion report |
| T5.2 | 任务切换时保存 context dump | progress / open questions / next step |
| T5.3 | 记录实际耗时和预计耗时差异 | duration calibration |
| T5.4 | 记录 attention residue | switch cost signal |
| T5.5 | 根据反馈更新 memory | personalized memory |

## 8. T6：Memory / Embedding Search

### 8.1 草图依据

第三页明确写到：

- embedding search
- 运动数据
- 对话数据
- dynamic

这说明系统需要把不同来源的数据统一进入 memory，并在后续调度时检索。

### 8.2 数据来源

| 数据 | 来源 | 用途 |
| --- | --- | --- |
| profile | 初始问答 / 用户主页 | 长期偏好 |
| tasks | 任务输入 | 待调度对象 |
| runtime state | 滑动条 / emoji | 当前认知资源 |
| chat turns | AI 对话 | 行为语言特征 |
| context dump | 中断记录 | 恢复任务 |
| completion feedback | 完成反馈 | 更新估时和任务偏好 |
| environment / fixed events | 固定任务 | 排程约束 |

### 8.3 需要实现的任务

| 子任务 | 内容 | 输出 |
| --- | --- | --- |
| T6.1 | 明确每类数据是否入 memory | memory policy |
| T6.2 | 每次调度前检索相似记录 | retrieved context |
| T6.3 | 检索结果进入 prompt | prompt evidence |
| T6.4 | UI 上不暴露 embedding 术语 | 用户可读解释 |

## 9. T7：LLM Prompt / Confidence

### 9.1 草图依据

草图写到：

- DeepSeek v4?
- LLM
- result + confidence
- confidence 0.8
- confidence > 0.75
- 客观 / 对话数据 / 输出

### 9.2 LLM 应输出什么

建议每次调度输出：

```json
{
  "plan": [],
  "confidence": 0.82,
  "reason": "为什么这样排",
  "risks": [],
  "questions": [],
  "requires_confirmation": true
}
```

### 9.3 confidence 的使用

| confidence | 行为 |
| --- | --- |
| >= 0.75 | 可以生成明确计划，但仍需用户确认 |
| 0.5 - 0.75 | 生成建议，同时提出 1-2 个澄清问题 |
| < 0.5 | 不直接排程，先问固定问题 |

## 10. T8：Fixed Questions / Flexibility

### 10.1 草图依据

第二页写到：

- fixed question
- flexibility
- problem
- 你现在精力如何
- 你刚刚感觉好吗
- 你现在状态如何
- 1-7 Likert

### 10.2 固定问题池

| 触发条件 | 固定问题 |
| --- | --- |
| 缺 DDL | 这个任务最晚什么时候要完成？ |
| 缺预计时长 | 你估计它大概需要多久？ |
| 缺可用时间 | 这周哪些时间可以安排学习？ |
| energy 低 | 你现在更适合做完整任务，还是先做一个 25 分钟小步骤？ |
| stress 高 | 这个任务里最让你有压力的是哪一部分？ |
| 切换任务 | 回来继续时第一步是什么？ |
| 完成任务 | 实际花了多久？比预期更难还是更容易？ |

## 11. T9：Environment / Fixed Tasks

### 11.1 草图依据

第五页出现：

- 常规任务
- 固定时间条件
- 事件
- environment
- fixed tasks

### 11.2 需要区分

| 类型 | 说明 |
| --- | --- |
| fixed events | 不可移动的课程、会议、约定 |
| flexible tasks | 系统可调度的学习任务 |
| environment constraints | 地点、设备、材料、身体状态等外部条件 |

### 11.3 需要实现的任务

| 子任务 | 内容 | 输出 |
| --- | --- | --- |
| T9.1 | 新增 fixed event 类型 | fixed calendar item |
| T9.2 | fixed event 不进入任务优先队列 | calendar constraint |
| T9.3 | flexible task 围绕 fixed event 自动排 | conflict-free plan |
| T9.4 | 环境条件作为任务约束 | environment field |

## 12. 推荐开发顺序

### Phase 1：任务输入重构

1. 区分 Flexible Task 和 Fixed Task。
2. Flexible Task 最低门槛改为 DDL + 预计时长。
3. Fixed Task 需要具体开始时间。
4. 聊天追问从“几点做”改成“DDL / 预计时长 / 可用时间”。

### Phase 2：Profile / Self-report 重构

1. Profile 字段按调度用途排序。
2. 增加 daily self-report。
3. 保留 focus / energy / stress 滑动条。
4. 增加 emotion / readiness / attention residue。

### Phase 3：调度逻辑重构

1. Fixed Task 先占据日历。
2. Flexible Task 按 DDL 进入 ready queue。
3. 根据可用窗口和预计时长排程。
4. 根据当前状态调整 session length。
5. 增加约束验证。

### Phase 4：Memory / LLM

1. 明确哪些数据进入 memory。
2. 调度前 embedding search。
3. prompt 拼接 profile + runtime + tasks + memory + constraints。
4. DeepSeek 输出 plan + confidence + questions。

### Phase 5：反馈闭环

1. 任务完成后收集 completion feedback。
2. 任务切换时收集 context dump。
3. 用实际耗时更新预计时长。
4. 用中断原因更新恢复提示。

## 13. 最小可执行版本

如果只做 MVP，优先做以下 6 件事：

1. 任务输入只要求：任务名、DDL、预计时长。
2. 新增固定事件：会议 / 课程 / 约定。
3. Profile 增加：本周可用时间、偏好专注时长、低精力时间。
4. 调度排序改为：DDL 优先。
5. 调度 prompt 必须包含：focus、energy、stress、profile、memory。
6. 任务完成 / 中断时必须记录：实际进展、下一步、实际耗时、状态反馈。

## 14. 总结

这份手写草图的重点不是 UI，而是把 HumanOS 拆成一个完整的调度系统：

- User context 定义资源状态。
- Task input 定义待调度对象。
- Fixed tasks 定义不可移动约束。
- Self-report 定义实时状态。
- Embedding memory 定义历史经验。
- DeepSeek / LLM 负责综合判断、输出计划、置信度和解释。
- Switch / completion feedback 负责形成下一轮个性化调度的数据。

因此，后续实现应围绕“任务约束输入 + 状态自评 + DDL 调度 + 中断反馈 + memory 检索”展开。
