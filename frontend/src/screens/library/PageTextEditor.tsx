import type { KeyboardEvent } from "react";
import type { MaterialPageRead } from "../../api/materials";
import { Button } from "../../components/ui";

/** У смешанного PDF Markdown содержит вырез, а его OCR лежит во фрагменте. */
export function editablePageText(page: MaterialPageRead): string {
  const images = page.fragments.filter((fragment) => fragment.element_kind === "image" && fragment.has_asset);
  const manuallyEdited = page.fragments.some((fragment) => fragment.recognition_source === "manual");
  let imageIndex = 0;
  return (page.markdown || page.text).replace(/!\[[^\]]*\]\(assets\/[^\n)]+\)/g, (match) => {
    const fragment = images[imageIndex++];
    if (!fragment) return match;
    // После ручной правки OCR уже входит в текст; исходные вырезы сервер хранит отдельно.
    if (manuallyEdited || fragment.recognition_source === "native") return "";
    const transcript = fragment.text.trim();
    return /^\[?(изображение|image)\]?$/iu.test(transcript) ? "" : transcript;
  }).trim();
}

interface PageTextEditorProps {
  pageNumber: number;
  text: string;
  dirty: boolean;
  busy: boolean;
  error: string | null;
  zoom: number;
  onChange(text: string): void;
  onSave(): void;
  onCancel(): void;
}

export function PageTextEditor({ pageNumber, text, dirty, busy, error, zoom, onChange, onSave, onCancel }: PageTextEditorProps) {
  function saveWithShortcut(event: KeyboardEvent) {
    if (!(event.ctrlKey || event.metaKey) || (event.key !== "Enter" && event.code !== "Enter")) return;
    event.preventDefault();
    event.stopPropagation();
    if (!busy && dirty && text.trim()) onSave();
  }

  return (
    <div className="library-page-editor" aria-busy={busy} onKeyDownCapture={saveWithShortcut}>
      <div className="library-editor-head">
        <label htmlFor="library-page-text">Текст страницы {pageNumber}</label>
        <div className="library-editor-actions">
          <Button variant="ghost" disabled={busy} onClick={onCancel}>Отмена</Button>
          <Button disabled={busy || !dirty || !text.trim()} onClick={onSave}>
            {busy ? "Сохраняем…" : "Сохранить"}
          </Button>
        </div>
      </div>
      <p className="library-editor-hint" id="library-editor-hint">
        Сверяйте текст с оригиналом. Сохранение создаст новую версию для всех проектов; изображения останутся.
      </p>
      {error && <p className="library-editor-error" role="alert">{error}</p>}
      <textarea
        id="library-page-text"
        autoFocus
        aria-describedby="library-editor-hint"
        spellCheck={false}
        readOnly={busy}
        value={text}
        style={{ fontSize: `calc(var(--text-base) * ${zoom})` }}
        onChange={(event) => onChange(event.target.value)}
      />
      <div className="library-editor-foot" role="status">
        <span>{dirty ? "Есть несохранённые изменения" : "Нет изменений"}</span>
        <span>Ctrl + Enter — сохранить</span>
      </div>
    </div>
  );
}
