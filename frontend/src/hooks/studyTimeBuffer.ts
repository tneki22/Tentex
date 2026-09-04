/** Буфер IndexedDB переживает перезагрузку; удаляются только подтверждённые сервером интервалы. */
import type { Interval } from "../api/preparation";
interface BufferedInterval extends Interval {
  project_id: string;
}
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
export const bufferInterval = (project_id: string, interval: Interval) =>
  transact("readwrite", (store) => store.put({ ...interval, project_id }));
export const pendingIntervals = async (project: string): Promise<Interval[]> =>
  (await transact<BufferedInterval[]>("readonly", (store) => store.getAll()))
    .filter((row) => row.project_id === project)
    .map(({ project_id: _, ...interval }) => interval);
export async function acknowledgeIntervals(ids: string[]) {
  for (const id of ids)
    await transact("readwrite", (store) => store.delete(id));
}
