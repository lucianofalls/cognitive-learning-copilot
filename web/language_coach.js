// Language Coach (Phase 1: text Q&A + scenario practice).
// See docs/LANGUAGE_COACH_ARCHITECTURE.md. Loaded after app.js and reuses
// its card-feed visual language, but keeps its own feed/template because
// LanguageCoachExplanation/ScenarioPractice don't share MeetingCoachResponse's
// shape -- see src/meeting_copilot/llm/schemas.py.
//
// 2026-08-13: moved from an always-visible panel/tab into an on-demand
// drawer (web/ui.js's openLanguageCoachDrawer/closeLanguageCoachDrawer) --
// "fica mais poderoso justamente ficando menos visível" (direct feedback).
// Every entry point below opens the drawer itself so the result is never
// created in a place the user isn't looking at.

const LC_KIND_LABELS = {
  explanation: "Explicação",
  scenario: "Cenário",
  pronunciation_guide: "Pronúncia",
};

let lcNextCardId = 1;

const lc$ = (id) => document.getElementById(id);

function createLanguageCoachCard(kind) {
  if (typeof openLanguageCoachDrawer === "function") openLanguageCoachDrawer();

  const feed = lc$("language-coach-feed");
  feed.querySelector(".feed-empty-hint")?.remove();

  const template = lc$("language-coach-card-template");
  const fragment = template.content.cloneNode(true);
  const card = fragment.querySelector(".lc-card");

  card.dataset.cardId = String(lcNextCardId++);
  card.dataset.kind = kind;
  card.querySelector(".lc-card-kind").textContent = LC_KIND_LABELS[kind] || kind;
  card.querySelector(".response-card-time").textContent = new Date().toLocaleTimeString("pt-BR", {
    hour12: false,
  });

  // Newest on top, same reasoning as app.js's createResponseCard: a fast
  // follow-up click shouldn't push the card being waited on out of view.
  feed.insertBefore(card, feed.firstChild);
  animateCardIn(card);
  return card;
}

function setLanguageCoachCardState(card, state, statusText) {
  card.dataset.state = state;
  card.querySelector(".response-card-status").textContent = statusText;
  card.querySelector(".response-card-spinner").classList.toggle("hidden", state !== "loading");
  card.querySelector(".response-card-content").classList.toggle("hidden", state !== "ready");
  card.querySelector(".response-card-error").classList.toggle("hidden", state !== "error");
  // "retrieval" -- the retrieval-practice-first prompt state, see
  // showRetrievalPrompt below. Not every card has this element (only the
  // language-coach-card-template does), hence the guard.
  const retrievalEl = card.querySelector(".lc-retrieval-prompt");
  if (retrievalEl) retrievalEl.classList.toggle("hidden", state !== "retrieval");
}

function fillOptional(card, selector, text) {
  const el = card.querySelector(selector);
  if (text) {
    el.textContent = text;
    el.classList.remove("hidden");
  } else {
    el.classList.add("hidden");
  }
}

// LANGUAGE_COACH_PEDAGOGY.md theory #15 -- see app.js's identical pair for
// why this is duplicated here rather than shared (same convention as lc$).
const LC_PROCESSING_LOAD_EFFORT_LABELS_PT = {
  listening_analysis: "Escuta/Compreensão",
  memory: "Memória",
  production: "Produção",
  coordination: "Coordenação",
};
const LC_PROCESSING_LOAD_CONFIDENCE_LABELS_PT = { low: "baixa", medium: "média", high: "alta" };

function fillProcessingLoadBadge(card, processingLoad) {
  const el = card.querySelector(".processing-load");
  if (!el) return;
  if (processingLoad && processingLoad.dominant_effort) {
    const effort = LC_PROCESSING_LOAD_EFFORT_LABELS_PT[processingLoad.dominant_effort] || processingLoad.dominant_effort;
    const confidence =
      LC_PROCESSING_LOAD_CONFIDENCE_LABELS_PT[processingLoad.confidence] || processingLoad.confidence;
    el.textContent = `🎯 Sinal detectado agora: ${effort} (confiança ${confidence})`;
    el.classList.remove("hidden");
  } else {
    el.classList.add("hidden");
  }
}

function renderExplanationCard(card, data) {
  // Dual Coding pairing (pedagogy theory #13a/#14c) -- a genuinely
  // relevant local visual anchor next to the text, never a decorative
  // placeholder; see web/visual_anchors.js for why this is a curated
  // local lookup instead of an external image API.
  const anchorEl = card.querySelector(".lc-visual-anchor");
  if (anchorEl) {
    const anchor = findVisualAnchor(`${data.idiomatic_chunk || ""} ${data.source_sentence_en || ""}`);
    if (anchor) {
      anchorEl.textContent = anchor;
      anchorEl.classList.remove("hidden");
    } else {
      anchorEl.classList.add("hidden");
    }
  }
  fillOptional(card, ".lc-source-sentence", data.source_sentence_en);
  fillOptional(card, ".lc-explanation", data.explanation_pt);
  fillOptional(card, ".lc-native-reasoning", data.native_reasoning_pt);
  fillOptional(card, ".lc-idiomatic-chunk", data.idiomatic_chunk ? `💬 ${data.idiomatic_chunk}` : "");

  const examplesDetails = card.querySelector(".lc-examples-details");
  const examplesList = card.querySelector(".lc-examples");
  examplesList.innerHTML = "";
  if (data.alternative_examples && data.alternative_examples.length) {
    data.alternative_examples.forEach((example) => {
      const li = document.createElement("li");
      li.textContent = example;
      examplesList.appendChild(li);
    });
    examplesDetails.classList.remove("hidden");
  } else {
    examplesDetails.classList.add("hidden");
  }

  fillOptional(card, ".lc-follow-up", data.follow_up_question_pt);

  // "▶ Ouvir e repetir": speaks the chunk if there is one (the reusable
  // takeaway), falling back to the source sentence otherwise -- there's
  // always *something* worth hearing pronounced correctly.
  const speakBtn = card.querySelector(".lc-speak-btn");
  const speakText = data.idiomatic_chunk || data.source_sentence_en;
  if (speakText) {
    speakBtn.classList.remove("hidden");
    speakBtn.dataset.speakText = speakText;
  } else {
    speakBtn.classList.add("hidden");
  }

  // Feeds the practice loop: an explanation's idiomatic_chunk becomes the
  // target_pattern for a scenario (docs/LANGUAGE_COACH_ARCHITECTURE.md,
  // "The practice loop"). No chunk -> nothing to practice, hide the button.
  const scenarioBtn = card.querySelector(".lc-scenario-btn");
  if (data.idiomatic_chunk) {
    scenarioBtn.classList.remove("hidden");
    scenarioBtn.dataset.targetPattern = data.idiomatic_chunk;
  } else {
    scenarioBtn.classList.add("hidden");
  }

  // "mark for review": only offered alongside the same chunk the
  // scenario button targets -- nothing to schedule a review of otherwise.
  const addReviewBtn = card.querySelector(".lc-add-review-btn");
  if (data.idiomatic_chunk) {
    addReviewBtn.classList.remove("hidden");
    addReviewBtn.dataset.contentEn = data.idiomatic_chunk;
    addReviewBtn.dataset.contextSentence = data.source_sentence_en || "";
  } else {
    addReviewBtn.classList.add("hidden");
  }

  fillProcessingLoadBadge(card, data.processing_load);
}

function renderScenarioCard(card, data) {
  fillOptional(card, ".lc-scenario-pt", data.scenario_pt);
  fillOptional(card, ".lc-scenario-prompt", data.scenario_prompt_en ? `👉 ${data.scenario_prompt_en}` : "");

  const speakBtn = card.querySelector(".lc-speak-btn");
  if (data.scenario_prompt_en) {
    speakBtn.classList.remove("hidden");
    speakBtn.dataset.speakText = data.scenario_prompt_en;
  } else {
    speakBtn.classList.add("hidden");
  }

  // "Gravar sua tentativa" -- the practice loop's production step
  // (docs/LANGUAGE_COACH_ARCHITECTURE.md section 8, step 3): record
  // an attempt at the scenario's English line, check pronunciation
  // against it. Stored as a data attribute (not parsed back out of the
  // "👉 "-prefixed display text) so the raw target text stays exact.
  const recordBtn = card.querySelector(".lc-record-btn");
  if (data.scenario_prompt_en) {
    recordBtn.classList.remove("hidden");
    recordBtn.dataset.targetText = data.scenario_prompt_en;
  } else {
    recordBtn.classList.add("hidden");
  }

  fillProcessingLoadBadge(card, data.processing_load);
}

function renderPronunciationGuideCard(card, data) {
  fillOptional(card, ".lc-source-sentence", data.source_text_en);
  fillOptional(card, ".lc-phonetic-respelling", data.phonetic_respelling_pt ? `🗣️ ${data.phonetic_respelling_pt}` : "");
  fillOptional(card, ".lc-stress-note", data.stress_note_pt);

  const speakBtn = card.querySelector(".lc-speak-btn");
  if (data.source_text_en) {
    speakBtn.classList.remove("hidden");
    speakBtn.dataset.speakText = data.source_text_en;
  } else {
    speakBtn.classList.add("hidden");
  }
}

// -- TTS playback ("Ouvir") ----------------------------------------------

async function speakText(text, lang = "en") {
  try {
    const res = await fetch("/api/language-coach/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, lang }),
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.addEventListener("ended", () => URL.revokeObjectURL(url));
    await audio.play();
  } catch {
    // Best-effort affordance -- a failed playback shouldn't surface as an
    // error card; the text is already visible on screen either way.
  }
}

// -- spaced-repetition review queue ---------------------------------------

let lcReviewQueue = [];
let lcReviewCurrent = null;

async function refreshReviewQueue() {
  try {
    const res = await fetch("/api/language-coach/review-queue");
    if (!res.ok) return;
    const data = await res.json();
    lcReviewQueue = data.enabled ? data.items : [];
    const count = lcReviewQueue.length;
    // Two mirrors of the same count: the drawer's own "Revisar" button,
    // and the ••• overflow menu's Language Coach entry (visible without
    // opening the drawer first -- see web/ui.js).
    [lc$("language-coach-review-count"), lc$("coach-review-badge")].forEach((el) => {
      if (!el) return;
      if (count > 0) {
        el.textContent = String(count);
        el.classList.remove("hidden");
      } else {
        el.classList.add("hidden");
      }
    });
  } catch {
    // Review queue is a nice-to-have surfaced count -- silently skip a
    // failed refresh rather than showing an error for a background poll.
  }
}

function renderReviewCard() {
  const emptyEl = lc$("language-coach-review-empty");
  const cardEl = lc$("language-coach-review-card");
  lcReviewCurrent = lcReviewQueue[0] || null;

  if (!lcReviewCurrent) {
    emptyEl.classList.remove("hidden");
    cardEl.classList.add("hidden");
    return;
  }
  emptyEl.classList.add("hidden");
  cardEl.classList.remove("hidden");
  cardEl.querySelector(".lc-review-context").textContent =
    lcReviewCurrent.context_sentence || "(sem frase de contexto)";
  cardEl.querySelector(".lc-review-chunk").textContent = lcReviewCurrent.content_en;
  cardEl.querySelector(".lc-review-chunk").classList.add("hidden");
  lc$("language-coach-review-reveal").classList.remove("hidden");
  lc$("language-coach-review-actions").classList.add("hidden");
  lc$("language-coach-review-feedback")?.classList.add("hidden");

  // Same Dual Coding pairing as the explanation cards -- and, per
  // pedagogy theory #14d (ADHD/dopamine, Optimal Stimulation Theory), a
  // real reason beyond decoration: a flat repeated-flashcard format is
  // exactly the low-novelty task shape that research says loses ADHD
  // attention fastest, so a genuinely relevant visual per item is a
  // small, evidence-grounded source of variation within the format.
  const anchorEl = lc$("language-coach-review-anchor");
  if (anchorEl) {
    const anchor = findVisualAnchor(`${lcReviewCurrent.content_en} ${lcReviewCurrent.context_sentence || ""}`);
    if (anchor) {
      anchorEl.textContent = anchor;
      anchorEl.classList.remove("hidden");
    } else {
      anchorEl.classList.add("hidden");
    }
  }
}

// Pedagogy doc theory #14b/#14a: a miss here isn't a generic "wrong
// answer" -- it's very likely the specific, well-documented
// Dunning-Kruger "valley of despair" pattern, so it gets a named-pattern
// reassurance instead of neutral silence. A real consolidation milestone
// (review_count >= 3, matching SM-2's own interval progression in
// context/spaced_repetition.py) gets an equally honest, non-gamified
// acknowledgment grounded in Kandel's synaptic-consolidation finding.
function reviewFeedbackMessage(recalled, reviewCount) {
  if (!recalled) {
    return "Sentir que ficou mais difícil agora é normal -- é sinal de que você está percebendo mais nuances do inglês, não de que regrediu. Isso já foi estudado especificamente em aprendizado de idiomas.";
  }
  if (reviewCount >= 3) {
    return "Você já lembrou isso várias vezes espaçadas -- pelo que se sabe sobre como a memória se forma, isso já está virando memória de longo prazo, não só decoreba de curto prazo.";
  }
  return "";
}

async function submitReviewResult(recalled) {
  if (!lcReviewCurrent) return;
  const itemId = lcReviewCurrent.id;
  let updatedItem = null;
  try {
    const res = await fetch("/api/language-coach/review-result", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId, recalled }),
    });
    if (res.ok) updatedItem = await res.json();
  } catch {
    // Best-effort -- the item just won't reschedule this time; it stays
    // due and will be offered again on the next queue refresh.
  }
  lcReviewQueue = lcReviewQueue.filter((item) => item.id !== itemId);

  const message = reviewFeedbackMessage(recalled, updatedItem?.review_count ?? 0);
  const feedbackEl = lc$("language-coach-review-feedback");
  if (message && feedbackEl) {
    feedbackEl.textContent = message;
    feedbackEl.classList.remove("hidden");
    lc$("language-coach-review-actions").classList.add("hidden");
    // Brief, one-time, non-looping delay so the message is actually
    // readable before the next card replaces it.
    setTimeout(() => {
      feedbackEl.classList.add("hidden");
      renderReviewCard();
      refreshReviewQueue();
    }, 3200);
    return;
  }
  renderReviewCard();
  refreshReviewQueue();
}

// -- pronunciation practice (record -> whisper-cli -> feedback) ----------
// encodeWav/recordAudio come from audio_utils.js.

const LC_RECORDING_MAX_MS = 8000;

let lcActiveRecording = null;

function setPronunciationError(card, message) {
  const errorEl = card.querySelector(".lc-pronunciation-error");
  errorEl.textContent = message;
  errorEl.classList.remove("hidden");
}

async function startRecording(card) {
  if (lcActiveRecording) return; // a recording is already in progress somewhere
  card.querySelector(".lc-pronunciation-error").classList.add("hidden");
  card.querySelector(".lc-pronunciation-feedback").classList.add("hidden");

  const btn = card.querySelector(".lc-record-btn");
  let recording;
  try {
    recording = await recordAudio(LC_RECORDING_MAX_MS);
  } catch {
    setPronunciationError(card, "Não foi possível acessar o microfone.");
    return;
  }
  lcActiveRecording = recording;
  btn.textContent = "⏹ Parar gravação";
  btn.classList.add("recording");

  const wavBlob = await recording.done;
  lcActiveRecording = null;
  btn.textContent = "🎙️ Gravar tentativa";
  btn.classList.remove("recording");
  await handleRecordingStopped(card, wavBlob);
}

function stopRecording() {
  if (lcActiveRecording) lcActiveRecording.stop();
}

async function handleRecordingStopped(card, wavBlob) {
  const targetText = card.querySelector(".lc-record-btn").dataset.targetText || "";
  if (!targetText) return;

  const statusEl = card.querySelector(".lc-pronunciation-status");
  statusEl.textContent = "Processando pronúncia -- pode levar alguns segundos...";
  statusEl.classList.remove("hidden");

  try {
    const formData = new FormData();
    formData.append("target_text", targetText);
    formData.append("audio", wavBlob, "attempt.wav");

    const res = await fetch("/api/language-coach/pronunciation-check", {
      method: "POST",
      body: formData,
    });
    statusEl.classList.add("hidden");
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      setPronunciationError(card, errBody.detail || `Erro (${res.status}) ao verificar pronúncia.`);
      return;
    }
    renderPronunciationFeedback(card, await res.json());
  } catch {
    statusEl.classList.add("hidden");
    setPronunciationError(card, "Não foi possível processar a gravação.");
  }
}

function renderPronunciationFeedback(card, data) {
  const block = card.querySelector(".lc-pronunciation-feedback");
  block.querySelector(".lc-pronunciation-heard").textContent = `Ouvi: "${data.heard_text || "(nada reconhecível)"}"`;
  block.querySelector(".lc-pronunciation-specific").textContent = data.specific_feedback_pt;
  block.querySelector(".lc-pronunciation-encouragement").textContent = data.encouragement_pt;
  block.classList.remove("hidden");

  // Closes the practice loop (LANGUAGE_COACH_ARCHITECTURE.md section 8:
  // every practice attempt should end in a retry affordance -- .lc-record-btn
  // is already there, still enabled -- or a "mark as practiced" action
  // feeding spaced repetition). Reuses the same .lc-add-review-btn every
  // card template already has.
  const addReviewBtn = card.querySelector(".lc-add-review-btn");
  if (data.target_text) {
    addReviewBtn.classList.remove("hidden");
    addReviewBtn.dataset.contentEn = data.target_text;
    addReviewBtn.dataset.contextSentence = "";
    // kind="pronunciation", not the default "chunk" -- this item came from
    // an actual recorded practice attempt, not just a noticed idiom.
    addReviewBtn.dataset.kind = "pronunciation";
  } else {
    addReviewBtn.classList.add("hidden");
  }

  fillProcessingLoadBadge(card, data.processing_load);
}

async function runLanguageCoachRequest(card, endpoint, body, renderFn) {
  // Same 95s ceiling and reasoning as app.js's runAction: the backend's own
  // Ollama timeout is 90s, so this always gives it a chance to reply first.
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 95000);
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      card.querySelector(".response-card-error").textContent =
        errBody.detail || `Erro (${res.status}) ao consultar o Language Coach.`;
      setLanguageCoachCardState(card, "error", "erro");
      return;
    }
    const data = await res.json();
    renderFn(card, data);
    setLanguageCoachCardState(card, "ready", "pronto");
  } catch (err) {
    card.querySelector(".response-card-error").textContent =
      err.name === "AbortError"
        ? "O modelo local demorou demais para responder (timeout)."
        : "Não foi possível contatar o backend local.";
    setLanguageCoachCardState(card, "error", "erro");
  } finally {
    clearTimeout(timeoutId);
  }
}

// Retrieval-practice-first (Roediger & Karpicke; docs/LANGUAGE_COACH_
// PEDAGOGY.md theory #2/#10) -- shown BEFORE the real explanation
// whenever there's one specific sentence to ask about ("?" click,
// noticing-flag click): the user is asked what they think it means
// first, so looking it up follows a genuine retrieval attempt instead of
// skipping straight to the answer. Only applies here, not to a typed
// free-form question -- there's no single "guess this" target for an
// open-ended question, so that path (the `question` branch below) still
// goes straight to the real request as before.
function showRetrievalPrompt(card, sourceSentenceEn) {
  card.dataset.pendingSentence = sourceSentenceEn;
  card.querySelector(".lc-retrieval-sentence").textContent = sourceSentenceEn;
  setLanguageCoachCardState(card, "retrieval", "aguardando você");
}

function revealExplanationAfterRetrieval(card) {
  const sourceSentenceEn = card.dataset.pendingSentence || "";
  setLanguageCoachCardState(card, "loading", "carregando...");
  // The guess itself isn't sent anywhere -- retrieval practice's benefit
  // is in the act of attempting recall, not in grading the attempt (no
  // backend support for that, and it's not what the research this is
  // grounded in calls for either).
  runLanguageCoachRequest(
    card,
    "/api/language-coach/ask",
    { question: "", source_sentence_en: sourceSentenceEn },
    renderExplanationCard
  );
}

function askLanguageCoach({ question = "", sourceSentenceEn = "" } = {}) {
  if (!question && !sourceSentenceEn) return;
  const card = createLanguageCoachCard("explanation");
  if (sourceSentenceEn && !question) {
    showRetrievalPrompt(card, sourceSentenceEn);
    return;
  }
  runLanguageCoachRequest(
    card,
    "/api/language-coach/ask",
    { question, source_sentence_en: sourceSentenceEn },
    renderExplanationCard
  );
}

function runLanguageCoachScenario(targetPattern) {
  if (!targetPattern) return;
  const card = createLanguageCoachCard("scenario");
  runLanguageCoachRequest(
    card,
    "/api/language-coach/scenario",
    { target_pattern: targetPattern },
    renderScenarioCard
  );
}

function runLanguageCoachPronunciationGuide(sourceTextEn) {
  if (!sourceTextEn) return;
  const card = createLanguageCoachCard("pronunciation_guide");
  runLanguageCoachRequest(
    card,
    "/api/language-coach/pronunciation-guide",
    { source_text_en: sourceTextEn },
    renderPronunciationGuideCard
  );
}

function wireLanguageCoachControls() {
  lc$("language-coach-ask-btn").addEventListener("click", () => {
    const input = lc$("language-coach-input");
    const question = input.value.trim();
    if (!question) return;
    askLanguageCoach({ question });
    input.value = "";
  });
  lc$("language-coach-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") lc$("language-coach-ask-btn").click();
  });

  // The "?" and "🗣️" affordances are created dynamically by app.js's
  // addConversationEntry, so they're wired via delegation here rather
  // than at creation time. #transcript is now the paired conversation
  // timeline (2026-08-13 redesign), but the delegation target/logic is
  // unchanged -- the buttons still live inside it either way.
  lc$("transcript").addEventListener("click", (event) => {
    const explainBtn = event.target.closest(".explain-sentence-btn");
    if (explainBtn) {
      askLanguageCoach({ sourceSentenceEn: explainBtn.dataset.sentence || "" });
      return;
    }
    const pronounceBtn = event.target.closest(".pronounce-sentence-btn");
    if (pronounceBtn) {
      runLanguageCoachPronunciationGuide(pronounceBtn.dataset.sentence || "");
    }
  });

  // Proactive noticing badge (app.js's handleServerEvent, "noticing.flag") --
  // clicking opens the same explanation flow as the transcript-line "?"
  // (retrieval-practice-first included); left alone it self-dismisses on
  // its own timeout, no action needed.
  lc$("noticing-badge").addEventListener("click", () => {
    const badge = lc$("noticing-badge");
    askLanguageCoach({ sourceSentenceEn: badge.dataset.sentence || "" });
    badge.classList.add("hidden");
  });

  // Same "🗣️" affordance, plus a "🔊" listen button, on the reverse
  // pipeline's English output (app.js's appendPtLiveTranslatedText) --
  // this text is already English, so pronunciation-guide and speakText
  // both apply directly, no back-mapping needed.
  lc$("pt-live-translated").addEventListener("click", (event) => {
    const pronounceBtn = event.target.closest(".pronounce-sentence-btn");
    if (pronounceBtn) {
      runLanguageCoachPronunciationGuide(pronounceBtn.dataset.sentence || "");
      return;
    }
    const speakBtn = event.target.closest(".speak-en-inline-btn");
    if (speakBtn) {
      speakText(speakBtn.dataset.speakText || "");
    }
  });

  lc$("language-coach-feed").addEventListener("click", (event) => {
    const retrievalSubmit = event.target.closest(".lc-retrieval-submit");
    const retrievalSkip = event.target.closest(".lc-retrieval-skip");
    if (retrievalSubmit || retrievalSkip) {
      revealExplanationAfterRetrieval(event.target.closest(".lc-card"));
      return;
    }
    const scenarioBtn = event.target.closest(".lc-scenario-btn");
    if (scenarioBtn) {
      runLanguageCoachScenario(scenarioBtn.dataset.targetPattern || "");
      return;
    }
    const speakBtn = event.target.closest(".lc-speak-btn");
    if (speakBtn) {
      speakText(speakBtn.dataset.speakText || "");
      return;
    }
    const addReviewBtn = event.target.closest(".lc-add-review-btn");
    if (addReviewBtn) {
      addReviewBtn.disabled = true;
      addReviewBtn.textContent = "Adicionado ✓";
      fetch("/api/language-coach/learning-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content_en: addReviewBtn.dataset.contentEn || "",
          context_sentence: addReviewBtn.dataset.contextSentence || "",
          kind: addReviewBtn.dataset.kind || "chunk",
        }),
      })
        .then(refreshReviewQueue)
        .catch(() => {});
      return;
    }
    const recordBtn = event.target.closest(".lc-record-btn");
    if (recordBtn) {
      const card = recordBtn.closest(".lc-card");
      // Bug fix 2026-08-13: this referenced an undefined `lcMediaRecorder`
      // (never declared anywhere in this file) -- clicking the button
      // while a recording was already active threw a ReferenceError
      // instead of stopping it. See docs/FIXED_BUGS.md.
      if (lcActiveRecording) {
        stopRecording();
      } else {
        startRecording(card);
      }
    }
  });

  lc$("language-coach-review-btn").addEventListener("click", () => {
    const panel = lc$("language-coach-review-panel");
    const opening = panel.classList.contains("hidden");
    panel.classList.toggle("hidden");
    if (opening) renderReviewCard();
  });

  lc$("language-coach-review-reveal").addEventListener("click", () => {
    lc$("language-coach-review-card").querySelector(".lc-review-chunk").classList.remove("hidden");
    lc$("language-coach-review-reveal").classList.add("hidden");
    lc$("language-coach-review-actions").classList.remove("hidden");
  });

  lc$("language-coach-review-recalled").addEventListener("click", () => {
    // Positive reinforcement moment, not just a state change -- ties
    // directly to the Affective Filter Hypothesis (pedagogy point 1) and
    // its "motivational, not just functional" extension (theory #13).
    animatePulse(lc$("language-coach-review-recalled"));
    submitReviewResult(true);
  });
  lc$("language-coach-review-forgot").addEventListener("click", () => submitReviewResult(false));

  refreshReviewQueue();
}

wireLanguageCoachControls();
