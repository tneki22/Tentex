import {
  type ChangeEvent,
  type DragEvent,
  type ReactNode,
  useId,
  useState,
} from "react";
import { FileText, RotateCcw, UploadCloud, X } from "lucide-react";
import type { MaterialRead } from "../../api/materials";
import { Button, Card, SegmentedTabs } from "../../components/ui";

export type ExamMaterialInputMode = "files" | "text";

interface ExamMaterialUploadPanelProps {
  icon: ReactNode;
  title: string;
  description: string;
  allowText?: boolean;
  mode: ExamMaterialInputMode;
  onModeChange: (mode: ExamMaterialInputMode) => void;
  materials: MaterialRead[];
  multiple?: boolean;
  text: string;
  onTextChange: (text: string) => void;
  onFiles: (files: File[]) => Promise<void>;
  onRemove: (material: MaterialRead) => Promise<void>;
  onRetry?: (material: MaterialRead) => Promise<void>;
}

const STATUS_LABELS: Record<MaterialRead["status"], string> = {
  ready_to_process: "Загружен",
  queued: "В очереди",
  processing: "Обрабатывается",
  paused: "На паузе",
  ready: "Готов",
  failed: "Ошибка обработки",
};

export function ExamMaterialUploadPanel({
  icon,
  title,
  description,
  allowText = false,
  mode,
  onModeChange,
  materials,
  multiple = false,
  text,
  onTextChange,
  onFiles,
  onRemove,
  onRetry,
}: ExamMaterialUploadPanelProps) {
  const inputId = useId();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const atLimit = !multiple && materials.length > 0;

  async function addFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0 || atLimit) return;
    const selected = Array.from(fileList);
    setUploading(true);
    setError("");
    try {
      await onFiles(multiple ? selected : selected.slice(0, 1));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось загрузить файл");
    } finally {
      setUploading(false);
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    void addFiles(event.dataTransfer.files);
  }

  return (
    <Card className="wizard-upload-panel">
      <div className="wizard-upload-head">
        <span className="wizard-upload-icon">{icon}</span>
        <span>
          <strong>{title}</strong>
          <small>{description}</small>
        </span>
        {allowText && (
          <SegmentedTabs
            label={`Способ добавления: ${title}`}
            value={mode}
            onChange={onModeChange}
            tabs={[
              { value: "files", label: "Файлы" },
              { value: "text", label: "Вставить текст" },
            ]}
          />
        )}
      </div>

      {mode === "files" || !allowText ? (
        <>
          {!atLimit && (
            <div
              className={`wizard-dropzone${uploading ? " is-disabled" : ""}`}
              aria-busy={uploading}
              onDragOver={(event) => event.preventDefault()}
              onDrop={onDrop}
            >
              <UploadCloud size={24} aria-hidden="true" />
              <span>
                <b>{uploading ? "Загружаем…" : "Перетащите файлы сюда"}</b>
                <small>PDF, DOCX, TXT, MD или изображения — до 100 МБ и 500 страниц</small>
              </span>
              <label className="secondary-button" htmlFor={inputId}>Выбрать файлы</label>
              <input
                id={inputId}
                className="wizard-file-input"
                type="file"
                accept=".pdf,.docx,.txt,.md,image/*"
                multiple={multiple}
                disabled={uploading}
                onChange={(event: ChangeEvent<HTMLInputElement>) => {
                  void addFiles(event.currentTarget.files);
                  event.currentTarget.value = "";
                }}
              />
            </div>
          )}

          {materials.length > 0 && (
            <div className="wizard-file-list" aria-live="polite">
              {materials.map((material) => (
                <div className="wizard-file-row" key={material.id}>
                  <span className="wizard-file-type"><FileText size={16} aria-hidden="true" /></span>
                  <span className="wizard-file-name">
                    <b>{material.display_name}</b>
                    <small className={material.status === "failed" ? "inline-error" : ""}>
                      {material.status === "failed"
                        ? material.error || STATUS_LABELS.failed
                        : STATUS_LABELS[material.status]}
                    </small>
                  </span>
                  {material.status === "failed" && onRetry && (
                    <Button
                      variant="ghost"
                      aria-label={`Повторить обработку ${material.display_name}`}
                      onClick={() => void onRetry(material)}
                    >
                      <RotateCcw size={15} aria-hidden="true" />
                    </Button>
                  )}
                  <button
                    type="button"
                    className="wizard-remove-file"
                    aria-label={`Убрать ${material.display_name}`}
                    onClick={() => void onRemove(material)}
                  >
                    <X size={16} aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="wizard-paste-area">
          <textarea
            rows={8}
            value={text}
            onChange={(event) => onTextChange(event.target.value)}
            placeholder={title === "Готовые ответы"
              ? "1. Ответ: база данных — это…\n\n2. Ответ: реляционная модель…"
              : "1. Понятие базы данных.\n2. Реляционная модель данных.\n3. Нормальные формы…"}
          />
        </div>
      )}

      {error && <p className="inline-error" role="alert">{error}</p>}
    </Card>
  );
}
