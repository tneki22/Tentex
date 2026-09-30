/**
 * Ходы чатов, которые ушли на сервер и ещё не закончились.
 *
 * Ответ модели идёт десятки секунд, а пользователь за это время уходит на другой экран.
 * Запрос при этом не обрывается и сервер дописывает ответ, но хук чата уже размонтирован:
 * вернувшись, экран не знал, что ход идёт, — не было ни индикатора, ни ответа до
 * перезагрузки страницы. Реестр живёт вне компонентов, поэтому новый экземпляр хука
 * находит здесь идущий ход, показывает ожидание и перечитывает переписку по его окончании.
 */

export interface InflightTurn {
  /** Текст реплики: если ход упадёт, он возвращается в поле ввода. */
  text: string;
  /** Резолвится текстом ошибки хода; пустая строка — ход закончился без ошибки. */
  done: Promise<string>;
  abort(): void;
}

const turns = new Map<string, InflightTurn>();

export function trackTurn(key: string, turn: InflightTurn): void {
  turns.set(key, turn);
  const forget = () => {
    if (turns.get(key) === turn) turns.delete(key);
  };
  void turn.done.then(forget, forget);
}

export function activeTurn(key: string): InflightTurn | undefined {
  return turns.get(key);
}
