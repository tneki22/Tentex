import { useEffect, useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { LESSON_STATUS_LABELS, type LessonSummaryRead } from "../../api/lessons";
import {
  exportLessons,
  saveFile,
  type LessonExportFormat,
  type LessonExportSources,
} from "../../api/lessonTransfer";
import { Button, Checkbox, Dialog, EmptyState, RadioCards, Select, Switch } from "../../components/ui";
import type { RadioCardOption } from "../../components/ui";
import type { ProgramTreeNode } from "../programTree";
import { errorText } from "./lessonTree";

const FORMATS: Array<RadioCardOption<LessonExportFormat>> = [
  {
    value: "pdf",
    title: "PDF",
    description: "Читать и печатать. Формулы видны, а скопированный текст несёт их в LaTeX $…$.",
  },
  {
    value: "latex",
    title: "LaTeX",
    description: "Документ .tex для pdflatex, xelatex, lualatex; формулы — те же, что в уроке.",
  },
  {
    value: "markdown",
    title: "Markdown",
    description: "Формулы $…$ — текст вставляется обратно в пояснения урока.",
  },
  {
    value: "tentex",
    title: "Файл уроков Tentex",
    description: "Для другой установки: уроки, задания, изображения. Куски найдут учебник по файлу.",
  },
];

const SOURCE_OPTIONS: Array<{ value: LessonExportSources; label: string }> = [
  { value: "text", label: "Текстом, как в режиме «Текст»" },
  { value: "pages", label: "Листами страниц" },
  { value: "reference", label: "Только ссылкой «В учебнике: …»" },
];

interface LessonExportDialogProps {
  projectId: string;
  open: boolean;
  onOpenChange(open: boolean): void;
  lessons: LessonSummaryRead[];
  /** Изучаемые темы в порядке программы: по ним группируется и сортируется список. */
  topics: ProgramTreeNode[];
  /** Открытый сейчас урок отмечен при открытии диалога. */
  currentLessonId: string | null;
}

interface LessonGroup {
  topic: ProgramTreeNode | null;
  lessons: LessonSummaryRead[];
}

/**
 * «Экспорт уроков»: выбранные уроки — одним файлом в порядке программы.
 * Несколько уроков PDF собирает с титулом и содержанием, текстовые форматы —
 * одним документом, файл уроков — одним архивом для импорта.
 */
export function LessonExportDialog({ projectId, open, onOpenChange, lessons, topics, currentLessonId }: LessonExportDialogProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [format, setFormat] = useState<LessonExportFormat>("pdf");
  const [sources, setSources] = useState<LessonExportSources>("text");
  const [answers, setAnswers] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setSelected(new Set(currentLessonId ? [currentLessonId] : []));
    setQuery("");
    setError("");
  }, [open, currentLessonId]);

  const groups = useMemo<LessonGroup[]>(() => {
    const byTopic = new Map<string, LessonSummaryRead[]>();
    const loose: LessonSummaryRead[] = [];
    const known = new Set(topics.map((topic) => topic.id));
    for (const lesson of lessons) {
      const topicId = lesson.program_node_ids.find((id) => known.has(id));
      if (!topicId) { loose.push(lesson); continue; }
      byTopic.set(topicId, [...(byTopic.get(topicId) ?? []), lesson]);
    }
    const result: LessonGroup[] = topics
      .filter((topic) => byTopic.has(topic.id))
      .map((topic) => ({ topic, lessons: byTopic.get(topic.id)! }));
    if (loose.length > 0) result.push({ topic: null, lessons: loose });
    return result;
  }, [lessons, topics]);

  const ordered = useMemo(() => groups.flatMap((group) => group.lessons), [groups]);
  const needle = query.trim().toLocaleLowerCase("ru");
  const visible = useMemo(() => groups
    .map((group) => ({
      ...group,
      lessons: needle && !(group.topic?.title ?? "").toLocaleLowerCase("ru").includes(needle)
        ? group.lessons.filter((lesson) => lesson.title.toLocaleLowerCase("ru").includes(needle))
        : group.lessons,
    }))
    .filter((group) => group.lessons.length > 0), [groups, needle]);
  const visibleIds = visible.flatMap((group) => group.lessons.map((lesson) => lesson.id));
  const allVisibleChosen = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));

  function toggle(ids: string[], value: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (value) next.add(id); else next.delete(id);
      }
      return next;
    });
  }

  async function download() {
    const ids = ordered.filter((lesson) => selected.has(lesson.id)).map((lesson) => lesson.id);
    if (ids.length === 0) return;
    setBusy(true);
    setError("");
    try {
      saveFile(await exportLessons(projectId, { lesson_ids: ids, format, sources, answers }));
      onOpenChange(false);
    } catch (caught) {
      setError(errorText(caught, "Файл не собрался"));
    } finally {
      setBusy(false);
    }
  }

  const count = selected.size;
  const textual = format !== "tentex";
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => { if (!busy) onOpenChange(next); }}
      title="Экспорт уроков"
      description="Отмеченные уроки собираются в один файл в порядке программы."
      className="lesson-export-dialog"
      footer={(
        <>
          {error && <p className="inline-error" role="alert">{error}</p>}
          <span className="lesson-export-count">{count === 0 ? "Уроки не выбраны" : count === 1 ? "1 урок" : `Уроков: ${count} — одним файлом`}</span>
          <Button variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>Отмена</Button>
          <Button disabled={busy || count === 0} onClick={() => void download()}>
            {busy ? "Собираем файл…" : "Скачать"}
          </Button>
        </>
      )}
    >
      {lessons.length === 0 ? (
        <EmptyState title="В проекте пока нет уроков">
          <p>Соберите урок по теме — и его можно будет выгрузить.</p>
        </EmptyState>
      ) : (
        <div className="lesson-export-body">
          <section className="lesson-export-pick" aria-label="Какие уроки">
            <div className="lesson-export-tools">
              <label className="workspace-tree-search">
                <Search size={15} />
                <span className="sr-only">Найти урок</span>
                <input type="search" placeholder="Найти урок или тему" value={query} onChange={(event) => setQuery(event.target.value)} />
                {query && <button type="button" onClick={() => setQuery("")} aria-label="Очистить поиск"><X size={14} /></button>}
              </label>
              <Button variant="ghost" onClick={() => toggle(visibleIds, !allVisibleChosen)} disabled={visibleIds.length === 0}>
                {allVisibleChosen ? "Снять все" : needle ? "Отметить найденные" : "Отметить все"}
              </Button>
            </div>
            <div className="lesson-export-list">
              {visible.length === 0 && <p className="lesson-export-empty">Ничего не нашлось.</p>}
              {visible.map((group) => (
                <div className="lesson-export-group" key={group.topic?.id ?? "loose"}>
                  <p className="lesson-export-topic">
                    {group.topic ? <><span>{group.topic.number}</span> {group.topic.title}</> : "Тема вне программы"}
                  </p>
                  {group.lessons.map((lesson) => (
                    <div className="lesson-export-row" key={lesson.id}>
                      <Checkbox
                        label={lesson.title}
                        checked={selected.has(lesson.id)}
                        onCheckedChange={(value) => toggle([lesson.id], value)}
                      />
                      <small className={`lesson-export-status is-${lesson.status}`}>{LESSON_STATUS_LABELS[lesson.status]}</small>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </section>
          <section className="lesson-export-options" aria-label="Формат">
            <RadioCards label="Формат файла" value={format} options={FORMATS} onChange={setFormat} layout="rows" className="lesson-export-formats" />
            <div className={`lesson-export-settings${textual ? "" : " is-disabled"}`}>
              <label className="lesson-export-field">
                <span>Материал учебника</span>
                <Select
                  ariaLabel="Как показать куски материала"
                  value={sources}
                  disabled={!textual}
                  options={SOURCE_OPTIONS}
                  onValueChange={(value) => { if (value) setSources(value as LessonExportSources); }}
                />
              </label>
              <Switch
                label="Ответы к заданиям"
                hint="Отдельным разделом в конце урока"
                checked={answers}
                disabled={!textual}
                onCheckedChange={setAnswers}
              />
            </div>
            {!textual && (
              <p className="lesson-export-note">
                Материал в файл не входит: в другой установке кусок станет живой ссылкой, если там есть тот же файл учебника, иначе — снимком текста.
              </p>
            )}
          </section>
        </div>
      )}
    </Dialog>
  );
}
