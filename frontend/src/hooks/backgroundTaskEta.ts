/** Якорь наблюдения: момент и счётчик, от которых считается скорость задачи. */
interface EtaAnchor {
  anchorAt: number;
  anchorDone: number;
}

const anchors = new Map<string, EtaAnchor>();

/**
 * Оценка остатка по фактической скорости самой задачи, а не по усреднённому
 * времени на страницу «вообще» — тот способ на реальных файлах расходился с
 * правдой в разы. Первое наблюдение задачи становится точкой отсчёта; оценка
 * появляется только когда после неё набралось хотя бы две страницы (меньше —
 * не оценка, а совпадение), и каждая следующая страница её уточняет.
 * `updatedAt` берётся с сервера (момент сохранения страницы), а не из
 * локальных часов — так пауза между страницами не искажает скорость.
 */
export function estimateEtaSeconds(
  id: string,
  done: number,
  total: number,
  updatedAt: string,
): number | null {
  const left = Math.max(0, total - done);
  const at = new Date(updatedAt).getTime();

  let anchor = anchors.get(id);
  if (!anchor || done < anchor.anchorDone) {
    anchor = { anchorAt: at, anchorDone: done };
    anchors.set(id, anchor);
  }
  if (left === 0) return null;

  const donePages = done - anchor.anchorDone;
  const elapsedSeconds = (at - anchor.anchorAt) / 1000;
  if (donePages < 2 || elapsedSeconds <= 0) return null;

  const secondsPerPage = elapsedSeconds / donePages;
  return Math.max(1, Math.ceil(left * secondsPerPage));
}
