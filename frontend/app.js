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
};

const elements = Object.fromEntries(
  [
    "patientBubble", "patientSprite", "learnerBubble", "learnerSprite", "coachSprite", "coachLine",
    "patientName",
    "recordToggle", "recordCount", "recordPreview", "recordModal", "recordFeed",
    "closeRecordBtn", "chartToggle", "chartTitle", "chartPreview", "chartModal", "chartSummary", "chartFeed",
    "closeChartBtn", "difficultyLabel", "composer", "freeQuestion", "sendBtn", "startBtn", "resetBtn",
    "finishBtn", "reportPanel", "closeReportBtn",
    "reportCoverage", "reportMissed", "reportReasoning", "reportSavedNote",
    "criticalFailBanner", "coreChecklist", "emotionDetectedBanner", "emotionChecklist",
    "ppiResults", "ppiNarrative", "recommendationContent", "nextCaseBtn",
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
  const detail = typeof payload.detail === "string" ? payload.detail : null;
  if (!response.ok) throw new Error(detail || payload.error || `요청 실패 (${response.status})`);
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

function patientGenderFromCase(caseItem) {
  const chart = caseItem?.chart || {};
  const genderText = [
    chart["나이_성별"],
    chart["나이 성별"],
    chart["성별"],
    caseItem?.safe_metadata,
  ].filter(Boolean).join(" ");
  if (/(여성|여자|여환|female)/i.test(genderText)) return "female";
  return "male";
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

function renderPatientSpriteProfile() {
  if (!elements.patientSprite) return;
  elements.patientSprite.classList.toggle("patient-female", patientGenderFromCase(state.currentCase) === "female");
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
  const initialEmotion = options.initialEmotion || randomItem(EMOTION_OPTIONS) || state.initialEmotion;
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
    renderPatientSpriteProfile();
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

const PPI_LABELS = {
  "1": "효율적으로 묻고 들어주었다",
  "2": "생각과 배경을 알아냈다",
  "3": "이해하기 쉽게 설명하였다",
  "4": "좋은 유대관계를 형성하였다",
  "5": "면담을 체계적으로 이끌었다",
  "6": "신체진찰 태도가 좋았다",
};

function reportItemsByCode() {
  const map = new Map();
  (state.report?.items || []).forEach((item) => {
    if (item?.id) map.set(item.id, item);
  });
  return map;
}

function labelForEvaluationCode(code) {
  return reportItemsByCode().get(code)?.label || code;
}

function appendRawDebug(container, title, raw) {
  if (!container) return;
  container.replaceChildren();
  container.append(createTextElement("p", "empty-state", title));
  const pre = createTextElement("pre", "raw-debug", String(raw || ""));
  container.append(pre);
}

function checklistResults(checklistAxis) {
  const core = checklistAxis?.core_results || {};
  const emotion = checklistAxis?.emotion_response?.results || {};
  return [...Object.values(core), ...Object.values(emotion)].filter((value) => {
    return value && typeof value === "object" && ["O", "X"].includes(value.result);
  });
}

function ppiRatingValue(rating) {
  const match = String(rating ?? "").match(/\d+(\.\d+)?/);
  if (!match) return null;
  const value = Number(match[0]);
  return Number.isFinite(value) ? value : null;
}

function ppiAverage(ppiAxis) {
  const ratings = Object.values(ppiAxis?.ppi_results || {})
    .map((item) => ppiRatingValue(item?.rating))
    .filter((value) => value !== null);
  if (!ratings.length) return null;
  const average = ratings.reduce((sum, value) => sum + value, 0) / ratings.length;
  return average.toFixed(1).replace(/\.0$/, "");
}

function renderEvaluationRows(container, items, emptyText) {
  if (!container) return;
  container.replaceChildren();
  const entries = Object.entries(items || {});
  if (!entries.length) {
    container.append(createTextElement("p", "empty-state", emptyText));
    return;
  }

  entries.forEach(([code, value]) => {
    const result = value && typeof value === "object" ? value : {};
    const passed = result.result === "O";
    const mark = passed ? "O" : "X";
    const row = document.createElement("div");
    row.className = `evaluation-row ${passed ? "passed" : "failed"}`;
    row.append(createTextElement("span", `evaluation-mark ${passed ? "pass" : "fail"}`, mark));
    row.append(createTextElement("span", "evaluation-code", code));

    const body = document.createElement("div");
    body.className = "evaluation-row-body";
    body.append(createTextElement("strong", "", labelForEvaluationCode(code)));
    const evidence = String(result.evidence || "").trim();
    if (evidence) body.append(createTextElement("p", "", evidence));
    row.append(body);
    container.append(row);
  });
}

function renderCriticalFails(checklistAxis) {
  if (!elements.criticalFailBanner) return;
  const banner = elements.criticalFailBanner;
  banner.replaceChildren();
  banner.className = "critical-fail-banner";

  if (checklistAxis?._parse_error) {
    banner.classList.add("error");
    banner.append(createTextElement("strong", "", "체크리스트 평가 응답을 해석하지 못했습니다."));
    banner.append(createTextElement("pre", "raw-debug", String(checklistAxis._raw || "")));
    return;
  }

  const criticalFails = Array.isArray(checklistAxis?.critical_fails_triggered)
    ? checklistAxis.critical_fails_triggered
    : [];
  if (!criticalFails.length) {
    banner.classList.add("success");
    banner.append(createTextElement("strong", "", "Critical Fail 없음"));
    banner.append(createTextElement("span", "", "환자 안전과 면담 기본 원칙을 크게 위반한 항목은 감지되지 않았습니다."));
    return;
  }

  const evidence = checklistAxis?.critical_fail_evidence || {};
  banner.classList.add("fail");
  banner.append(createTextElement("strong", "", `Critical Fail 발생: ${criticalFails.length}개`));
  const list = document.createElement("ul");
  criticalFails.forEach((code) => {
    const item = createTextElement("li", "", `${labelForEvaluationCode(code)} (${code})`);
    const detail = String(evidence[code] || "").trim();
    if (detail) item.append(createTextElement("span", "", detail));
    list.append(item);
  });
  banner.append(list);
}

function renderEmotionResponse(emotionResponse) {
  const detected = Array.isArray(emotionResponse?.detected_emotions)
    ? emotionResponse.detected_emotions
    : [];
  setText(
    elements.emotionDetectedBanner,
    detected.length
      ? `감지된 환자 감정: ${detected.join(", ")}`
      : "뚜렷한 감정 반응이 감지되지 않았습니다.",
  );
  renderEvaluationRows(
    elements.emotionChecklist,
    emotionResponse?.results || {},
    "감정 대응 평가 항목이 없습니다.",
  );
}

function renderPpiRows(ppiAxis) {
  if (ppiAxis?._parse_error) {
    appendRawDebug(elements.ppiResults, "PPI 평가 응답을 해석하지 못했습니다.", ppiAxis._raw);
    if (elements.ppiNarrative) elements.ppiNarrative.replaceChildren();
    return;
  }

  if (!elements.ppiResults) return;
  elements.ppiResults.replaceChildren();
  const entries = Object.entries(ppiAxis?.ppi_results || {});
  if (!entries.length) {
    elements.ppiResults.append(createTextElement("p", "empty-state", "PPI 평가 항목이 없습니다."));
  }

  entries.forEach(([key, value]) => {
    const row = document.createElement("div");
    row.className = "ppi-row";
    const body = document.createElement("div");
    body.append(createTextElement("strong", "", PPI_LABELS[key] || key));
    const reason = String(value?.reason || "").trim();
    if (reason) body.append(createTextElement("p", "", reason));
    row.append(body);
    row.append(createTextElement("span", "ppi-rating", String(value?.rating ?? "-")));
    elements.ppiResults.append(row);
  });

  renderNarrativeFeedback(ppiAxis?.narrative_feedback);
}

function renderNarrativeFeedback(narrative) {
  if (!elements.ppiNarrative) return;
  elements.ppiNarrative.replaceChildren();
  const sections = [
    { key: "strengths", title: "잘한 점" },
    { key: "areas_to_improve", title: "보완하면 좋을 점" },
    { key: "must_fix", title: "다음엔 반드시 고칠 점" },
  ];

  sections.forEach(({ key, title }) => {
    const items = Array.isArray(narrative?.[key]) ? narrative[key] : [];
    if (!items.length) return;
    const section = document.createElement("section");
    section.className = `narrative-block ${key}`;
    section.append(createTextElement("h4", "", title));
    const list = document.createElement("ul");
    items.forEach((text) => list.append(createTextElement("li", "", text)));
    section.append(list);
    elements.ppiNarrative.append(section);
  });
}

function renderRecommendation() {
  if (!elements.recommendationContent) return;
  elements.recommendationContent.replaceChildren();
  const recommendation = state.report?.recommendation;
  const weakness = state.report?.weakness_analysis;
  if (!recommendation) {
    elements.recommendationContent.append(createTextElement("p", "empty-state", "추천 정보가 없습니다."));
    elements.nextCaseBtn.hidden = true;
    return;
  }

  const counts = weakness?.category_counts || {};
  const countsLine = Object.entries(counts)
    .filter(([, count]) => Number(count) > 0)
    .map(([category, count]) => `${category} X ${count}개`)
    .join(" · ") || "없음";
  elements.recommendationContent.append(createTextElement("p", "recommendation-kicker", `부족했던 영역: ${countsLine}`));
  if (recommendation.message) {
    elements.recommendationContent.append(createTextElement("p", "recommendation-message", recommendation.message));
  }
  if (recommendation.recommended_case_id) {
    const next = [
      recommendation.recommended_case_title,
      recommendation.recommended_emotion,
      recommendation.recommended_difficulty,
    ].filter(Boolean).join(" · ");
    elements.recommendationContent.append(createTextElement("p", "recommendation-next", `다음 추천: ${next}`));
  }
  if (recommendation.case_pool_note) {
    elements.recommendationContent.append(createTextElement("p", "recommendation-note", recommendation.case_pool_note));
  }

  const recommendedCase = state.nextCase?.case;
  elements.nextCaseBtn.hidden = !recommendedCase;
  if (recommendedCase) {
    const caseTitle = recommendation.recommended_case_title || recommendedCase.title || "추천";
    setText(elements.nextCaseBtn, `${caseTitle} 케이스 시작`);
  }
}

function renderEvaluationReport() {
  const checklistAxis = state.report?.checklist_axis || {};
  const ppiAxis = state.report?.ppi_axis || {};
  const results = checklistResults(checklistAxis);
  const passed = results.filter((item) => item.result === "O").length;
  const criticalFails = Array.isArray(checklistAxis.critical_fails_triggered)
    ? checklistAxis.critical_fails_triggered
    : [];
  const ppi = ppiAverage(ppiAxis);

  setText(elements.reportCoverage, results.length ? `${passed}/${results.length}` : "-");
  setText(elements.reportMissed, String(criticalFails.length));
  setText(elements.reportReasoning, ppi ? `${ppi}/5` : "-");
  setText(
    elements.reportSavedNote,
    state.report?.report_id ? `평가 저장 ID: ${state.report.report_id.slice(0, 8)}...` : "",
  );

  renderCriticalFails(checklistAxis);
  renderEvaluationRows(
    elements.coreChecklist,
    checklistAxis.core_results || {},
    "체크리스트 평가 항목이 없습니다.",
  );
  renderEmotionResponse(checklistAxis.emotion_response);
  renderPpiRows(ppiAxis);
  renderRecommendation();
}

async function finishEncounter() {
  if (!state.session?.can_complete || state.pending || state.completed) return;
  state.pending = true;
  setText(elements.coachLine, "대화를 평가하는 중입니다. 체크리스트와 PPI 평가를 생성하고 있어요.");
  renderStatus();
  try {
    const payload = await api(`/api/sessions/${encodeURIComponent(state.sessionId)}/complete`, {
      method: "POST",
      body: JSON.stringify({ assessment: {} }),
    });
    state.completed = true;
    state.report = payload.report;
    state.nextCase = payload.next_case;
    renderEvaluationReport();
    toggleRecord(false);
    elements.reportPanel.parentElement.scrollTo({ top: 0, behavior: "auto" });
    elements.reportPanel.hidden = false;
    elements.reportPanel.focus({ preventScroll: true });
    setText(elements.patientBubble, "대화가 종료됐습니다. 교육용 리포트를 확인해 주세요.");
    setPatientEmotionSprite(null);
    setText(elements.coachLine, "체크리스트, 감정 대응, PPI 평가표를 확인해 주세요.");
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
  state.currentCase = null;
  renderPatientName();
  renderPatientSpriteProfile();
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
  const recommendedCase = state.nextCase?.case || null;
  const nextDifficulty = (state.nextCase?.constraints || [])
    .find((item) => item.startsWith("next_difficulty="))
    ?.split("=")[1];
  const nextEmotion = (state.nextCase?.constraints || [])
    .find((item) => item.startsWith("next_initial_emotion="))
    ?.split("=")[1];
  resetEncounter();
  if (nextDifficulty) state.selectedDifficulty = nextDifficulty;
  await startEncounter({
    caseItem: recommendedCase,
    initialEmotion: nextEmotion,
  });
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
renderPatientSpriteProfile();
renderChart();
renderStatus();
loadCases();
