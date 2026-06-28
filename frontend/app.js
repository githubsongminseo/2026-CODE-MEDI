const EMOTION_OPTIONS = ["부정", "분노", "협상", "우울"];
const PRE_SESSION_COACH_MESSAGE = "난이도를 선택한 뒤 대화 시작을 눌러 케이스를 시작하세요.";
const SESSION_START_COACH_MESSAGE = "당신이 먼저 인사하며 문진을 시작하세요 (예: '안녕하세요, 담당 의료진 OOO입니다.')";
const EMOTION_SPRITE_CLASS = {
  "부정": "emotion-denial",
  "분노": "emotion-anger",
  "협상": "emotion-bargaining",
  "우울": "emotion-depression",
};
const EMOTION_INDICATORS = {
  "부정": ["부정", "믿기지", "말도 안", "아니", "오진", "고개를 젓", "당황", "혼란"],
  "분노": ["분노", "화", "짜증", "언성", "소리", "주먹", "격앙", "따지", "노려"],
  "협상": ["협상", "혹시", "제발", "간절", "매달", "애원", "방법", "희망", "기회"],
  "우울": ["우울", "눈물", "울", "흐느", "고개를 숙", "한숨", "무기력", "막막", "멍하"],
};

const state = {
  ready: false,
  pending: false,
  loadError: "",
  cases: [],
  currentCase: null,
  selectedDifficulty: "중",
  initialEmotion: "부정",
  sessionId: null,
  session: null,
  completed: false,
  report: null,
  nextCase: null,
  selectedReportItemId: null,
};

const elements = Object.fromEntries(
  [
    "patientBubble", "patientSprite", "learnerBubble", "learnerSprite", "coachSprite", "coachLine",
    "patientName",
    "recordToggle", "recordCount", "recordPreview", "recordModal", "recordFeed",
    "closeRecordBtn", "chartToggle", "chartTitle", "chartPreview", "chartModal", "chartSummary", "chartFeed",
    "closeChartBtn", "difficultyLabel", "composer", "freeQuestion", "sendBtn", "startBtn", "resetBtn",
    "finishBtn", "reportPanel", "closeReportBtn",
    "reportCoverage", "reportCoverageBar", "reportMissed", "reportReasoning", "missedList", "reportDetail",
    "weaknessTags", "nextFocus", "nextCaseList", "nextCaseBtn",
  ].map((id) => [id, document.querySelector(`#${id}`)]),
);

function setText(node, value) {
  if (node) node.textContent = value;
}

function createTextElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `요청 실패 (${response.status})`);
  return payload;
}

function messages() {
  return state.session?.messages || [];
}

function visibleMessages() {
  const transcript = messages();
  return transcript.some((message) => message.role === "learner") ? transcript : [];
}

function randomItem(items) {
  if (!Array.isArray(items) || !items.length) return null;
  return items[Math.floor(Math.random() * items.length)];
}

function patientNameFromCase(caseItem) {
  const chartName = caseItem?.chart?.["이름"];
  if (chartName) return chartName;
  const displayName = caseItem?.display_name || caseItem?.safe_metadata?.split(" · ")[0];
  return displayName?.replace(/\s*\([^)]*\)\s*$/, "").trim() || "환자";
}

function chartPreviewFromCase(caseItem) {
  const chart = caseItem?.chart || {};
  const demographics = chart["나이_성별"] || chart["나이 성별"];
  if (demographics) return demographics;
  return caseItem?.safe_metadata || "클릭해서 차트 보기";
}

function renderPatientName() {
  setText(elements.patientName, patientNameFromCase(state.currentCase));
}

function setPatientEmotionSprite(emotion) {
  if (!elements.patientSprite) return;
  Object.values(EMOTION_SPRITE_CLASS).forEach((className) => {
    elements.patientSprite.classList.remove(className);
  });
  const emotionClass = EMOTION_SPRITE_CLASS[emotion];
  if (emotionClass) elements.patientSprite.classList.add(emotionClass);
}

function emotionInstructionText(text) {
  const instructionMatches = [...(text || "").matchAll(/[\[(（(]([^)\]）]+)[)\]）]/g)];
  return instructionMatches.map((match) => match[1]).join(" ");
}

function patientEmotionFromInstruction(text) {
  const instruction = emotionInstructionText(text);
  if (!instruction) return null;
  return EMOTION_OPTIONS.find((emotion) => {
    const indicators = EMOTION_INDICATORS[emotion] || [];
    return indicators.some((indicator) => instruction.includes(indicator));
  }) || null;
}

function renderStatus() {
  const started = Boolean(state.sessionId);

  elements.startBtn.disabled = !state.ready || started || state.pending;
  elements.sendBtn.disabled = !started || state.completed || state.pending;
  elements.freeQuestion.disabled = !started || state.completed || state.pending;
  elements.finishBtn.disabled = !started || state.completed || state.pending || !state.session?.can_complete;
  elements.chartToggle.disabled = !state.currentCase;
  document.querySelectorAll(".difficulty-option").forEach((button) => {
    const isActive = button.dataset.difficulty === state.selectedDifficulty;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
    button.disabled = started || state.pending;
  });
  setText(elements.difficultyLabel, state.selectedDifficulty);
}

function positionPatientBubble(text) {
  const cleanLength = (text || "").trim().length;
  const sceneHeight = document.querySelector(".scene-stage")?.clientHeight || 390;
  const mobileScene = sceneHeight <= 385;
  const baseTop = mobileScene ? 96 : 104;
  const lift = Math.min(mobileScene ? 18 : 24, Math.max(0, Math.ceil((cleanLength - 56) / 42) * 6));
  const top = Math.max(mobileScene ? 78 : 82, baseTop - lift);
  const tailTop = top < 90 ? 26 : 36;
  elements.patientBubble.style.setProperty("--patient-bubble-top", `${top}px`);
  elements.patientBubble.style.setProperty("--patient-bubble-tail-top", `${tailTop}px`);
}

function renderConversation() {
  const transcript = visibleMessages();
  const latestPatient = [...transcript].reverse().find((message) => message.role === "patient");
  const latestLearner = [...transcript].reverse().find((message) => message.role === "learner");
  const patientText = latestPatient?.content || "대화 시작을 누른 뒤 질문을 입력하면 환자가 답변합니다.";
  setText(elements.patientBubble, patientText);
  setPatientEmotionSprite(latestPatient ? patientEmotionFromInstruction(patientText) : null);
  positionPatientBubble(patientText);
  if (latestLearner) {
    setText(elements.learnerBubble, latestLearner.content);
    elements.learnerBubble.hidden = false;
  } else {
    elements.learnerBubble.hidden = true;
  }
  renderRecord();
}

function renderRecord() {
  elements.recordFeed.replaceChildren();
  const transcript = visibleMessages();
  const questionCount = transcript.filter((message) => message.role === "learner").length;
  setText(elements.recordCount, questionCount ? `질문 ${questionCount}개` : "기록 없음");
  if (!transcript.length) {
    elements.recordFeed.append(createTextElement("p", "empty-state", "질문과 환자 답변이 여기에 기록됩니다."));
    setText(elements.recordPreview, "아직 기록 없음");
    return;
  }
  transcript.forEach((message) => {
    const line = document.createElement("p");
    line.className = `log-line ${message.role}`;
    line.append(createTextElement("strong", "", message.role === "learner" ? "학습자" : "환자"));
    line.append(document.createTextNode(message.content));
    elements.recordFeed.append(line);
  });
  setText(elements.recordPreview, transcript[transcript.length - 1].content);
}

function chartEntries(caseItem) {
  if (!caseItem?.chart) return [];
  return Object.entries(caseItem.chart).filter(([key]) => key !== "_comment");
}

function renderChart() {
  elements.chartFeed.replaceChildren();
  elements.chartSummary.replaceChildren();
  if (!state.currentCase) {
    setText(elements.chartTitle, "대기 중");
    setText(elements.chartPreview, "대화 시작 후 확인");
    elements.chartSummary.append(createTextElement("p", "empty-state", "대화를 시작하면 환자 정보가 표시됩니다."));
    return;
  }

  setText(elements.chartTitle, patientNameFromCase(state.currentCase));
  setText(elements.chartPreview, chartPreviewFromCase(state.currentCase));
  const meta = createTextElement("p", "chart-meta", state.currentCase.safe_metadata || "");
  const instruction = createTextElement("p", "chart-instruction", state.currentCase.instruction_to_learner || "");
  elements.chartSummary.append(meta, instruction);

  const entries = chartEntries(state.currentCase);
  if (!entries.length) {
    elements.chartFeed.append(createTextElement("p", "empty-state", "표시할 차트 정보가 없습니다."));
    return;
  }
  entries.forEach(([key, value]) => {
    const row = document.createElement("div");
    row.className = "chart-row";
    row.append(createTextElement("strong", "", key.replace(/_/g, " ")));
    row.append(createTextElement("span", "", String(value)));
    elements.chartFeed.append(row);
  });
}

function toggleChart(forceOpen) {
  if (!state.currentCase) return;
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : elements.chartModal.hidden;
  renderChart();
  elements.chartModal.hidden = !shouldOpen;
  elements.chartToggle.setAttribute("aria-expanded", String(shouldOpen));
  if (shouldOpen) elements.chartModal.parentElement.scrollTo({ top: 0, behavior: "auto" });
  if (shouldOpen) elements.closeChartBtn.focus();
  else elements.chartToggle.focus();
}

function setDifficulty(difficulty) {
  if (!["하", "중", "상"].includes(difficulty) || state.sessionId || state.pending) return;
  state.selectedDifficulty = difficulty;
  renderStatus();
}

function toggleRecord(forceOpen) {
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : elements.recordModal.hidden;
  elements.recordModal.hidden = !shouldOpen;
  elements.recordToggle.setAttribute("aria-expanded", String(shouldOpen));
  if (shouldOpen) elements.recordModal.parentElement.scrollTo({ top: 0, behavior: "auto" });
  if (shouldOpen) elements.closeRecordBtn.focus();
  else elements.recordToggle.focus();
}

async function startEncounter(options = {}) {
  if (!state.ready || state.sessionId || state.pending) return;
  const caseItem = options.caseItem || randomItem(state.cases);
  const initialEmotion = randomItem(EMOTION_OPTIONS) || state.initialEmotion;
  if (!caseItem) {
    setText(elements.coachLine, "사용 가능한 케이스가 없습니다.");
    return;
  }
  state.pending = true;
  renderStatus();
  try {
    const payload = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({
        case_id: caseItem.case_id,
        difficulty: state.selectedDifficulty,
        initial_emotion: initialEmotion,
      }),
    });
    state.sessionId = payload.session_id;
    state.session = payload.session;
    state.currentCase = payload.case;
    state.selectedDifficulty = payload.session?.difficulty || state.selectedDifficulty;
    state.initialEmotion = payload.session?.initial_emotion || initialEmotion;
    renderPatientName();
    renderChart();
    setText(elements.coachLine, SESSION_START_COACH_MESSAGE);
    renderConversation();
    requestAnimationFrame(() => elements.freeQuestion.focus());
  } catch (error) {
    setText(elements.coachLine, error.message);
  } finally {
    state.pending = false;
    renderStatus();
  }
}

async function submitQuestion(value) {
  const question = value.trim();
  if (!question || !state.sessionId || state.pending || state.completed) return;
  state.pending = true;
  elements.freeQuestion.value = "";
  elements.learnerSprite.classList.add("typing");
  setText(elements.coachLine, "환자 답변을 확인하고 있습니다.");
  renderStatus();
  try {
    const payload = await api(`/api/sessions/${encodeURIComponent(state.sessionId)}/questions`, {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    state.session = payload.session;
    const guidance = {
      answered: "답변에서 확인한 내용을 다음 질문으로 연결하세요.",
      unmatched: "증상, 시작 시점, 병력처럼 한 항목씩 구체적으로 질문하세요.",
      boundary: "환자 역할에서 답할 수 있는 증상과 경험을 질문해 주세요.",
    };
    setText(elements.coachLine, guidance[payload.result.kind] || guidance.answered);
    renderConversation();
  } catch (error) {
    setText(elements.coachLine, error.message);
    elements.freeQuestion.value = question;
  } finally {
    state.pending = false;
    elements.learnerSprite.classList.remove("typing");
    renderStatus();
    elements.freeQuestion.focus();
  }
}

function reportItems() {
  const items = state.report?.items || [];
  const priority = { missed: 0, needs_review: 1, completed: 2 };
  return [...items].sort(
    (left, right) => (priority[left.status] ?? 3) - (priority[right.status] ?? 3),
  );
}

function renderReportList() {
  elements.missedList.replaceChildren();
  reportItems().forEach((item) => {
    const listItem = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = `report-item-button status-${item.status || "unknown"}`;
    button.setAttribute("aria-pressed", String(item.id === state.selectedReportItemId));
    const statusLabel = item.status === "missed"
      ? "놓친 항목"
      : item.status === "needs_review"
        ? "보완 필요"
        : "확인 완료";
    button.append(createTextElement("span", "", `${item.category} · ${statusLabel}`));
    button.append(createTextElement("strong", "", item.label));
    button.append(createTextElement("small", "", item.feedback));
    button.addEventListener("click", () => {
      state.selectedReportItemId = item.id;
      renderReportList();
      renderReportDetail();
    });
    listItem.append(button);
    elements.missedList.append(listItem);
  });
}

function renderReportDetail() {
  elements.reportDetail.replaceChildren();
  const item = reportItems().find((entry) => entry.id === state.selectedReportItemId);
  if (!item) {
    elements.reportDetail.append(createTextElement("p", "empty-state", "표시할 피드백이 없습니다."));
    return;
  }
  elements.reportDetail.append(createTextElement("h3", "", item.label));
  elements.reportDetail.append(createTextElement("p", "detail-summary", item.feedback));

  const whySection = document.createElement("section");
  whySection.className = "detail-section";
  whySection.append(createTextElement("h4", "", "왜 중요한가"));
  whySection.append(createTextElement("p", "detail-copy", item.why_it_matters));
  elements.reportDetail.append(whySection);

  const learnerSection = document.createElement("section");
  learnerSection.className = "detail-section";
  learnerSection.append(createTextElement("h4", "", "내 기록"));
  const learnerEvidence = Array.isArray(item.learner_evidence) ? item.learner_evidence : [];
  if (learnerEvidence.length) {
    const list = document.createElement("ul");
    learnerEvidence.forEach((entry) => list.append(createTextElement("li", "", entry)));
    learnerSection.append(list);
  } else {
    learnerSection.append(createTextElement("p", "detail-copy", "관련 질문 기록이 없습니다."));
  }
  elements.reportDetail.append(learnerSection);

  const evidence = Array.isArray(item.evidence) ? item.evidence : [];
  const validEvidence = evidence.filter((entry) => {
    if (!entry || typeof entry.title !== "string" || typeof entry.url !== "string") return false;
    try {
      return ["http:", "https:"].includes(new URL(entry.url).protocol);
    } catch {
      return false;
    }
  });
  if (validEvidence.length) {
    const evidenceSection = document.createElement("section");
    evidenceSection.className = "detail-section";
    evidenceSection.append(createTextElement("h4", "", "관련 근거"));
    const list = document.createElement("ul");
    validEvidence.forEach((entry) => {
      const listItem = document.createElement("li");
      const link = document.createElement("a");
      link.href = entry.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = entry.title;
      listItem.append(link);
      list.append(listItem);
    });
    evidenceSection.append(list);
    elements.reportDetail.append(evidenceSection);
  }
}

function renderNextPractice() {
  elements.weaknessTags.replaceChildren();
  elements.nextCaseList.replaceChildren();
  const reviewItems = state.report.items.filter((item) => ["missed", "needs_review"].includes(item.status));
  reviewItems.slice(0, 4).forEach((item) => {
    elements.weaknessTags.append(createTextElement("span", "", item.label));
  });
  const modeLabel = state.nextCase?.mode === "progression" ? "확장 연습" : "보완 연습";
  if (!reviewItems.length && state.nextCase?.mode === "progression") {
    elements.weaknessTags.append(createTextElement("span", "", "새로운 계통 적용"));
  }
  const directions = state.nextCase?.directions || [];
  const nextFocus = directions[0] || "같은 핵심 문진을 유지하며 질문 순서를 반복합니다.";
  setText(elements.nextFocus, `${modeLabel} · ${nextFocus}`);
  directions.slice(1).forEach((direction) => {
    elements.nextCaseList.append(createTextElement("li", "", direction));
  });
  const recommendedCase = state.nextCase?.case;
  elements.nextCaseBtn.hidden = !recommendedCase;
  if (recommendedCase) {
    setText(elements.nextCaseBtn, "랜덤 케이스 시작");
  }
}

function assessmentPayload() {
  return {
    problem_summary: "대화 종료 후 외부 평가 모델을 연결할 예정입니다.",
    primary_impression: "외부 평가 모델 연결 예정",
    differential_diagnoses: "외부 평가 모델 연결 예정",
    reasoning: "현재 데모에서는 대화 종료 즉시 리포트를 확인합니다.",
  };
}

async function finishEncounter() {
  if (!state.session?.can_complete || state.pending || state.completed) return;
  state.pending = true;
  renderStatus();
  try {
    const payload = await api(`/api/sessions/${encodeURIComponent(state.sessionId)}/complete`, {
      method: "POST",
      body: JSON.stringify({ assessment: assessmentPayload() }),
    });
    state.completed = true;
    state.report = payload.report;
    state.nextCase = payload.next_case;
    const items = reportItems();
    state.selectedReportItemId = items[0]?.id || null;
    const coveragePercent = Math.max(0, Math.min(100, Number(state.report.coverage_percent) || 0));
    setText(elements.reportCoverage, `${coveragePercent}%`);
    if (elements.reportCoverageBar) {
      elements.reportCoverageBar.style.width = `${coveragePercent}%`;
    }
    setText(elements.reportMissed, String(state.report.items.filter((item) => item.status === "missed").length));
    setText(elements.reportReasoning, String(state.report.assessment_review_count));
    renderReportList();
    renderReportDetail();
    renderNextPractice();
    toggleRecord(false);
    elements.reportPanel.parentElement.scrollTo({ top: 0, behavior: "auto" });
    elements.reportPanel.hidden = false;
    elements.reportPanel.focus({ preventScroll: true });
    setText(elements.patientBubble, "대화가 종료됐습니다. 교육용 리포트를 확인해 주세요.");
    setPatientEmotionSprite(null);
    setText(elements.coachLine, "리포트는 진단 스프레드시트와 데모 카드의 비공개 형성평가 기준으로 생성했습니다.");
    positionPatientBubble(elements.patientBubble.textContent);
    elements.coachSprite.classList.add("writing");
  } catch (error) {
    setText(elements.coachLine, error.message);
  } finally {
    state.pending = false;
    renderStatus();
  }
}

function resetEncounter() {
  state.sessionId = null;
  state.session = null;
  state.completed = false;
  state.report = null;
  state.nextCase = null;
  state.selectedReportItemId = null;
  state.currentCase = null;
  renderPatientName();
  setPatientEmotionSprite(null);
  elements.reportPanel.hidden = true;
  elements.recordModal.hidden = true;
  elements.chartModal.hidden = true;
  elements.recordToggle.setAttribute("aria-expanded", "false");
  elements.chartToggle.setAttribute("aria-expanded", "false");
  elements.coachSprite.classList.remove("writing");
  setText(elements.coachLine, PRE_SESSION_COACH_MESSAGE);
  renderChart();
  renderConversation();
  renderStatus();
}

async function startRandomFollowupCase() {
  if (state.pending) return;
  resetEncounter();
  await startEncounter();
}

function closeReport() {
  elements.reportPanel.hidden = true;
  elements.resetBtn.focus();
}

async function loadCases() {
  try {
    const payload = await api("/api/cases");
    if (!Array.isArray(payload.cases) || !payload.cases.length) throw new Error("사용 가능한 케이스가 없습니다.");
    state.cases = payload.cases;
    state.ready = true;
  } catch (error) {
    state.loadError = `${error.message} CPX 서버를 먼저 실행하세요.`;
    setText(elements.coachLine, state.loadError);
    console.error("CODE MEDI CPX API load failed", error);
  }
  renderStatus();
}

elements.startBtn.addEventListener("click", startEncounter);
elements.resetBtn.addEventListener("click", resetEncounter);
elements.recordToggle.addEventListener("click", () => toggleRecord());
elements.closeRecordBtn.addEventListener("click", () => toggleRecord(false));
elements.chartToggle.addEventListener("click", () => toggleChart());
elements.closeChartBtn.addEventListener("click", () => toggleChart(false));
elements.finishBtn.addEventListener("click", finishEncounter);
elements.closeReportBtn.addEventListener("click", closeReport);
elements.nextCaseBtn.addEventListener("click", startRandomFollowupCase);
document.querySelectorAll(".difficulty-option").forEach((button) => {
  button.addEventListener("click", () => setDifficulty(button.dataset.difficulty));
});
elements.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitQuestion(elements.freeQuestion.value);
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!elements.recordModal.hidden) toggleRecord(false);
  else if (!elements.chartModal.hidden) toggleChart(false);
  else if (!elements.reportPanel.hidden) closeReport();
});
window.addEventListener("resize", () => positionPatientBubble(elements.patientBubble.textContent));

renderConversation();
renderPatientName();
renderChart();
renderStatus();
loadCases();
