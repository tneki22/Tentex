import { useCallback, useEffect, useRef, useState } from "react";
import { transcribeAudio } from "../api/ai";
import { ProjectApiError } from "../api/projects";
import { toWav } from "./dictationAudio";

export type DictationState = "idle" | "recording" | "transcribing";

/** Реплика в чат, а не лекция: длиннее — почти наверняка забытая запись. */
const MAX_RECORDING_SECONDS = 300;

// Chrome и Edge пишут webm/opus, Firefox — ogg/opus, Safari — mp4; берём то, что
// умеет браузер, а перед отправкой `toWav` приводит запись к одному формату.
const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];

export function dictationSupported(): boolean {
  return typeof MediaRecorder !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia);
}

function pickMimeType(): string | undefined {
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type));
}

function microphoneError(caught: unknown): string {
  const name = caught instanceof DOMException ? caught.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Нет доступа к микрофону. Разрешите его в настройках браузера.";
  }
  if (name === "NotFoundError") return "Микрофон не найден. Подключите его и повторите.";
  if (name === "NotReadableError") return "Микрофон занят другим приложением.";
  return "Не удалось включить микрофон.";
}

function recognitionError(caught: unknown): string {
  if (caught instanceof ProjectApiError) {
    if (caught.code === "ai_model_not_configured") {
      return "Модель для речи не выбрана: Параметры ИИ → Модели по умолчанию → «Для речи».";
    }
    return caught.message;
  }
  return "Не удалось распознать речь. Проверьте соединение.";
}

export function formatDuration(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/**
 * Диктовка: первое нажатие пишет с микрофона, второе останавливает запись и
 * отправляет её модели речи из «Параметров ИИ». Готовый текст отдаётся в
 * `onText` — вставить его или отправить решает вызывающий, чтобы человек успел
 * поправить расшифровку.
 */
export function useDictation(onText: (text: string) => void) {
  const [state, setState] = useState<DictationState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<number | null>(null);
  // Запись, оборванная уходом со страницы, в модель не отправляется.
  const discardRef = useRef(false);
  const onTextRef = useRef(onText);

  useEffect(() => {
    onTextRef.current = onText;
  }, [onText]);

  const stopTimer = useCallback(() => {
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = null;
  }, []);

  const send = useCallback(async (audio: Blob) => {
    const controller = new AbortController();
    abortRef.current = controller;
    setState("transcribing");
    try {
      // Не удалось перекодировать — отправляем как записано: Groq и OpenAI webm понимают.
      const upload = await toWav(audio).catch(() => audio);
      const result = await transcribeAudio(upload, controller.signal);
      if (controller.signal.aborted) return;
      const text = result.text.trim();
      if (text) onTextRef.current(text);
      else setError("Речь не распознана. Повторите ближе к микрофону.");
    } catch (caught) {
      if (!controller.signal.aborted) setError(recognitionError(caught));
    } finally {
      if (!controller.signal.aborted) setState("idle");
    }
  }, []);

  const start = useCallback(async () => {
    setError("");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (caught) {
      setError(microphoneError(caught));
      return;
    }
    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    recorder.onstop = () => {
      // Без остановки дорожек в браузере горит значок записи.
      stream.getTracks().forEach((track) => track.stop());
      stopTimer();
      recorderRef.current = null;
      if (discardRef.current) {
        discardRef.current = false;
        return;
      }
      void send(new Blob(chunks, { type: recorder.mimeType || mimeType || "audio/webm" }));
    };
    recorderRef.current = recorder;
    recorder.start();
    setSeconds(0);
    setState("recording");
    const startedAt = Date.now();
    timerRef.current = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      setSeconds(elapsed);
      if (elapsed >= MAX_RECORDING_SECONDS && recorder.state === "recording") recorder.stop();
    }, 500);
  }, [send, stopTimer]);

  const toggle = useCallback(() => {
    if (state === "recording") recorderRef.current?.stop();
    else if (state === "idle") void start();
  }, [start, state]);

  useEffect(() => () => {
    abortRef.current?.abort();
    stopTimer();
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      discardRef.current = true;
      recorder.stop();
    }
  }, [stopTimer]);

  return { state, seconds, error, toggle };
}
