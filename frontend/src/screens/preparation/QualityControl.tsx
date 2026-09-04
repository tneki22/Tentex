/** Качество воспроизведения уточняет интервалы, не заменяя вердикт проверяющего. */
import { useState } from "react";
import { Select } from "../../components/ui";
import { preparation, errorText } from "../../api/preparation";
export function QualityControl({
  projectId,
  attemptId,
  value,
  onSaved,
}: {
  projectId: string;
  attemptId: string;
  value?: number | null;
  onSaved?: () => void;
}) {
  const [quality, setQuality] = useState(value ?? null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save(next: string | null) {
    if (next === null) return;
    setBusy(true);
    try {
      await preparation.quality(projectId, attemptId, Number(next));
      setQuality(Number(next));
      setError(null);
      onSaved?.();
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="prep-quality">
      <Select
        ariaLabel="Качество воспроизведения"
        value={quality === null ? null : String(quality)}
        placeholder="Уточнить качество 0–5"
        disabled={busy}
        options={[
          "Не вспомнил",
          "Узнал после подсказки",
          "Вспомнил с трудом",
          "Ответил с усилием",
          "Ответил уверенно",
          "Вспомнил легко",
        ].map((label, value) => ({
          value: String(value),
          label: `${value} — ${label}`,
        }))}
        onValueChange={(next) => void save(next)}
      />
      <small>Уточнение памяти, отдельно от оценки ответа.</small>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
