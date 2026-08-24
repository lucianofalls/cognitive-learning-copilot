# Cognitive Learning Copilot

A private, local-first copilot for technical meetings (or any English
audio — a real meeting, a video, a podcast) in English. It transcribes
the room's audio with `whisper.cpp`, keeps a rolling context of the
discussion, continuously translates it to Brazilian Portuguese (a
dedicated local NMT model, not an LLM -- translates each transcript
segment as it arrives, no batching delay), and — on demand — explains
what's being discussed and suggests short, easy-to-pronounce English
phrases you can use to respond, ask a question, or politely disagree.

**This is not just a translator.** The app is built around a Language
Coach grounded in real cognitive-science and second-language-acquisition
research — not guessed pedagogy — aimed specifically at people for whom
real-time bilingual production is genuinely hard: mild ADHD, attention
and focus differences, and the working-memory load anyone faces
listening, translating, and composing a response all at once. It
detects *this specific user's* real-time processing bottleneck (which
of Gile's four interpreting efforts — listening & analysis, memory,
production, coordination — is straining, right now, from real signals
already in the transcript: repeated self-corrections, long
pre-response pauses, requests to repeat) and adapts what it surfaces
and when, instead of applying one fixed rule to every learner. The
reasoning behind each feature lives directly in the code as comments
next to the logic it justifies (see `src/meeting_copilot/context/
processing_load_detector.py` and `noticing_detector.py` as starting
points) rather than in a separate design doc, so it stays next to what
it explains as the code evolves.

Everything runs on your machine. No ChatGPT, no Gemini, no Otter, no paid
API, no cloud call of any kind during a session.

By default nothing is written to disk. If
`privacy.persist_learning_notes` is enabled in `config/settings.yaml`
(off by default), the PT-BR translation and a derived summary are
appended to a local markdown file per session under `data/sessions/` --
read `PrivacySettings` in `src/meeting_copilot/config.py` and think
about your own use case (and your employer's policies, if this is a
work meeting) before turning this on.

## 1. Compliance notice

This app processes meeting audio locally. Before you use it:

- Confirm this is permitted under your employer's policies.
- Inform meeting participants when required by law or internal rules.

The app shows this same reminder every time you start a session. It is
a prompt, not a legal opinion.

## 2. Architecture

Single-user, single-process FastAPI app. The frontend is vanilla
JS/HTML/CSS (`web/`, no build step) with a React foundation in progress
(`web-react/`, not yet wired to application logic). Short version:

```
Mic, or a loopback device for any audio (video, call, podcast)
  -> whisper.cpp / whisper-stream
  -> rolling transcript + incremental summary (in memory only)
  -> translation: opus_mt (local NMT, default) or argos/Ollama fallback
  -> coach actions: Ollama (JSON-structured output)
  -> FastAPI + WebSocket
  -> browser UI at http://127.0.0.1:8000
```

For the module map, coding conventions, and the reasoning behind
specific choices (why a dedicated NMT model instead of the coach's own
LLM, why two whisper-stream processes run concurrently for the reverse
pipeline, etc.), read the module-level docstrings in
`src/meeting_copilot/` -- each subpackage (`audio/`, `context/`,
`llm/`, `services/`, `persistence/`) explains its own responsibilities
and boundaries at the top of its `__init__.py` or its most central
file.

## 3. Requirements

- Apple Silicon Mac (`arm64`), 16 GB unified memory or more.
- macOS with Xcode Command Line Tools.
- [Homebrew](https://brew.sh/).
- [Ollama](https://ollama.com/download).
- A few GB free disk for models (a Whisper ggml model, an Ollama model
  a couple GB in size, a small NMT translation model), downloaded on
  first use.

## 4. Installation

Each step prints what it will download, why, how big it is, whether it
needs the internet, and how to remove it — read before confirming.

```bash
git clone <this-repo-url> cognitive-learning-copilot
cd cognitive-learning-copilot

scripts/bootstrap_macos.sh   # Command Line Tools check, Homebrew packages, .venv
scripts/build_whisper.sh     # clones + compiles whisper.cpp with SDL2
scripts/download_models.sh   # Whisper + Ollama models
scripts/doctor.sh            # verifies everything above
```

Then set up your own config:

```bash
cp config/profile.example.yaml config/profile.yaml
# edit config/profile.yaml: your name, role, expertise
```

`config/profile.yaml` is gitignored on purpose -- it holds your real
name and background, not something to commit.

## 5. Quick start

```bash
scripts/start.sh
```

This opens `http://127.0.0.1:8000` in your browser. Confirm the
compliance dialog, click **Iniciar escuta**, and start talking (or play
audio near the Mac's microphone).

## 6. Preparing a meeting

Click **Preparar reunião** before a session to give the copilot context:
title, objective, agenda, expected topics, known systems/acronyms, and
desired outcome. This is session-only — it is not saved to disk unless
you explicitly choose to. See `config/meeting.example.yaml` for the full
field list and an example.

## 7. Shortcuts

| Shortcut | Action |
|---|---|
| Cmd+1 | Explicar contexto |
| Cmd+2 | Sugerir resposta |
| Cmd+3 | Sugerir pergunta |
| Cmd+4 | Discordar educadamente |
| Cmd+5 | Pedir esclarecimento |
| Cmd+6 | Confirmar entendimento |
| Cmd+7 | Explicar inglês |
| Esc | Fechar modal |

## 8. Configuration

- `config/profile.yaml` — who you are, your expertise, answer
  preferences. Gitignored; copy `config/profile.example.yaml` to create
  it (see section 4).
- `config/glossary.yaml` — technical terms to preserve in English.
- `config/settings.yaml` — server, privacy, whisper, Ollama, UI, automation.
- `config/meeting.example.yaml` — template for the "Preparar reunião" screen.

Edit these directly, or through the UI / REST endpoints (see
`src/meeting_copilot/api/` for the full route list).

## 9. Privacy

- No audio saved by default.
- No transcript persisted by default.
- No external network calls during a session.
- Server binds only to `127.0.0.1` (enforced in code, not just config
  -- see `main.py`'s `_assert_loopback_only`).
- Permanent memory requires an explicit "Aprovar memória" action.
- "Apagar sessão" clears all in-memory session state on demand.
- Optional, off-by-default local persistence for PT-BR translation +
  summary only, never raw audio or raw English transcript (see the
  intro section above and `PrivacySettings` in
  `src/meeting_copilot/config.py`).

## 10. Tests

```bash
source .venv/bin/activate
pytest
```

Unit and integration tests run without macOS, whisper.cpp, or Ollama
(they use mocks/fixtures) -- no real hardware or subprocess needed for
the automated suite. Manually verifying the real microphone/whisper-
stream/Ollama path is on you.

## 11. Troubleshooting

Common issues -- whisper-stream failing to start, Ollama unavailable,
port 8000 already in use, memory pressure -- are usually visible
directly in the status bar and the server's own log output. If
`scripts/doctor.sh` passes but something still doesn't work, check that
whisper-stream and Ollama aren't fighting over the same CPU cores
(`whisper.threads` in `config/settings.yaml`), and that
`config/profile.yaml` actually exists (see section 4).

## 12. Removing everything

```bash
rm -rf ~/Developer/whisper.cpp
ollama rm <model-name>                   # `ollama list` shows what's actually pulled
brew uninstall --cask blackhole-2ch      # only if you installed it, for loopback audio capture
brew uninstall git cmake sdl2 ffmpeg python@3.11   # only if unused elsewhere
rm -rf .venv
rm -rf data/sessions                     # only if privacy.persist_learning_notes was ever enabled
```

## 13. Roadmap

Out of scope for this MVP by design: RAG/vector DB, autonomous agents,
fine-tuning, native Teams bot integration, speech synthesis, reliable
multi-speaker diarization, a native macOS app. These are only worth
considering after the core transcribe → context → suggest loop is
validated in real meetings.

**Built, running alongside the existing pipeline with no impact on
transcription/translation speed**: the Language Coach -- grammar Q&A
("why this verb, why this conjugation"), idiomatic-chunk explanations,
hypothetical-scenario practice, judgment-free pronunciation feedback,
spaced repetition (real SM-2 scheduling, not a gamified streak), and
real-time processing-load detection that adapts to *this user's*
listening/memory/production/coordination bottleneck as it happens (see
the "not just a translator" section above). Fine-grained pronunciation
phoneme scoring is the one piece still not started. Read
`src/meeting_copilot/context/processing_load_detector.py`,
`spaced_repetition.py`, and `services/language_coach_service.py` for
the current implementation and the reasoning behind it before touching
any of this -- the tone and pacing of every piece of coaching copy is
theory-backed, not arbitrary.
