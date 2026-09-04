import { getProject, type ProgramNodeRead } from "../../api/projects";
/** Фильтры передаются серверу до пагинации и сохраняются в адресе экрана. */
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import {
  Button,
  Dialog,
  Field,
  Select,
  ErrorState,
  LoadingState,
  ConfirmDialog,
} from "../../components/ui";
import {
  preparation,
  activityLabels,
  outcomeLabels,
  errorText,
  type Activity,
  type Overview,
  type Schema,
} from "../../api/preparation";
import { ManualActivityDialog } from "./ManualActivityDialog";
import { AttemptDetails } from "./AttemptDetails";
const PAGE_SIZE = 30;
const filters = [
  "date_from",
  "date_to",
  "section_id",
  "node_id",
  "kind",
  "outcome",
  "method",
  "q",
  "answer_mode",
  "disputed",
] as const;
export function History({
  overview,
  onChanged,
}: {
  overview: Overview;
  onChanged: () => void;
}) {
  const [params, setParams] = useSearchParams();
  const [sections, setSections] = useState<ProgramNodeRead[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    getProject(overview.project_id, controller.signal)
      .then((detail) => {
        if (!controller.signal.aborted)
          setSections(
            detail.program.nodes.filter((node) => node.node_type === "section"),
          );
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorText(caught));
      });
    return () => controller.abort();
  }, [overview.project_id]);
  const [result, setResult] = useState<Schema["HistoryRead"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [manual, setManual] = useState<Activity | "new" | null>(null);
  const [deleting, setDeleting] = useState<Activity | null>(null);
  const [selected, setSelected] = useState<Activity[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [compare, setCompare] = useState(false);
  const query = new URLSearchParams();
  filters.forEach((key) => {
    const value = params.get(key);
    if (value) query.set(key, value);
  });
  query.set("offset", params.get("offset") ?? "0");
  query.set("limit", String(PAGE_SIZE));
  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    preparation
      .history(
        overview.project_id,
        new URLSearchParams(query.toString()),
        controller.signal,
      )
      .then((value) => {
        setResult(value);
        setError(null);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorText(caught));
      });
    return () => controller.abort();
  }, [overview.project_id, query.toString(), version]);
  const update = (key: string, value: string | null) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value) next.set(key, value);
        else next.delete(key);
        if (key !== "offset") next.delete("offset");
        return next;
      },
      { replace: true },
    );
  const refresh = () => {
    setVersion((value) => value + 1);
    onChanged();
  };
  return (
    <section className="prep-history">
      <header className="prep-section-head">
        <h2>История занятий</h2>
        <Button
          variant="secondary"
          disabled={overview.readonly}
          onClick={() => setManual("new")}
        >
          Добавить занятие
        </Button>
        <Button
          variant="ghost"
          disabled={selected.length !== 2}
          onClick={() => setCompare(true)}
        >
          Сравнить две попытки
        </Button>
      </header>
      <div className="prep-filters">
        <Field label="С даты">
          <input
            type="date"
            value={params.get("date_from") ?? ""}
            onChange={(event) => update("date_from", event.target.value)}
          />
        </Field>
        <Field label="По дату">
          <input
            type="date"
            value={params.get("date_to") ?? ""}
            onChange={(event) => update("date_to", event.target.value)}
          />
        </Field>
        <Field label="Раздел">
          <Select
            value={params.get("section_id")}
            emptyOption="Все разделы"
            ariaLabel="Раздел истории"
            options={sections.map((node) => ({
              value: node.id,
              label: node.title,
            }))}
            onValueChange={(value) => update("section_id", value)}
          />
        </Field>
        <Field label="Вопрос">
          <Select
            value={params.get("node_id")}
            emptyOption="Все вопросы"
            ariaLabel="Вопрос истории"
            options={overview.topics.map((topic) => ({
              value: topic.node_id,
              label: topic.title,
            }))}
            onValueChange={(value) => update("node_id", value)}
          />
        </Field>
        <Field label="Занятие">
          <Select
            value={params.get("kind")}
            emptyOption="Все занятия"
            ariaLabel="Вид занятия истории"
            options={Object.entries(activityLabels).map(([value, label]) => ({
              value,
              label,
            }))}
            onValueChange={(value) => update("kind", value)}
          />
        </Field>
        <Field label="Результат">
          <Select
            value={params.get("outcome")}
            emptyOption="Все результаты"
            ariaLabel="Результат"
            options={Object.entries(outcomeLabels).map(([value, label]) => ({
              value,
              label,
            }))}
            onValueChange={(value) => update("outcome", value)}
          />
        </Field>
        <Field label="Проверка">
          <Select
            value={params.get("method")}
            emptyOption="Все методы"
            ariaLabel="Метод проверки"
            options={[
              "exact_match",
              "key_terms",
              "sql",
              "semantic",
              "ai_judge",
              "self_assessment",
            ].map((value) => ({
              value,
              label:
                {
                  exact_match: "Точное совпадение",
                  key_terms: "Ключевые термины",
                  sql: "SQL",
                  semantic: "Семантическая",
                  ai_judge: "ИИ-судья",
                  self_assessment: "Самооценка",
                }[value] ?? value,
            }))}
            onValueChange={(value) => update("method", value)}
          />
        </Field>
        <Field label="Режим ответа">
          <Select
            value={params.get("answer_mode")}
            emptyOption="Все режимы"
            ariaLabel="Режим ответа"
            options={[
              { value: "memory", label: "По памяти" },
              { value: "supported", label: "С опорой" },
            ]}
            onValueChange={(value) => update("answer_mode", value)}
          />
        </Field>
        <label className="prep-check">
          <input
            type="checkbox"
            checked={params.get("disputed") === "true"}
            onChange={(event) =>
              update("disputed", event.target.checked ? "true" : null)
            }
          />
          Спорные оценки
        </label>
        <Field label="Поиск по ответу и заметке">
          <input
            value={params.get("q") ?? ""}
            onChange={(event) => update("q", event.target.value)}
          />
        </Field>
      </div>
      <Button
        variant="ghost"
        onClick={() =>
          setParams((current) => {
            const next = new URLSearchParams(current);
            filters.forEach((key) => next.delete(key));
            next.delete("offset");
            return next;
          })
        }
      >
        Сбросить фильтры
      </Button>
      {error && <ErrorState title="История не загрузилась" message={error} />}{" "}
      {!result && !error && <LoadingState label="Загружаем историю" />}
      {result?.items.map((activity) => (
        <article className="prep-history-row" key={activity.id}>
          <header>
            {activity.attempt_id && (
              <input
                aria-label={`Сравнить попытку ${activity.title}`}
                type="checkbox"
                checked={selected.some((item) => item.id === activity.id)}
                disabled={
                  selected.length === 2 &&
                  !selected.some((item) => item.id === activity.id)
                }
                onChange={(event) =>
                  setSelected((current) =>
                    event.target.checked
                      ? [...current, activity]
                      : current.filter((item) => item.id !== activity.id),
                  )
                }
              />
            )}
            <strong>{activity.title}</strong>
            <span>
              {activityLabels[activity.kind] ?? activity.kind} ·{" "}
              {new Date(activity.occurred_at).toLocaleString("ru-RU")}
            </span>
            <span>
              {activity.seconds === null
                ? "Время не измерено"
                : `${Math.round(activity.seconds / 60)} мин`}
            </span>
          </header>
          <p>{activity.note}</p>
          {activity.outcome && (
            <p>
              {outcomeLabels[activity.outcome] ?? activity.outcome} ·{" "}
              {activity.answer_mode === "memory"
                ? "По памяти"
                : activity.answer_mode === "supported"
                  ? "С опорой"
                  : "Режим не указан"}
              {activity.self_assessment
                ? ` · Самооценка: ${outcomeLabels[activity.self_assessment] ?? activity.self_assessment}`
                : ""}
            </p>
          )}
          <div className="prep-actions">
            {activity.attempt_id && (
              <Button
                variant="ghost"
                onClick={() =>
                  setExpanded(expanded === activity.id ? null : activity.id)
                }
              >
                Ответ и разбор
              </Button>
            )}
            {activity.kind === "manual" && !overview.readonly && (
              <>
                <Button variant="ghost" onClick={() => setManual(activity)}>
                  Изменить
                </Button>
                <Button variant="ghost" onClick={() => setDeleting(activity)}>
                  Удалить
                </Button>
              </>
            )}
          </div>
          {expanded === activity.id && (
            <AttemptDetails
              projectId={overview.project_id}
              activity={activity}
            />
          )}
        </article>
      ))}
      {result?.total === 0 && (
        <p>
          По выбранным фильтрам занятий нет. Измените период или добавьте
          занятие вручную.
        </p>
      )}
      {result && (
        <div className="prep-actions">
          <Button
            disabled={result.offset === 0}
            variant="ghost"
            onClick={() =>
              update("offset", String(Math.max(0, result.offset - PAGE_SIZE)))
            }
          >
            Назад
          </Button>
          <span>
            {result.total === 0 ? 0 : result.offset + 1}–
            {Math.min(result.offset + result.items.length, result.total)} из{" "}
            {result.total}
          </span>
          <Button
            variant="ghost"
            disabled={result.offset + result.items.length >= result.total}
            onClick={() => update("offset", String(result.offset + PAGE_SIZE))}
          >
            Далее
          </Button>
        </div>
      )}
      {manual && (
        <ManualActivityDialog
          projectId={overview.project_id}
          topics={overview.topics}
          activity={manual === "new" ? undefined : manual}
          onClose={() => setManual(null)}
          onSaved={refresh}
        />
      )}
      {deleting && (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open) setDeleting(null);
          }}
          title="Удалить ручное занятие?"
          confirmLabel="Удалить занятие"
          destructive
          onConfirm={async () => {
            try {
              await preparation.deleteActivity(
                overview.project_id,
                deleting.id,
              );
              refresh();
              setDeleting(null);
            } catch (caught) {
              setError(errorText(caught));
              throw caught;
            }
          }}
        >
          <p>
            Запись «{deleting.note || deleting.title}» и её время будут удалены.
          </p>
        </ConfirmDialog>
      )}
      {compare && (
        <Dialog
          open
          onOpenChange={setCompare}
          title="Сравнение попыток"
          className="prep-dialog"
        >
          <div className="prep-comparison">
            {selected.map((activity) => (
              <AttemptDetails
                key={activity.id}
                projectId={overview.project_id}
                activity={activity}
              />
            ))}
          </div>
        </Dialog>
      )}
    </section>
  );
}
