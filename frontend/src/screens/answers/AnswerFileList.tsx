import { useRef } from "react";
import { FileText, Paperclip, X } from "lucide-react";
import { Button, SegmentedTabs, Tooltip } from "../../components/ui";

export type AnswerFileMode = "preview" | "list";

export interface AnswerFile {
  key: string;
  kind: "image" | "file";
  /** «material» приехал из привязки: удалять его здесь нельзя, только снять привязку. */
  origin: "attachment" | "material";
  name: string;
  /** Что встанет в текст ответа по кнопке «Вставить». */
  marker: string;
  url: string;
  sizeBytes?: number;
  pageNumber?: number;
  attachmentId?: string;
}

interface AnswerFileListProps {
  files: AnswerFile[];
  mode: AnswerFileMode;
  onModeChange: (mode: AnswerFileMode) => void;
  disabled: boolean;
  onInsert: (file: AnswerFile) => void;
  onRemove: (attachmentId: string) => void;
  onAdd: (files: FileList | null) => void;
}

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 ** 2).toFixed(1)} МБ`;
}

/**
 * Файлы ответа сразу под полем ввода: картинки из документа и свои вложения
 * в одном списке, потому что в тексте они ведут себя одинаково — маркером.
 *
 * Переключатель меняет только вид списка. Что попадёт в ответ, решает маркер
 * в тексте, а не эта настройка: иначе один и тот же эталон выглядел бы
 * по-разному здесь и в Рабочей области.
 */
export function AnswerFileList({
  files,
  mode,
  onModeChange,
  disabled,
  onInsert,
  onRemove,
  onAdd,
}: AnswerFileListProps) {
  const input = useRef<HTMLInputElement>(null);

  return (
    <section className="answer-files" aria-label="Файлы ответа">
      <header className="answer-files-head">
        <label>Файлы · {files.length}</label>
        <SegmentedTabs
          label="Как показывать файлы"
          value={mode}
          onChange={onModeChange}
          tabs={[
            { value: "preview", label: "Превью" },
            { value: "list", label: "Списком" },
          ]}
        />
      </header>

      {files.length > 0 && (
        <ul className={`answer-file-items is-${mode}`}>
          {files.map((file) => (
            <li className="answer-file" key={file.key}>
              <a
                className="answer-file-thumb"
                href={file.url}
                target="_blank"
                rel="noreferrer"
                aria-label={`Открыть «${file.name}»`}
              >
                {mode === "preview" && file.kind === "image"
                  ? <img src={file.url} alt="" loading="lazy" />
                  : <FileText size={16} aria-hidden="true" />}
              </a>
              <div className="answer-file-copy">
                <span className="answer-file-name" title={file.name}>{file.name}</span>
                <small>
                  {file.origin === "material"
                    ? `из документа${file.pageNumber ? `, стр. ${file.pageNumber}` : ""}`
                    : file.sizeBytes !== undefined ? sizeLabel(file.sizeBytes) : "вложение"}
                </small>
              </div>
              <div className="answer-file-actions">
                <Tooltip label="Поставить на позицию курсора в тексте ответа">
                  <Button variant="ghost" disabled={disabled} onClick={() => onInsert(file)}>Вставить</Button>
                </Tooltip>
                {file.origin === "attachment" && file.attachmentId && (
                  <button
                    type="button"
                    className="answer-file-remove"
                    disabled={disabled}
                    aria-label={`Убрать файл «${file.name}»`}
                    onClick={() => onRemove(file.attachmentId!)}
                  >
                    <X size={13} />
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="answer-files-add">
        <Button variant="secondary" disabled={disabled} onClick={() => input.current?.click()}>
          <Paperclip size={14} />Прикрепить файл
        </Button>
        <small>
          Изображения, PDF, DOCX, TXT и MD — до 20 МБ. Картинки из документа убираются
          снятием привязки в Материалах.
        </small>
        <input
          ref={input}
          type="file"
          multiple
          accept="image/*,.pdf,.docx,.txt,.md"
          className="materials-file-input"
          onChange={(event) => { onAdd(event.target.files); event.target.value = ""; }}
        />
      </div>
    </section>
  );
}
