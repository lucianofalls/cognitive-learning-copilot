// Vanilla JS client for the Local English Meeting Copilot.
// No build step, no external CDN dependency, no analytics. Talks only to
// this same-origin FastAPI backend over fetch() and a single WebSocket.

const ACTION_ENDPOINTS = {
  "explain-context": "/api/actions/explain-context",
  "suggest-answer": "/api/actions/suggest-answer",
  "suggest-question": "/api/actions/suggest-question",
  "disagree-politely": "/api/actions/disagree-politely",
  "request-clarification": "/api/actions/request-clarification",
  "confirm-understanding": "/api/actions/confirm-understanding",
  "explain-english": "/api/actions/explain-english",
};

const ACTION_LABELS = {
  "explain-context": "Contexto",
  "suggest-answer": "Responder",
  "suggest-question": "Perguntar",
  "disagree-politely": "Discordar",
  "request-clarification": "Clarificar",
  "confirm-understanding": "Confirmar",
  "explain-english": "Aprender",
};

const SHORTCUT_TO_ACTION = {
  "1": "explain-context",
  "2": "suggest-answer",
  "3": "suggest-question",
  "4": "disagree-politely",
  "5": "request-clarification",
  "6": "confirm-understanding",
  "7": "explain-english",
};

// A pause marker looks like "[pausa: 4.2s]" (see translation_manager.py's
// PAUSE_MARKER_THRESHOLD_SECONDS / prompts/translate.md), but the model
// doesn't always follow the exact format -- this is deliberately loose.
const PAUSE_MARKER_RE = /\[?\s*pausa:?\s*([\d.,]+)\s*s\s*\]?/gi;

let sessionStartedAt = null;
let timerInterval = null;
let ws = null;

// action-card-id -> the raw MeetingCoachResponse, for copy/feedback controls.
const cardResponses = new Map();
let nextCardId = 1;

const $ = (id) => document.getElementById(id);

// Maps every SessionStatus literal (models.py) to a status-dot color --
// "ready"/"running" read as ok, "starting"/"paused" as a transient warn,
// "error"/"unavailable" as error, everything else (the various "not
// doing anything right now" states: unknown/disabled/stopped) as neutral.
// Gile's Effort Model names, in pt-BR for UI copy (this project's
// convention: all UI-facing text is pt-BR, identifiers stay in
// English). Duplicated in language_coach.js rather than shared: same
// "each file self-contained" convention as lc$ duplicating $ there
// instead of reusing this one.
const PROCESSING_LOAD_EFFORT_LABELS_PT = {
  listening_analysis: "Escuta/Compreensão",
  memory: "Memória",
  production: "Produção",
  coordination: "Coordenação",
};
const PROCESSING_LOAD_CONFIDENCE_LABELS_PT = { low: "baixa", medium: "média", high: "alta" };

function fillProcessingLoadBadge(card, processingLoad) {
  const el = card.querySelector(".processing-load");
  if (!el) return;
  if (processingLoad && processingLoad.dominant_effort) {
    const effort = PROCESSING_LOAD_EFFORT_LABELS_PT[processingLoad.dominant_effort] || processingLoad.dominant_effort;
    const confidence = PROCESSING_LOAD_CONFIDENCE_LABELS_PT[processingLoad.confidence] || processingLoad.confidence;
    el.textContent = `🎯 Sinal detectado agora: ${effort} (confiança ${confidence})`;
    el.classList.remove("hidden");
  } else {
    el.classList.add("hidden");
  }
}

const STATUS_TONE = {
  ready: "ok",
  running: "ok",
  starting: "warn",
  paused: "warn",
  error: "error",
  unavailable: "error",
};

function setStatus(field, value) {
  const el = $(`status-${field}`);
  if (el) el.textContent = value;
  const dot = el?.closest(".status-item")?.querySelector(".status-dot");
  if (dot) dot.dataset.tone = STATUS_TONE[value] || "neutral";
}

// Topbar health warning -- 2026-08-13 redesign: replaces four permanent
// status pills (mic/whisper/whisper-pt/ollama) that were always visible
// regardless of whether anything was actually wrong ("é muita
// infraestrutura aparecendo... isso é observabilidade técnica, não
// experiência do usuário", direct feedback). The four raw signals still
// exist (moved into the ••• overflow menu via setStatus above) -- this
// only surfaces a short human message in the topbar when whisper,
// whisper_pt (if enabled), or ollama is actually in an "error" tone.
// Anything else (starting/paused/unknown/disabled/stopped -- all normal
// before/between sessions) stays silent.
const HEALTH_WARNING_MESSAGES = {
  whisper: "Whisper indisponível",
  "whisper-pt": "Whisper PT indisponível",
  ollama: "Ollama indisponível",
};

function updateHealthWarning(status) {
  const el = $("health-warning");
  if (!el) return;
  const broken = Object.entries(HEALTH_WARNING_MESSAGES).filter(([field]) => {
    const value = field === "whisper-pt" ? status.whisper_pt : status[field];
    return STATUS_TONE[value] === "error";
  });
  if (broken.length === 0) {
    el.classList.add("hidden");
    return;
  }
  el.textContent = `⚠ ${broken.map(([field]) => HEALTH_WARNING_MESSAGES[field]).join(" · ")}`;
  el.classList.remove("hidden");
}

// -- conversation timeline: English heard + PT-BR translation, paired --
// one entry per transcript segment instead of two separate scrolling
// panels (see the CSS comment above .conversation-entry). The backend
// events stay exactly as independent as before -- transcript.segment and
// translation.update are still two separate WebSocket messages, arriving
// at different times; this just groups them visually. Pairing strategy:
// each new transcript.segment opens an entry with its PT line pending;
// each translation.update fills the OLDEST still-pending entry. Not a
// guaranteed-exact 1:1 (TranslationManager can occasionally batch
// pending text across segments -- see session_service.py's
// _refresh_translation docstring), but matches the system's actual
// granularity closely enough, and best-effort here is consistent with
// how translation already worked before this redesign.
const conversationEntries = []; // { ptEl, filled }

function buildExplainAndPronounceButtons(sentence) {
  const fragment = document.createDocumentFragment();
  if (!sentence || !sentence.trim()) return fragment;

  // The Language Coach "?" affordance (docs/LANGUAGE_COACH_ARCHITECTURE.md,
  // section 8) goes on the English line, not the PT-BR translation: the
  // backend's source_sentence_en field and its prompt both need the real
  // English text, and there's no reliable 1:1 mapping from a translation
  // chunk back to it. Wired via delegation in language_coach.js.
  const explainBtn = document.createElement("button");
  explainBtn.type = "button";
  explainBtn.className = "explain-sentence-btn icon-btn";
  explainBtn.textContent = "?";
  explainBtn.title = "Perguntar ao Language Coach sobre este trecho";
  explainBtn.dataset.sentence = sentence.trim();
  fragment.appendChild(explainBtn);

  // Same reasoning (needs the exact English source text): English
  // spelling routinely doesn't predict pronunciation, so a quick "how
  // does this actually sound" affordance sits right next to "?". Wired
  // via the same delegation in language_coach.js.
  const pronounceBtn = document.createElement("button");
  pronounceBtn.type = "button";
  pronounceBtn.className = "pronounce-sentence-btn icon-btn";
  pronounceBtn.textContent = "🗣️";
  pronounceBtn.title = "Ver como isso soa de verdade (pronúncia)";
  pronounceBtn.dataset.sentence = sentence.trim();
  fragment.appendChild(pronounceBtn);

  return fragment;
}

function renderPtInto(ptEl, textPt) {
  ptEl.textContent = "";
  ptEl.classList.remove("conversation-entry-pt-pending");
  // Pause markers become their own visual separator, never inline text
  // in the middle of a sentence.
  const parts = textPt.split(PAUSE_MARKER_RE);
  for (let i = 0; i < parts.length; i++) {
    // String.split with a capturing global regex alternates
    // [text, capturedSeconds, text, capturedSeconds, ...].
    if (i % 2 === 1) {
      const sep = document.createElement("span");
      sep.className = "pause-marker";
      sep.textContent = ` · pausa de ${parts[i]}s · `;
      ptEl.appendChild(sep);
    } else if (parts[i] && parts[i].trim()) {
      const span = document.createElement("span");
      span.textContent = parts[i].trim();
      ptEl.appendChild(span);
    }
  }
}

function addConversationEntry(enText) {
  const container = $("transcript");
  container.querySelector(".feed-empty-hint")?.remove();

  // "AGORA" is a one-shot state, not ambient -- the previous current
  // entry settles back to normal the instant a new one arrives (see the
  // CSS comment above .conversation-entry-current).
  container.querySelector(".conversation-entry-current")?.classList.remove("conversation-entry-current");

  const entry = document.createElement("div");
  entry.className = "conversation-entry conversation-entry-current";

  const time = document.createElement("span");
  time.className = "conversation-entry-time";
  time.textContent = new Date().toLocaleTimeString("pt-BR", { hour12: false });

  const enLine = document.createElement("p");
  enLine.className = "conversation-entry-en";
  const enSpan = document.createElement("span");
  enSpan.textContent = enText;
  enLine.appendChild(enSpan);
  enLine.appendChild(buildExplainAndPronounceButtons(enText));

  const ptLine = document.createElement("p");
  ptLine.className = "conversation-entry-pt conversation-entry-pt-pending";
  ptLine.textContent = "traduzindo...";

  entry.append(time, enLine, ptLine);
  container.appendChild(entry);
  container.scrollTop = container.scrollHeight;

  conversationEntries.push({ ptEl: ptLine, filled: false });
}

function fillNextConversationTranslation(textPt) {
  const pending = conversationEntries.find((entry) => !entry.filled);
  if (!pending) return; // nothing waiting right now -- drop silently, same best-effort spirit as before
  pending.filled = true;
  renderPtInto(pending.ptEl, textPt);
}

// Reverse pipeline (Portuguese speech -> English) -- continuous, no
// button: appends each new segment as it arrives over the WebSocket.
// #pt-live-heard stays in the DOM (tucked in a <details>, see index.html)
// for anyone who wants to confirm what was actually heard; #pt-live-translated
// is the one shown at rest, since the English is what's actually
// actionable ("fold Falar em Português into Quero dizer", 2026-08-13
// redesign -- no separate module needed for it, just a compact section
// in the Assistant column).
function appendPtLiveText(elementId, text) {
  if (!text) return;
  const el = $(elementId);
  el.querySelector(".feed-empty-hint")?.remove();
  const p = document.createElement("p");
  p.textContent = text;
  el.appendChild(p);
  el.scrollTop = el.scrollHeight;
}

// Same two affordances as the main conversation timeline's English
// lines: "🗣️" (pronunciation guide) and "🔊" (listen, reuses
// language_coach.js's speakText()) -- this text is already English (the
// whole point of this pipeline), so there's no back-mapping problem the
// main transcript's translation had.
function appendPtLiveTranslatedText(text) {
  if (!text) return;
  const el = $("pt-live-translated");
  el.querySelector(".feed-empty-hint")?.remove();
  const wrapper = document.createElement("p");
  wrapper.className = "pt-live-translated-line";

  const span = document.createElement("span");
  span.textContent = text;
  wrapper.appendChild(span);

  const pronounceBtn = document.createElement("button");
  pronounceBtn.type = "button";
  pronounceBtn.className = "pronounce-sentence-btn icon-btn";
  pronounceBtn.title = "Ver como isso soa de verdade (pronúncia)";
  pronounceBtn.textContent = "🗣️";
  pronounceBtn.dataset.sentence = text;
  wrapper.appendChild(pronounceBtn);

  const speakBtn = document.createElement("button");
  speakBtn.type = "button";
  speakBtn.className = "speak-en-inline-btn icon-btn";
  speakBtn.title = "Ouvir em inglês";
  speakBtn.textContent = "🔊";
  speakBtn.dataset.speakText = text;
  wrapper.appendChild(speakBtn);

  el.appendChild(wrapper);
  el.scrollTop = el.scrollHeight;
}

function startTimer() {
  sessionStartedAt = Date.now();
  clearInterval(timerInterval);
  timerInterval = setInterval(() => {
    const elapsed = Math.floor((Date.now() - sessionStartedAt) / 1000);
    const h = String(Math.floor(elapsed / 3600)).padStart(2, "0");
    const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, "0");
    const s = String(elapsed % 60).padStart(2, "0");
    $("status-timer").textContent = `${h}:${m}:${s}`;
  }, 1000);
}

function stopTimer() {
  clearInterval(timerInterval);
  $("status-timer").textContent = "00:00:00";
}

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${protocol}://${window.location.host}/ws/events`);

  ws.addEventListener("message", (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    handleServerEvent(message.type, message.payload);
  });

  ws.addEventListener("close", () => {
    setTimeout(connectWebSocket, 2000);
  });
}

function handleServerEvent(type, payload) {
  if (type === "transcript.segment") {
    addConversationEntry(payload.text);
  } else if (type === "session.status") {
    setStatus("mic", payload.microphone || "unknown");
    setStatus("whisper", payload.whisper || "stopped");
    setStatus("whisper-pt", payload.whisper_pt || "disabled");
    setStatus("ollama", payload.ollama || "unknown");
    updateHealthWarning(payload);
    const running = payload.whisper === "running" || payload.whisper === "starting";
    $("start-btn").classList.toggle("hidden", running);
    $("stop-btn").classList.toggle("hidden", !running);
    $("listening-indicator").classList.toggle("hidden", !running);
    if (running && !timerInterval) startTimer();
    if (!running) stopTimer();
    $("learning-badge").classList.toggle("hidden", !payload.learning_persisted);
    // Changing the capture device mid-session is a no-op on the backend
    // (the whisper-stream process already launched with the old one) --
    // see api/session.py's put_audio_device. Disable it here too so
    // that's obvious instead of silently doing nothing.
    $("audio-device-select").disabled = running;
  } else if (type === "translation.update") {
    fillNextConversationTranslation(payload.text_pt);
  } else if (type === "transcript_pt.segment") {
    appendPtLiveText("pt-live-heard", payload.text);
  } else if (type === "translation_en.update") {
    appendPtLiveTranslatedText(payload.text_en);
  } else if (type === "possible_direct_question") {
    const badge = $("question-badge");
    badge.classList.remove("hidden");
    badge.textContent = `Possível pergunta para você: "${payload.matched_phrase}"`;
    // One-time pulse, not a loop/blink -- draws the eye once, then stays
    // still and readable. See web/motion.js's module docstring.
    animatePulse(badge);
    setTimeout(() => badge.classList.add("hidden"), 8000);
  } else if (type === "noticing.flag") {
    // Proactive half of the Noticing Hypothesis (LANGUAGE_COACH_PEDAGOGY.md
    // theory #2) -- flags a real idiom/phrasal verb just heard instead of
    // waiting for a transcript-line "?" click. Clicking opens the same
    // explanation flow (language_coach.js, now retrieval-practice-first);
    // left alone, it self-dismisses -- "optional, dismissible," never a
    // forced interruption.
    const badge = $("noticing-badge");
    badge.textContent = `💡 Notou "${payload.matched_phrase}"? Clique para entender`;
    badge.dataset.sentence = payload.sentence || "";
    badge.classList.remove("hidden");
    animatePulse(badge);
    setTimeout(() => badge.classList.add("hidden"), 10000);
  }
  // "coach.response" and "summary.update" are broadcast but not rendered
  // directly here: coach responses arrive as the runAction() fetch result
  // (each card owns its own request/response), and the summary only
  // feeds the persisted markdown log for now -- no summary panel yet.
}

// -- response feed (one independent card per action click) ---------------

function createResponseCard(action) {
  const feed = $("response-feed");
  feed.querySelector(".feed-empty-hint")?.remove();

  const template = $("response-card-template");
  const fragment = template.content.cloneNode(true);
  const card = fragment.querySelector(".response-card");

  const cardId = String(nextCardId++);
  card.dataset.cardId = cardId;
  card.querySelector(".response-card-action").textContent = ACTION_LABELS[action] || action;
  card.querySelector(".response-card-time").textContent = new Date().toLocaleTimeString("pt-BR", {
    hour12: false,
  });

  // Newest on top, so a fast follow-up click doesn't push the card the
  // user is waiting on below ones that already finished.
  feed.insertBefore(card, feed.firstChild);
  animateCardIn(card);
  return card;
}

function renderCardContent(card, response) {
  cardResponses.set(card.dataset.cardId, response);

  const contextEl = card.querySelector(".context-pt");
  contextEl.textContent = response.context_pt || "";
  contextEl.classList.toggle("hidden", !response.context_pt);
  card.querySelector(".suggested-answer").textContent = response.suggested_answer_en || "";
  card.querySelector(".simple-opening").textContent = response.simple_opening_en
    ? `Abertura simples: ${response.simple_opening_en}`
    : "";
  card.querySelector(".suggested-question").textContent = response.suggested_question_en || "";

  // Primary CTA: "▶ Ouvir e repetir", not "Copiar" -- 2026-08-13, direct
  // feedback: for someone using this to build fluency, hearing (and
  // repeating) the correct pronunciation matters more than the clipboard.
  // English audio for whichever English suggestion this card has.
  const speakBtn = card.querySelector(".card-speak-btn");
  const speakText = response.suggested_answer_en || response.suggested_question_en || "";
  if (speakText) {
    speakBtn.classList.remove("hidden");
    speakBtn.dataset.speakText = speakText;
  } else {
    speakBtn.classList.add("hidden");
  }

  const grammarEl = card.querySelector(".grammar-note");
  if (response.grammar_note_pt) {
    grammarEl.textContent = response.grammar_note_pt;
    grammarEl.classList.remove("hidden");
  } else {
    grammarEl.classList.add("hidden");
  }

  const vocabDetails = card.querySelector(".key-vocab-details");
  const vocabList = card.querySelector(".key-vocabulary");
  vocabList.innerHTML = "";
  if (response.key_vocabulary && response.key_vocabulary.length) {
    response.key_vocabulary.forEach((term) => {
      const li = document.createElement("li");
      li.textContent = term;
      vocabList.appendChild(li);
    });
    vocabDetails.classList.remove("hidden");
  } else {
    vocabDetails.classList.add("hidden");
  }

  const evidenceDetails = card.querySelector(".evidence-details");
  const evidenceList = card.querySelector(".evidence-list");
  evidenceList.innerHTML = "";
  if (response.evidence_from_transcript && response.evidence_from_transcript.length) {
    response.evidence_from_transcript.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      evidenceList.appendChild(li);
    });
    evidenceDetails.classList.remove("hidden");
  } else {
    evidenceDetails.classList.add("hidden");
  }

  // Confidence moves into "Por que esta resposta?" (progressive
  // disclosure) -- no longer shown at rest. 2026-08-13, direct feedback:
  // "HIGH" alone isn't actionable, it just becomes a second thing to
  // second-guess ("high significa que posso falar? medium?"). The one
  // case that IS actionable -- genuinely insufficient context -- gets
  // its own immediate, visible warning instead.
  const confidenceEl = card.querySelector(".confidence");
  confidenceEl.textContent = `Confiança: ${response.confidence}`;
  confidenceEl.className = `confidence ${response.confidence}`;

  const warningEl = card.querySelector(".insufficient-context-warning");
  warningEl.classList.toggle("hidden", !response.insufficient_context);

  fillProcessingLoadBadge(card, response.processing_load);
}

function setCardState(card, state, statusText) {
  card.dataset.state = state;
  card.querySelector(".response-card-status").textContent = statusText;
  card.querySelector(".response-card-spinner").classList.toggle("hidden", state !== "loading");
  card.querySelector(".response-card-content").classList.toggle("hidden", state !== "ready");
  const errorEl = card.querySelector(".response-card-error");
  errorEl.classList.toggle("hidden", state !== "error");
}

async function runAction(action, ideaPt = "") {
  const endpoint = ACTION_ENDPOINTS[action];
  if (!endpoint) return;

  const card = createResponseCard(action);

  // fetch() has no timeout of its own; without this, a lost response
  // (network hiccup, tab sleep) would leave the card stuck loading
  // forever. The backend's own Ollama timeout is 90s, so 95s always
  // gives it a chance to reply first.
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 95000);
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idea_pt: ideaPt }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      card.querySelector(".response-card-error").textContent =
        body.detail || `Erro (${res.status}) ao executar a ação.`;
      setCardState(card, "error", "erro");
      return;
    }
    const data = await res.json();
    renderCardContent(card, data);
    setCardState(card, "ready", "pronto");
  } catch (err) {
    card.querySelector(".response-card-error").textContent =
      err.name === "AbortError"
        ? "O modelo local demorou demais para responder (timeout)."
        : "Não foi possível contatar o backend local.";
    setCardState(card, "error", "erro");
  } finally {
    clearTimeout(timeoutId);
  }
}

// -- "Quero dizer..." box: auto-detects EN vs PT-BR, routes accordingly --
// PT input keeps the original, unchanged behavior (LLM-coached "ready to
// say" English phrase, via the existing suggest-answer response card,
// now always visible in the Assistant column -- no tab to switch to).
// EN input: a literal, fast NMT translation to PT-BR (context/opus_mt.py),
// shown inline with a "🔊 Ouvir" button in the matching language.
async function runIdeaBox(idea) {
  $("idea-translation-result").classList.add("hidden");

  let language = "pt";
  try {
    const res = await fetch("/api/translate/detect-language", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: idea }),
    });
    if (res.ok) {
      language = (await res.json()).language;
    }
  } catch {
    // Detection failing shouldn't block the existing PT flow.
  }

  if (language === "en") {
    await runIdeaEnToPt(idea);
  } else {
    runAction("suggest-answer", idea);
  }
}

async function runIdeaEnToPt(text) {
  const resultEl = $("idea-translation-result");
  const textEl = resultEl.querySelector(".idea-translation-text");
  const speakBtn = $("idea-translation-speak-btn");
  textEl.textContent = "Traduzindo...";
  resultEl.classList.remove("hidden");
  try {
    const res = await fetch("/api/translate/en-to-pt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      textEl.textContent = "Não foi possível traduzir.";
      return;
    }
    const data = await res.json();
    textEl.textContent = data.translated_pt;
    speakBtn.dataset.speakText = data.translated_pt;
    speakBtn.dataset.lang = "pt";
  } catch {
    textEl.textContent = "Não foi possível contatar o backend local.";
  }
}

function copyCardSuggestion(card) {
  const response = cardResponses.get(card.dataset.cardId);
  if (!response) return;
  const text =
    response.suggested_answer_en || response.suggested_question_en || response.simple_opening_en || "";
  if (text) navigator.clipboard.writeText(text);
}

function submitCardFeedback(card, rating) {
  const response = cardResponses.get(card.dataset.cardId);
  if (!response) return;
  const sentence = response.suggested_answer_en || response.suggested_question_en || "";
  fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action: response.action,
      rating,
      sentence_length: sentence.length,
    }),
  });
}

function wireStaticControls() {
  document.querySelectorAll(".action-btn").forEach((btn) => {
    btn.addEventListener("click", () => runAction(btn.dataset.action));
  });

  // Response cards are created dynamically, so their internal buttons
  // (copy, speak, feedback) are wired via delegation on the feed
  // container rather than per-card listeners.
  $("response-feed").addEventListener("click", (event) => {
    const card = event.target.closest(".response-card");
    if (!card) return;
    if (event.target.closest(".copy-btn")) {
      copyCardSuggestion(card);
    } else if (event.target.closest(".card-speak-btn")) {
      const btn = event.target.closest(".card-speak-btn");
      speakText(btn.dataset.speakText || "", "en");
    } else if (event.target.matches(".feedback-buttons .btn-tiny")) {
      submitCardFeedback(card, event.target.dataset.rating);
    }
  });

  $("idea-submit").addEventListener("click", async () => {
    const idea = $("idea-input").value.trim();
    if (!idea) return;
    $("idea-input").value = "";
    await runIdeaBox(idea);
  });
  $("idea-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") $("idea-submit").click();
  });
  $("idea-translation-speak-btn").addEventListener("click", () => {
    const btn = $("idea-translation-speak-btn");
    speakText(btn.dataset.speakText || "", btn.dataset.lang || "pt");
  });

  $("start-btn").addEventListener("click", async () => {
    try {
      const res = await fetch("/api/config");
      const config = await res.json();
      $("learning-consent-note").classList.toggle(
        "hidden",
        !config?.privacy?.persist_learning_notes
      );
    } catch {
      // If the config fetch fails, fall back to showing no persistence
      // note rather than blocking the consent dialog entirely.
    }
    $("consent-overlay").classList.remove("hidden");
  });
  $("consent-cancel").addEventListener("click", () => {
    $("consent-overlay").classList.add("hidden");
  });
  $("consent-confirm").addEventListener("click", async () => {
    $("consent-overlay").classList.add("hidden");
    await fetch("/api/session/start", { method: "POST" });
  });

  $("stop-btn").addEventListener("click", async () => {
    await fetch("/api/session/stop", { method: "POST" });
  });

  $("delete-btn").addEventListener("click", () => {
    $("delete-overlay").classList.remove("hidden");
  });
  $("delete-cancel").addEventListener("click", () => {
    $("delete-overlay").classList.add("hidden");
  });
  $("delete-confirm").addEventListener("click", async () => {
    $("delete-overlay").classList.add("hidden");
    await fetch("/api/session/delete", { method: "POST" });
    $("transcript").innerHTML = '<p class="feed-empty-hint">Nada ouvido ainda.</p>';
    conversationEntries.length = 0;
    const feed = $("response-feed");
    feed.innerHTML = '<p class="feed-empty-hint">Nenhuma ação executada ainda. Use a barra abaixo.</p>';
    cardResponses.clear();
    $("learning-badge").classList.add("hidden");
  });

  $("prepare-meeting-btn").addEventListener("click", () => {
    $("prepare-meeting-modal").classList.remove("hidden");
  });
  $("meeting-cancel").addEventListener("click", () => {
    $("prepare-meeting-modal").classList.add("hidden");
  });
  $("meeting-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    const toList = (value) =>
      (value || "")
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
    const meeting = {
      title: form.get("title") || "",
      objective: form.get("objective") || "",
      agenda: toList(form.get("agenda")),
      expected_topics: toList(form.get("expected_topics")),
      known_systems: toList(form.get("known_systems")),
      known_acronyms: toList(form.get("known_acronyms")),
      desired_outcome: form.get("desired_outcome") || "",
      notes: form.get("notes") || "",
    };
    await fetch("/api/config/meeting", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(meeting),
    });
    $("prepare-meeting-modal").classList.add("hidden");
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      document.querySelectorAll(".overlay:not(.hidden)").forEach((el) => el.classList.add("hidden"));
      return;
    }
    if (!(event.metaKey || event.ctrlKey)) return;
    const action = SHORTCUT_TO_ACTION[event.key];
    if (action) {
      event.preventDefault();
      runAction(action);
    }
  });

  $("audio-device-select").addEventListener("change", async (event) => {
    const value = event.target.value;
    if (value === "") return; // "(padrão do sistema)" -- nothing to send
    const res = await fetch("/api/config/audio-device", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ capture_device: Number(value) }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      alert(body.detail || "Não foi possível trocar o dispositivo de áudio.");
    }
  });

  // "Falar em Português" pause/resume -- the one background process a UI
  // action can meaningfully save real CPU on (a second continuous
  // whisper-stream process, session_service.py). No longer tied to a
  // generic panel-minimize gesture (that whole mechanism went away with
  // the sidebar/tabs redesign) -- its own small, explicit button instead.
  $("pt-live-pause-btn").addEventListener("click", async () => {
    const btn = $("pt-live-pause-btn");
    const pausing = btn.textContent.trim() === "Pausar";
    const endpoint = pausing ? "/api/session/pause-pt-stream" : "/api/session/resume-pt-stream";
    try {
      await fetch(endpoint, { method: "POST" });
      btn.textContent = pausing ? "Retomar" : "Pausar";
    } catch {
      // Best-effort -- leave the button label as-is so a failed call reads
      // as "nothing changed" rather than lying about the new state.
    }
  });
}

async function loadAudioDevices() {
  const select = $("audio-device-select");
  try {
    const res = await fetch("/api/audio/devices");
    const data = await res.json();
    (data.devices || []).forEach((device) => {
      const option = document.createElement("option");
      option.value = String(device.index);
      option.textContent = `${device.index}: ${device.name}`;
      if (device.index === data.current) option.selected = true;
      select.appendChild(option);
    });
  } catch {
    // Best-effort: leave just the "(padrão do sistema)" option if the
    // backend couldn't enumerate devices (e.g. whisper-stream missing).
  }
}

wireStaticControls();
connectWebSocket();
loadAudioDevices();
