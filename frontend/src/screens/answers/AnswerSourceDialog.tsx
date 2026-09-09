import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { FileText, LibraryBig, Upload } from "lucide-react";
import type { MaterialRead, MaterialState } from "../../api/materials";
import { Button, Dialog, LoadingState, Progress } from "../../components/ui";

const STATUS_COPY: Record<MaterialState, string> = {
  ready_to_process: "Файл добавлен, но текст ещё не подготовлен.",
  queued: "Файл в очереди на разбор.",
  processing: "Разбираем файл.",
  paused: "Разбор на паузе.",
  needs_input: "Нужны файлы проекта или выбор точки входа.",
  ready: "Файл разобран.",
  failed: "Разбор не удался.",
};

interface AnswerSourceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  /** Файл эталонных ответов проекта; их всегда не больше одного. */
  answersMaterial: MaterialRead | null;
  busy: boolean;
  onUploadFile: (file: File) => void;
  onPickFromLibrary: () => void;
  onImportText: () => void;
  onStartProcessing: (materialId: string) => void;
}

/**
 * Что делать, когда «Из файла ответов» нажали, а привязывать ещё нечего.
 *
 * Готовый файл сюда не попадает: для него сразу открывается выбор способа
 * сопоставления. Здесь остаются два честных случая — файла нет вовсе и файл
 * есть, но ещё не разобран.
 */
export function AnswerSourceDialog({
  open,
  onOpenChange,
  projectId,
  answersMaterial,
  busy,
  onUploadFile,
  onPickFromLibrary,
  onImportText,
  onStartProcessing,
}: AnswerSourceDialogProps) {
  const input = useRef<HTMLInputElement>(null);
  const [replacing, setReplacing] = useState(false);

  useEffect(() => {
    if (open) setReplacing(false);
  }, [open]);

  const pending = answersMaterial && !replacing && answersMaterial.status !== "ready";
  const task = answersMaterial?.task;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={pending ? "Файл ответов ещё разбирается" : "Файл с ответами"}
      description={pending
        ? "Сопоставление запустится само, как только текст будет готов."
        : "Один файл со всеми ответами: из него автоматика разложит их по вопросам."}
      className="answer-source-dialog"
      footer={<Button variant="ghost" onClick={() => onOpenChange(false)}>Закрыть</Button>}
    >
      {pending && answersMaterial ? (
        <div className="answer-source-status">
          <p><b>{answersMaterial.display_name}</b></p>
          <p>{STATUS_COPY[answersMaterial.status]}</p>
          {task && task.total > 0 && task.state === "running" && (
            <Progress value={task.done} max={task.total} label="Разбор файла" />
          )}
          {task?.state === "running" && task.total === 0 && <LoadingState label="Разбираем" />}
          {answersMaterial.error && <p className="inline-error">{answersMaterial.error}</p>}
          <div className="answer-source-actions">
            {answersMaterial.status === "ready_to_process" && (
              <Button disabled={busy} onClick={() => onStartProcessing(answersMaterial.id)}>
                Разобрать файл
              </Button>
            )}
            <Link
              className="secondary-button"
              to={`/projects/${projectId}/materials/${answersMaterial.id}`}
            >
              Открыть в материалах
            </Link>
            <Button variant="ghost" onClick={() => setReplacing(true)}>Выбрать другой файл</Button>
          </div>
        </div>
      ) : (
        <div className="answer-source-choices">
          <button type="button" className="answer-source-choice" disabled={busy} onClick={() => input.current?.click()}>
            <Upload size={18} aria-hidden="true" />
            <b>Выбрать файл</b>
            <small>PDF, DOCX, TXT или MD с вашего компьютера. Разбор начнётся сразу.</small>
          </button>
          <button type="button" className="answer-source-choice" disabled={busy} onClick={onPickFromLibrary}>
            <LibraryBig size={18} aria-hidden="true" />
            <b>Из Библиотеки</b>
            <small>Файл уже загружен в другой проект — подключим без повторного разбора.</small>
          </button>
          <button type="button" className="answer-source-choice" disabled={busy} onClick={onImportText}>
            <FileText size={18} aria-hidden="true" />
            <b>Вставить текстом</b>
            <small>Файла нет, ответы есть текстом: заголовок вопроса, затем ответ.</small>
          </button>
          <input
            ref={input}
            type="file"
            accept=".pdf,.docx,.txt,.md"
            className="materials-file-input"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) onUploadFile(file);
            }}
          />
        </div>
      )}
    </Dialog>
  );
}
