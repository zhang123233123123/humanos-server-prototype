const seedTasks = [
  {
    id: "lit-review",
    title: "整理 interruption 与 task resumption 文献",
    due: "周三 18:00",
    duration: 90,
    priority: "高",
    status: "running",
    context: "需要比较 Adamczyk & Bailey、Iqbal & Bailey、TaskTracer、TaskSnap 与 HumanOS 的差异。",
    slot: { start: 9, end: 10.5, color: "blue" },
    checkpoints: [
      {
        label: "上次进展",
        text: "已确认 interruption timing 文献能支撑最小打扰原则。"
      },
      {
        label: "未解决问题",
        text: "还需要区分 Motion 式自动安排和 HumanOS 式中断后继续。"
      },
      {
        label: "下一步",
        text: "写出 related work gap：AI task manager 已有自动安排，但缺少学术任务中断后的继续支持。"
      }
    ]
  },
  {
    id: "survey-frame",
    title: "重写 formative survey RQ",
    due: "周四 12:00",
    duration: 75,
    priority: "高",
    status: "scheduled",
    context: "把问卷从泛泛控制感收窄到中断、切换、恢复、计划调整。",
    slot: { start: 11, end: 12.25, color: "green" },
    checkpoints: []
  },
  {
    id: "prototype",
    title: "HumanOS 原型流程图",
    due: "周五 15:00",
    duration: 120,
    priority: "中",
    status: "scheduled",
    context: "参考 Motion 的日历自动安排，但加入中断记录和继续提示。",
    slot: { start: 14, end: 16, color: "violet" },
    checkpoints: []
  },
  {
    id: "meeting",
    title: "整理导师会议纪要",
    due: "今晚",
    duration: 45,
    priority: "低",
    status: "queued",
    context: "提炼杨强、马东、尚永怡对方向的分歧。",
    slot: null,
    checkpoints: []
  }
];

function cloneSeedTasks() {
  return JSON.parse(JSON.stringify(seedTasks));
}

let tasks = JSON.parse(localStorage.getItem("humanosMotionTasks") || "null");
if (!Array.isArray(tasks)) tasks = cloneSeedTasks();
tasks = tasks.map(normalizeBackendTask);
let activeId = tasks[0]?.id || null;
let activeSelectionMode = "auto";
const API_HOST = window.location.hostname || "127.0.0.1";
const API_PROTOCOL = window.location.protocol === "https:" ? "https:" : "http:";
const API_BASE = window.HUMANOS_API_BASE || `${API_PROTOCOL}//${API_HOST}:8787`;
const CHAT_CONTEXT_TURN_LIMIT = 50;
const CHAT_MESSAGE_DISPLAY_LIMIT = CHAT_CONTEXT_TURN_LIMIT * 2;
const DEBUG_NOW_KEY = "humanosDebugNowMs";
const LANG_KEY = "humanosLanguage";
let currentUser = JSON.parse(localStorage.getItem("humanosUser") || "null");
let currentLang = localStorage.getItem(LANG_KEY) === "en" ? "en" : "zh";
let authMode = "login";
let backendOnline = false;
let authPending = false;
let calendarView = "day";
let chatMessages = [];
let pendingSchedulePlan = null;
let debugNowMs = Number(localStorage.getItem(DEBUG_NOW_KEY)) || null;
let miniCalendarCursor = new Date(getNow().getFullYear(), getNow().getMonth(), 1);
const promptedSlots = new Set(JSON.parse(localStorage.getItem("humanosPromptedSlots") || "[]"));
let currentProfile = {
  role: "研究型学生",
  deep_work_window: "09:00-11:30",
  low_energy_window: "14:00-15:30",
  control_preference: "confirm_before_reschedule"
};
let lastDecision = null;
let editingTaskId = null;
const deletingTaskIds = new Set();
const HOUR_ROW_HEIGHT = 64;
const CALENDAR_START_HOUR = 0;
const CALENDAR_END_HOUR = 24;
const DRAG_STEP_MINUTES = 15;

const calendar = document.getElementById("calendar");
const chatThread = document.getElementById("chatThread");
const chatInput = document.getElementById("chatInput");
const chatSendBtn = document.getElementById("chatSendBtn");
const activeTask = document.getElementById("activeTask");
const contextWindow = document.getElementById("contextWindow");
const checkpointView = document.getElementById("checkpointView");
const checkpointCount = document.getElementById("checkpointCount");
const resumeBrief = document.getElementById("resumeBrief");
const reasoning = document.getElementById("reasoning");
const schedulingLens = document.getElementById("schedulingLens");
const modePill = document.getElementById("modePill");
const resumeSubtitle = document.getElementById("resumeSubtitle");
const dialog = document.getElementById("taskDialog");
const focusInput = document.getElementById("focusInput");
const energyInput = document.getElementById("energyInput");
const stressInput = document.getElementById("stressInput");
const focusValue = document.getElementById("focusValue");
const energyValue = document.getElementById("energyValue");
const stressValue = document.getElementById("stressValue");
const backendStatus = document.getElementById("backendStatus");
const profileRole = document.getElementById("profileRole");
const profileDeepWork = document.getElementById("profileDeepWork");
const profileControl = document.getElementById("profileControl");
const openProfileWizardBtn = document.getElementById("openProfileWizardBtn");
const authScreen = document.getElementById("authScreen");
const authForm = document.getElementById("authForm");
const authName = document.getElementById("authName");
const authEmail = document.getElementById("authEmail");
const authPassword = document.getElementById("authPassword");
const authNameLabel = document.getElementById("authNameLabel");
const authError = document.getElementById("authError");
const authSubmitBtn = document.getElementById("authSubmitBtn");
const loginModeBtn = document.getElementById("loginModeBtn");
const registerModeBtn = document.getElementById("registerModeBtn");
const userBadge = document.getElementById("userBadge");
const debugTimeBadge = document.getElementById("debugTimeBadge");
const debugTimeInput = document.getElementById("debugTimeInput");
const debugApplyTimeBtn = document.getElementById("debugApplyTimeBtn");
const debugStepTimeBtn = document.getElementById("debugStepTimeBtn");
const debugResetTimeBtn = document.getElementById("debugResetTimeBtn");
const logoutBtn = document.getElementById("logoutBtn");
const workspaceNavBtn = document.getElementById("workspaceNavBtn");
const profileHomeBtn = document.getElementById("profileHomeBtn");
const workspaceView = document.getElementById("workspaceView");
const profileHomeView = document.getElementById("profileHomeView");
const langToggleBtn = document.getElementById("langToggleBtn");
const accountChipBtn = document.getElementById("accountChipBtn");
const sidebarCollapseBtn = document.getElementById("sidebarCollapseBtn");
const sidebarNewTaskBtn = document.getElementById("sidebarNewTaskBtn");
const sidebarChatBtn = document.getElementById("sidebarChatBtn");
const sidebarCalendarBtn = document.getElementById("sidebarCalendarBtn");
const sidebarTasksBtn = document.getElementById("sidebarTasksBtn");
const sidebarProfileBtn = document.getElementById("sidebarProfileBtn");
const sidebarDateLabel = document.getElementById("sidebarDateLabel");
const navDateLabel = document.getElementById("navDateLabel");
const navTaskCount = document.getElementById("navTaskCount");
const todayJumpBtn = document.getElementById("todayJumpBtn");
const miniMonthLabel = document.getElementById("miniMonthLabel");
const miniCalendarGrid = document.getElementById("miniCalendarGrid");
const miniPrevBtn = document.getElementById("miniPrevBtn");
const miniNextBtn = document.getElementById("miniNextBtn");
const dayViewBtn = document.getElementById("dayViewBtn");
const weekViewBtn = document.getElementById("weekViewBtn");
const taskForm = document.getElementById("taskForm");
const closeTaskDialogBtn = document.getElementById("closeTaskDialogBtn");
const pendingSchedule = document.getElementById("pendingSchedule");
const pendingScheduleText = document.getElementById("pendingScheduleText");
const confirmScheduleBtn = document.getElementById("confirmScheduleBtn");
const rejectScheduleBtn = document.getElementById("rejectScheduleBtn");
const todayBadge = document.getElementById("todayBadge");
const taskDialogTitle = document.getElementById("taskDialogTitle");
const saveTaskBtn = document.getElementById("saveTaskBtn");
const deleteTaskBtn = document.getElementById("deleteTaskBtn");
const appRoot = document.getElementById("appRoot");
const profileScreen = document.getElementById("profileScreen");
const profileWizard = document.getElementById("profileWizard");
const wizardRole = document.getElementById("wizardRole");
const wizardDeepWork = document.getElementById("wizardDeepWork");
const wizardAvailableWindows = document.getElementById("wizardAvailableWindows");
const wizardLowEnergy = document.getElementById("wizardLowEnergy");
const wizardSessionLength = document.getElementById("wizardSessionLength");
const wizardLearningMode = document.getElementById("wizardLearningMode");
const wizardCurrentCourses = document.getElementById("wizardCurrentCourses");
const wizardNearDeadlines = document.getElementById("wizardNearDeadlines");
const wizardTools = document.getElementById("wizardTools");
const wizardPlanningGap = document.getElementById("wizardPlanningGap");
const wizardGoal = document.getElementById("wizardGoal");
const wizardSupportNeed = document.getElementById("wizardSupportNeed");
const wizardControl = document.getElementById("wizardControl");
const wizardError = document.getElementById("wizardError");
const skipProfileBtn = document.getElementById("skipProfileBtn");
const wizardPrevBtn = document.getElementById("wizardPrevBtn");
const wizardNextBtn = document.getElementById("wizardNextBtn");
const saveWizardBtn = document.getElementById("saveWizardBtn");
const wizardStepBadge = document.getElementById("wizardStepBadge");
const profileSummary = document.getElementById("profileSummary");
let wizardStep = 0;
const WIZARD_STEP_COUNT = 4;

const I18N = {
  zh: {
    appSubtitle: "AI 学习计划 · 中断恢复 · 个性化安排",
    workspace: "工作台",
    profileHome: "个人主页",
    logout: "退出",
    addTask: "新增任务",
    newShort: "New",
    aiChat: "AI 对话",
    calendar: "日历",
    tasks: "任务",
    profile: "个人设置",
    aiAssistant: "AI 学习助手",
    assistantHint: "输入任务、状态和中断原因",
    send: "发送",
    currentState: "当前状态",
    stateUse: "用于安排今天任务",
    focus: "专注",
    energy: "精力",
    stress: "压力",
    today: "Today",
    day: "日",
    week: "周",
    cancel: "取消",
    confirmCalendar: "确认加入日历",
    taskDetail: "任务详情",
    contextWindow: "上下文窗口",
    contextHint: "恢复任务时先看这里",
    interruptions: "中断记录",
    resumeTip: "恢复提示",
    continueStart: "继续开始",
    notLoggedIn: "未登录",
    realTime: "真实时间",
    simulated: "模拟",
    todayPrefix: "今天：",
    noTask: "暂无任务",
    empty: "Empty",
    noTaskDetail: "点击右上角“新增任务”，先建立一个需要安排的学习任务。",
    unscheduled: "尚未进入日历",
    prioritySuffix: "优先级",
    minutes: "分钟",
    progress: "当前进展",
    firstStep: "回来第一步",
    openQuestions: "开放问题",
    edit: "编辑",
    deleteTask: "删除任务",
    noCheckpoint: "暂无中断记录",
    checkpointHelp: "新增任务后，可以在切换前保存当前进展、未解决问题和下一步。",
    checkpointTaskHelp: "暂停任务时会保存进展、未解决问题和下一步。",
    items: "条",
    noContext: "暂无上下文窗口",
    contextEmptyHelp: "新增任务后，这里会显示当前进展、下一步、开放问题和恢复线索。",
    nextStep: "下一步",
    unresolved: "未解决问题",
    materials: "资料线索",
    recoveryCue: "恢复条件",
    resumeEntry: "继续入口",
    createTaskFirst: "先创建一个学习任务",
    generatedAfterTask: "新增任务后生成",
    suggestedBlock: "建议时间块",
    notSet: "未设置",
    fromLastCheckpoint: "从最近中断记录继续",
    saveCheckpointFirst: "先保存一次中断记录",
    saveContextFirst: "先用 10 分钟写下当前任务状态，再决定是否继续。",
    pending: "待确认",
    completed: "已完成",
    executionWindow: "执行窗口",
    noSchedule: "暂无安排",
    systemTitle: "HumanOS",
    systemIntro: "你可以像聊天一样描述任务、进展、中断原因或当前卡点。我会解析后在右侧生成待确认安排。",
    stateTitle: "当前状态",
    taskHasCheckpoint: "这个任务已有中断记录。继续时先看右侧提示，再开始第一步。",
    taskNoCheckpoint: "这个任务还没有中断记录。如果马上要切换，请先保存当前进展、未解决问题和回来第一步。",
    createTaskHint: "先新增一个学习任务，右侧会显示日历安排和继续入口。",
    suggestion: "个性化建议",
    confidence: "置信度",
    risk: "注意",
    selectTask: "选择一个任务",
    taskUpdated: "任务已更新",
    taskSaved: "任务已保存",
    saveFailed: "保存失败",
    invalidDebug: "Debug 时间无效",
    pickFullDate: "请选择一个完整的日期和时间。",
    debugChanged: "Debug 时间已切换",
    currentSimTime: "当前模拟时间",
    debugOff: "Debug 时间已关闭",
    backToReal: "已回到真实当前时间。",
    scheduleConfirmed: "安排已确认",
    scheduleConfirmedBody: "我已经把这些时间块加入右侧日历。到对应时间点时，我会主动询问任务情况。",
    scheduleCanceled: "已取消安排",
    scheduleCanceledBody: "这次建议没有加入日历。你可以继续描述限制条件，我会重新生成。",
    noTaskAuto: "暂无任务",
    noTaskAutoBody: "请先新增一个任务。",
    manualAdded: "已手动添加",
    manualAddedBody: "已加入日历视图。",
    editDecision: "编辑判断",
    autoReason: "根据当前任务和状态生成安排。",
    accountTitle: "打开个人主页",
    collapseTitle: "收起侧边栏",
    expandTitle: "展开侧边栏",
    prevMonth: "上个月",
    nextMonth: "下个月"
  },
  en: {
    appSubtitle: "AI study planning · interruption recovery · personalized scheduling",
    workspace: "Workspace",
    profileHome: "Profile",
    logout: "Log out",
    addTask: "Add task",
    newShort: "New",
    aiChat: "AI Chat",
    calendar: "Calendar",
    tasks: "Tasks",
    profile: "Profile",
    aiAssistant: "AI Study Assistant",
    assistantHint: "Enter tasks, state, and interruption reasons",
    send: "Send",
    currentState: "Current State",
    stateUse: "Used for today's scheduling",
    focus: "Focus",
    energy: "Energy",
    stress: "Stress",
    today: "Today",
    day: "Day",
    week: "Week",
    cancel: "Cancel",
    confirmCalendar: "Add to calendar",
    taskDetail: "Task Details",
    contextWindow: "Context Window",
    contextHint: "Check this before resuming",
    interruptions: "Interruptions",
    resumeTip: "Resume Prompt",
    continueStart: "Start again",
    notLoggedIn: "Not signed in",
    realTime: "Real time",
    simulated: "Simulated",
    todayPrefix: "Today: ",
    noTask: "No task",
    empty: "Empty",
    noTaskDetail: "Click “Add task” in the top right to create a study task.",
    unscheduled: "Not on calendar",
    prioritySuffix: " priority",
    minutes: "min",
    progress: "Progress",
    firstStep: "First step back",
    openQuestions: "Open questions",
    edit: "Edit",
    deleteTask: "Delete task",
    noCheckpoint: "No interruption records",
    checkpointHelp: "After adding a task, save progress, open questions, and the next step before switching away.",
    checkpointTaskHelp: "Paused tasks store progress, unresolved questions, and the next step.",
    items: "items",
    noContext: "No context window",
    contextEmptyHelp: "After adding a task, this area shows progress, next step, open questions, and recovery cues.",
    nextStep: "Next step",
    unresolved: "Open questions",
    materials: "Materials",
    recoveryCue: "Recovery cue",
    resumeEntry: "Resume from",
    createTaskFirst: "Create a study task first",
    generatedAfterTask: "Generated after adding a task",
    suggestedBlock: "Suggested block",
    notSet: "Not set",
    fromLastCheckpoint: "Latest interruption record",
    saveCheckpointFirst: "Save one interruption record first",
    saveContextFirst: "Spend 10 minutes writing the current task state, then decide whether to continue.",
    pending: "Pending",
    completed: "Completed",
    executionWindow: "Work block",
    noSchedule: "No schedule",
    systemTitle: "HumanOS",
    systemIntro: "Describe tasks, progress, interruptions, or blockers like a chat. I will parse it and create a pending schedule on the right.",
    stateTitle: "Current state",
    taskHasCheckpoint: "This task has interruption records. Check the right-side prompt before taking the first step.",
    taskNoCheckpoint: "This task has no interruption record yet. If you are about to switch away, save progress, open questions, and the first step back.",
    createTaskHint: "Add a study task first. The right side will show scheduling and a resume entry.",
    suggestion: "Personalized suggestion",
    confidence: "Confidence",
    risk: "Note",
    selectTask: "Select a task",
    taskUpdated: "Task updated",
    taskSaved: "Task saved",
    saveFailed: "Save failed",
    invalidDebug: "Invalid debug time",
    pickFullDate: "Choose a complete date and time.",
    debugChanged: "Debug time changed",
    currentSimTime: "Current simulated time",
    debugOff: "Debug time off",
    backToReal: "Returned to real current time.",
    scheduleConfirmed: "Schedule confirmed",
    scheduleConfirmedBody: "I added these blocks to the calendar. At the scheduled time, I will ask about task status.",
    scheduleCanceled: "Schedule canceled",
    scheduleCanceledBody: "This suggestion was not added. Describe more constraints and I will generate a new plan.",
    noTaskAuto: "No task",
    noTaskAutoBody: "Add a task first.",
    manualAdded: "Added manually",
    manualAddedBody: "was added to the calendar view.",
    editDecision: "Edit review",
    autoReason: "Generate a schedule from current tasks and state.",
    accountTitle: "Open profile",
    collapseTitle: "Collapse sidebar",
    expandTitle: "Expand sidebar",
    prevMonth: "Previous month",
    nextMonth: "Next month"
  }
};

function t(key) {
  return I18N[currentLang]?.[key] || I18N.zh[key] || key;
}

function isEnglish() {
  return currentLang === "en";
}

function save() {
  localStorage.setItem("humanosMotionTasks", JSON.stringify(tasks));
  localStorage.setItem("humanosPromptedSlots", JSON.stringify(Array.from(promptedSlots)));
}

function priorityClass(priority) {
  return priority === "高" ? "high" : priority === "中" ? "medium" : "low";
}

function selectedTask() {
  return tasks.find((task) => task.id === activeId) || tasks[0];
}

function schedulingNodeForTask(task) {
  if (!task) {
    return {
      title: "Ready Queue",
      zh: "候选任务池",
      className: "green",
      product: "任务尚未进入执行状态，系统只维护候选任务和可用状态。",
      evidence: "对应 OS 的 ready queue：任务已经可运行，但还需要 scheduler 判断是否适合当前资源。"
    };
  }
  if (task.status === "running") {
    return {
      title: "Running on CPU",
      zh: "正在执行",
      className: "red",
      product: "当前任务被视为正在占用主要认知资源，需要持续记录进展、卡点和切换风险。",
      evidence: "对应 OS 的 running state：任务不是排进日历就结束，而是在执行中产生新的运行证据。"
    };
  }
  if (task.status === "paused") {
    return {
      title: "Context Switch",
      zh: "上下文切换",
      className: "gold",
      product: "任务暂停时需要保存当前进展、开放问题和回来后的第一步。",
      evidence: "对应 OS context switch：切换不是免费的，需要保存状态，避免恢复时丢失任务上下文。"
    };
  }
  if (task.status === "blocked") {
    return {
      title: "Waiting / Blocked",
      zh: "等待 / 阻塞",
      className: "blue",
      product: "任务暂时依赖材料、回复、审批或外部条件，不应继续占用深度工作资源。",
      evidence: "对应 OS blocked state：等待 I/O 或外部事件时，进程离开 CPU，事件完成后再回到 ready queue。"
    };
  }
  if (task.status === "completed") {
    return {
      title: "Terminated",
      zh: "完成 / 结束",
      className: "gray",
      product: "任务完成后应比较预估和实际负荷，更新个人 profile 与后续调度基线。",
      evidence: "对应 OS terminated state：释放资源并记录结果；HumanOS 进一步做反思和模型更新。"
    };
  }
  if (task.slot) {
    return {
      title: "Dispatcher",
      zh: "已派发到日历",
      className: "coral",
      product: "任务已经获得一个执行窗口，但仍保留用户确认、编辑和拖拽调整。",
      evidence: "对应 OS dispatcher：scheduler 选中任务后，dispatcher 把它交到实际执行入口。"
    };
  }
  return {
    title: "Ready Queue",
    zh: "等待调度",
    className: "green",
    product: "任务已被记录，但还没有进入具体时间块，正在候选任务池中等待安排。",
    evidence: "对应 OS ready queue：可运行任务先排队，再由 scheduler 按策略选择。"
  };
}

function selectTask(taskId, mode = "manual") {
  if (!tasks.some((task) => task.id === taskId)) return;
  activeId = taskId;
  activeSelectionMode = mode;
}

function hasSelectedTask() {
  return Boolean(selectedTask());
}

function currentUserId() {
  return currentUser?.id || null;
}

function getNow() {
  return debugNowMs ? new Date(debugNowMs) : new Date();
}

function isDebugTimeEnabled() {
  return Boolean(debugNowMs);
}

function formatDateTimeLocal(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatDebugBadgeTime(date) {
  return new Intl.DateTimeFormat(isEnglish() ? "en-US" : "zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    weekday: "short"
  }).format(date);
}

function syncDebugTimeControl() {
  if (!debugTimeInput || !debugTimeBadge) return;
  const now = getNow();
  debugTimeInput.value = formatDateTimeLocal(now);
  debugTimeBadge.textContent = isDebugTimeEnabled()
    ? `${t("simulated")}：${formatDebugBadgeTime(now)}`
    : t("realTime");
  debugTimeBadge.classList.toggle("active", isDebugTimeEnabled());
}

function applyDebugNow(ms, announce = true) {
  if (!Number.isFinite(ms)) return;
  debugNowMs = ms;
  localStorage.setItem(DEBUG_NOW_KEY, String(debugNowMs));
  syncDebugTimeControl();
  if (announce) {
    addChatMessage("ai", t("debugChanged"), `${t("currentSimTime")}：${todayLabel()} ${formatHour(currentHourFloat())}。`);
  }
  activeSelectionMode = "auto";
  checkTaskTimePrompts(false);
  render();
}

function resetDebugNow(announce = true) {
  debugNowMs = null;
  localStorage.removeItem(DEBUG_NOW_KEY);
  syncDebugTimeControl();
  if (announce) addChatMessage("ai", t("debugOff"), t("backToReal"));
  activeSelectionMode = "auto";
  checkTaskTimePrompts(false);
  render();
}

function todayLabel() {
  return new Intl.DateTimeFormat(isEnglish() ? "en-US" : "zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long"
  }).format(getNow());
}

function shortDateLabel() {
  return new Intl.DateTimeFormat(isEnglish() ? "en-US" : "zh-CN", {
    weekday: "short",
    month: "short",
    day: "2-digit"
  }).format(getNow());
}

function renderMiniCalendar() {
  if (!miniCalendarGrid || !miniMonthLabel) return;
  const now = new Date(miniCalendarCursor);
  const today = getNow();
  const year = now.getFullYear();
  const month = now.getMonth();
  miniMonthLabel.textContent = new Intl.DateTimeFormat(isEnglish() ? "en-US" : "zh-CN", {
    month: "long",
    year: "numeric"
  }).format(now);

  const first = new Date(year, month, 1);
  const start = new Date(first);
  start.setDate(first.getDate() - first.getDay());
  const todayKey = today.toDateString();
  const cells = [];
  for (let i = 0; i < 42; i += 1) {
    const date = new Date(start);
    date.setDate(start.getDate() + i);
    const isMuted = date.getMonth() !== month;
    const isToday = date.toDateString() === todayKey;
    const dateMs = date.getTime();
    cells.push(`
      <button class="${isMuted ? "muted" : ""} ${isToday ? "today" : ""}" type="button" data-date-ms="${dateMs}">
        ${date.getDate()}
      </button>
    `);
  }
  miniCalendarGrid.innerHTML = cells.join("");
  miniCalendarGrid.querySelectorAll("button[data-date-ms]").forEach((button) => {
    button.addEventListener("click", () => {
      applyDebugNow(Number(button.dataset.dateMs), false);
    });
  });
}

function renderMotionShellMeta() {
  const label = shortDateLabel();
  if (sidebarDateLabel) sidebarDateLabel.textContent = label;
  if (navDateLabel) navDateLabel.textContent = label;
  if (navTaskCount) navTaskCount.textContent = String(tasks.length);
  renderMiniCalendar();
}

function applyTranslations() {
  document.documentElement.lang = isEnglish() ? "en" : "zh-CN";
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  if (langToggleBtn) langToggleBtn.textContent = isEnglish() ? "中文" : "EN";
  if (chatInput) {
    chatInput.placeholder = isEnglish()
      ? "Describe a task, progress, or blocker. For calendar scheduling, include day, time, and estimated duration. Enter sends, Shift+Enter inserts a line break."
      : "说一句任务、进展或卡点。排日历至少需要：哪一天、几点、预计多久。Enter 发送，Shift+Enter 换行。";
  }
  if (accountChipBtn) accountChipBtn.title = t("accountTitle");
  if (sidebarCollapseBtn) {
    sidebarCollapseBtn.title = document.body.classList.contains("sidebar-collapsed")
      ? t("expandTitle")
      : t("collapseTitle");
  }
  if (miniPrevBtn) miniPrevBtn.title = t("prevMonth");
  if (miniNextBtn) miniNextBtn.title = t("nextMonth");
  const weekdays = isEnglish()
    ? ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
    : ["日", "一", "二", "三", "四", "五", "六"];
  document.querySelectorAll(".mini-weekdays span").forEach((node, index) => {
    node.textContent = weekdays[index] || node.textContent;
  });
}

function showAuth() {
  authScreen.classList.remove("hidden");
  profileScreen.classList.add("hidden");
  appRoot.classList.add("hidden");
  userBadge.textContent = currentUser?.email || t("notLoggedIn");
}

function hideAuth() {
  authScreen.classList.add("hidden");
  userBadge.textContent = currentUser?.email || t("notLoggedIn");
}

function updateWizardStep() {
  document.querySelectorAll(".wizard-step").forEach((step, index) => {
    step.classList.toggle("active", index === wizardStep);
  });
  document.querySelectorAll(".wizard-progress span").forEach((dot, index) => {
    dot.classList.toggle("active", index <= wizardStep);
  });
  if (wizardStepBadge) wizardStepBadge.textContent = `${wizardStep + 1} / ${WIZARD_STEP_COUNT}`;
  wizardPrevBtn.classList.toggle("hidden", wizardStep === 0);
  wizardNextBtn.classList.toggle("hidden", wizardStep === WIZARD_STEP_COUNT - 1);
  saveWizardBtn.classList.toggle("hidden", wizardStep !== WIZARD_STEP_COUNT - 1);
}

function showProfileSetup() {
  wizardStep = 0;
  hideAuth();
  profileScreen.classList.remove("hidden");
  appRoot.classList.add("hidden");
  syncWizardForm();
  updateWizardStep();
}

function showApp() {
  hideAuth();
  profileScreen.classList.add("hidden");
  appRoot.classList.remove("hidden");
  showWorkspaceView();
}

function showWorkspaceView() {
  workspaceView.classList.remove("hidden");
  profileHomeView.classList.add("hidden");
  workspaceNavBtn.classList.add("active");
  profileHomeBtn.classList.remove("active");
}

function showProfileHomeView() {
  workspaceView.classList.add("hidden");
  profileHomeView.classList.remove("hidden");
  workspaceNavBtn.classList.remove("active");
  profileHomeBtn.classList.add("active");
  renderProfileSummary();
}

function setAuthMode(mode) {
  authMode = mode;
  const isRegister = mode === "register";
  authNameLabel.classList.toggle("hidden", !isRegister);
  loginModeBtn.classList.toggle("active", !isRegister);
  registerModeBtn.classList.toggle("active", isRegister);
  authSubmitBtn.textContent = isRegister
    ? (isEnglish() ? "Register and set up" : "注册并开始设置")
    : (isEnglish() ? "Sign in" : "登录并进入");
  authPassword.autocomplete = isRegister ? "new-password" : "current-password";
  authError.textContent = "";
}

function userFacingRole(role) {
  return role === "research_student" ? "研究型学生" : role;
}

function addChatMessage(sender, title, text) {
  chatMessages.push({
    sender,
    title,
    text,
    createdAt: getNow().toLocaleTimeString(isEnglish() ? "en-US" : "zh-CN", { hour: "2-digit", minute: "2-digit" })
  });
  if (chatMessages.length > CHAT_MESSAGE_DISPLAY_LIMIT) {
    chatMessages = chatMessages.slice(-CHAT_MESSAGE_DISPLAY_LIMIT);
  }
}

function formatConfidence(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "";
  const normalized = numeric > 1 ? numeric / 100 : numeric;
  return `${t("confidence")}：${Math.round(normalized * 100)}%`;
}

function chatConfidence(turn = {}) {
  return turn.confidence ?? turn.features?.confidence;
}

function formatBackendTime(ms) {
  if (!ms) return "";
  return new Date(ms).toLocaleTimeString(isEnglish() ? "en-US" : "zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function chatMessagesFromTurns(turns = []) {
  return turns.flatMap((turn) => {
    const createdAt = formatBackendTime(turn.created_at);
    const confidenceText = formatConfidence(chatConfidence(turn));
    const blockerText = turn.features?.blockers?.length ? `\n可能卡点：${turn.features.blockers.join(" / ")}` : "";
    const featureText = `${blockerText}${confidenceText ? `\n${confidenceText}` : ""}`;
    return [
      {
        sender: "user",
        title: "你",
        text: turn.user_text,
        createdAt
      },
      {
        sender: "ai",
        title: "HumanOS",
        text: `${turn.assistant_reply}${featureText}`,
        createdAt
      }
    ];
  }).slice(-CHAT_MESSAGE_DISPLAY_LIMIT);
}

function missingTimeConfirmationFields(task) {
  const due = task?.deadline || task?.due || "";
  const missing = [];
  const type = taskScheduleType(task);
  if (!task?.title) missing.push("任务标题");
  if (type === "fixed_event") {
    if (!hasDueDate(due)) missing.push("哪一天");
    if (!hasDueClock(due)) missing.push("开始时间");
  } else if (!hasDueDate(due)) {
    missing.push("截止日期");
  }
  if (!task?.duration && !task?.estimated_duration) missing.push("预计时长");
  if (Number(task?.duration || task?.estimated_duration || 0) <= 0) missing.push("预计时长");
  return missing;
}

function localFallbackTasksFromText(text) {
  const clean = String(text || "").trim();
  const relativeDay = "(今天|今晚|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天])";
  const timeWord = "(((早上|上午|中午|下午|晚上)\\s*)?\\d{1,2}\\s*(点|时)|\\d{1,2}[:：]\\d{2})";
  const connectorSegments = clean
    .split(/然后|最后|再|接着|之后|，|,|。|；|;/)
    .map((segment) => segment.replace(/^[，,。；;、\s]+|[，,。；;、\s]+$/g, ""))
    .filter(Boolean);
  const actionPattern = /会议|开会|组会|学习|复习|写|读|阅读|总结|整理|完善|完成|处理|准备|提交|看|做|备战|取|拿|办|买|发/;
  const mergedConnectorSegments = [];
  connectorSegments.forEach((segment) => {
    const hasDurationOnly = inferDurationMinutesFromText(segment) && !actionPattern.test(segment);
    if (hasDurationOnly && mergedConnectorSegments.length) {
      mergedConnectorSegments[mergedConnectorSegments.length - 1] = `${mergedConnectorSegments[mergedConnectorSegments.length - 1]}，${segment}`;
    } else {
      mergedConnectorSegments.push(segment);
    }
  });
  const pattern = new RegExp(`((?:${relativeDay})?\\s*(?:${timeWord})?[^，。；;、]*(?:会议|开会|组会|学习|复习|写|读|阅读|总结|整理|完善|完成|处理|准备|提交|看|做|备战|取|拿|办|买|发)[^，。；;]*)`, "g");
  let segments = [];
  let match;
  while ((match = pattern.exec(clean))) {
    const segment = match[1].replace(/^[，,。；;、\s]+|[，,。；;、\s]+$/g, "");
    if (segment) segments.push(segment);
  }
  if (mergedConnectorSegments.length && mergedConnectorSegments.length >= segments.length) segments = mergedConnectorSegments;
  const sourceSegments = segments.length ? segments : [clean];
  let lastDay = "";
  let lastPeriod = "";
  return sourceSegments.slice(0, 8).map((segment, index) => {
    const dayMatch = segment.match(new RegExp(relativeDay));
    if (dayMatch) lastDay = dayMatch[0];
    const periodMatch = segment.match(/早上|上午|中午|下午|晚上/);
    if (periodMatch) lastPeriod = periodMatch[0];
    const dueMatch = segment.match(new RegExp(`(${relativeDay}\\s*${timeWord}|${timeWord}|${relativeDay})`));
    let due = dueMatch ? dueMatch[0] : "未设置";
    const separateTimeMatch = segment.match(new RegExp(timeWord));
    if (due !== "未设置" && dayMatch && separateTimeMatch && !new RegExp(timeWord).test(due)) {
      due = `${dayMatch[0]}${separateTimeMatch[0]}`;
    }
    if (due !== "未设置" && lastDay && !new RegExp(relativeDay).test(due)) due = `${lastDay}${due}`;
    if (due !== "未设置" && lastPeriod && /\d{1,2}\s*(点|时)/.test(due) && !/(早上|上午|中午|下午|晚上)/.test(due)) {
      due = due.replace(/(\d{1,2}\s*(点|时))/, `${lastPeriod}$1`);
    }
    if (due === "未设置" && lastDay && periodMatch) due = `${lastDay}${periodMatch[0]}`;
    const title = segment
      .replace(new RegExp(relativeDay, "g"), "")
      .replace(new RegExp(timeWord, "g"), "")
      .replace(/然后|最后|先|需要|进行|我们的|我们|这个|的|吧|之前|以前|前/g, "")
      .replace(/\d+\s*(个)?\s*(分钟|min|小时|h)/gi, "")
      .replace(/大概|大约|预计|左右/g, "")
      .replace(/\s+/g, "")
      .replace(/^[，,。；;、]+|[，,。；;、]+$/g, "")
      || segment;
    return {
      id: `task-${Date.now()}-${index}`,
      title: title.slice(0, 42),
      due,
      deadline: due,
      duration: inferDurationMinutesFromText(segment) || 60,
      estimated_duration: inferDurationMinutesFromText(segment) || 60,
      task_type: hasDueClock(due) ? "fixed_event" : "flexible_task",
      priority: /紧急|重要|ddl|deadline|优先级高|高优先级/.test(segment) ? "高" : "中",
      status: "queued",
      context: segment,
      slot: null,
      checkpoints: []
    };
  });
}

function parseDueStartHour(due = "") {
  const text = String(due);
  const colonMatch = text.match(/(\d{1,2})[:：](\d{2})/);
  if (colonMatch) {
    let hour = Number(colonMatch[1]);
    const minute = Number(colonMatch[2]);
    if (/(下午|晚上)/.test(text) && hour < 12) hour += 12;
    if (/中午/.test(text) && hour < 11) hour += 12;
    return hour + minute / 60;
  }
  const hourMatch = text.match(/(早上|上午|中午|下午|晚上)?\s*(\d{1,2})\s*(点|时)/);
  if (!hourMatch) return null;
  const period = hourMatch[1] || "";
  let hour = Number(hourMatch[2]);
  if ((period === "下午" || period === "晚上") && hour < 12) hour += 12;
  if (period === "中午" && hour < 11) hour += 12;
  return hour;
}

function hasDueDate(due = "") {
  return /(今天|今晚|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天]|\d{1,2}[/-]\d{1,2}|\d{4}[/-]\d{1,2}[/-]\d{1,2})/.test(String(due || ""));
}

function hasDueClock(due = "") {
  return /\d{1,2}[:：]\d{2}|(上午|下午|晚上|早上|中午)?\s*\d{1,2}\s*(点|时)/.test(String(due || ""));
}

function taskScheduleType(task = {}) {
  const explicit = task.task_type || task.taskType || task.contextWindow?.taskType || task.contextWindow?.task_type;
  if (explicit) return explicit;
  if (hasDueClock(task.due)) return "fixed_event";
  return "flexible_task";
}

function inferDialogTaskType(title = "", context = "", due = "", previous = {}) {
  const existing = previous.task_type || previous.contextWindow?.taskType;
  const text = `${title} ${context} ${due}`;
  const fixedWords = /(会议|开会|组会|上课|面试|meeting|appointment)/i.test(text);
  if (hasDueClock(due) && (fixedWords || existing === "fixed_event")) return "fixed_event";
  return "flexible_task";
}

function dayIndexFromDue(due = "") {
  const text = String(due);
  const map = { 一: 0, 二: 1, 三: 2, 四: 3, 五: 4, 六: 5, 日: 6, 天: 6 };
  const weekMatch = text.match(/(?:周|星期)([一二三四五六日天])/);
  if (weekMatch) return map[weekMatch[1]];
  const base = getNow();
  if (/今天|今晚/.test(text)) return (base.getDay() + 6) % 7;
  if (/明天/.test(text)) {
    const tomorrow = new Date(base.getTime() + 86400000);
    return tomorrow.getDay() === 0 ? 6 : tomorrow.getDay() - 1;
  }
  if (/后天/.test(text)) {
    const afterTomorrow = new Date(base.getTime() + 2 * 86400000);
    return afterTomorrow.getDay() === 0 ? 6 : afterTomorrow.getDay() - 1;
  }
  return null;
}

function normalizedSlotForDue(task) {
  const slot = task?.slot;
  if (!slot) return null;
  const durationHours = taskDurationHours(task);
  const dueStart = taskScheduleType(task) === "fixed_event" ? parseDueStartHour(task.due) : null;
  if (dueStart !== null && Math.abs(Number(slot.start) - dueStart) > 0.01) {
    return {
      ...slot,
      start: dueStart,
      end: dueStart + durationHours,
      correctedFromDue: true
    };
  }
  const start = Number(slot.start);
  const end = Number(slot.end);
  return {
    ...slot,
    start,
    end: Number.isFinite(end) && end > start ? end : start + durationHours
  };
}

function dueWithStartHour(due = "", startHour = null) {
  if (startHour === null || startHour === undefined || Number.isNaN(Number(startHour))) return due || "未设置";
  const timeText = formatHour(startHour);
  const clean = String(due || "").trim();
  const hasDay = /(今天|今晚|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天]|\d{1,2}[/-]\d{1,2}|\d{4}[/-]\d{1,2}[/-]\d{1,2})/.test(clean);
  const timePattern = /(早上|上午|中午|下午|晚上)?\s*\d{1,2}\s*(点|时)|\d{1,2}[:：]\d{2}/;
  if (timePattern.test(clean)) return clean.replace(timePattern, timeText);
  if (hasDay) return `${clean} ${timeText}`;
  return `今天 ${timeText}`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function profileCompleted(profile = currentProfile) {
  return Boolean(profile.task_preferences?.onboarding_completed);
}

async function submitAuth() {
  if (authPending) return;
  authPending = true;
  authSubmitBtn.disabled = true;
  authError.textContent = "";
  try {
    setBackendStatus("正在进入", false);
    const result = await api(`/api/auth/${authMode}`, {
      method: "POST",
      body: JSON.stringify({
        name: authName.value.trim(),
        email: authEmail.value.trim(),
        password: authPassword.value
      })
    });
    currentUser = result.user;
    currentProfile = result.profile;
    localStorage.setItem("humanosUser", JSON.stringify(currentUser));
    localStorage.removeItem("humanosMotionTasks");
    tasks = [];
    syncProfileForm();
    hideAuth();
    await loadBackendState();
    setBackendStatus(authMode === "register" ? "注册成功，请完善偏好" : "登录成功", true);
  } catch (error) {
    currentUser = null;
    localStorage.removeItem("humanosUser");
    showAuth();
    authError.textContent = error.message.includes("409")
      ? "这个邮箱已经注册，请直接登录。"
      : error.message.includes("401")
        ? "邮箱或密码不正确。"
        : "暂时无法进入，请稍后再试。";
    setBackendStatus("认证失败", false);
  } finally {
    authPending = false;
    authSubmitBtn.disabled = false;
  }
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(`${response.status}: ${error}`);
  }
  return response.json();
}

function setBackendStatus(text, online = backendOnline) {
  backendStatus.textContent = text;
  backendStatus.style.color = online ? "var(--green)" : "var(--muted)";
}

function inferDurationMinutesFromText(text = "") {
  const clean = String(text);
  const match = clean.match(/(\d+)\s*(?:个\s*)?(分钟|min|小时|h)/i);
  if (!match) return null;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount) || amount <= 0) return null;
  return ["小时", "h"].includes(match[2].toLowerCase()) ? amount * 60 : amount;
}

function normalizeDuration(task) {
  const explicit = inferDurationMinutesFromText(`${task.title || ""} ${task.context || ""}`);
  if (explicit) return explicit;
  return Number(task.duration) || 60;
}

function normalizeBackendTask(task) {
  const checkpoints = task.checkpoints || [];
  const normalized = {
    id: task.id,
    title: task.title,
    due: task.due || task.deadline || "未设置",
    deadline: task.deadline || task.due || "未设置",
    duration: normalizeDuration(task),
    estimated_duration: task.estimated_duration || task.duration || 60,
    priority: task.priority || "中",
    status: task.status || "queued",
    context: task.context || "",
    slot: task.slot,
    checkpoints,
    contextWindow: normalizeContextWindow({ ...task, checkpoints }),
    type: task.type,
    task_type: task.task_type || task.taskType || task.contextWindow?.taskType || task.context_window?.taskType,
    cognitive_load: task.cognitive_load,
    ambiguity: task.ambiguity,
    switch_cost: task.switch_cost,
    reentry_cost: task.reentry_cost
  };
  normalized.slot = normalizedSlotForDue(normalized);
  return normalized;
}

function checkpointText(task, keywords) {
  return (task.checkpoints || []).find((item) => {
    const label = `${item.label || ""}`;
    return keywords.some((keyword) => label.includes(keyword));
  })?.text || "";
}

function normalizeContextWindow(task) {
  const saved = task.contextWindow || task.context_window || {};
  const progress = saved.progress
    || checkpointText(task, ["进展", "当前"])
    || task.context
    || "尚未记录当前进展。";
  const nextStep = saved.nextStep
    || saved.next_step
    || checkpointText(task, ["下一步", "继续"])
    || "回来后先确认任务目标，再选择一个 15-30 分钟内可完成的小步骤。";
  const openQuestions = saved.openQuestions
    || saved.open_questions
    || checkpointText(task, ["未解决", "问题", "卡点"])
    || "暂无明确开放问题。";
  const materials = saved.materials
    || saved.references
    || saved.links
    || "暂无绑定资料；可以在任务上下文中补充文献、链接或文件名。";
  const recoveryCue = saved.recoveryCue
    || saved.recovery_cue
    || (task.slot ? "到计划时间后先打开当前资料，再执行下一步。" : "安排进日历前先补齐时间、材料和下一步。");

  return { progress, nextStep, openQuestions, materials, recoveryCue };
}

function syncProfileForm() {
  profileRole.value = userFacingRole(currentProfile.role || "研究型学生");
  profileDeepWork.value = currentProfile.deep_work_window || "09:00-11:30";
  profileControl.value = currentProfile.control_preference || "confirm_before_reschedule";
}

function syncWizardForm() {
  const preferences = currentProfile.task_preferences || {};
  wizardRole.value = userFacingRole(currentProfile.role || "研究型学生");
  wizardDeepWork.value = currentProfile.deep_work_window || "09:00-11:30";
  wizardLowEnergy.value = currentProfile.low_energy_window || "14:00-15:30";
  wizardAvailableWindows.value = preferences.available_windows || "";
  wizardSessionLength.value = String(preferences.preferred_session_minutes || "45");
  wizardLearningMode.value = preferences.learning_mode || "reading_writing";
  wizardCurrentCourses.value = preferences.current_courses || "";
  wizardNearDeadlines.value = preferences.near_deadlines || "";
  wizardTools.value = Array.isArray(preferences.planning_tools) ? preferences.planning_tools.join(", ") : "";
  wizardPlanningGap.value = preferences.planning_gap || "";
  wizardGoal.value = preferences.short_term_goal || "";
  wizardSupportNeed.value = preferences.support_need || "clarify_next_action";
  wizardControl.value = currentProfile.control_preference || "confirm_before_reschedule";
  document.querySelectorAll('input[name="wizardBlocker"]').forEach((input) => {
    input.checked = (currentProfile.blocker_patterns || []).includes(input.value);
  });
}

function renderProfileSummary() {
  const preferences = currentProfile.task_preferences || {};
  const tools = Array.isArray(preferences.planning_tools) && preferences.planning_tools.length
    ? preferences.planning_tools.join(" / ")
    : "尚未填写";
  const blockers = Array.isArray(currentProfile.blocker_patterns) && currentProfile.blocker_patterns.length
    ? currentProfile.blocker_patterns.join(" / ")
    : "尚未填写";
  profileSummary.innerHTML = `
    <div class="summary-row">
      <span>学习场景</span>
      <strong>${userFacingRole(currentProfile.role || "研究型学生")}</strong>
    </div>
    <div class="summary-row">
      <span>深度工作</span>
      <strong>${currentProfile.deep_work_window || "09:00-11:30"}</strong>
    </div>
    <div class="summary-row">
      <span>低精力时间</span>
      <strong>${currentProfile.low_energy_window || "14:00-15:30"}</strong>
    </div>
    <div class="summary-row">
      <span>可用时间</span>
      <strong>${preferences.available_windows || "尚未填写"}</strong>
    </div>
    <div class="summary-row">
      <span>专注时长</span>
      <strong>${preferences.preferred_session_minutes ? `${preferences.preferred_session_minutes} 分钟` : "尚未填写"}</strong>
    </div>
    <div class="summary-row">
      <span>学习方式</span>
      <strong>${learningModeLabel(preferences.learning_mode)}</strong>
    </div>
    <div class="summary-row">
      <span>当前任务</span>
      <strong>${preferences.current_courses || "尚未填写"}</strong>
    </div>
    <div class="summary-row">
      <span>近期截止</span>
      <strong>${preferences.near_deadlines || "尚未填写"}</strong>
    </div>
    <div class="summary-row">
      <span>计划工具</span>
      <strong>${tools}</strong>
    </div>
    <div class="summary-row">
      <span>常见卡点</span>
      <strong>${blockers}</strong>
    </div>
    <div class="summary-row">
      <span>最近情况</span>
      <strong>${preferences.planning_gap || "尚未填写"}</strong>
    </div>
    <div class="summary-row">
      <span>两周目标</span>
      <strong>${preferences.short_term_goal || "尚未填写"}</strong>
    </div>
    <div class="summary-row">
      <span>主要支持</span>
      <strong>${supportNeedLabel(preferences.support_need)}</strong>
    </div>
  `;
}

function selectedWizardBlockers() {
  return Array.from(document.querySelectorAll('input[name="wizardBlocker"]:checked')).map((input) => input.value);
}

function planningTools() {
  return wizardTools.value
    .split(/[,，、]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function learningModeLabel(value) {
  return {
    reading_writing: "阅读和写作",
    visual: "图表 / 视频 / 可视化",
    discussion: "讨论 / 讲给别人听",
    practice: "做题 / 实操 / 项目推进",
    mixed: "混合方式"
  }[value] || "尚未填写";
}

function supportNeedLabel(value) {
  return {
    clarify_next_action: "把任务变成下一步行动",
    schedule_feasible_plan: "安排可执行时间表",
    recover_after_interruption: "中断后帮我接回来",
    balance_load_and_rest: "平衡负荷和休息"
  }[value] || "尚未填写";
}

async function loadBackendState() {
  try {
    const health = await api("/api/health");
    backendOnline = Boolean(health.ok);
    setBackendStatus(currentUser ? "已同步" : "请先登录", Boolean(currentUser));
    if (!currentUser) {
      showAuth();
      return;
    }

    const profileResponse = await api(`/api/profile?user_id=${currentUserId()}`);
    currentProfile = profileResponse.profile;
    syncProfileForm();
    userBadge.textContent = currentUser.email;

    const taskResponse = await api(`/api/tasks?user_id=${currentUserId()}`);
    if (taskResponse.tasks.length) {
      tasks = taskResponse.tasks.map(normalizeBackendTask);
      const correctedTasks = tasks.filter((task) => task.slot?.correctedFromDue);
      correctedTasks.forEach((task) => {
        delete task.slot.correctedFromDue;
      });
      if (correctedTasks.length) {
        await Promise.all(correctedTasks.map((task) => patchBackendTask(task).catch(() => null)));
      }
    } else {
      tasks = [];
    }
    const chatResponse = await api(`/api/chat/turns?user_id=${currentUserId()}&limit=${CHAT_CONTEXT_TURN_LIMIT}`);
    chatMessages = chatMessagesFromTurns(chatResponse.turns || []);
    activeSelectionMode = "auto";
    activeId = defaultActiveTaskId();
    if (profileCompleted(currentProfile)) {
      showApp();
    } else {
      showProfileSetup();
    }
    render();
  } catch (error) {
    backendOnline = false;
    setBackendStatus("暂时离线", false);
    showAuth();
    console.warn("HumanOS backend unavailable:", error.message);
  }
}

async function saveProfileToBackend() {
  currentProfile = {
    ...currentProfile,
    user_id: currentUserId(),
    role: profileRole.value.trim() || "研究型学生",
    deep_work_window: profileDeepWork.value.trim() || "09:00-11:30",
    control_preference: profileControl.value
  };
  if (!backendOnline) {
    setBackendStatus("偏好已更新", false);
    render();
    return;
  }
  const response = await api(`/api/profile?user_id=${currentUserId()}`, {
    method: "PUT",
    body: JSON.stringify(currentProfile)
  });
  currentProfile = response.profile;
  syncProfileForm();
  setBackendStatus("偏好已保存", true);
  render();
}

async function saveWizardProfile(markCompleted = true) {
  wizardError.textContent = "";
  currentProfile = {
    ...currentProfile,
    user_id: currentUserId(),
    role: wizardRole.value,
    deep_work_window: wizardDeepWork.value.trim() || "09:00-11:30",
    low_energy_window: wizardLowEnergy.value.trim() || "14:00-15:30",
    control_preference: wizardControl.value,
    blocker_patterns: selectedWizardBlockers(),
    task_preferences: {
      ...(currentProfile.task_preferences || {}),
      onboarding_completed: markCompleted,
      available_windows: wizardAvailableWindows.value.trim(),
      preferred_session_minutes: Number(wizardSessionLength.value) || 45,
      learning_mode: wizardLearningMode.value,
      current_courses: wizardCurrentCourses.value.trim(),
      near_deadlines: wizardNearDeadlines.value.trim(),
      planning_tools: planningTools(),
      planning_gap: wizardPlanningGap.value.trim(),
      short_term_goal: wizardGoal.value.trim(),
      support_need: wizardSupportNeed.value,
      recovery_preference: wizardControl.value
    }
  };
  if (backendOnline) {
    const response = await api(`/api/profile?user_id=${currentUserId()}`, {
      method: "PUT",
      body: JSON.stringify(currentProfile)
    });
    currentProfile = response.profile;
  }
  syncProfileForm();
  showApp();
  setBackendStatus(markCompleted ? "偏好已保存" : "稍后设置", backendOnline);
  render();
}

async function saveRuntimeStateToBackend() {
  if (!backendOnline) return null;
  const response = await api("/api/state-checkins", {
    method: "POST",
    body: JSON.stringify({
      user_id: currentUserId(),
      focus: Number(focusInput.value),
      energy: Number(energyInput.value),
      stress: Number(stressInput.value)
    })
  });
  return response.runtime_state;
}

async function patchBackendTask(task) {
  if (!backendOnline) return;
  await api(`/api/tasks/${task.id}?user_id=${encodeURIComponent(currentUserId())}`, {
    method: "PATCH",
    body: JSON.stringify({ ...task, user_id: currentUserId() })
  });
}

async function deleteBackendTask(taskId) {
  if (!backendOnline) return;
  await api(`/api/tasks/${taskId}?user_id=${encodeURIComponent(currentUserId())}`, { method: "DELETE" });
}

function normalizePendingSchedulePlan(plan) {
  if (!plan) return null;
  if (!Array.isArray(plan.plan_patch) && Array.isArray(plan.plan)) {
    plan.plan_patch = plan.plan;
  }
  if (!Array.isArray(plan.plan_patch)) plan.plan_patch = [];
  return plan;
}

function pendingPlanBlocks(plan = pendingSchedulePlan) {
  return normalizePendingSchedulePlan(plan)?.plan_patch || [];
}

async function deleteTaskById(taskId, closeDialog = false) {
  if (!taskId) return;
  if (deletingTaskIds.has(taskId)) return;
  deletingTaskIds.add(taskId);
  const task = tasks.find((item) => item.id === taskId);
  const title = task?.title || "任务";
  const previousTasks = [...tasks];
  normalizePendingSchedulePlan(pendingSchedulePlan);
  const previousPendingPlan = pendingSchedulePlan ? {
    ...pendingSchedulePlan,
    plan_patch: [...pendingPlanBlocks()],
    violations: [...(pendingSchedulePlan.violations || [])]
  } : null;
  tasks = tasks.filter((item) => item.id !== taskId);
  if (pendingPlanBlocks().length) {
    pendingSchedulePlan.plan_patch = pendingPlanBlocks().filter((block) => block.task_id !== taskId);
    pendingSchedulePlan.violations = (pendingSchedulePlan.violations || []).filter((violation) => {
      if (violation.task_id === taskId) return false;
      if ((violation.task_ids || []).includes(taskId)) return false;
      return true;
    });
    if (!pendingSchedulePlan.plan_patch.length) pendingSchedulePlan = null;
  }
  try {
    await deleteBackendTask(taskId);
    activeSelectionMode = "auto";
    activeId = defaultActiveTaskId();
    addChatMessage("ai", "已删除任务", `${title} 已从日历和任务记录中删除。`);
    if (editingTaskId === taskId) editingTaskId = null;
    deleteTaskBtn.classList.add("hidden");
    if (closeDialog && dialog.open) dialog.close("deleted");
  } catch (error) {
    tasks = previousTasks;
    pendingSchedulePlan = previousPendingPlan;
    addChatMessage("ai", "删除失败", `${title} 暂时没有删除成功，请稍后再试。`);
    console.error(error);
  } finally {
    deletingTaskIds.delete(taskId);
  }
  render();
}

async function createTaskFromPayload(task) {
  if (backendOnline) {
    const response = await api(`/api/tasks?user_id=${currentUserId()}`, {
      method: "POST",
      body: JSON.stringify({ ...task, user_id: currentUserId() })
    });
    return normalizeBackendTask({
      ...task,
      ...response.task,
      contextWindow: response.task.contextWindow || task.contextWindow
    });
  }
  return task;
}

function taskDurationHours(task) {
  return Math.max(Number(task?.duration || 60), 15) / 60;
}

function colorForTask(task, index = 0) {
  if (task.slot?.color) return task.slot.color;
  if (task.priority === "高") return "blue";
  if (task.priority === "低") return "gold";
  return ["green", "violet", "blue", "gold"][index % 4];
}

function taskCalendarBlock(task, index = 0) {
  const explicitStart = taskScheduleType(task) === "fixed_event" ? parseDueStartHour(task.due) : null;
  const start = task.slot?.start ?? explicitStart;
  if (start === null || start === undefined) return null;
  const end = task.slot?.end ?? (start + taskDurationHours(task));
  return {
    task,
    task_id: task.id,
    start,
    end,
    color: colorForTask(task, index),
    source: task.slot ? "scheduled" : "suggested"
  };
}

function visibleCalendarBlocks() {
  const pendingIds = new Set(pendingPlanBlocks().map((block) => block.task_id));
  const taskBlocks = tasks
    .map((task, index) => taskCalendarBlock(task, index))
    .filter((block) => block && !pendingIds.has(block.task_id));
  const pendingBlocks = pendingPlanBlocks()
    .map((block) => {
      const task = tasks.find((item) => item.id === block.task_id);
      if (!task) return null;
      return { ...block, task, source: "pending", color: block.color || colorForTask(task) };
    })
    .filter(Boolean);
  return [...taskBlocks, ...pendingBlocks].sort((a, b) => a.start - b.start);
}

function todayCalendarBlocks() {
  const todayIndex = dayIndexFromDue("今天");
  return visibleCalendarBlocks().filter((block) => dayIndexFromDue(block.task.due) === todayIndex);
}

function overlapLayout(blocks) {
  return blocks.map((block) => {
    const overlaps = blocks.filter((other) => block.start < other.end && other.start < block.end);
    const ordered = overlaps.sort((a, b) => a.start - b.start || a.end - b.end || a.task_id.localeCompare(b.task_id));
    const columnCount = Math.max(ordered.length, 1);
    const columnIndex = Math.max(ordered.findIndex((item) => item.task_id === block.task_id), 0);
    return { ...block, columnCount, columnIndex };
  });
}

function roundHourToStep(hour, stepMinutes = DRAG_STEP_MINUTES) {
  const step = stepMinutes / 60;
  return Math.round(Number(hour) / step) * step;
}

function clampTaskStart(task, startHour) {
  const duration = taskDurationHours(task);
  const minStart = CALENDAR_START_HOUR;
  const maxStart = Math.max(CALENDAR_START_HOUR, CALENDAR_END_HOUR - duration);
  return Math.min(Math.max(roundHourToStep(startHour), minStart), maxStart);
}

function dropHourFromEvent(event, slot) {
  const rect = slot.getBoundingClientRect();
  const baseHour = Number(slot.dataset.hour);
  const offset = Math.min(Math.max(event.clientY - rect.top, 0), Math.max(rect.height, 1));
  const fraction = offset / Math.max(rect.height, 1);
  return roundHourToStep(baseHour + fraction);
}

function pendingBlockForTask(taskId) {
  return pendingPlanBlocks().find((block) => block.task_id === taskId) || null;
}

function taskStatusClass(task, block) {
  const now = currentHourFloat();
  const classes = [];
  if (task.status === "completed" || task.status === "terminated") classes.push("completed");
  if (task.status === "running" || (dayIndexFromDue(task.due) === dayIndexFromDue("今天") && now >= block.start && now < block.end)) {
    classes.push("current");
  }
  if (task.id === activeId) classes.push("selected");
  if (block.source === "pending") classes.push("pending");
  if (block.source === "suggested") classes.push("suggested");
  return classes.join(" ");
}

async function moveTaskToHour(taskId, startHour) {
  const task = tasks.find((item) => item.id === taskId);
  if (!task) return;
  const start = clampTaskStart(task, startHour);
  const pendingBlock = pendingBlockForTask(taskId);
  if (pendingBlock) {
    pendingBlock.start = start;
    pendingBlock.end = start + taskDurationHours(task);
    pendingBlock.color = pendingBlock.color || colorForTask(task);
    selectTask(task.id, "manual");
    addChatMessage(
      "ai",
      "待确认安排已调整",
      `${task.title} 的建议时间已移动到 ${formatHour(pendingBlock.start)}-${formatHour(pendingBlock.end)}。确认后才会写入日历。`
    );
    render();
    return;
  }
  task.slot = {
    start,
    end: start + taskDurationHours(task),
    color: colorForTask(task)
  };
  if (taskScheduleType(task) === "fixed_event") {
    task.due = dueWithStartHour(task.due, start);
    task.deadline = task.due;
  }
  if (task.status === "queued") task.status = "scheduled";
  selectTask(task.id, "manual");
  await patchBackendTask(task);
  addChatMessage(
    "ai",
    "调整判断",
    `${task.title} 已移动到 ${formatHour(task.slot.start)}-${formatHour(task.slot.end)}。${stateBasedScheduleNote(task)}`
  );
  render();
}

function stateBasedScheduleNote(task) {
  const energy = Number(energyInput.value);
  const stress = Number(stressInput.value);
  if (taskDurationHours(task) >= 2 && (energy <= 3 || stress >= 6)) {
    return "当前状态下这个时间块偏长，建议中途保留一次上下文检查。";
  }
  return "这个安排会保留在日历上，你仍然可以继续拖拽调整。";
}

async function requestTentativeSchedule(reason = "基于当前输入生成安排", targetTasks = null) {
  const sourceTasks = Array.isArray(targetTasks) && targetTasks.length ? targetTasks : tasks;
  const schedulableTasks = sourceTasks.filter((task) => missingTimeConfirmationFields(task).length === 0);
  if (!schedulableTasks.length) {
    addChatMessage("ai", "需要确认条件", "生成安排前，我至少需要知道：任务标题、截止日期、预计时长。只有固定会议或固定事件才需要具体开始时间。");
    return;
  }
  if (backendOnline) {
    const runtimeState = await saveRuntimeStateToBackend();
    const response = await api("/api/schedules/decide", {
      method: "POST",
      body: JSON.stringify({
        user_id: currentUserId(),
        runtime_state: runtimeState,
        tasks: schedulableTasks
      })
    });
    pendingSchedulePlan = normalizePendingSchedulePlan(response.decision);
    pendingSchedulePlan.plan_patch = (pendingSchedulePlan.plan_patch || []).map((block) => {
      const task = tasks.find((item) => item.id === block.task_id);
      if (taskScheduleType(task) !== "fixed_event") return block;
      const explicitStart = parseDueStartHour(task?.due);
      if (explicitStart === null) return block;
      return {
        ...block,
        start: explicitStart,
        end: explicitStart + taskDurationHours(task)
      };
    });
  } else {
    const task = selectedTask() && missingTimeConfirmationFields(selectedTask()).length === 0
      ? selectedTask()
      : schedulableTasks[0];
    const slotStart = taskScheduleType(task) === "fixed_event"
      ? (parseDueStartHour(task.due) ?? 9)
      : (task.priority === "高" ? 9 : task.priority === "中" ? 14 : 16);
    pendingSchedulePlan = normalizePendingSchedulePlan({
      action: "suggest_plan",
      plan_patch: [{
        task_id: task.id,
        start: slotStart,
        end: slotStart + taskDurationHours(task),
        color: task.priority === "高" ? "blue" : task.priority === "中" ? "violet" : "gold"
      }],
      explanation: reason,
      requires_confirmation: true
    });
  }
  lastDecision = pendingSchedulePlan;
  addChatMessage("ai", "请确认安排", "我已经在右侧生成待确认安排。确认后才会加入日历。");
}

async function handleChatTurn(text) {
  const clean = text.trim();
  if (!clean) {
    addChatMessage("ai", "需要输入", "请直接告诉我你想安排、推进或反馈的任务。");
    render();
    return;
  }
  addChatMessage("user", "你", clean);
  chatSendBtn.disabled = true;
  try {
    let turn;
    if (backendOnline) {
      const response = await api("/api/chat/turn", {
        method: "POST",
        body: JSON.stringify({ user_id: currentUserId(), text: clean })
      });
      turn = response.turn;
    } else {
      turn = {
        reply: "我会先把这句话拆成任务处理，并生成待确认安排。",
        confidence: 0.58,
        features: { intent: "add_task", blockers: [], confidence: 0.58 },
        tasks: localFallbackTasksFromText(clean)
      };
    }
    const createdTasks = (turn.tasks || []).map(normalizeBackendTask);
    createdTasks.forEach((task) => {
      const existingIndex = tasks.findIndex((item) => item.id === task.id);
      if (existingIndex >= 0) {
        tasks[existingIndex] = task;
      } else {
        tasks.push(task);
      }
    });
    if (createdTasks.length) {
      activeSelectionMode = "auto";
      activeId = defaultActiveTaskId();
    }
    chatInput.value = "";
    const confidenceText = formatConfidence(chatConfidence(turn));
    const blockerText = turn.features?.blockers?.length ? `\n可能卡点：${turn.features.blockers.join(" / ")}` : "";
    const featureText = `${blockerText}${confidenceText ? `\n${confidenceText}` : ""}`;
    addChatMessage("ai", "HumanOS", `${turn.reply}${featureText}`);
    if (createdTasks.length) {
      const incompleteTasks = createdTasks
        .map((task) => ({ task, missing: missingTimeConfirmationFields(task) }))
        .filter((item) => item.missing.length);
      const schedulableTasks = createdTasks.filter((task) => missingTimeConfirmationFields(task).length === 0);
      if (incompleteTasks.length) {
        addChatMessage(
          "ai",
          "需要确认时间",
          incompleteTasks
            .map(({ task, missing }) => `${task.title}：还需要 ${missing.join("、")}`)
            .join("\n")
        );
      }
      if (schedulableTasks.length) {
        await requestTentativeSchedule("根据刚刚解析出的任务生成安排。", schedulableTasks);
      }
    }
    render();
  } catch (error) {
    addChatMessage("ai", "处理失败", "暂时无法处理这条消息，请稍后再试。");
    console.error(error);
    render();
  } finally {
    chatSendBtn.disabled = false;
  }
}

function currentHourFloat() {
  const now = getNow();
  return now.getHours() + now.getMinutes() / 60;
}

function dayDistanceFromToday(dayIndex) {
  if (dayIndex === null || dayIndex === undefined) return 14;
  const todayIndex = dayIndexFromDue("今天");
  return (dayIndex - todayIndex + 7) % 7;
}

function activeCandidateScore(block) {
  const dayDistance = dayDistanceFromToday(dayIndexFromDue(block.task.due));
  const nowHour = currentHourFloat();
  const start = Number(block.start);
  const end = Number(block.end);
  if (dayDistance === 0 && start <= nowHour && nowHour < end) return -1000 + start;
  if (dayDistance === 0 && start >= nowHour) return start;
  return dayDistance * 24 + start;
}

function defaultActiveTaskId() {
  const candidates = visibleCalendarBlocks()
    .filter((block) => block.task.status !== "completed" && block.task.status !== "terminated")
    .sort((a, b) => activeCandidateScore(a) - activeCandidateScore(b));
  if (candidates.length) return candidates[0].task.id;
  const fallback = tasks.find((task) => task.status !== "completed" && task.status !== "terminated") || tasks[0];
  return fallback?.id || null;
}

function ensureActiveTask() {
  const activeExists = tasks.some((task) => task.id === activeId);
  if (activeSelectionMode === "auto" || !activeExists) {
    activeId = defaultActiveTaskId();
    activeSelectionMode = "auto";
  }
}

function checkTaskTimePrompts(force = false) {
  const nowHour = currentHourFloat();
  tasks.filter((task) => task.slot).forEach((task) => {
    const startKey = `${task.id}:start:${task.slot.start}`;
    const endKey = `${task.id}:end:${task.slot.end}`;
    if ((force || Math.abs(nowHour - task.slot.start) <= 0.08) && !promptedSlots.has(startKey)) {
      promptedSlots.add(startKey);
      addChatMessage("ai", "任务开始提醒", `${task.title} 的计划时间到了。你现在准备开始吗？如果不能开始，可以告诉我原因。`);
    }
    if ((force || Math.abs(nowHour - task.slot.end) <= 0.08) && !promptedSlots.has(endKey)) {
      promptedSlots.add(endKey);
      addChatMessage("ai", "任务进展检查", `${task.title} 这个时间块结束了。现在进展到哪里？下一步是什么？`);
    }
  });
  save();
  renderChat();
}

function statusLabel(task) {
  if (task.status === "running") return isEnglish() ? "Running" : "执行中";
  if (task.status === "paused") return isEnglish() ? "Suspended" : "已暂停";
  if (task.status === "scheduled") return isEnglish() ? "Scheduled" : "已安排";
  if (task.status === "completed") return isEnglish() ? "Completed" : "已完成";
  if (task.status === "queued") return isEnglish() ? "Ready" : "候选";
  return isEnglish() ? "Ready" : "候选";
}

function renderChat() {
  const task = selectedTask();
  const focus = focusInput.value;
  const energy = energyInput.value;
  const stress = stressInput.value;
  const hasCheckpoint = task?.checkpoints?.length > 0;
  const systemMessages = [
    {
      sender: "ai",
      title: t("systemTitle"),
      text: `${isEnglish() ? "Today is" : "今天是"} ${todayLabel()}。\n${t("systemIntro")}`
    },
    {
      sender: "ai",
      title: t("stateTitle"),
      text: `${t("focus")} ${focus}/7，${t("energy")} ${energy}/7，${t("stress")} ${stress}/7。`
    },
    {
      sender: "ai",
      title: task ? task.title : t("noTask"),
      text: task
        ? hasCheckpoint
          ? t("taskHasCheckpoint")
          : t("taskNoCheckpoint")
        : t("createTaskHint")
    }
  ];
  const decisionMessages = lastDecision ? [{
    sender: "ai",
    title: t("suggestion"),
    text: `${lastDecision.explanation}${formatConfidence(lastDecision.confidence) ? `\n${formatConfidence(lastDecision.confidence)}` : ""}${lastDecision.first_action ? `\n${t("firstStep")}：${lastDecision.first_action}` : ""}${lastDecision.risk ? `\n${t("risk")}：${lastDecision.risk}` : ""}`
  }] : [];
  chatThread.innerHTML = [...systemMessages, ...decisionMessages, ...chatMessages].map((message) => `
    <div class="message ${message.sender}">
      <strong>${escapeHtml(message.title)}${message.createdAt ? ` · ${escapeHtml(message.createdAt)}` : ""}</strong>
      ${escapeHtml(message.text).replace(/\n/g, "<br>")}
    </div>
  `).join("");
  chatThread.scrollTop = chatThread.scrollHeight;
}

function renderCalendar() {
  if (calendarView === "week") {
    renderWeekCalendar();
    return;
  }
  const hours = Array.from({ length: CALENDAR_END_HOUR - CALENDAR_START_HOUR }, (_, index) => CALENDAR_START_HOUR + index);
  const blocks = overlapLayout(todayCalendarBlocks());

  calendar.innerHTML = `
    <div class="time-col">
      ${hours.map((hour) => `<div class="time-label">${String(hour).padStart(2, "0")}:00</div>`).join("")}
    </div>
    <div class="slot-col">
      ${hours.map((hour) => `<div class="slot" data-hour="${hour}"></div>`).join("")}
    </div>
  `;

  calendar.querySelectorAll(".slot").forEach((slot) => {
    slot.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      slot.classList.add("drag-over");
    });
    slot.addEventListener("dragleave", () => {
      slot.classList.remove("drag-over");
    });
    slot.addEventListener("drop", (event) => {
      event.preventDefault();
      slot.classList.remove("drag-over");
      const taskId = event.dataTransfer.getData("text/task-id");
      if (taskId) moveTaskToHour(taskId, dropHourFromEvent(event, slot));
    });
  });

  blocks.forEach((block) => {
    const task = block.task;
    const firstSlot = calendar.querySelector(`.slot[data-hour="${Math.floor(block.start)}"]`);
    if (!firstSlot) return;
    const top = (block.start - Math.floor(block.start)) * HOUR_ROW_HEIGHT;
    const height = Math.max((block.end - block.start) * HOUR_ROW_HEIGHT - 8, 44);
    const width = 100 / block.columnCount;
    const left = width * block.columnIndex;
    const event = document.createElement("article");
    event.className = `event ${block.color} ${taskStatusClass(task, block)}`;
    event.style.top = `${top + 4}px`;
    event.style.height = `${height}px`;
    event.style.left = `calc(${left}% + 12px)`;
    event.style.width = `calc(${width}% - 18px)`;
    event.style.right = "auto";
    event.dataset.id = task.id;
    event.draggable = true;
    const label = block.source === "pending" ? t("pending") : block.source === "suggested" ? t("pending") : task.status === "completed" ? t("completed") : t("executionWindow");
    event.innerHTML = `
      <button class="event-delete" type="button" aria-label="${t("deleteTask")} ${escapeHtml(task.title)}">×</button>
      <h3>${escapeHtml(task.title)}</h3>
      <p>${label} · ${formatHour(block.start)}-${formatHour(block.end)}</p>
    `;
    event.addEventListener("dragstart", (dragEvent) => {
      dragEvent.dataTransfer.setData("text/task-id", task.id);
      dragEvent.dataTransfer.effectAllowed = "move";
      event.classList.add("dragging");
    });
    event.addEventListener("dragend", () => {
      event.classList.remove("dragging");
      calendar.querySelectorAll(".slot.drag-over").forEach((slot) => slot.classList.remove("drag-over"));
    });
    event.querySelector(".event-delete")?.addEventListener("click", (deleteEvent) => {
      deleteEvent.stopPropagation();
      deleteTaskById(task.id);
    });
    event.addEventListener("click", () => {
      selectTask(task.id, "manual");
      openTaskDialog(task);
    });
    firstSlot.appendChild(event);
  });
}

function renderWeekCalendar() {
  const days = isEnglish()
    ? ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    : ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  const allBlocks = visibleCalendarBlocks();
  const blocksByDay = days.map((_, dayIndex) => {
    return allBlocks
      .filter((block) => dayIndexFromDue(block.task.due) === dayIndex)
      .sort((a, b) => a.start - b.start);
  });
  calendar.innerHTML = `
    <div class="week-grid">
      ${days.map((day, dayIndex) => `
        <section class="week-day">
          <h3>${day}</h3>
          ${blocksByDay[dayIndex].length ? blocksByDay[dayIndex]
            .map((block) => `
              <article class="week-event ${block.color} ${taskStatusClass(block.task, block)}" data-id="${block.task.id}">
                <button class="event-delete" type="button" aria-label="${t("deleteTask")} ${escapeHtml(block.task.title)}">×</button>
                <strong>${escapeHtml(block.task.title)}</strong>
                <span>${formatHour(block.start)}-${formatHour(block.end)} · ${block.source === "pending" || block.source === "suggested" ? t("pending") : `${block.task.duration} ${t("minutes")}`}</span>
              </article>
            `).join("") : `<p>${t("noSchedule")}</p>`}
        </section>
      `).join("")}
    </div>
  `;
  document.querySelectorAll(".week-event").forEach((event) => {
    event.querySelector(".event-delete")?.addEventListener("click", (deleteEvent) => {
      deleteEvent.stopPropagation();
      deleteTaskById(event.dataset.id);
    });
    event.addEventListener("click", () => {
      selectTask(event.dataset.id, "manual");
      openTaskDialog(selectedTask());
    });
  });
}

function formatHour(value) {
  const hour = Math.floor(Number(value));
  const minute = Math.round((Number(value) - hour) * 60);
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function renderActiveTask() {
  const task = selectedTask();
  if (!task) {
    resumeSubtitle.textContent = t("noTask");
    modePill.textContent = t("empty");
    activeTask.innerHTML = `
      <h3>${t("noTask")}</h3>
      <p>${t("noTaskDetail")}</p>
    `;
    return;
  }
  resumeSubtitle.textContent = task.title;
  modePill.textContent = statusLabel(task);
  const windowData = normalizeContextWindow(task);
  const block = taskCalendarBlock(task);
  const scheduleText = block ? `${formatHour(block.start)}-${formatHour(block.end)}` : t("unscheduled");
  activeTask.innerHTML = `
    <h3>${escapeHtml(task.title)}</h3>
    <p>${escapeHtml(task.context || "暂无任务说明。")}</p>
    <div class="task-meta" style="margin-top:12px">
      <span class="tag ${priorityClass(task.priority)}">${escapeHtml(task.priority)}${t("prioritySuffix")}</span>
      <span class="tag">${task.duration} ${t("minutes")}</span>
      <span class="tag">${escapeHtml(task.due)}</span>
      <span class="tag">${scheduleText}</span>
      <span class="tag">${statusLabel(task)}</span>
    </div>
    <div class="active-task-context">
      <article>
        <span>${t("progress")}</span>
        <p>${escapeHtml(windowData.progress)}</p>
      </article>
      <article>
        <span>${t("firstStep")}</span>
        <p>${escapeHtml(windowData.nextStep)}</p>
      </article>
      <article>
        <span>${t("openQuestions")}</span>
        <p>${escapeHtml(windowData.openQuestions)}</p>
      </article>
    </div>
    <div class="task-actions">
      <button class="ghost" type="button" data-action="edit-active-task">${t("edit")}</button>
      <button class="danger" type="button" data-action="delete-active-task">${t("deleteTask")}</button>
    </div>
  `;
  activeTask.querySelector('[data-action="edit-active-task"]')?.addEventListener("click", () => {
    openTaskDialog(task);
  });
  activeTask.querySelector('[data-action="delete-active-task"]')?.addEventListener("click", () => {
    deleteTaskById(task.id);
  });
}

function renderCheckpoints() {
  const task = selectedTask();
  if (!task) {
    checkpointCount.textContent = `0 ${t("items")}`;
    checkpointView.innerHTML = `
      <div class="checkpoint-item">
        <strong>${t("noCheckpoint")}</strong>
        <p>${t("checkpointHelp")}</p>
      </div>
    `;
    return;
  }
  checkpointCount.textContent = `${task.checkpoints.length} ${t("items")}`;
  if (!task.checkpoints.length) {
    checkpointView.innerHTML = `
      <div class="checkpoint-item">
        <strong>${t("noCheckpoint")}</strong>
        <p>${t("checkpointTaskHelp")}</p>
      </div>
    `;
    return;
  }

  checkpointView.innerHTML = task.checkpoints.map((item) => `
    <div class="checkpoint-item">
      <strong>${item.label}</strong>
      <p>${item.text}</p>
    </div>
  `).join("");
}

function renderSchedulingLens() {
  if (!schedulingLens) return;
  const task = selectedTask();
  const node = schedulingNodeForTask(task);
  schedulingLens.innerHTML = `
    <article class="scheduling-lens ${node.className}">
      <div>
        <span>${node.title}</span>
        <strong>${node.zh}</strong>
      </div>
      <p>${node.product}</p>
      <small>${node.evidence}</small>
    </article>
  `;
}

function renderContextWindow() {
  const task = selectedTask();
  if (!task) {
    contextWindow.innerHTML = `
      <div class="context-window-empty">
        <strong>${t("noContext")}</strong>
        <p>${t("contextEmptyHelp")}</p>
      </div>
    `;
    return;
  }
  const windowData = normalizeContextWindow(task);
  task.contextWindow = windowData;
  const items = [
    [t("progress"), windowData.progress],
    [t("nextStep"), windowData.nextStep],
    [t("unresolved"), windowData.openQuestions],
    [t("materials"), windowData.materials],
    [t("recoveryCue"), windowData.recoveryCue]
  ];
  contextWindow.innerHTML = items.map(([label, value]) => `
    <article class="context-window-item">
      <span>${escapeHtml(label)}</span>
      <p>${escapeHtml(value).replace(/\n/g, "<br>")}</p>
    </article>
  `).join("");
}

function renderBrief() {
  const task = selectedTask();
  if (!task) {
    resumeBrief.innerHTML = `
      <div class="brief-card">
        <h3>${t("noTask")}</h3>
        <ul>
          <li>${t("resumeEntry")}：${t("generatedAfterTask")}</li>
          <li>${t("nextStep")}：${t("createTaskFirst")}</li>
          <li>${t("suggestedBlock")}：${t("notSet")}</li>
        </ul>
      </div>
    `;
    return;
  }
  const hasCheckpoint = task.checkpoints.length > 0;
  const nextAction = hasCheckpoint
    ? task.checkpoints[task.checkpoints.length - 1].text
    : t("saveContextFirst");

  resumeBrief.innerHTML = `
    <div class="brief-card">
      <h3>${task.title}</h3>
      <ul>
        <li>${t("resumeEntry")}：${hasCheckpoint ? t("fromLastCheckpoint") : t("saveCheckpointFirst")}</li>
        <li>${t("nextStep")}：${nextAction}</li>
        <li>${t("suggestedBlock")}：${Math.min(task.duration, 45)} ${t("minutes")}</li>
      </ul>
    </div>
  `;
}

function renderReasoning() {
  if (!reasoning) return;
  const task = selectedTask();
  const focus = Number(focusInput.value);
  const energy = Number(energyInput.value);
  const stress = Number(stressInput.value);
  if (!task) {
    reasoning.innerHTML = `
      <div class="reason-card">
        <h3>为什么这样排</h3>
        <ul>
          <li>当前还没有任务，因此不会生成具体日历安排。</li>
          <li>用户状态：专注 ${focus}/7，精力 ${energy}/7，压力 ${stress}/7。</li>
          <li>新增任务后，会显示安排依据和是否需要确认。</li>
        </ul>
      </div>
    `;
    return;
  }
  const node = schedulingNodeForTask(task);
  reasoning.innerHTML = `
    <div class="reason-card">
      <h3>为什么这样排</h3>
      <ul>
        <li>当前任务处于 ${statusLabel(task)}，优先级为 ${task.priority}，截止期为 ${task.due}。</li>
        <li>调度映射：当前对应 ${node.title} / ${node.zh}，因此系统关注的是${node.zh === "等待调度" ? "是否进入日历执行窗口" : node.zh === "上下文切换" ? "保存与恢复上下文" : node.zh === "正在执行" ? "执行证据和切换风险" : "状态迁移和用户确认"}。</li>
        <li>用户状态：专注 ${focus}/7，精力 ${energy}/7，压力 ${stress}/7。</li>
        <li>${energy <= 3 || stress >= 6 ? "状态和任务负荷存在冲突，所以系统倾向于先拆小、保存上下文或要求确认。" : "当前状态可以执行较完整时间块，但切换前仍需要保存上下文。"}</li>
        <li>你的学习场景：${userFacingRole(currentProfile.role || "研究型学生")}，适合专注的时间 ${currentProfile.deep_work_window || "09:00-11:30"}。</li>
        <li>${lastDecision?.memory_evidence?.length ? `参考了 ${lastDecision.memory_evidence.length} 条相似的过往情况。` : "后续建议会显示更多记录依据。"}</li>
      </ul>
    </div>
  `;
}

function render() {
  ensureActiveTask();
  applyTranslations();
  syncDebugTimeControl();
  if (focusValue) focusValue.textContent = focusInput.value;
  if (energyValue) energyValue.textContent = energyInput.value;
  if (stressValue) stressValue.textContent = stressInput.value;
  todayBadge.textContent = `${t("todayPrefix")}${todayLabel()}`;
  renderMotionShellMeta();
  dayViewBtn.classList.toggle("active", calendarView === "day");
  weekViewBtn.classList.toggle("active", calendarView === "week");
  renderProfileSummary();
  renderPendingSchedule();
  renderChat();
  renderCalendar();
  renderActiveTask();
  renderSchedulingLens();
  renderContextWindow();
  renderCheckpoints();
  renderBrief();
  save();
}

function renderPendingSchedule() {
  if (!pendingPlanBlocks().length) {
    pendingSchedule.classList.add("hidden");
    pendingScheduleText.textContent = "";
    return;
  }
  const lines = pendingPlanBlocks().map((block) => {
    const task = tasks.find((item) => item.id === block.task_id);
    return `${task?.title || (isEnglish() ? "Task" : "任务")}：${formatHour(block.start)}-${formatHour(block.end)}`;
  });
  const violationLines = (pendingSchedulePlan.violations || [])
    .map((violation) => {
      if (violation.type === "fixed_event_conflict") {
        const names = (violation.task_ids || [])
          .map((id) => tasks.find((item) => item.id === id)?.title)
          .filter(Boolean)
          .join(" 与 ");
        return names ? `${isEnglish() ? "Fixed event conflict" : "固定事件冲突"}：${names} ${isEnglish() ? "overlap at" : "在"} ${formatHour(violation.start)}-${formatHour(violation.end)}` : "";
      }
      const task = tasks.find((item) => item.id === violation.task_id);
      const title = task?.title || (isEnglish() ? "Task" : "任务");
      if (violation.type === "outside_available_window") return isEnglish() ? `${title} is outside your available window` : `${title} 超出你填写的可用时间`;
      if (violation.type === "high_load_in_low_energy_window") return isEnglish() ? `${title} may fall in a low-energy window` : `${title} 可能落在低能量时段`;
      if (violation.type === "low_task_clarity") return isEnglish() ? `${title} needs a clearer goal` : `${title} 的目标还需要再明确`;
      if (violation.type === "missing_deadline") return isEnglish() ? `${title} is missing a deadline` : `${title} 还缺截止日期`;
      if (violation.type === "missing_duration") return isEnglish() ? `${title} is missing estimated duration` : `${title} 还缺预计时长`;
      return "";
    })
    .filter(Boolean);
  pendingSchedule.classList.remove("hidden");
  pendingScheduleText.textContent = `${pendingSchedulePlan.explanation || (isEnglish() ? "Suggested schedule generated." : "已生成建议安排。")} ${violationLines.join("；")} ${lines.join("；")}`;
}

function createCheckpointFromFeedback(text) {
  const clean = text.trim() || "用户暂停任务，但没有补充详细说明。";
  return [
    { label: "暂停原因", text: clean.includes("切换") || clean.includes("开会") ? "用户需要切换到其他任务，当前任务进入暂停状态。" : "用户反馈当前计划需要调整。" },
    { label: "当前进展", text: clean },
    { label: "下一步", text: clean.includes("下一步") ? clean.slice(clean.indexOf("下一步")).replace(/^下一步[：: ]*/, "") : "恢复时先回顾当前材料，再选择一个 30 分钟内可完成的小步骤。" }
  ];
}

function openTaskDialog(task = null) {
  editingTaskId = task?.id || null;
  taskDialogTitle.textContent = task ? (isEnglish() ? "Edit Task" : "编辑任务") : (isEnglish() ? "Add Academic Task" : "新增学术任务");
  saveTaskBtn.textContent = task ? (isEnglish() ? "Save changes" : "保存修改") : (isEnglish() ? "Save" : "保存");
  deleteTaskBtn.classList.toggle("hidden", !task);
  document.getElementById("newTitle").value = task?.title || "整理 HumanOS related work";
  document.getElementById("newDue").value = task?.due || "周五 18:00";
  document.getElementById("newDuration").value = task?.duration || 90;
  document.getElementById("newPriority").value = task?.priority || "中";
  document.getElementById("newStatus").value = task?.status || "queued";
  document.getElementById("newContext").value = task?.context || "需要比较 Motion、TaskSnap、TaskTracer 和 HumanOS 的差异。";
  const windowData = normalizeContextWindow(task || {});
  document.getElementById("newProgress").value = task ? windowData.progress : "";
  document.getElementById("newNextStep").value = task ? windowData.nextStep : "";
  document.getElementById("newOpenQuestions").value = task ? windowData.openQuestions : "";
  if (!dialog.open) dialog.showModal();
  document.getElementById("newTitle").focus();
}

function taskPayloadFromDialog(id, previous = {}) {
  const initialContext = document.getElementById("newContext").value.trim() || "暂无上下文。";
  const progress = document.getElementById("newProgress").value.trim();
  const nextStep = document.getElementById("newNextStep").value.trim();
  const openQuestions = document.getElementById("newOpenQuestions").value.trim();
  const due = document.getElementById("newDue").value.trim() || "未设置";
  const title = document.getElementById("newTitle").value.trim() || "未命名任务";
  const duration = inferDurationMinutesFromText(`${title} ${initialContext}`) || Number(document.getElementById("newDuration").value) || 60;
  const slotStart = parseDueStartHour(due);
  const inferredTaskType = inferDialogTaskType(title, initialContext, due, previous);
  const shouldRefreshSlot = inferredTaskType === "fixed_event" && previous.slot && slotStart !== null;
  return {
    ...previous,
    id,
    title,
    due,
    deadline: due,
    duration,
    estimated_duration: duration,
    task_type: inferredTaskType,
    priority: document.getElementById("newPriority").value,
    status: document.getElementById("newStatus").value,
    context: initialContext,
    contextWindow: {
      ...(previous.contextWindow || {}),
      progress: progress || initialContext,
      nextStep: nextStep || "回来后先确认任务目标，再选择一个 15-30 分钟内可完成的小步骤。",
      openQuestions: openQuestions || "暂无明确开放问题。",
      materials: previous.contextWindow?.materials || "暂无绑定资料；可以在任务上下文中补充文献、链接或文件名。",
      recoveryCue: previous.contextWindow?.recoveryCue || "安排进日历前先补齐时间、材料和下一步。"
    },
    slot: shouldRefreshSlot
      ? { ...previous.slot, start: slotStart, end: slotStart + duration / 60 }
      : previous.slot || null,
    checkpoints: previous.checkpoints || []
  };
}

[focusInput, energyInput, stressInput].forEach((input) => {
  input.addEventListener("input", render);
});

debugApplyTimeBtn.addEventListener("click", () => {
  const value = debugTimeInput.value;
  const next = value ? new Date(value).getTime() : NaN;
  if (!Number.isFinite(next)) {
    addChatMessage("ai", "Debug 时间无效", "请选择一个完整的日期和时间。");
    render();
    return;
  }
  applyDebugNow(next);
});

debugStepTimeBtn.addEventListener("click", () => {
  applyDebugNow(getNow().getTime() + 15 * 60 * 1000);
});

debugResetTimeBtn.addEventListener("click", () => {
  resetDebugNow();
});

debugTimeInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    debugApplyTimeBtn.click();
  }
});

document.getElementById("autoScheduleBtn").addEventListener("click", async () => {
  if (!tasks.length) {
    addChatMessage("ai", t("noTaskAuto"), t("noTaskAutoBody"));
    render();
    return;
  }
  await requestTentativeSchedule(t("autoReason"));
  render();
});

confirmScheduleBtn.addEventListener("click", async () => {
  if (!pendingPlanBlocks().length) return;
  for (const block of pendingPlanBlocks()) {
    const target = tasks.find((item) => item.id === block.task_id);
    if (target) {
      target.status = target.status === "paused" ? "paused" : "scheduled";
      target.slot = { start: block.start, end: block.end, color: block.color || "blue" };
      if (taskScheduleType(target) === "fixed_event") {
        target.due = dueWithStartHour(target.due, block.start);
        target.deadline = target.due;
      }
      await patchBackendTask(target);
    }
  }
  addChatMessage("ai", t("scheduleConfirmed"), t("scheduleConfirmedBody"));
  pendingSchedulePlan = null;
  activeSelectionMode = "auto";
  activeId = defaultActiveTaskId();
  checkTaskTimePrompts(false);
  render();
});

rejectScheduleBtn.addEventListener("click", () => {
  pendingSchedulePlan = null;
  addChatMessage("ai", t("scheduleCanceled"), t("scheduleCanceledBody"));
  render();
});

document.getElementById("addTaskBtn").addEventListener("click", () => {
  openTaskDialog();
});

sidebarNewTaskBtn?.addEventListener("click", () => {
  openTaskDialog();
});

langToggleBtn?.addEventListener("click", () => {
  currentLang = isEnglish() ? "zh" : "en";
  localStorage.setItem(LANG_KEY, currentLang);
  setAuthMode(authMode);
  render();
});

accountChipBtn?.addEventListener("click", () => {
  showProfileHomeView();
});

sidebarCollapseBtn?.addEventListener("click", () => {
  document.body.classList.toggle("sidebar-collapsed");
  applyTranslations();
});

sidebarChatBtn?.addEventListener("click", () => {
  showWorkspaceView();
  document.body.classList.remove("sidebar-collapsed");
  chatInput.focus();
});

sidebarCalendarBtn?.addEventListener("click", () => {
  showWorkspaceView();
  calendar.scrollIntoView({ block: "nearest" });
  calendar.focus?.();
});

sidebarTasksBtn?.addEventListener("click", () => {
  showWorkspaceView();
  if (selectedTask()) {
    document.querySelector(".motion-right-rail")?.scrollTo({ top: 0, behavior: "smooth" });
  } else {
    openTaskDialog();
  }
});

miniPrevBtn?.addEventListener("click", () => {
  miniCalendarCursor = new Date(miniCalendarCursor.getFullYear(), miniCalendarCursor.getMonth() - 1, 1);
  renderMotionShellMeta();
});

miniNextBtn?.addEventListener("click", () => {
  miniCalendarCursor = new Date(miniCalendarCursor.getFullYear(), miniCalendarCursor.getMonth() + 1, 1);
  renderMotionShellMeta();
});

chatSendBtn.addEventListener("click", () => {
  handleChatTurn(chatInput.value);
});

chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    handleChatTurn(chatInput.value);
  }
});

workspaceNavBtn.addEventListener("click", () => {
  showWorkspaceView();
});

profileHomeBtn.addEventListener("click", () => {
  showProfileHomeView();
});

sidebarProfileBtn?.addEventListener("click", () => {
  showProfileHomeView();
});

todayJumpBtn?.addEventListener("click", () => {
  miniCalendarCursor = new Date(getNow().getFullYear(), getNow().getMonth(), 1);
  resetDebugNow(false);
  render();
});

closeTaskDialogBtn.addEventListener("click", () => {
  editingTaskId = null;
  deleteTaskBtn.classList.add("hidden");
  dialog.close("cancel");
});

dayViewBtn.addEventListener("click", () => {
  calendarView = "day";
  render();
});

weekViewBtn.addEventListener("click", () => {
  calendarView = "week";
  render();
});

taskForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (editingTaskId) {
    const index = tasks.findIndex((task) => task.id === editingTaskId);
    if (index >= 0) {
      const updated = normalizeBackendTask(taskPayloadFromDialog(editingTaskId, tasks[index]));
      tasks[index] = updated;
      selectTask(updated.id, "manual");
      await patchBackendTask(updated);
      addChatMessage("ai", t("editDecision"), `${updated.title} ${isEnglish() ? "was updated." : "已更新。"}${stateBasedScheduleNote(updated)}`);
      setBackendStatus("任务已更新", backendOnline);
    }
  } else {
    const id = `task-${Date.now()}`;
    const task = taskPayloadFromDialog(id, {});
    const created = await createTaskFromPayload(task);
    tasks.push(created);
    selectTask(created.id, "manual");
    addChatMessage("ai", t("manualAdded"), `${created.title} ${t("manualAddedBody")}`);
    setBackendStatus("任务已保存", backendOnline);
  }
  editingTaskId = null;
  deleteTaskBtn.classList.add("hidden");
  dialog.close("saved");
  render();
});

deleteTaskBtn.addEventListener("click", async () => {
  if (!editingTaskId) return;
  await deleteTaskById(editingTaskId, true);
});

document.getElementById("saveProfileBtn").addEventListener("click", () => {
  saveProfileToBackend().catch((error) => {
    setBackendStatus("保存失败", false);
    console.error(error);
  });
});

openProfileWizardBtn.addEventListener("click", () => {
  showProfileSetup();
});

wizardPrevBtn.addEventListener("click", () => {
  wizardStep = Math.max(0, wizardStep - 1);
  updateWizardStep();
});

wizardNextBtn.addEventListener("click", () => {
  wizardStep = Math.min(WIZARD_STEP_COUNT - 1, wizardStep + 1);
  updateWizardStep();
});

profileWizard.addEventListener("submit", (event) => {
  event.preventDefault();
  saveWizardProfile(true).catch((error) => {
    wizardError.textContent = "暂时无法保存，请稍后再试。";
    console.error(error);
  });
});

skipProfileBtn.addEventListener("click", () => {
  saveWizardProfile(false).catch((error) => {
    wizardError.textContent = "暂时无法进入，请稍后再试。";
    console.error(error);
  });
});

loginModeBtn.addEventListener("click", () => setAuthMode("login"));
registerModeBtn.addEventListener("click", () => setAuthMode("register"));

authForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitAuth();
});

logoutBtn.addEventListener("click", () => {
  currentUser = null;
  currentProfile = {
    role: "研究型学生",
    deep_work_window: "09:00-11:30",
    low_energy_window: "14:00-15:30",
    control_preference: "confirm_before_reschedule"
  };
  tasks = cloneSeedTasks();
  activeSelectionMode = "auto";
  activeId = defaultActiveTaskId();
  lastDecision = null;
  localStorage.removeItem("humanosUser");
  localStorage.removeItem("humanosMotionTasks");
  syncProfileForm();
  profileScreen.classList.add("hidden");
  appRoot.classList.add("hidden");
  setAuthMode("login");
  showAuth();
  render();
});

setAuthMode("login");
render();
loadBackendState();
setInterval(() => {
  if (!isDebugTimeEnabled()) syncDebugTimeControl();
  if (currentUser && !appRoot.classList.contains("hidden")) {
    checkTaskTimePrompts(false);
    render();
  }
}, 60000);
