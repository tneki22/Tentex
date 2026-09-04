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

/**
 * Подпись времени или `null`, если писать нечего.
 *
 * Меньше минуты — это не «0 мин»: надпись с нулём выглядит как отсутствие
 * работы там, где работа была, и занимает место без пользы.
 */
export const durationLabel = (seconds: number) =>
  seconds >= 60 ? duration(seconds) : null;
