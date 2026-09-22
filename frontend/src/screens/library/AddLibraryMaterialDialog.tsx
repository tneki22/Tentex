import { Braces, ChevronRight, FileUp, Globe, Type } from "lucide-react";
import { useRef, useState } from "react";
import { createLibraryExternalMaterial, createLibraryTextMaterial, uploadTypstMaterial, uploadLibraryMaterial, type LibraryMaterialDetailRead } from "../../api/materials";
import { Button, Dialog, ErrorState, Field, Progress } from "../../components/ui";

type Mode = "choose" | "file" | "text" | "link" | "typst";
type TypstChoice = { kind: "single" | "folder" | "zip"; files: File[] };
const ACCEPT = ".pdf,.docx,.txt,.md,.jpg,.jpeg,.png,.mp3,.wav,.m4a,.ogg,.flac";
const isYoutube = (url: string) => /(?:^|\.)youtube\.com|youtu\.be/i.test(url);
const fileSize = (bytes: number) => bytes < 1024 ** 2 ? `${Math.round(bytes / 1024)} КБ` : `${(bytes / 1024 ** 2).toFixed(1)} МБ`;

interface AddLibraryMaterialDialogProps { open: boolean; onOpenChange: (open: boolean) => void; onCreated: (material: LibraryMaterialDetailRead) => void; }

/** Сначала пользователь видит и при желании меняет имя, затем начинается загрузка. */
export function AddLibraryMaterialDialog({ open, onOpenChange, onCreated }: AddLibraryMaterialDialogProps) {
  const fileInput = useRef<HTMLInputElement>(null);
  const typstFileInput = useRef<HTMLInputElement>(null);
  const typstFolderInput = useRef<HTMLInputElement>(null);
  const typstZipInput = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<Mode>("choose");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [subject, setSubject] = useState("");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [typst, setTypst] = useState<TypstChoice | null>(null);
  const [progress, setProgress] = useState(0);

  function reset() { setMode("choose"); setBusy(false); setError(""); setDisplayName(""); setSubject(""); setText(""); setUrl(""); setFile(null); setTypst(null); setProgress(0); }
  async function submit(action: () => Promise<LibraryMaterialDetailRead>) {
    setBusy(true); setError("");
    try { const material = await action(); reset(); onOpenChange(false); onCreated(material); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Материал не добавился"); }
    finally { setBusy(false); }
  }
  function chooseFile(next: File) { setFile(next); setTypst(null); setDisplayName(next.name); setMode("file"); }
  function chooseTypst(kind: TypstChoice["kind"], list: FileList | null) {
    const files = list ? Array.from(list) : []; if (!files.length) return;
    setFile(null); setTypst({ kind, files });
    setDisplayName(kind === "folder" ? files[0].webkitRelativePath.split("/")[0] || files[0].name : files[0].name);
  }
  const source = file ?? typst?.files[0] ?? null;
  const sourceMode = mode === "file" || mode === "typst";
  const canSubmit = mode === "text" ? Boolean(text.trim()) : mode === "link" ? Boolean(url.trim()) : Boolean(source);
  const title = mode === "text" ? "Вставить текст" : mode === "link" ? "Добавить по ссылке" : mode === "typst" ? "Добавить Typst" : "Добавить материал";
  function submitSource() {
    if (file) void submit(() => uploadLibraryMaterial(file, setProgress, subject, displayName));
    if (typst) void submit(() => uploadTypstMaterial(typst.kind, typst.files, typst.files.map((item) => item.webkitRelativePath || item.name), undefined, subject, displayName));
  }
  function sourceCard(label: string, hint: string, onClick: () => void, icon = <FileUp size={18} />) {
    return <button type="button" disabled={busy} onClick={onClick}>{icon}<span><strong>{label}</strong><small>{hint}</small></span><ChevronRight size={15}/></button>;
  }
  return <Dialog open={open} onOpenChange={(next) => { if (!next) reset(); onOpenChange(next); }} title={title} description="Материал появится в Библиотеке. Подключить его к проекту можно позже."
    footer={mode === "choose" ? <Button variant="ghost" onClick={() => onOpenChange(false)}>Закрыть</Button> : <><Button variant="ghost" disabled={busy} onClick={() => { setMode("choose"); setFile(null); setTypst(null); }}>Назад</Button><Button disabled={busy || !canSubmit} onClick={() => { if (mode === "text") void submit(() => createLibraryTextMaterial({ name: "Заметка.md", text, subject: subject.trim() || null, display_name: displayName.trim() || null })); else if (mode === "link") void submit(() => createLibraryExternalMaterial({ kind: isYoutube(url) ? "youtube" : "url", url: url.trim(), subject: subject.trim() || null, display_name: displayName.trim() || null })); else submitSource(); }}>{mode === "link" ? "Сохранить снимок" : "Добавить"}</Button></>}
  >
    <input ref={fileInput} className="materials-file-input" type="file" accept={ACCEPT} tabIndex={-1} aria-hidden="true" onChange={(event) => { const next = event.target.files?.[0]; event.target.value = ""; if (next) chooseFile(next); }} />
    <input ref={typstFileInput} className="materials-file-input" type="file" accept=".typ" tabIndex={-1} aria-hidden="true" onChange={(event) => { chooseTypst("single", event.target.files); event.target.value = ""; }} />
    <input ref={(node) => { typstFolderInput.current = node; node?.setAttribute("webkitdirectory", ""); }} className="materials-file-input" type="file" multiple tabIndex={-1} aria-hidden="true" onChange={(event) => { chooseTypst("folder", event.target.files); event.target.value = ""; }} />
    <input ref={typstZipInput} className="materials-file-input" type="file" accept=".zip" tabIndex={-1} aria-hidden="true" onChange={(event) => { chooseTypst("zip", event.target.files); event.target.value = ""; }} />
    {error && <ErrorState message={error} />}
    {mode === "choose" && <div className="materials-add-grid">{sourceCard("Файл", "PDF, DOCX, TXT, MD, изображение или аудиозапись", () => fileInput.current?.click())}{sourceCard("Текст", "Вставить конспект или список вопросов прямо здесь", () => { setDisplayName("Заметка.md"); setMode("text"); }, <Type size={18} />)}{sourceCard("Ссылка", "Веб-страница или публичное YouTube-видео", () => setMode("link"), <Globe size={18} />)}{sourceCard("Typst", "Один файл, папка проекта или ZIP", () => setMode("typst"), <Braces size={18} />)}</div>}
    {mode !== "choose" && <><Field label="Название в библиотеке" hint="Если оставить пустым, возьмём имя файла или заголовок источника."><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></Field><Field label="Предмет" hint="Необязательно. Например, «Базы данных»"><input value={subject} onChange={(event) => setSubject(event.target.value)} /></Field></>}
    {sourceMode && source && <div className="materials-upload-progress"><FileUp size={18}/><span><strong>{source.name}</strong><small>{fileSize(source.size)}</small></span>{busy && <Progress value={progress} max={100} label="Загрузка файла" />}</div>}
    {mode === "text" && <Field label="Текст" required><textarea autoFocus value={text} onChange={(event) => setText(event.target.value)} placeholder={"# Заголовок\n\nТекст материала…"} /></Field>}
    {mode === "link" && <Field label="Адрес" required hint={isYoutube(url) ? "Похоже на YouTube — сохраним субтитры" : undefined}><input type="url" autoFocus value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.org/article" /></Field>}
    {mode === "typst" && <div className="materials-add-grid">{sourceCard("Один файл", "Автономный `.typ`", () => typstFileInput.current?.click())}{sourceCard("Папка проекта", "Исходники и изображения сохранят пути", () => typstFolderInput.current?.click())}{sourceCard("ZIP", "Безопасно нормализуем архив", () => typstZipInput.current?.click())}</div>}
  </Dialog>;
}
