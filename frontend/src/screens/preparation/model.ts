/** Производные сведения экрана подготовки: один серверный снимок — все числа отсюда. */
import type { Overview, Phase, PlanItem, Unit } from "../../api/preparation";
import { purposeOf, type Purpose } from "../../components/domain";
import { addDays, dayNumber } from "./dates";

/** Склонение существительного при числе: «1 вопрос», «2 вопроса», «5 вопросов». */
export function plural(count: number, one: string, few: string, many: string) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

/** Дробное число по-русски: запятая, а не точка. */
export const decimal = (value: number, digits = 1) =>
  value.toFixed(digits).replace(".", ",");

export const WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
export const WEEKDAYS_LONG = [
  "понедельник",
  "вторник",
  "среда",
  "четверг",
  "пятница",
  "суббота",
  "воскресенье",
];

/** Состояние учебного дня по §7.9: цвет карточки в календаре. */
export type DayState = "empty" | "planned" | "partial" | "done" | "missed";

export interface DayFacts {
  date: string;
  /** Число месяца. */
  day: number;
  weekdayIndex: number;
  monthKey: string;
  isPast: boolean;
  isToday: boolean;
  isExam: boolean;
  /** Дата явно отмечена пропускаемой пользователем. */
  isRest: boolean;
  /** Бюджет дня нулевой: выходной по расписанию, но не отмеченный пропуск. */
  isOffDay: boolean;
  /** Уникальных вопросов, назначенных на дату. */
  planned: number;
  opened: number;
  tickets: number;
  seconds: number;
  plannedMinutes: number;
  purpose: Purpose;
  phaseTitle: string | null;
  state: DayState;
}

export const monthLabel = (key: string) =>
  new Date(`${key}-01T12:00:00Z`).toLocaleDateString("ru-RU", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

export const weekdayIndexOf = (date: string) =>
  (new Date(`${date}T12:00:00Z`).getUTCDay() + 6) % 7;

export const dayOfMonth = (date: string) => Number(date.slice(8, 10));

export const longDateLabel = (date: string) =>
  new Date(`${date}T12:00:00Z`).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  });

/** Список дат от `start` до `end` включительно. */
export function datesBetween(start: string, end: string): string[] {
  const result: string[] = [];
  let cursor = start;
  let guard = 0;
  while (cursor <= end && guard < 800) {
    result.push(cursor);
    cursor = addDays(cursor, 1);
    guard += 1;
  }
  return result;
}

/** Назначения, сгруппированные по дате: уникальные вопросы и виды работы. */
export interface DayAssignments {
  items: PlanItem[];
  units: Set<string>;
  openedUnits: Set<string>;
  kinds: Set<string>;
}

export function assignmentsByDate(overview: Overview): Map<string, DayAssignments> {
  const completed = new Set(overview.plan.completed_ids);
  const map = new Map<string, DayAssignments>();
  for (const item of overview.plan.items) {
    let bucket = map.get(item.on_date);
    if (!bucket) {
      bucket = { items: [], units: new Set(), openedUnits: new Set(), kinds: new Set() };
      map.set(item.on_date, bucket);
    }
    bucket.items.push(item);
    bucket.units.add(item.unit_id);
    bucket.kinds.add(item.kind);
    if (completed.has(item.id)) bucket.openedUnits.add(item.unit_id);
  }
  return map;
}

/** Блок подготовки, накрывающий дату. */
function phaseAt(overview: Overview, date: string) {
  return overview.plan.phases.find((phase) => phase.start <= date && date <= phase.end) ?? null;
}

/**
 * Полное описание дней от `start` до `end`.
 *
 * Состояние считается по открытиям, а не по сдачам ответов: §3.3 «открыл —
 * зелёный». День без назначений цвета не получает и пропуском не считается.
 */
export function buildDays(overview: Overview, start: string, end: string): DayFacts[] {
  const assignments = assignmentsByDate(overview);
  const loads = new Map(overview.days.map((day) => [day.date, day]));
  const rest = new Set(overview.settings.config.rest_dates ?? []);
  const units = new Map(overview.units.map((unit) => [unit.id, unit]));
  return datesBetween(start, end).map((date) => {
    const bucket = assignments.get(date);
    const load = loads.get(date);
    const planned = bucket ? bucket.units.size : 0;
    const opened = bucket ? bucket.openedUnits.size : 0;
    const isPast = date < overview.today;
    // «Пропуск» — только явная отметка пользователя. Нулевой бюджет выходного
    // сервер тоже помечает `is_rest`, но это не пропущенный день.
    const isRest = rest.has(date);
    const isOffDay = !isRest && (load?.is_rest ?? false);
    let state: DayState = "empty";
    if (planned > 0) {
      if (opened >= planned) state = "done";
      else if (opened > 0) state = "partial";
      else state = isPast ? "missed" : "planned";
    }
    const phase = phaseAt(overview, date);
    return {
      date,
      day: dayOfMonth(date),
      weekdayIndex: weekdayIndexOf(date),
      monthKey: date.slice(0, 7),
      isPast,
      isToday: date === overview.today,
      isExam: overview.deadline === date,
      isRest,
      isOffDay,
      planned,
      opened,
      tickets: bucket
        ? [...bucket.units].filter((id) => units.get(id)?.kind === "ticket").length
        : 0,
      seconds: load?.active_seconds ?? 0,
      plannedMinutes: load?.planned_minutes ?? 0,
      purpose: bucket ? purposeOf(bucket.kinds) : "none",
      phaseTitle: phase?.title ?? null,
      state,
    };
  });
}

/** Долг — неоткрытые назначения прошлых дат, и ничего больше. */
export function debtOf(overview: Overview) {
  const completed = new Set(overview.plan.completed_ids);
  const items = overview.plan.items.filter(
    (item) => item.on_date < overview.today && !completed.has(item.id),
  );
  const units = new Set(items.map((item) => item.unit_id));
  const dates = [...new Set(items.map((item) => item.on_date))].sort();
  return { items, units, dates, count: units.size };
}

export interface SectionStat {
  title: string;
  total: number;
  opened: number;
  assigned: number;
}

/** Вопрос считается открытым, если по нему есть занятие или отметка разбора. */
const topicOpened = (topic: Overview["topics"][number]) =>
  topic.status !== "unseen" || topic.active_seconds > 0;

/** Состав программы по разделам экзамена: открыто, назначено, не в плане. */
export function sectionStats(overview: Overview): SectionStat[] {
  const openedIds = new Set(overview.days.flatMap(day => day.opened_topic_ids ?? []));
  const assignedUnits = new Set(overview.plan.items.map((item) => item.unit_id));
  const order: string[] = [];
  const map = new Map<string, SectionStat>();
  for (const topic of overview.topics) {
    const title = topic.path[0] ?? "Без раздела";
    let stat = map.get(title);
    if (!stat) {
      stat = { title, total: 0, opened: 0, assigned: 0 };
      map.set(title, stat);
      order.push(title);
    }
    stat.total += 1;
    if (openedIds.has(topic.node_id) || topicOpened(topic)) stat.opened += 1;
    else if (assignedUnits.has(topic.unit_id)) stat.assigned += 1;
  }
  return order.map((title) => map.get(title)!);
}

export function programTotals(overview: Overview) {
  const stats = sectionStats(overview);
  return stats.reduce(
    (sum, stat) => ({
      total: sum.total + stat.total,
      opened: sum.opened + stat.opened,
      assigned: sum.assigned + stat.assigned,
    }),
    { total: 0, opened: 0, assigned: 0 },
  );
}

/** Два признака шапки: составленность плана и его выполнение (§7.4). */
export function planStatus(overview: Overview) {
  const debt = debtOf(overview);
  const items = overview.plan.items.length;
  const unassigned = overview.plan.unassigned_ids.length;
  const composed = items === 0 ? "none" : unassigned === 0 ? "full" : "partial";
  const hasPastDay = overview.plan.items.some((item) => item.on_date < overview.today);
  return {
    composed: composed as "none" | "partial" | "full",
    unassigned,
    debt: debt.count,
    /** Признак выполнения показывается только когда есть от чего отставать. */
    progress: items > 0 && hasPastDay ? (debt.count > 0 ? "behind" : "onTrack") : null,
  };
}

export interface QueueCard {
  unitId: string;
  title: string;
  kind: Unit["kind"];
  purpose: Purpose;
  opened: boolean;
  seconds: number;
  topicIds: string[];
  /** Для билета — его вопросы с отметкой открытия. */
  questions: { nodeId: string; title: string; opened: boolean }[];
}

/** Секунды за сегодняшний учебный день по вопросам. */
export function todaySecondsByTopic(overview: Overview): Map<string, number> {
  const map = new Map<string, number>();
  for (const interval of overview.today_intervals ?? []) {
    if (!interval.node_id) continue;
    map.set(interval.node_id, (map.get(interval.node_id) ?? 0) + interval.seconds);
  }
  return map;
}

/** Карточки очереди выбранного дня в порядке программы. */
export function queueCards(overview: Overview, date: string): QueueCard[] {
  const completed = new Set(overview.plan.completed_ids);
  const units = new Map(overview.units.map((unit) => [unit.id, unit]));
  const topics = new Map(overview.topics.map((topic) => [topic.node_id, topic]));
  const seconds = todaySecondsByTopic(overview);
  const grouped = new Map<string, { kinds: Set<string>; opened: boolean }>();
  for (const item of overview.plan.items) {
    if (item.on_date !== date) continue;
    let bucket = grouped.get(item.unit_id);
    if (!bucket) {
      bucket = { kinds: new Set(), opened: false };
      grouped.set(item.unit_id, bucket);
    }
    bucket.kinds.add(item.kind);
    if (completed.has(item.id)) bucket.opened = true;
  }
  const order = overview.units.map((unit) => unit.id);
  return [...grouped.entries()]
    .sort((left, right) => order.indexOf(left[0]) - order.indexOf(right[0]))
    .map(([unitId, bucket]) => {
      const unit = units.get(unitId);
      const topicIds = unit?.topic_ids ?? [];
      return {
        unitId,
        title: unit?.title ?? "Вопрос",
        kind: unit?.kind ?? "question",
        purpose: purposeOf(bucket.kinds),
        opened: bucket.opened,
        seconds: topicIds.reduce((sum, id) => sum + (seconds.get(id) ?? 0), 0),
        topicIds,
        questions: topicIds.map((id) => ({
          nodeId: id,
          title: topics.get(id)?.title ?? "Вопрос",
          opened: (seconds.get(id) ?? 0) > 0 || (topics.get(id)?.status ?? "unseen") !== "unseen",
        })),
      };
    });
}

/** Назначение блока подготовки: подпись и токен цвета. */
export const PHASE_KINDS = [
  { value: "learn", label: "Изучение", token: "--purpose-study" },
  { value: "review", label: "Повторение", token: "--purpose-review" },
  { value: "answer", label: "Сдача ответов", token: "--purpose-review" },
  { value: "gaps", label: "Разбор пробелов", token: "--purpose-study" },
  { value: "final", label: "Финальный проход", token: "--accent" },
  { value: "rest", label: "Отдых", token: "--muted" },
  { value: "skip", label: "Пропуск", token: "--faint" },
] as const;

export const phaseKind = (kind: string) =>
  PHASE_KINDS.find((entry) => entry.value === kind) ?? PHASE_KINDS[0];

/** Пересечение блоков запрещено (§3.2): возвращает первый конфликт. */
export function overlappingPhase(
  phases: Overview["plan"]["phases"],
  candidate: { id: string; start: string; end: string },
) {
  return (
    phases.find(
      (phase) =>
        phase.id !== candidate.id && phase.start <= candidate.end && candidate.start <= phase.end,
    ) ?? null
  );
}

/**
 * Схема блоков без ИИ.
 *
 * Чуть больше половины срока — первичное изучение, остальное повторение.
 * При пяти и более днях до экзамена накануне остаётся отдых; при меньшем
 * сроке отдых не выделяется — это правило приоритетнее (§3.9).
 */
export function autoPhases(today: string, deadline: string) {
  const total = dayNumber(deadline) - dayNumber(today);
  if (total < 1) return [];
  const rest = total >= 5 ? 1 : 0;
  const working = total - rest;
  const study = Math.max(1, Math.ceil(working * 0.55));
  const review = working - study;
  const phases: Phase[] = [
    {
      id: crypto.randomUUID(),
      title: "Первичное изучение",
      start: today,
      end: addDays(today, study - 1),
      kind: "learn",
      order: 0,
      origin: "local",
    },
  ];
  if (review > 0)
    phases.push({
      id: crypto.randomUUID(),
      title: "Повторение",
      start: addDays(today, study),
      end: addDays(today, study + review - 1),
      kind: "review",
      order: 1,
      origin: "local",
    });
  if (rest) phases.push({ id: crypto.randomUUID(), title: "Отдых перед экзаменом", start: addDays(deadline, -1), end: addDays(deadline, -1), kind: "rest", order: phases.length, origin: "local" });
  return phases;
}

/** Дата отдыха накануне экзамена, если срок это позволяет. */
export function autoRestDate(today: string, deadline: string): string | null {
  return dayNumber(deadline) - dayNumber(today) >= 5 ? addDays(deadline, -1) : null;
}

/** Фактический и требуемый темп в вопросах за учебный день. */
export function paceOf(overview: Overview, days: DayFacts[]) {
  const window = days.filter(
    (day) => day.date <= overview.today && day.date > addDays(overview.today, -7),
  );
  const loads = new Map(overview.days.map(day => [day.date, day]));
  const studied = window.filter(day => (loads.get(day.date)?.opened_topic_ids?.length ?? 0) > 0 || day.seconds > 0);
  const first = window[0]?.date ?? overview.today;
  const before = [...overview.days].reverse().find(day => day.date < first)?.passed_count ?? 0;
  const opened = Math.max(0, (loads.get(overview.today)?.passed_count ?? 0) - before);
  const eligible = window.filter(day => !day.isRest && !day.isOffDay || day.seconds > 0);
  const totals = programTotals(overview);
  const remaining = totals.total - totals.opened;
  const available = days.filter(
    (day) => day.date > overview.today && !day.isRest && !day.isOffDay && !day.isExam
      && (!overview.deadline || day.date < overview.deadline),
  ).length;

  return {
    actual: studied.length >= 1 && eligible.length ? opened / eligible.length : null,
    required: available > 0 ? remaining / available : null,
    observedDays: studied.length,
    remaining,
    available,
  };
}

/** Накопительные ряды для графика «План и факт». */
export function burnUp(overview: Overview, days: DayFacts[]) {
  const totals = programTotals(overview);
  const firstByUnit = new Map<string, string>();
  for (const item of overview.plan.items) {
    const known = firstByUnit.get(item.unit_id);
    if (!known || item.on_date < known) firstByUnit.set(item.unit_id, item.on_date);
  }
  const unitsToTopics = new Map(overview.units.map((unit) => [unit.id, unit.topic_ids.length || 1]));
  const plannedByDate = new Map<string, number>();
  for (const [unitId, date] of firstByUnit) {
    plannedByDate.set(date, (plannedByDate.get(date) ?? 0) + (unitsToTopics.get(unitId) ?? 1));
  }
  const loads = new Map(overview.days.map((day) => [day.date, day]));
  let planCursor = 0;
  const plan: { x: number; y: number }[] = [];
  const fact: { x: number; y: number }[] = [];
  days.forEach((day, index) => {
    planCursor += plannedByDate.get(day.date) ?? 0;
    plan.push({ x: index, y: Math.min(planCursor, totals.total) });
    if (day.date <= overview.today) {
      const load = loads.get(day.date);
      fact.push({ x: index, y: load?.passed_count ?? 0 });
    }
  });
  return { plan, fact, total: totals.total };
}
