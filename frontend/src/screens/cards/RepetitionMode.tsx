import { useEffect, useMemo, useState } from "react";
import { ArrowRight, BarChart3, Clock3, Play } from "lucide-react";
import {
  createCardSession,
  type CardOverviewRead,
  type CardSessionCreate,
  type CardSessionRead,
} from "../../api/cards";
import {
  Button,
  Checkbox,
  Dialog,
  Disclosure,
  EmptyState,
  PageHead,
  RadioCards,
  SegmentedTabs,
  StackedColumns,
} from "../../components/ui";

interface RepetitionModeProps {
  projectId: string;
  overview: CardOverviewRead;
  period: 7 | 30;
  onPeriodChange: (period: 7 | 30) => void;
  onStart: (session: CardSessionRead) => void;
  onContinue: () => void;
  onOpenBank: (cardId: string) => void;
  onCreate: (unitId?: string | null) => void;
}

type Scope = CardSessionCreate["scope"];
type Pace = CardSessionCreate["pace"];
type Duration = "5" | "10" | "15" | "all";

const GRADE_META: Array<{ label: string; token: string }> = [
  { label: "Не вспомнил", token: "--tone-danger" },
  { label: "Частично", token: "--tone-warning" },
  { label: "Вспомнил", token: "--tone-success" },
  { label: "Легко", token: "--accent" },
];

function plural(value: number, one: string, few: string, many: string): string {
  const mod100 = value % 100;
  const mod10 = value % 10;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

function defaultScope(overview: CardOverviewRead): Scope {
  if (overview.today_units.some((row) => row.card_count > 0)) return "today";
  if (overview.hard_cards.length) return "hard";
  return "all";
}

function coverageStatus(overview: CardOverviewRead): string {
  const total = overview.today_units.length;
  if (!overview.program_exists) return "Сначала добавьте вопросы экзамена";
  if (!overview.plan_exists) return "План подготовки пока не составлен";
  if (!total) return "На сегодня повторений не запланировано";
  if (!overview.covered_unit_count) {
    return `Для сегодняшних ${total} ${plural(total, "вопроса", "вопросов", "вопросов")} карточек пока нет`;
  }
  if (overview.covered_unit_count === total) {
    return `Карточки готовы для всех ${total} ${plural(total, "вопроса", "вопросов", "вопросов")}`;
  }
  return `Карточки есть для ${overview.covered_unit_count} из ${total} вопросов`;
}

export function RepetitionMode(props: RepetitionModeProps) {
  const {
    projectId,
    overview,
    period,
    onPeriodChange,
    onStart,
    onContinue,
    onOpenBank,
    onCreate,
  } = props;
  const [dialogOpen, setDialogOpen] = useState(false);
  const [scope, setScope] = useState<Scope>(() => defaultScope(overview));
  const [pace, setPace] = useState<Pace>("calm");
  const [duration, setDuration] = useState<Duration>("15");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectedUnitId, setSelectedUnitId] = useState(
    overview.today_units[0]?.unit.id ?? null,
  );
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!selectedUnitId && overview.today_units[0]) {
      setSelectedUnitId(overview.today_units[0].unit.id);
    }
  }, [overview.today_units, selectedUnitId]);

  const selectedToday = overview.today_units.find(
    (row) => row.unit.id === selectedUnitId,
  );
  const selectedCards = useMemo(
    () => overview.today_units.find((row) => row.unit.id === selectedUnitId)?.cards ?? [],
    [overview.today_units, selectedUnitId],
  );
  const laneCards = overview.today_units.length
    ? selectedCards
    : [...overview.hard_cards, ...overview.recent_cards].filter(
        (card, index, rows) => rows.findIndex((item) => item.id === card.id) === index,
      ).slice(0, 6);
  const missingToday = overview.today_units.filter((row) => !row.covered);
  const scopeCounts: Record<Scope, number> = {
    today: overview.today_units.reduce((sum, row) => sum + row.card_count, 0),
    hard: overview.hard_cards.length,
    selected: overview.units.filter((unit) => selected.has(unit.id)).length,
    all: overview.active_card_count,
  };

  async function start() {
    setStarting(true);
    setError("");
    try {
      const result = await createCardSession(projectId, {
        scope,
        selected_unit_ids: scope === "selected" ? [...selected] : [],
        pace,
        limit_minutes: duration === "all" ? null : Number(duration) as 5 | 10 | 15,
        replace_active: false,
      });
      setDialogOpen(false);
      onStart(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось начать сеанс");
    } finally {
      setStarting(false);
    }
  }

  const hasToday = overview.today_units.length > 0;
  const questionsWord = plural(overview.today_units.length, "вопрос", "вопроса", "вопросов");
  const cardsWord = plural(scopeCounts.today, "карточка", "карточки", "карточек");

  return (
    <div className="repetition-mode">
      <PageHead
        title="Карточки"
        actions={
          <Button onClick={overview.active_session ? onContinue : () => setDialogOpen(true)}>
            <Play size={15} />
            {overview.active_session ? "Продолжить сеанс" : "Начать сеанс"}
          </Button>
        }
      />

      <section className="repetition-intro" aria-labelledby="today-heading">
        <h2 id="today-heading">
          {hasToday ? (
            <>
              На сегодня <span className="repetition-figure">{overview.today_units.length} {questionsWord}</span>. По ним{" "}
              <span className="repetition-figure">{scopeCounts.today} {cardsWord}</span> — примерно{" "}
              <span className="repetition-figure">{overview.estimated_minutes} мин</span>.
            </>
          ) : (
            coverageStatus(overview)
          )}
        </h2>
        {hasToday && <p className="repetition-coverage">{coverageStatus(overview)}</p>}
        {!overview.program_exists ? (
          <Button variant="secondary" onClick={() => window.location.assign(`/projects/${projectId}/program`)}>
            Добавить вопросы
          </Button>
        ) : !overview.plan_exists ? (
          <>
            <p>Здесь появятся карточки по вопросам, которые вы запланируете повторить сегодня.</p>
            <Button variant="secondary" onClick={() => window.location.assign(`/projects/${projectId}/preparation`)}>
              Перейти в «Мою подготовку»
            </Button>
          </>
        ) : !hasToday ? (
          <p>Можно потренировать сложные, выбранные или все активные карточки.</p>
        ) : null}
      </section>

      <section className="repetition-lanes">
        <div className="repetition-lane">
          <header><div><h3>Сегодняшние вопросы</h3><p>В порядке календарного плана.</p></div></header>
          {overview.today_units.length ? (
            <ol className="repetition-queue-list">
              {overview.today_units.map((row, index) => (
                <li key={row.unit.id}>
                  <button
                    type="button"
                    className={selectedUnitId === row.unit.id ? "is-active" : ""}
                    onClick={() => setSelectedUnitId(row.unit.id)}
                  >
                    <span className="repetition-queue-top">
                      <span className="repetition-queue-number">{index + 1}</span>
                      <strong>{row.unit.title}</strong>
                    </span>
                    <span className="repetition-queue-count">{row.card_count} карт.</span>
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            <EmptyState title="Сегодняшняя лента пуста">
              <p>Назначьте повторения в календаре или запустите одну из свободных подборок.</p>
            </EmptyState>
          )}
        </div>
        <div className="repetition-lane">
          <header>
            <div>
              <h3>{selectedToday ? selectedToday.unit.title : "Недавние и сложные"}</h3>
              <p>{selectedToday ? "Карточки выбранного вопроса." : "Короткая подборка без календарного назначения."}</p>
            </div>
          </header>
          {laneCards.length ? (
            <div className="repetition-card-list">
              {laneCards.map((card) => (
                <button type="button" key={card.id} onClick={() => onOpenBank(card.id)}>
                  <strong>{card.front}</strong>
                  <span>{card.source.label}</span>
                  <small>{card.last_confidence ? `Последняя оценка: ${card.last_confidence}` : "Без оценок"}</small>
                  <ArrowRight size={15} />
                </button>
              ))}
            </div>
          ) : selectedToday ? (
            <EmptyState title="У вопроса пока нет карточек">
              <p>Создайте первую вручную — вопрос уже будет выбран.</p>
              <Button onClick={() => onCreate(selectedToday.unit.id)}>Создать карточку</Button>
            </EmptyState>
          ) : (
            <EmptyState title="Карточек пока нет"><p>Создайте первую карточку вручную.</p><Button onClick={() => onCreate(null)}>Создать</Button></EmptyState>
          )}
        </div>
      </section>

      <section className="cards-analytics">
        <header>
          <div><BarChart3 size={17} /><div><h3>Аналитика</h3><p>{overview.analytics.observation_count} оценок в выборке</p></div></div>
          <SegmentedTabs
            label="Период аналитики"
            value={String(period)}
            onChange={(value) => onPeriodChange(Number(value) as 7 | 30)}
            tabs={[{ value: "7", label: "7 дней" }, { value: "30", label: "30 дней" }]}
          />
        </header>
        {overview.analytics.observation_count ? (
          <div className="cards-analytics-body">
            <ul className="cards-analytics-legend">
              {GRADE_META.map((grade) => (
                <li key={grade.label}>
                  <i style={{ background: `var(${grade.token})` }} />
                  {grade.label}
                </li>
              ))}
            </ul>
            <StackedColumns
              ariaLabel="Оценки уверенности по карточкам"
              height={96}
              data={overview.analytics.distribution.map((bucket, index) => ({
                key: String(bucket.confidence),
                label: GRADE_META[index].label,
                segments: [{ value: bucket.count, token: GRADE_META[index].token }],
                tooltip: `${GRADE_META[index].label}: ${bucket.count}`,
              }))}
            />
            <Disclosure
              className="cards-analytics-hard"
              summary={`Сложные карточки (${overview.analytics.hard_card_count})`}
            >
              {overview.hard_cards.length ? (
                <ul className="cards-analytics-hard-list">
                  {overview.hard_cards.map((card) => (
                    <li key={card.id}>
                      <button type="button" onClick={() => onOpenBank(card.id)}>{card.front}</button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="cards-analytics-hard-empty">Сложных карточек нет.</p>
              )}
            </Disclosure>
          </div>
        ) : (
          <p className="cards-analytics-empty">Пока нет оценок. Аналитика появится после первого сеанса.</p>
        )}
      </section>

      <Dialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="Начать сеанс"
        description="Состав фиксируется при старте и сохранится после перезагрузки."
        className="cards-session-dialog"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>Отменить</Button>
            <Button disabled={starting || scopeCounts[scope] === 0} onClick={() => void start()}>
              {starting ? "Начинаем…" : `Начать · ${scopeCounts[scope]}`}
            </Button>
          </>
        }
      >
        <div className="cards-session-settings">
          <RadioCards
            label="Состав сеанса"
            value={scope}
            onChange={setScope}
            layout="rows"
            options={[
              { value: "today", title: "На сегодня", description: `${scopeCounts.today} активных карточек по календарю` },
              { value: "hard", title: "Сложные", description: `${scopeCounts.hard} карточек с последней оценкой 1–2` },
              { value: "selected", title: "Выбранные", description: "Вопросы и целые билеты из дерева программы" },
              { value: "all", title: "Все", description: `${scopeCounts.all} активных карточек по порядку программы` },
            ]}
          />
          {scope === "selected" && (
            <section className="cards-question-picker">
              {overview.units.map((unit) => (
                <div key={unit.id}>
                  <Checkbox
                    checked={selected.has(unit.id)}
                    onCheckedChange={(checked) => {
                      setSelected((current) => {
                        const next = new Set(current);
                        if (checked) next.add(unit.id); else next.delete(unit.id);
                        return next;
                      });
                    }}
                    label={unit.title}
                  />
                  <small>{unit.path.join(" · ")}{unit.kind === "ticket" ? " · билет целиком" : ""}</small>
                </div>
              ))}
            </section>
          )}
          {scope === "today" && missingToday.length > 0 && (
            <div className="cards-missing-list">
              <strong>Без карточек и будут пропущены:</strong>
              <span>{missingToday.map((row) => row.unit.title).join(", ")}</span>
            </div>
          )}
          <section className="cards-setting-row">
            <div><h3>Длительность</h3><p>После лимита закончим текущий вопрос и предложим выбор.</p></div>
            <SegmentedTabs label="Длительность" value={duration} onChange={setDuration} tabs={[
              { value: "5", label: "5 мин" }, { value: "10", label: "10 мин" },
              { value: "15", label: "15 мин" }, { value: "all", label: "Без ограничения" },
            ]} />
          </section>
          <section className="cards-setting-row">
            <div>
              <h3>Темп</h3>
              <p>{pace === "calm" ? "Подсказки, источники и редактирование всегда видимы." : "Вторичные сведения свёрнуты; акцент на клавиатуре и карточке."}</p>
            </div>
            <SegmentedTabs label="Темп" value={pace} onChange={setPace} tabs={[
              { value: "calm", label: "Спокойный" }, { value: "fast", label: "Быстрый" },
            ]} />
          </section>
          {error && <p className="cards-form-error" role="alert">{error}</p>}
          <p className="cards-dialog-note"><Clock3 size={14} /> Активное время не считает паузу по бездействию.</p>
        </div>
      </Dialog>
    </div>
  );
}
