"""Supervises `whisper-stream` as a subprocess.

This is the only place in the codebase that launches an external process.
Rules enforced here, matching section 16 of the product spec:

- never build the command through shell interpolation of user input;
- validate the binary and model exist before starting;
- read stdout/stderr asynchronously without blocking the event loop;
- restart once on unexpected exit, then require manual intervention;
- always terminate the subprocess cleanly on stop().
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from meeting_copilot.audio.transcript_parser import parse_line
from meeting_copilot.config import WhisperSettings
from meeting_copilot.logging_config import log_event

logger = logging.getLogger(__name__)

# How often to log a "still alive" heartbeat with cumulative stdout-line
# counts, even if nothing usable has been yielded. Distinguishes "whisper
# is producing output slowly" from "whisper has gone silent" without
# spamming a log line per raw stdout write (whisper-stream redraws its
# line frequently via \r, most of which parse_line() drops as noise).
_HEARTBEAT_SECONDS = 10.0

MAX_AUTOMATIC_RESTARTS = 1


class WhisperBinaryNotFound(RuntimeError):
    pass


class WhisperModelNotFound(RuntimeError):
    pass


def validate_whisper_setup(settings: WhisperSettings) -> None:
    """Raise a descriptive error if whisper-stream cannot possibly start."""
    binary = settings.binary_path_expanded
    model = settings.model_path_expanded
    if not binary.exists():
        raise WhisperBinaryNotFound(
            f"whisper-stream binary not found at {binary}. "
            "Run scripts/build_whisper.sh."
        )
    if not model.exists():
        raise WhisperModelNotFound(
            f"Whisper model not found at {model}. "
            "Run scripts/download_models.sh."
        )


def build_command(settings: WhisperSettings) -> list[str]:
    """Build the whisper-stream argv list.

    Flags are limited to the ones documented as stable in section 16 of
    the spec (-m, -t, --step, --length, -l). Before adding any new flag,
    run `whisper-stream --help` against the installed binary and confirm
    it exists -- do not assume flags from unrelated versions.

    `-l`/`--language` was a real, silent bug until 2026-07-22: this field
    existed on WhisperSettings and defaulted to "en" but was never
    actually passed to the subprocess, so it did nothing -- invisible as
    long as the only model in use was the English-only ggml-small.en.bin
    (which can't produce anything but English regardless of `-l`).
    Building the reverse "Falar em português" pipeline
    (services/session_service.py's second, multilingual-model
    WhisperProcessManager) surfaced it immediately: without this flag,
    that second process defaulted to `-l en` and transcribed Portuguese
    speech as garbled English guesses instead of Portuguese, confirmed
    by inspecting `ps aux` output showing no `-l` flag on either process.
    """
    command = [
        str(settings.binary_path_expanded),
        "-m",
        str(settings.model_path_expanded),
        "-t",
        str(settings.threads),
        "--step",
        str(settings.step_ms),
        "--length",
        str(settings.length_ms),
        "-l",
        settings.language,
    ]
    if settings.capture_device is not None and settings.capture_device >= 0:
        command += ["-c", str(settings.capture_device)]
    return command


class WhisperProcessManager:
    """Owns the whisper-stream subprocess lifecycle for one session."""

    def __init__(
        self,
        settings: WhisperSettings,
        on_status_change: Callable[[str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._process: asyncio.subprocess.Process | None = None
        self._restart_count = 0
        self._stopped_intentionally = False
        self._on_status_change = on_status_change or (lambda status: None)

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        validate_whisper_setup(self._settings)
        command = build_command(self._settings)
        log_event(logger, "whisper_process", "process_starting", command=" ".join(Path(c).name for c in command))
        self._process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stopped_intentionally = False
        self._on_status_change("running")
        log_event(logger, "whisper_process", "process_started", pid=self._process.pid)

    async def stop(self) -> None:
        self._stopped_intentionally = True
        if self._process is None:
            return
        if self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        log_event(logger, "whisper_process", "process_stopped")
        self._on_status_change("stopped")
        self._process = None

    async def iter_transcript_lines(self) -> AsyncIterator[str]:
        """Yield cleaned transcript text lines until the process stops.

        Restarts the subprocess once on an unexpected exit; a second
        unexpected exit propagates so the caller can surface an error to
        the UI instead of looping forever.
        """
        while True:
            if self._process is None:
                await self.start()
            assert self._process is not None
            assert self._process.stdout is not None

            last_output_at = time.monotonic()
            last_heartbeat_at = last_output_at
            raw_line_count = 0
            usable_line_count = 0

            try:
                async for raw_bytes in self._process.stdout:
                    now = time.monotonic()
                    raw_line_count += 1
                    raw_line = raw_bytes.decode("utf-8", errors="replace")
                    text = parse_line(raw_line)
                    if text:
                        usable_line_count += 1
                        log_event(
                            logger,
                            "whisper_process",
                            "transcript_line_ready",
                            gap_since_last_line_ms=round((now - last_output_at) * 1000),
                            text_length=len(text),
                        )
                        last_output_at = now
                        yield text
                    if now - last_heartbeat_at >= _HEARTBEAT_SECONDS:
                        log_event(
                            logger,
                            "whisper_process",
                            "heartbeat",
                            raw_lines_since_last_heartbeat=raw_line_count,
                            usable_lines_since_last_heartbeat=usable_line_count,
                            seconds_since_last_usable_line=round(now - last_output_at, 1),
                        )
                        last_heartbeat_at = now
                        raw_line_count = 0
                        usable_line_count = 0
            finally:
                returncode = self._process.returncode if self._process else None

            if self._stopped_intentionally:
                return

            if returncode not in (0, None) and self._restart_count < MAX_AUTOMATIC_RESTARTS:
                self._restart_count += 1
                log_event(
                    logger,
                    "whisper_process",
                    "process_restarting",
                    level=logging.WARNING,
                    returncode=returncode,
                    attempt=self._restart_count,
                )
                self._process = None
                self._on_status_change("starting")
                await self.start()
                continue

            log_event(
                logger,
                "whisper_process",
                "process_exited",
                level=logging.ERROR,
                returncode=returncode,
            )
            self._on_status_change("error")
            return

    async def read_stderr_line(self) -> str | None:
        """Read one line of stderr, if available, without blocking long."""
        if self._process is None or self._process.stderr is None:
            return None
        try:
            raw_bytes = await asyncio.wait_for(self._process.stderr.readline(), timeout=0.1)
        except asyncio.TimeoutError:
            return None
        if not raw_bytes:
            return None
        return raw_bytes.decode("utf-8", errors="replace").strip()


# Matches SDL2's actual startup banner, e.g.:
#   init:    - Capture device #0: 'Microfone (MacBook Pro)'
# Not "starts with 'capture device'" (see the bug this replaced below) --
# the real line is prefixed with "init:" and indentation.
_DEVICE_LINE_RE = re.compile(r"Capture device #(\d+):\s*'(.+)'")

# whisper-stream does not have a stable, documented device-listing flag
# across versions. It never lists devices in response to --help (that
# only prints the option table). What it *does* do: the SDL2 audio
# backend it links against enumerates every capture device and prints
# them to stdout as soon as it starts up, before it even tries to open
# one. -c 999 is meant to be an obviously-invalid index, but empirically
# SDL2 doesn't error on it -- it silently falls back to some device and
# whisper-stream carries on into a full session (model load, "[Start
# speaking]", listening indefinitely). So this can't wait for the
# process to exit or for communicate() to return; it has to read stdout
# line-by-line and kill the process itself as soon as the device list
# line appears (which happens within about a second, long before model
# loading starts).
_DEVICE_LISTING_INVALID_DEVICE_ID = 999
_DEVICE_LISTING_READ_TIMEOUT_SECONDS = 5.0


async def list_capture_devices(settings: WhisperSettings) -> list[dict[str, int | str]]:
    """Start whisper-stream with a deliberately-invalid device ID and parse SDL2's device list.

    Best-effort: returns an empty list (never raises) if the binary is
    missing, if SDL2's output format doesn't match, or if nothing usable
    shows up before the read timeout.
    """
    validate_whisper_setup(settings)
    command = [
        str(settings.binary_path_expanded),
        "-m",
        str(settings.model_path_expanded),
        "-c",
        str(_DEVICE_LISTING_INVALID_DEVICE_ID),
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert process.stdout is not None

    devices: list[dict[str, int | str]] = []
    seen_attempt_line = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _DEVICE_LISTING_READ_TIMEOUT_SECONDS
    try:
        while loop.time() < deadline:
            remaining = deadline - loop.time()
            try:
                raw_line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace")
            match = _DEVICE_LINE_RE.search(line)
            if match:
                devices.append({"index": int(match.group(1)), "name": match.group(2)})
            elif "attempt to open capture device" in line:
                # Everything we need has been printed; no reason to let
                # the process go on to load the model.
                seen_attempt_line = True
                break
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()

    if devices and not seen_attempt_line:
        log_event(
            logger,
            "whisper_process",
            "device_listing_ended_early",
            level=logging.WARNING,
            device_count=len(devices),
        )
    return devices
