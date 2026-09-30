/** Убирает timestamp-префиксы из сохранённого YouTube-транскрипта для ручного предпросмотра. */
const STAMP = /^\[(?:\d{2}:)?\d{2}:\d{2}\]\s*/;
const SENTENCE = /[.?!…]+(?:[»”"')\]]+)?$/u;

export function hasYoutubeTimestamps(text: string): boolean {
  return text.split(/\r?\n/).some((line) => STAMP.test(line));
}

export function removeYoutubeTimestamps(text: string): string {
  const prefix: string[] = [];
  const cues: string[] = [];
  let sawCue = false;
  for (const line of text.split(/\r?\n/)) {
    if (STAMP.test(line)) { cues.push(line.replace(STAMP, "").trim()); sawCue = true; }
    else if (!sawCue && line.trim()) prefix.push(line.trim());
  }
  if (!cues.length) return text;
  const paragraphs: string[] = [];
  let sentenceCount = 0;
  let current = "";
  for (const cue of cues) {
    if (!cue) continue;
    current = `${current}${current ? " " : ""}${cue}`;
    if (SENTENCE.test(cue)) sentenceCount += 1;
    if (sentenceCount >= 3 || (sentenceCount === 0 && current.length > 600)) {
      paragraphs.push(current); current = ""; sentenceCount = 0;
    }
  }
  if (current) paragraphs.push(current);
  return [...prefix, ...paragraphs].join("\n\n");
}
