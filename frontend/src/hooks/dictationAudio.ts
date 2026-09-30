/**
 * Запись MediaRecorder → WAV 16 кГц моно.
 *
 * Chrome пишет webm/opus, а чат-модели с приёмом аудио (Gemini через
 * OpenRouter) принимают только wav, mp3, ogg и подобные. WAV понимают все три
 * пути распознавания, так что браузерный формат к провайдеру не доходит.
 * Речь весит 32 КБ/с, пятиминутный потолок диктовки — меньше 10 МБ.
 */
const SAMPLE_RATE = 16_000;

export async function toWav(recording: Blob): Promise<Blob> {
  // Контекст с нужной частотой сам пересэмплирует при декодировании.
  const context = new AudioContext({ sampleRate: SAMPLE_RATE });
  try {
    const decoded = await context.decodeAudioData(await recording.arrayBuffer());
    return new Blob([encodeWav(mixToMono(decoded))], { type: "audio/wav" });
  } finally {
    void context.close();
  }
}

function mixToMono(buffer: AudioBuffer): Float32Array {
  const mono = new Float32Array(buffer.length);
  for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
    const samples = buffer.getChannelData(channel);
    for (let index = 0; index < samples.length; index += 1) {
      mono[index] += samples[index] / buffer.numberOfChannels;
    }
  }
  return mono;
}

function encodeWav(samples: Float32Array): ArrayBuffer {
  const bytes = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(bytes);
  const writeText = (offset: number, text: string) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };
  writeText(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeText(8, "WAVE");
  writeText(12, "fmt ");
  view.setUint32(16, 16, true); // размер блока fmt
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // моно
  view.setUint32(24, SAMPLE_RATE, true);
  view.setUint32(28, SAMPLE_RATE * 2, true); // байт в секунду
  view.setUint16(32, 2, true); // байт на отсчёт
  view.setUint16(34, 16, true); // бит на отсчёт
  writeText(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let index = 0; index < samples.length; index += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(44 + index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }
  return bytes;
}
