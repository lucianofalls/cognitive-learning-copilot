"""Local English Meeting Copilot.

A local-first, offline-first assistant that transcribes English meeting
audio, keeps a rolling context of the discussion, and suggests short
English phrases the user can use to respond, ask questions, or politely
disagree -- all explained in Brazilian Portuguese.

Nothing in this package talks to a remote service. Transcription runs
through a local `whisper.cpp` subprocess and reasoning runs through a
local Ollama instance -- see README.md's Privacy section for the
guarantees this package is designed to uphold.
"""

__version__ = "0.1.0"
