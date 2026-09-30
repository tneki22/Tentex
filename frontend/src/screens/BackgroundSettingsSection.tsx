import { useState } from "react";
import { RadioGroup } from "radix-ui";
import { BACKGROUNDS, BACKGROUND_INTENSITY, prepareBackgroundPhoto, useBackground } from "../app/Background";
import { Button, Switch } from "../components/ui";

/** Настройки общего фона и инструкция по добавлению новых пресетов через агента. */
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
      <input type="range" min={BACKGROUND_INTENSITY.min} max={BACKGROUND_INTENSITY.max} step="1" value={preference.intensity} disabled={busy}
        onChange={(event) => update({ intensity: Number(event.target.value) })} />
      <small>От 0% (фон скрыт) до 100% (без приглушения). Подберите заметность, при которой вам удобно читать.</small>
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
      <p>Новые фоны добавляются через агента в код проекта. Подойдёт <code>.tsx</code> с React-компонентом,
        который рисует сам фон: градиент, линии, частицы или другой декоративный эффект.</p>
      <p>Например, выберите фон в <a href="https://21st.dev/community/components/s/background" target="_blank" rel="noopener noreferrer">коллекции фонов 21st.dev</a>,
        скопируйте исходный код компонента в <code>.tsx</code> и приложите файл агенту вместе с промптом.
        Нужен код эффекта, а не только демонстрационная страница с его импортом.</p>
      <p><small>Если компонент использует отдельные CSS-файлы, другие компоненты, изображения или библиотеки,
        приложите их тоже либо укажите ссылки и список зависимостей. Код с Tailwind или Motion агент адаптирует под Tentex.
        Загрузка TSX через поле для фото не поддерживается; новый фон появится после изменения кода и пересборки.</small></p>
      <p role="status">{copyStatus}</p>
    </div>
    {(error || uploadError) && <p role="alert">{uploadError || error}</p>}
  </section>;
}

const BACKGROUND_PROMPT = `Добавь приложенный TSX как новый пресет заднего фона Tentex.
В файле должен быть сам React-компонент эффекта, а не только демостраница с импортом. Если не хватает связанных файлов, стилей или зависимостей, уточни их.
Можно взять исходник из https://21st.dev/community/components/s/background; Tailwind-классы и Motion адаптируй под CSS и токены Tentex.
Изучи frontend/src/app/Background.tsx, BackgroundPresets.tsx и frontend/src/styles/background.css.
Сохрани рисунок исходного эффекта, убери демостраницу, тексты, кнопки и внешние загрузки.
Сделай декоративный React-компонент без аргументов; добавь { id, label, component } в BACKGROUNDS.
Общий слой уже задаёт заметность от 0 до 100% и покрывает весь экран. Не ограничивай её внутри компонента. Используй цвета из tokens.css.
SVG/CSS предпочтительны; анимации должны останавливаться при data-motion=false и prefers-reduced-motion: reduce.
Превью в background-swatch должно быть статичным. Для canvas освобождай ресурсы, останавливай requestAnimationFrame в скрытой вкладке и при выключенном движении; учитывай тему и resize.
Не выполняй загруженный код в браузере и не добавляй зависимости без необходимости.
Проверь выбор, превью, сохранение, обе темы и остановку движения; обнови SCREENS.md, выполни typecheck, build и тест frontend/background.spec.ts.`;
