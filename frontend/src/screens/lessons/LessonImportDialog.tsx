import { useEffect, useMemo, useRef, useState } from "react";
import { FileUp } from "lucide-react";
import {
  importLessons,
  LESSON_PACKAGE_SUFFIX,
  previewLessonImport,
  type LessonImportMaterialRead,
  type LessonImportPreviewRead,
  type LessonImportResult,
} from "../../api/lessonTransfer";
import { listMaterials, type MaterialRead } from "../../api/materials";
import { undoProjectAction } from "../../api/projects";
import { Button, Checkbox, Dialog, LoadingState, Select, StatusBadge } from "../../components/ui";
import type { SelectOption, StatusTone } from "../../components/ui";
import type { ProgramTreeNode } from "../programTree";
import { errorText } from "./lessonTree";

/** Значение списка «чем стать куску»: снимок текста вместо живой ссылки. */
const SNAPSHOT = "snapshot";

const MATERIAL_STATUS: Record<LessonImportMaterialRead["status"], { label: string; tone: StatusTone }> = {
  project: { label: "Есть в проекте", tone: "success" },
  library: { label: "Есть в Библиотеке", tone: "info" },
  missing: { label: "Нет в этой установке", tone: "warning" },
};

interface LessonImportDialogProps {
  projectId: string;
  open: boolean;
  onOpenChange(open: boolean): void;
  /** Изучаемые темы в порядке программы — куда можно положить урок. */
  topics: ProgramTreeNode[];
  onImported(): void;
  onOpenLesson(topicId: string, lessonId: string): void;
}

function piecesLabel(count: number): string {
  if (count % 10 === 1 && count % 100 !== 11) return `${count} кусок`;
  if ([2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100)) return `${count} куска`;
  return `${count} кусков`;
}

/**
 * «Импорт уроков»: файл `.tentex-lessons` из другой установки. Сначала видно,
 * что в файле и куда он ляжет — тема для каждого урока и судьба каждого
 * материала; ничего не пишется до «Импортировать». Весь импорт — одно «Отменить».
 */
export function LessonImportDialog({ projectId, open, onOpenChange, topics, onImported, onOpenLesson }: LessonImportDialogProps) {
  const input = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<LessonImportPreviewRead | null>(null);
  const [materials, setMaterials] = useState<MaterialRead[]>([]);
  const [included, setIncluded] = useState<Set<string>>(new Set());
  const [topicOf, setTopicOf] = useState<Record<string, string | null>>({});
  const [materialOf, setMaterialOf] = useState<Record<string, string>>({});
  const [result, setResult] = useState<LessonImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setFile(null);
    setPreview(null);
    setResult(null);
    setError("");
    const controller = new AbortController();
    listMaterials(projectId, controller.signal).then(setMaterials).catch(() => setMaterials([]));
    return () => controller.abort();
  }, [open, projectId]);

  const topicOptions = useMemo<SelectOption[]>(
    () => topics.map((topic) => ({ value: topic.id, label: `${topic.number} ${topic.title}` })),
    [topics],
  );
  const topicById = useMemo(() => new Map(topics.map((topic) => [topic.id, topic])), [topics]);

  async function choose(next: File | undefined) {
    if (!next) return;
    setFile(next);
    setPreview(null);
    setError("");
    setBusy(true);
    try {
      const read = await previewLessonImport(projectId, next);
      setPreview(read);
      setIncluded(new Set(read.lessons.map((lesson) => lesson.key)));
      setTopicOf(Object.fromEntries(read.lessons.map((lesson) => [lesson.key, lesson.program_node_id])));
      setMaterialOf(Object.fromEntries(read.materials.map((item) => [item.key, item.material_id ?? SNAPSHOT])));
    } catch (caught) {
      setError(errorText(caught, "Файл уроков не прочитался"));
    } finally {
      setBusy(false);
    }
  }

  function materialOptions(item: LessonImportMaterialRead): SelectOption[] {
    const options: SelectOption[] = [];
    if (item.status === "library" && item.material_id) {
      options.push({ value: item.material_id, label: "Подключить из Библиотеки к проекту", description: "Тот же файл учебника: куски станут живыми ссылками" });
    }
    for (const material of materials) {
      options.push({
        value: material.id,
        label: material.id === item.material_id ? `${material.display_name} — тот же файл` : `Сопоставить с «${material.display_name}»`,
        description: material.id === item.material_id ? undefined : "Другой файл: границы найдутся по тексту абзацев, где совпадёт",
      });
    }
    options.push({ value: SNAPSHOT, label: "Оставить снимком текста", description: "Кусок покажет текст из файла; связать можно позже" });
    return options;
  }

  const chosenLessons = preview?.lessons.filter((lesson) => included.has(lesson.key)) ?? [];
  const missingTopic = chosenLessons.some((lesson) => !topicOf[lesson.key]);

  async function runImport() {
    if (!file || !preview || chosenLessons.length === 0 || missingTopic) return;
    setBusy(true);
    setError("");
    try {
      const done = await importLessons(projectId, file, {
        lessons: chosenLessons.map((lesson) => ({ key: lesson.key, program_node_id: topicOf[lesson.key]! })),
        materials: Object.fromEntries(Object.entries(materialOf).map(([key, value]) => [key, value === SNAPSHOT ? null : value])),
      });
      setResult(done);
      onImported();
    } catch (caught) {
      setError(errorText(caught, "Импорт не удался"));
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    const sequence = result?.latest_undoable_action?.sequence;
    if (!sequence) return;
    setBusy(true);
    setError("");
    try {
      await undoProjectAction(projectId, sequence);
      setResult(null);
      onImported();
      onOpenChange(false);
    } catch (caught) {
      setError(errorText(caught, "Не удалось отменить импорт"));
    } finally {
      setBusy(false);
    }
  }

  const first = result?.lessons[0];
  const footer = result ? (
    <>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {result.latest_undoable_action && <Button variant="ghost" disabled={busy} onClick={() => void undo()}>Отменить импорт</Button>}
      {first && first.program_node_ids[0] && (
        <Button variant="secondary" onClick={() => { onOpenLesson(first.program_node_ids[0], first.id); onOpenChange(false); }}>Открыть первый</Button>
      )}
      <Button onClick={() => onOpenChange(false)}>Готово</Button>
    </>
  ) : (
    <>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {preview && missingTopic && <span className="lesson-export-count">Выберите тему для каждого урока</span>}
      <Button variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>Отмена</Button>
      {preview && (
        <Button disabled={busy || chosenLessons.length === 0 || missingTopic} onClick={() => void runImport()}>
          {busy ? "Импортируем…" : `Импортировать · ${chosenLessons.length}`}
        </Button>
      )}
    </>
  );

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => { if (!busy) onOpenChange(next); }}
      title="Импорт уроков"
      description="Уроки из файла .tentex-lessons другой установки или другого проекта."
      className="lesson-import-dialog"
      footer={footer}
    >
      <input ref={input} type="file" accept={`${LESSON_PACKAGE_SUFFIX},.zip`} hidden
        onChange={(event) => { void choose(event.target.files?.[0]); event.target.value = ""; }} />

      {result ? (
        <div className="lesson-import-result" role="status">
          <strong>Импортировано уроков: {result.lessons.length}</strong>
          <ul>
            <li>живых ссылок на материал: {result.linked_pieces}</li>
            <li>кусков снимком текста: {result.snapshot_pieces}{result.snapshot_pieces > 0 ? " — их можно связать позже, когда учебник появится в проекте" : ""}</li>
            {result.attached_materials > 0 && <li>подключено материалов из Библиотеки: {result.attached_materials}</li>}
          </ul>
          <p className="lesson-export-note">Уроки пришли со своими статусами; прохождение и попытки заданий не переносятся.</p>
        </div>
      ) : (
        <>
          <div className="lesson-import-file">
            <Button variant="secondary" disabled={busy} onClick={() => input.current?.click()}>
              <FileUp size={15} />{file ? "Другой файл…" : "Выбрать файл…"}
            </Button>
            <span>{file ? file.name : "Файл уроков — .tentex-lessons"}</span>
          </div>
          {busy && !preview && <LoadingState label="Читаем файл уроков" />}
          {preview && (
            <div className="lesson-import-preview">
              <p className="lesson-export-note">
                {preview.source_project ? `Из проекта «${preview.source_project}»` : "Файл уроков"}
                {preview.exported_at ? ` · ${new Date(preview.exported_at).toLocaleDateString("ru")}` : ""}
                {` · уроков: ${preview.lessons.length}`}
              </p>
              <section aria-label="Уроки и темы">
                <h3 className="lesson-import-heading">Уроки → темы этого проекта</h3>
                <div className="lesson-import-lessons">
                  {preview.lessons.map((lesson) => {
                    const topic = topicOf[lesson.key] ? topicById.get(topicOf[lesson.key]!) : null;
                    return (
                      <div className="lesson-import-row" key={lesson.key}>
                        <div className="lesson-import-title">
                          <Checkbox
                            label={lesson.title}
                            checked={included.has(lesson.key)}
                            onCheckedChange={(value) => setIncluded((current) => {
                              const next = new Set(current);
                              if (value) next.add(lesson.key); else next.delete(lesson.key);
                              return next;
                            })}
                          />
                          <small>
                            {lesson.topic_titles[0] ? `было: «${lesson.topic_titles[0]}» · ` : ""}
                            {piecesLabel(lesson.pieces)}{lesson.tasks ? ` · заданий: ${lesson.tasks}` : ""}
                            {lesson.program_node_id && topic ? " · тема нашлась" : ""}
                          </small>
                        </div>
                        <Select
                          ariaLabel={`Тема для урока «${lesson.title}»`}
                          className="lesson-import-topic"
                          value={topicOf[lesson.key] ?? null}
                          placeholder="Выберите тему"
                          disabled={!included.has(lesson.key)}
                          aria-invalid={included.has(lesson.key) && !topicOf[lesson.key]}
                          options={topicOptions}
                          onValueChange={(value) => setTopicOf((current) => ({ ...current, [lesson.key]: value }))}
                        />
                      </div>
                    );
                  })}
                </div>
              </section>
              {preview.materials.length > 0 && (
                <section aria-label="Материалы">
                  <h3 className="lesson-import-heading">Материалы кусков</h3>
                  <div className="lesson-import-lessons">
                    {preview.materials.map((item) => (
                      <div className="lesson-import-row" key={item.key}>
                        <div className="lesson-import-title">
                          <strong>{item.name}</strong>
                          <small>
                            <StatusBadge tone={MATERIAL_STATUS[item.status].tone}>{MATERIAL_STATUS[item.status].label}</StatusBadge>
                            {" "}{piecesLabel(item.pieces)}
                          </small>
                        </div>
                        <Select
                          ariaLabel={`Чем станут куски «${item.name}»`}
                          className="lesson-import-topic"
                          value={materialOf[item.key] ?? SNAPSHOT}
                          options={materialOptions(item)}
                          onValueChange={(value) => setMaterialOf((current) => ({ ...current, [item.key]: value ?? SNAPSHOT }))}
                        />
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </div>
          )}
        </>
      )}
    </Dialog>
  );
}
