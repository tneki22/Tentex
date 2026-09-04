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
export const duration = (seconds: number) => `${Math.round(seconds / 60)} мин`;
export const dayNumber = (value: string) =>
  Date.parse(`${value}T12:00:00Z`) / 86_400_000;
