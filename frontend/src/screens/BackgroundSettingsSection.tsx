import { useState } from "react";
import { RadioGroup } from "radix-ui";
import { BACKGROUNDS, prepareBackgroundPhoto, useBackground } from "../app/Background";
import { Button, Switch } from "../components/ui";

export function BackgroundSettingsSection() {
  const { preference, update, error } = useBackground();
  const [uploadError, setUploadError] = useState("");
  const [busy, setBusy] = useState(false);
  return <section className="background-settings" aria-labelledby="background-heading">
    <header><h2 id="background-heading">Задний фон</h2>
      <p>Один фон для всех экранов, включая левую панель. Карточки и текст остаются чёткими.</p></header>
    <RadioGroup.Root className="background-options" aria-label="Вариант фона" value={preference.id}
      onValueChange={(id) => update({ id: id as typeof preference.id })} disabled={busy}>
      {BACKGROUNDS.map(({ id, label }) => <RadioGroup.Item key={id} value={id}
        className="background-option" disabled={id === "photo" && !preference.photo}>
        <span aria-hidden="true" className={`background-swatch background-${id}`}
          style={id === "photo" && preference.photo ? { backgroundImage: `url("${preference.photo}")` } : undefined} />
        <span>{label}</span><RadioGroup.Indicator className="background-selected">✓</RadioGroup.Indicator>
      </RadioGroup.Item>)}
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
    {(preference.id === "aurora" || preference.id === "waves") && <Switch label="Плавное движение" checked={preference.motion}
      disabled={busy} onCheckedChange={(motion) => update({ motion })}
      hint="Останавливается в неактивной вкладке и при системном уменьшении движения." />}
    {(error || uploadError) && <p role="alert">{uploadError || error}</p>}
  </section>;
}
