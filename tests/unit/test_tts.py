import pytest

from meeting_copilot.context.tts import SpeechSynthesisError, synthesize_speech


@pytest.mark.asyncio
async def test_synthesize_speech_returns_wav_bytes():
    audio = await synthesize_speech("test", voice="Daniel")
    assert audio.startswith(b"RIFF")  # WAV container magic bytes
    assert len(audio) > 44  # more than just a WAV header


@pytest.mark.asyncio
async def test_synthesize_speech_rejects_empty_text():
    with pytest.raises(SpeechSynthesisError):
        await synthesize_speech("   ")
