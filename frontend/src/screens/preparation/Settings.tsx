/** Все ограничения календаря редактируются явно: сон не подменяет дневной бюджет. */
import { useState } from "react";
import { Button, Field, Select, ErrorState } from "../../components/ui";
import {
  preparation,
  errorText,
  type Config,
  type Overview,
} from "../../api/preparation";
const weekdays = [
  "Понедельник",
  "Вторник",
  "Среда",
  "Четверг",
  "Пятница",
  "Суббота",
  "Воскресенье",
];
export function Settings({
  overview,
  onSaved,
}: {
  overview: Overview;
  onSaved: () => void;
}) {
  const [config, setConfig] = useState(overview.settings.config);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [exception, setException] = useState({
    date: overview.today,
    minutes: 0,
  });
  const patch = (value: Partial<Config>) =>
    setConfig((current) => ({ ...current, ...value }));
  async function save() {
    setBusy(true);
    try {
      await preparation.settings(overview.project_id, {
        expected_revision: overview.settings.revision,
        config,
      });
      onSaved();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="prep-settings">
      {error && <ErrorState title="Настройки не сохранены" message={error} />}
      <Field label="Дневной бюджет, минут">
        <input
          type="number"
          min={0}
          max={1440}
          value={config.daily_minutes ?? ""}
          placeholder="Например, 90"
          onChange={(event) =>
            patch({
              daily_minutes:
                event.target.value === "" ? null : Number(event.target.value),
            })
          }
        />
      </Field>
      <details open>
        <summary>Сон и учебный день</summary>
        <Field label="Часовой пояс">
          <input
            value={config.timezone}
            onChange={(event) => patch({ timezone: event.target.value })}
          />
        </Field>
        {(
          [
            ["day_boundary", "Начало учебного дня"],
            ["sleep_start", "Ложусь спать"],
            ["sleep_end", "Просыпаюсь"],
          ] as const
        ).map(([key, label]) => (
          <Field key={key} label={label}>
            <input
              type="time"
              value={config[key]?.slice(0, 5)}
              onChange={(event) => patch({ [key]: event.target.value })}
            />
          </Field>
        ))}
      </details>
      <details>
        <summary>Бюджет по дням недели</summary>
        {weekdays.map((day, index) => (
          <Field key={day} label={day}>
            <input
              type="number"
              min={0}
              max={1440}
              placeholder="Обычный бюджет"
              value={config.weekday_minutes?.[index] ?? ""}
              onChange={(event) => {
                const next = { ...config.weekday_minutes };
                if (event.target.value === "") delete next[index];
                else next[index] = Number(event.target.value);
                patch({ weekday_minutes: next });
              }}
            />
          </Field>
        ))}
      </details>
      <details>
        <summary>Исключения и отдых</summary>
        <Field label="Дата">
          <input
            type="date"
            value={exception.date}
            onChange={(event) =>
              setException({ ...exception, date: event.target.value })
            }
          />
        </Field>
        <Field label="Минут">
          <input
            type="number"
            min={0}
            max={1440}
            value={exception.minutes}
            onChange={(event) =>
              setException({
                ...exception,
                minutes: Number(event.target.value),
              })
            }
          />
        </Field>
        <Button
          variant="ghost"
          onClick={() =>
            patch({
              date_minutes: {
                ...config.date_minutes,
                [exception.date]: exception.minutes,
              },
            })
          }
        >
          Задать бюджет даты
        </Button>
        <Button
          variant="ghost"
          onClick={() =>
            patch({
              rest_dates: [
                ...new Set([...(config.rest_dates ?? []), exception.date]),
              ],
            })
          }
        >
          Добавить отдых
        </Button>
        {Object.entries(config.date_minutes ?? {}).map(([date, minutes]) => (
          <p key={date}>
            {date}: {minutes} мин{" "}
            <Button
              variant="ghost"
              onClick={() => {
                const next = { ...config.date_minutes };
                delete next[date];
                patch({ date_minutes: next });
              }}
            >
              Убрать
            </Button>
          </p>
        ))}
        {config.rest_dates?.map((date) => (
          <p key={date}>
            {date} · отдых{" "}
            <Button
              variant="ghost"
              onClick={() =>
                patch({
                  rest_dates: config.rest_dates?.filter(
                    (item) => item !== date,
                  ),
                })
              }
            >
              Убрать
            </Button>
          </p>
        ))}
      </details>
      <details>
        <summary>Занятые часы</summary>
        {config.busy_windows?.map((window, index) => (
          <div className="prep-card" key={index}>
            <Field label="Начало">
              <input
                type="time"
                value={window.start.slice(0, 5)}
                onChange={(event) =>
                  patch({
                    busy_windows: config.busy_windows?.map((item, i) =>
                      i === index
                        ? { ...item, start: event.target.value }
                        : item,
                    ),
                  })
                }
              />
            </Field>
            <Field label="Конец">
              <input
                type="time"
                value={window.end.slice(0, 5)}
                onChange={(event) =>
                  patch({
                    busy_windows: config.busy_windows?.map((item, i) =>
                      i === index ? { ...item, end: event.target.value } : item,
                    ),
                  })
                }
              />
            </Field>
            <Select
              ariaLabel="День занятых часов"
              value={window.weekday == null ? null : String(window.weekday)}
              emptyOption="Каждый день"
              options={weekdays.map((label, value) => ({
                label,
                value: String(value),
              }))}
              onValueChange={(day) =>
                patch({
                  busy_windows: config.busy_windows?.map((item, i) =>
                    i === index
                      ? { ...item, weekday: day === null ? null : Number(day) }
                      : item,
                  ),
                })
              }
            />
            <Field label="Только в дату (необязательно)">
              <input
                type="date"
                value={window.on_date ?? ""}
                onChange={(event) =>
                  patch({
                    busy_windows: config.busy_windows?.map((item, i) =>
                      i === index
                        ? { ...item, on_date: event.target.value || null }
                        : item,
                    ),
                  })
                }
              />
            </Field>
            <Button
              variant="ghost"
              onClick={() =>
                patch({
                  busy_windows: config.busy_windows?.filter(
                    (_, i) => i !== index,
                  ),
                })
              }
            >
              Убрать интервал
            </Button>
          </div>
        ))}
        <Button
          variant="ghost"
          onClick={() =>
            patch({
              busy_windows: [
                ...(config.busy_windows ?? []),
                { start: "09:00", end: "18:00", weekday: null, on_date: null },
              ],
            })
          }
        >
          Добавить интервал
        </Button>
      </details>
      <details>
        <summary>Нагрузка и экзамен</summary>
        {(
          [
            ["max_new_per_day", "Новых за день", 1, 10000],
            ["max_reviews_per_day", "Повторений за день", 1, 10000],
            ["max_interval_days", "Максимальный интервал, дней", 1, 3650],
            ["exam_reserve_minutes", "Резерв перед экзаменом, минут", 0, 1440],
            ["final_day_ratio", "Доля бюджета накануне экзамена", 0, 1],
          ] as const
        ).map(([key, label, min, max]) => (
          <Field key={key} label={label}>
            <input
              type="number"
              min={min}
              max={max}
              step={key === "final_day_ratio" ? 0.1 : 1}
              value={config[key]}
              onChange={(event) => patch({ [key]: Number(event.target.value) })}
            />
          </Field>
        ))}
        <label className="prep-check">
          <input
            type="checkbox"
            checked={config.exam_day_enabled}
            onChange={(event) =>
              patch({ exam_day_enabled: event.target.checked })
            }
          />
          Заниматься в день экзамена
        </label>
      </details>
      <Field label="Что делать с долгом">
        <Select
          value={config.debt_rule}
          ariaLabel="Правило долга"
          options={[
            { value: "spread", label: "Распределить" },
            { value: "catch_up", label: "Наверстать" },
            { value: "dismiss", label: "Снять назначения" },
          ]}
          onValueChange={(value) =>
            patch({ debt_rule: value as Config["debt_rule"] })
          }
        />
      </Field>
      <Field label="Тон наставника">
        <Select
          value={config.coach_tone}
          ariaLabel="Тон наставника"
          options={[
            { value: "calm", label: "Спокойный" },
            { value: "gentle", label: "Мягкий" },
            { value: "strict", label: "Строгий" },
          ]}
          onValueChange={(value) =>
            patch({ coach_tone: value as Config["coach_tone"] })
          }
        />
      </Field>
      <details>
        <summary>Пожелания к ИИ</summary>
        {[
          ["phases", "Блоки"],
          ["distribute", "Распределение"],
          ["coach", "Наставник"],
        ].map(([key, label]) => (
          <Field key={key} label={label}>
            <textarea
              value={config.ai_instructions?.[key] ?? ""}
              onChange={(event) =>
                patch({
                  ai_instructions: {
                    ...config.ai_instructions,
                    [key]: event.target.value,
                  },
                })
              }
            />
          </Field>
        ))}
      </details>
      <Button disabled={busy || overview.readonly} onClick={() => void save()}>
        {busy ? "Сохраняем…" : "Сохранить параметры"}
      </Button>
    </div>
  );
}
