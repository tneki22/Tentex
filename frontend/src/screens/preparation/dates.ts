/** Даты календаря не переводятся в UTC через локальный часовой пояс браузера. */
export function addDays(value: string, days: number): string {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}
export const dateLabel = (value: string) =>
  new Date(`${value}T12:00:00Z`).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
export const duration = (seconds: number) => {
  const minutes = Math.max(0, Math.round(seconds / 60));
  return minutes < 60 ? `${minutes} мин`
    : `${Math.floor(minutes / 60)} ч${minutes % 60 ? ` ${minutes % 60} мин` : ""}`;
};
export const dayNumber = (value: string) =>
  Date.parse(`${value}T12:00:00Z`) / 86_400_000;

/** События до границы учебного дня относятся к предыдущей дате проекта. */
export function studyDate(value: string, config: { timezone: string; day_boundary: string }): string {
  const timestamp = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: config.timezone, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(timestamp));
  const part = (name: string) => parts.find(item => item.type === name)!.value;
  const date = `${part("year")}-${part("month")}-${part("day")}`;
  return `${part("hour")}:${part("minute")}` < config.day_boundary.slice(0, 5) ? addDays(date, -1) : date;
}

/**
 * Подпись времени или `null`, если писать нечего.
 *
 * Меньше минуты — это не «0 мин»: надпись с нулём выглядит как отсутствие
 * работы там, где работа была, и занимает место без пользы.
 */
export const durationLabel = (seconds: number) =>
  seconds >= 60 ? duration(seconds) : null;
