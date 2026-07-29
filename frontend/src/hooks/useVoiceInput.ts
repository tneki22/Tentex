import { useEffect, useRef, useState } from "react";

export type VoiceInputStatus = "idle" | "recording" | "transcribing" | "error";

interface UseVoiceInputOptions {
  /**
   * Куда отправлять запись. В virtex сюда был вшит клиент API экзамена;
   * здесь это просто функция, чтобы хук не знал про транспорт.
   * На этапе 10 сюда придёт вызов Groq Whisper (§16 требований).
   */
  transcribe: (audio: Blob) => Promise<{ text: string }>;
  enabled?: boolean;
  onTranscript: (text: string) => void;
}

const MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/ogg;codecs=opus",
  "audio/webm",
];

const MAX_RECORDING_MS = 5 * 60 * 1_000;

export function useVoiceInput({ transcribe, enabled = true, onTranscript }: UseVoiceInputOptions) {
  const [status, setStatus] = useState<VoiceInputStatus>("idle");
  const [error, setError] = useState("");
  const [durationSeconds, setDurationSeconds] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const stopTimerRef = useRef<number | null>(null);
  const durationTimerRef = useRef<number | null>(null);
  const onTranscriptRef = useRef(onTranscript);
  const transcribeRef = useRef(transcribe);
  const mountedRef = useRef(true);
  onTranscriptRef.current = onTranscript;
  transcribeRef.current = transcribe;

  function clearTimers() {
    if (stopTimerRef.current !== null) window.clearTimeout(stopTimerRef.current);
    if (durationTimerRef.current !== null) window.clearInterval(durationTimerRef.current);
    stopTimerRef.current = null;
    durationTimerRef.current = null;
  }

  function releaseStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  async function start() {
    if (!enabled || status === "transcribing") return;
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MIME_TYPES.find((candidate) => MediaRecorder.isTypeSupported(candidate));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      streamRef.current = stream;
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        clearTimers();
        if (!mountedRef.current) {
          releaseStream();
          recorderRef.current = null;
          return;
        }
        setStatus("transcribing");
        const audio = new Blob(chunksRef.current, {
          type: recorder.mimeType || mimeType || "audio/webm",
        });
        void transcribeRef.current(audio)
          .then((result) => {
            if (result.text.trim()) onTranscriptRef.current(result.text.trim());
            setStatus("idle");
          })
          .catch((reason: Error) => {
            setError(reason.message);
            setStatus("error");
          })
          .finally(() => {
            releaseStream();
            recorderRef.current = null;
          });
      };
      recorder.start();
      setDurationSeconds(0);
      setStatus("recording");
      durationTimerRef.current = window.setInterval(
        () => setDurationSeconds((current) => current + 1),
        1_000,
      );
      stopTimerRef.current = window.setTimeout(() => {
        if (recorder.state === "recording") recorder.stop();
      }, MAX_RECORDING_MS);
    } catch (reason) {
      releaseStream();
      setError(reason instanceof Error ? reason.message : "Нет доступа к микрофону");
      setStatus("error");
    }
  }

  function stop() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearTimers();
      if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      releaseStream();
    };
  }, []);

  return {
    status,
    error,
    durationSeconds,
    toggle: () => (status === "recording" ? stop() : start()),
  };
}
