import { createContext, useContext, useEffect, useState, type CSSProperties, type PropsWithChildren } from "react";

export const BACKGROUNDS = [
  { id: "plain", label: "Однотонный" },
  { id: "aurora", label: "Сияние" },
  { id: "waves", label: "Волны" },
  { id: "photo", label: "Своё фото" },
] as const;
type BackgroundId = typeof BACKGROUNDS[number]["id"];
type Preference = { id: BackgroundId; intensity: number; motion: boolean; photo: string };
const DEFAULT: Preference = { id: "plain", intensity: 12, motion: false, photo: "" };
const KEY = "tentex:background";

function readPreference(): Preference {
  try {
    const value = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (!value || !BACKGROUNDS.some(({ id }) => id === value.id)) return DEFAULT;
    const photo = typeof value.photo === "string" && /^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(value.photo)
      && value.photo.length < 1_500_000 ? value.photo : "";
    return {
      id: value.id === "photo" && !photo ? "plain" : value.id,
      intensity: Number.isFinite(value.intensity) ? Math.max(5, Math.min(20, value.intensity)) : 12,
      motion: value.motion === true,
      photo,
    };
  } catch { return DEFAULT; }
}

const BackgroundContext = createContext<{
  preference: Preference;
  update: (patch: Partial<Preference>) => void;
  error: string;
} | null>(null);

export function useBackground() {
  const context = useContext(BackgroundContext);
  if (!context) throw new Error("BackgroundProvider отсутствует");
  return context;
}

/** Один неподвижный слой под всей оболочкой; переходы между экранами его не перезапускают. */
export function BackgroundProvider({ children }: PropsWithChildren) {
  const [preference, setPreference] = useState(readPreference);
  const [error, setError] = useState("");
  const [hidden, setHidden] = useState(document.hidden);
  useEffect(() => {
    const sync = () => setPreference(readPreference());
    const visibility = () => setHidden(document.hidden);
    window.addEventListener("storage", sync);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.removeEventListener("storage", sync);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);
  function update(patch: Partial<Preference>) {
    const next = { ...preference, ...patch };
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
      setPreference(next);
      setError("");
    } catch { setError("Не удалось сохранить фон в браузере. Освободите место и повторите."); }
  }
  const active = preference.id !== "plain";
  return <BackgroundContext.Provider value={{ preference, update, error }}>
    <div className="background-root" data-background={active ? "custom" : "plain"}>
      {active && <div className="app-background" aria-hidden="true" style={{ opacity: preference.intensity / 100 }}>
        <div className={`background-art background-${preference.id}`} data-motion={preference.motion && !hidden}
          style={preference.id === "photo" ? { backgroundImage: `url("${preference.photo}")` } as CSSProperties : undefined} />
      </div>}
      <div className="background-content">{children}</div>
    </div>
  </BackgroundContext.Provider>;
}

/** Сжимаем фото до записи: localStorage ограничен, исходный файл никуда не отправляется. */
export async function prepareBackgroundPhoto(file: File): Promise<string> {
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 20 * 1024 * 1024) {
    throw new Error("Выберите JPG, PNG или WebP размером до 20 МБ.");
  }
  const bitmap = await createImageBitmap(file);
  try {
    const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Браузер не смог подготовить фото.");
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const photo = canvas.toDataURL("image/jpeg", 0.8);
    if (photo.length >= 1_500_000) throw new Error("Фото слишком сложное. Выберите изображение меньшего размера.");
    return photo;
  } finally { bitmap.close(); }
}
