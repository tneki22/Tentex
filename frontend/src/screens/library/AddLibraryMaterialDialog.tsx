import { ChevronRight, FileUp, Globe, Type } from "lucide-react";
import { useRef, useState } from "react";
import {
  createLibraryExternalMaterial,
  createLibraryTextMaterial,
  uploadLibraryMaterial,
  type LibraryMaterialDetailRead,
} from "../../api/materials";
import { Button, Dialog, ErrorState, Field, Progress } from "../../components/ui";

type Mode = "choose" | "text" | "link";

const ACCEPT = ".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.mp3,.wav,.m4a,.ogg,.flac";

function looksLikeYoutube(url: string): boolean {
  return /(?:^|\.)youtube\.com|youtu\.be/i.test(url);
}

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} КБ`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} МБ`;
  return `${(bytes / 1024 ** 3).toFixed(1)} ГБ`;
}

interface AddLibraryMaterialDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (material: LibraryMaterialDetailRead) => void;
}

/**
 * Добавление общего материала. Активный проект не требуется: файл появляется в
 * Библиотеке, а подключение к проекту остаётся отдельным действием.
 */
export function AddLibraryMaterialDialog({
  open,
  onOpenChange,
  onCreated,
}: AddLibraryMaterialDialogProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<Mode>("choose");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [name, setName] = useState("Заметка.md");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [uploadingFile, setUploadingFile] = useState<File | null>(null);
  const [uploadPercent, setUploadPercent] = useState(0);

  function reset() {
    setMode("choose");
    setError("");
    setName("Заметка.md");
    setText("");
    setUrl("");
    setUploadingFile(null);
    setUploadPercent(0);
  }

  async function submit(action: () => Promise<LibraryMaterialDetailRead>) {
    setBusy(true);
    setError("");
    try {
      const created = await action();
      reset();
      onOpenChange(false);
      onCreated(created);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Материал не добавился");
      setUploadingFile(null);
    } finally {
      setBusy(false);
    }
  }

  function submitFile(file: File) {
    setUploadingFile(file);
    setUploadPercent(0);
    void submit(() => uploadLibraryMaterial(file, setUploadPercent));
  }

  const titles: Record<Mode, string> = {
    choose: "Добавить материал",
    text: "Вставить текст",
    link: "Добавить по ссылке",
  };
  const descriptions: Record<Mode, string> = {
    choose: "Материал появится в Библиотеке. Подключить его к проекту можно позже.",
    text: "Текст сохранится как отдельный материал установки.",
    link: "Tentex сохранит локальный снимок: веб-страницу текстом, YouTube — субтитрами.",
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
      title={titles[mode]}
      description={descriptions[mode]}
      footer={mode === "choose" ? (
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Закрыть</Button>
      ) : mode === "text" ? (
        <>
          <Button variant="ghost" onClick={() => setMode("choose")}>Назад</Button>
          <Button
            disabled={busy || !text.trim() || !name.trim()}
            onClick={() => void submit(() => createLibraryTextMaterial({ name, text }))}
          >
            Добавить текст
          </Button>
        </>
      ) : (
        <>
          <Button variant="ghost" onClick={() => setMode("choose")}>Назад</Button>
          <Button
            disabled={busy || !url.trim()}
            onClick={() => void submit(() => createLibraryExternalMaterial({
              kind: looksLikeYoutube(url) ? "youtube" : "url",
              url: url.trim(),
            }))}
          >
            Сохранить снимок
          </Button>
        </>
      )}
    >
      <input
        ref={fileInput}
        className="materials-file-input"
        type="file"
        tabIndex={-1}
        aria-hidden="true"
        accept={ACCEPT}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) submitFile(file);
        }}
      />

      {error && <ErrorState message={error} />}

      {mode === "choose" && uploadingFile && (
        <div className="materials-upload-progress">
          <FileUp size={18} />
          <span>
            <strong>{uploadingFile.name}</strong>
            <small>{sizeLabel(uploadingFile.size)}</small>
          </span>
          <Progress value={uploadPercent} max={100} label="Загрузка файла" />
        </div>
      )}

      {mode === "choose" && !uploadingFile && (
        <div className="materials-add-grid">
          <button type="button" disabled={busy} onClick={() => fileInput.current?.click()}>
            <FileUp size={18} />
            <span>
              <strong>Файл</strong>
              <small>PDF, DOCX, TXT, MD, изображение или аудиозапись</small>
            </span>
            <ChevronRight size={15} />
          </button>
          <button type="button" disabled={busy} onClick={() => setMode("text")}>
            <Type size={18} />
            <span>
              <strong>Текст</strong>
              <small>Вставить конспект или список вопросов прямо здесь</small>
            </span>
            <ChevronRight size={15} />
          </button>
          <button type="button" disabled={busy} onClick={() => setMode("link")}>
            <Globe size={18} />
            <span>
              <strong>Ссылка</strong>
              <small>Веб-страница или публичное YouTube-видео — вид определится по адресу</small>
            </span>
            <ChevronRight size={15} />
          </button>
        </div>
      )}

      {mode === "text" && (
        <div className="materials-text-form">
          <Field label="Название" required>
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </Field>
          <Field label="Текст" required>
            <textarea
              autoFocus
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder={"# Заголовок\n\nТекст материала…"}
            />
          </Field>
        </div>
      )}

      {mode === "link" && (
        <div className="materials-text-form">
          <Field
            label="Адрес"
            required
            hint={looksLikeYoutube(url) ? "Похоже на YouTube — сохраним субтитры" : undefined}
          >
            <input
              type="url"
              autoFocus
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://example.org/article"
            />
          </Field>
        </div>
      )}
    </Dialog>
  );
}
