/** Буфер IndexedDB переживает перезагрузку; удаляются только подтверждённые сервером интервалы. */
import type { Interval } from "../api/preparation";
import type { LessonTimeInterval } from "../api/lessonPlanning";
export type BufferedStudyInterval = Interval | LessonTimeInterval;
type BufferedInterval = BufferedStudyInterval & {
  project_id: string;
};
const DATABASE = "tentex-study-time";
const STORE = "intervals";
function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const task = indexedDB.open(DATABASE, 1);
    task.onupgradeneeded = () =>
      task.result.createObjectStore(STORE, { keyPath: "id" });
    task.onsuccess = () => resolve(task.result);
    task.onerror = () => reject(task.error);
  });
}
async function transact<T>(
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(STORE, mode);
    const task = run(transaction.objectStore(STORE));
    transaction.oncomplete = () => {
      database.close();
      resolve(task.result);
    };
    transaction.onerror = () => {
      database.close();
      reject(transaction.error);
    };
    transaction.onabort = () => {
      database.close();
      reject(transaction.error ?? new Error("Буфер времени недоступен"));
    };
  });
}
export const bufferInterval = (project_id: string, interval: BufferedStudyInterval) =>
  transact("readwrite", (store) => store.put({ ...interval, project_id }));
export async function pendingIntervals(project: string, lesson: true): Promise<LessonTimeInterval[]>;
export async function pendingIntervals(project: string, lesson?: false): Promise<Interval[]>;
export async function pendingIntervals(project: string, lesson = false): Promise<BufferedStudyInterval[]> {
  return (await transact<BufferedInterval[]>("readonly", (store) => store.getAll()))
    .filter((row) => row.project_id === project && ("lesson_id" in row) === lesson)
    .map(({ project_id: _, ...interval }) => interval);
}
export async function acknowledgeIntervals(ids: string[]) {
  for (const id of ids)
    await transact("readwrite", (store) => store.delete(id));
}
