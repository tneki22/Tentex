import { useState } from "react";
import { RadioGroup } from "radix-ui";
import { BACKGROUNDS, prepareBackgroundPhoto, useBackground } from "../app/Background";
import { Button, Switch } from "../components/ui";

export function BackgroundSettingsSection() {
  const { preference, update, error } = useBackground();
  const [uploadError, setUploadError] = useState("");
  const [copyStatus, setCopyStatus] = useState("");
  const [busy, setBusy] = useState(false);
  return <section className="background-settings" aria-labelledby="background-heading">
    <header><h2 id="background-heading">Задний фон</h2>
      <p>Один фон для всех экранов, включая левую панель. Карточки и текст остаются чёткими.</p></header>
    <RadioGroup.Root className="background-options" aria-label="Вариант фона" value={preference.id}
      onValueChange={(id) => update({ id: id as typeof preference.id })} disabled={busy}>
      {BACKGROUNDS.map((preset) => {
        const { id, label } = preset;
        const Art = "component" in preset ? preset.component : null;
        return <RadioGroup.Item key={id} value={id}
        className="background-option" disabled={id === "photo" && !preference.photo}>
        <span aria-hidden="true" className={`background-swatch background-${id}`}
          style={id === "photo" && preference.photo ? { backgroundImage: `url("${preference.photo}")` } : undefined}>{Art && <Art />}</span>
        <span>{label}</span><RadioGroup.Indicator aria-hidden="true" className="background-selected">✓</RadioGroup.Indicator>
      </RadioGroup.Item>; })}
    </RadioGroup.Root>
    <label className="background-upload">{busy ? "Подготовка фото…" : "Загрузить своё фото"}
      <input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={async (event) => {
        const file = event.target.files?.[0];
        event.target.value = "";
        if (!file) return;
        setBusy(true); setUploadError("");
        try { update({ photo: await prepareBackgroundPhoto(file), id: "photo" }); }
        catch (cause) { setUploadError(cause instanceof Error ? cause.message : "Не удалось открыть фото."); }
        finally { setBusy(false); }
      }} />
      <small>JPG, PNG, WebP до 20 МБ. Фото хранится только в этом браузере; перед сохранением уменьшается.</small>
    </label>
    {preference.photo && <Button variant="secondary" disabled={busy} onClick={() => update({ photo: "", id: preference.id === "photo" ? "plain" : preference.id })}>Удалить фото</Button>}
    {preference.id !== "plain" && <label className="background-intensity">Заметность фона — {preference.intensity}%
      <input type="range" min="5" max="20" value={preference.intensity} disabled={busy}
        onChange={(event) => update({ intensity: Number(event.target.value) })} />
      <small>Приглушённая подложка сохраняет читаемость интерфейса.</small>
    </label>}
    {(preference.id !== "plain" && preference.id !== "photo") && <Switch label="Плавное движение" checked={preference.motion}
      disabled={busy} onCheckedChange={(motion) => update({ motion })}
      hint="Останавливается в неактивной вкладке и при системном уменьшении движения." />}
    <div>
      <Button variant="secondary" onClick={async () => {
        try {
          await navigator.clipboard.writeText(BACKGROUND_PROMPT);
          setCopyStatus("Промпт скопирован. Передайте его агенту вместе с TSX-файлом и доступом к проекту.");
        } catch { setCopyStatus("Не удалось скопировать. Промпт есть в docs/architecture/background-presets.md."); }
      }}>Копировать промпт для агента</Button>
      <p><small>Новые анимированные фоны добавляются через код проекта. Приложите агенту TSX-файл и этот промпт.</small></p>
      <p role="status">{copyStatus}</p>
    </div>
    {(error || uploadError) && <p role="alert">{uploadError || error}</p>}
  </section>;
}

const BACKGROUND_PROMPT = `Добавь приложенный TSX как новый пресет заднего фона Tentex.
Изучи frontend/src/app/Background.tsx, BackgroundPresets.tsx и frontend/src/styles/background.css.
Сохрани рисунок исходного эффекта, убери демостраницу, тексты, кнопки и внешние загрузки.
Сделай декоративный React-компонент без аргументов; добавь { id, label, component } в BACKGROUNDS.
Общий слой уже задаёт прозрачность и покрывает весь экран. Используй цвета из tokens.css.
SVG/CSS предпочтительны; анимации должны останавливаться при data-motion=false и prefers-reduced-motion: reduce.
Превью в background-swatch должно быть статичным. Для canvas освобождай ресурсы, останавливай requestAnimationFrame в скрытой вкладке и при выключенном движении; учитывай тему и resize.
Не выполняй загруженный код в браузере и не добавляй зависимости без необходимости.
Проверь выбор, превью, сохранение, обе темы и остановку движения; обнови SCREENS.md, выполни typecheck, build и тест frontend/background.spec.ts.`;
