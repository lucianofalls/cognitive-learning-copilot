// Shared audio recording/encoding utilities -- used by both app.js (the
// "Falar em português" reverse-translation button) and language_coach.js
// (the pronunciation-check "Gravar tentativa" button). Loaded before both.

// whisper-cli only decodes flac/mp3/ogg/wav (confirmed via --help), not
// the webm/opus (Chrome) or mp4/aac (Safari) a MediaRecorder actually
// produces -- so every recording gets decoded and re-encoded as PCM WAV
// here, client-side, rather than adding a server-side transcoding
// dependency for this. Mono, matching a single-mic voice recording;
// stereo mixdown isn't needed for this use case.
function encodeWav(audioBuffer) {
  const numChannels = 1;
  const sampleRate = audioBuffer.sampleRate;
  const samples = audioBuffer.getChannelData(0);
  const bytesPerSample = 2;
  const blockAlign = numChannels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  const writeString = (offset, text) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bytesPerSample * 8, true);
  writeString(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

// Decodes whatever MediaRecorder produced into a WAV Blob ready to upload.
async function recordedBlobToWav(blob) {
  const arrayBuffer = await blob.arrayBuffer();
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  const audioCtx = new AudioContextClass();
  try {
    const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
    return encodeWav(audioBuffer);
  } finally {
    await audioCtx.close();
  }
}

// Records from the mic for up to `maxMs`, or until stopRecording() is
// called on the returned controller. Resolves with the recorded WAV Blob.
async function recordAudio(maxMs) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const chunks = [];
  const recorder = new MediaRecorder(stream);
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  });

  const stopped = new Promise((resolve) => {
    recorder.addEventListener("stop", () => {
      stream.getTracks().forEach((track) => track.stop());
      resolve();
    });
  });

  recorder.start();
  const timeoutId = setTimeout(() => {
    if (recorder.state === "recording") recorder.stop();
  }, maxMs);

  return {
    stop: () => {
      if (recorder.state === "recording") recorder.stop();
    },
    done: (async () => {
      await stopped;
      clearTimeout(timeoutId);
      const blob = new Blob(chunks, { type: chunks[0]?.type || "audio/webm" });
      return recordedBlobToWav(blob);
    })(),
  };
}
