import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { ImagePlus } from "lucide-react";

interface AnswerEditorProps {
  /** Приезжает от `Field`: подпись должна вести в само поле. */
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  /** Грузит файлы вложениями и отдаёт готовые маркеры для подстановки в текст. */
  onUploadFiles: (files: File[]) => Promise<string[]>;
}

function imagesFrom(list: FileList | null | undefined): File[] {
  return [...(list ?? [])].filter((file) => file.type.startsWith("image/"));
}

/** Скриншот из буфера всегда зовётся image.png — в списке файлов это нечитаемо. */
function namedPaste(file: File, index: number): File {
  if (file.name && file.name !== "image.png") return file;
  const now = new Date();
  const stamp = [
    String(now.getDate()).padStart(2, "0"),
    String(now.getMonth() + 1).padStart(2, "0"),
  ].join(".");
  const time = [now.getHours(), now.getMinutes(), now.getSeconds()]
    .map((part) => String(part).padStart(2, "0"))
    .join("-");
  const suffix = file.type === "image/jpeg" ? "jpg" : file.type.slice("image/".length) || "png";
  const tail = index > 0 ? ` (${index + 1})` : "";
  return new File([file], `Вставка ${stamp} ${time}${tail}.${suffix}`, { type: file.type });
}

/**
 * Поле эталонного ответа с вставкой картинок из буфера, как в Obsidian.
 *
 * Картинка не «прикрепляется куда-то вниз», а встаёт маркером на позицию
 * курсора: порядок текста и иллюстраций задаётся здесь и ровно так же
 * читается в Рабочей области.
 */
export function AnswerEditor({
  id,
  value,
  onChange,
  disabled = false,
  textareaRef,
  onUploadFiles,
}: AnswerEditorProps) {
  const [uploading, setUploading] = useState(false);
  const [dropping, setDropping] = useState(false);
  const [error, setError] = useState("");
  // Загрузка асинхронная, а пользователь мог успеть дописать строку.
  const latest = useRef(value);
  useEffect(() => { latest.current = value; }, [value]);

  async function accept(files: File[]) {
    if (files.length === 0 || disabled || uploading) return;
    const input = textareaRef.current;
    const start = input?.selectionStart ?? latest.current.length;
    const end = input?.selectionEnd ?? start;
    setUploading(true);
    setError("");
    try {
      const markers = await onUploadFiles(files.map(namedPaste));
      if (markers.length === 0) return;
      const current = latest.current;
      const head = current.slice(0, Math.min(start, current.length));
      const tail = current.slice(Math.min(end, current.length));
      const insertion = [
        head && !head.endsWith("\n") ? "\n" : "",
        markers.join("\n"),
        tail && !tail.startsWith("\n") ? "\n" : "",
      ].join("");
      onChange(`${head}${insertion}${tail}`);
      const caret = head.length + insertion.length;
      requestAnimationFrame(() => {
        input?.focus();
        input?.setSelectionRange(caret, caret);
      });
    } catch {
      setError("Картинку не удалось загрузить. Попробуйте ещё раз или прикрепите файлом.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className={`answer-editor ${dropping ? "is-dropping" : ""}`.trim()}>
      <textarea
        id={id}
        ref={textareaRef}
        className="answer-editor-input"
        value={value}
        disabled={disabled}
        placeholder="Ответ на вопрос. Картинку можно вставить прямо сюда — Ctrl+V"
        onChange={(event) => onChange(event.target.value)}
        onPaste={(event) => {
          const files = imagesFrom(event.clipboardData?.files);
          if (files.length === 0) return;
          event.preventDefault();
          void accept(files);
        }}
        onDragOver={(event) => {
          if (disabled || event.dataTransfer.types.every((type) => type !== "Files")) return;
          event.preventDefault();
          setDropping(true);
        }}
        onDragLeave={() => setDropping(false)}
        onDrop={(event) => {
          const files = imagesFrom(event.dataTransfer?.files);
          setDropping(false);
          if (files.length === 0) return;
          event.preventDefault();
          void accept(files);
        }}
      />
      <p className={`answer-editor-hint ${error && !uploading ? "is-error" : ""}`.trim()}>
        <ImagePlus size={13} aria-hidden="true" />
        {uploading
          ? "Загружаем картинку…"
          : error || "Ctrl+V или перетаскивание вставляет картинку на позицию курсора."}
      </p>
    </div>
  );
}
