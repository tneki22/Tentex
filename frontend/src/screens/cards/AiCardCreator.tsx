import { useState } from "react";
import {
  createGeneratedCard, generateCards,
  type CardGenerationMode, type CardRead, type GeneratedCard,
} from "../../api/cards";
import { Button } from "../../components/ui";

type Candidate = GeneratedCard & { status: "pending" | "saved" | "discarded"; savedId?: string };

interface AiCardCreatorProps {
  projectId: string;
  units: CardRead["unit"][];
  initialUnitId?: string | null;
  onChanged: () => void;
  onOpenBank: (cardId?: string) => void;
}

/** Предпросмотр и принятие предложений, которые пока не попали в Банк. */
export function AiCardCreator({
  projectId, units, initialUnitId, onChanged, onOpenBank,
}: AiCardCreatorProps) {
  const [unitId, setUnitId] = useState(initialUnitId ?? "");
  const [mode, setMode] = useState<CardGenerationMode>("connections");
  const [runId, setRunId] = useState("");
  const [items, setItems] = useState<Candidate[]>([]);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState<number | null>(null);
  const [error, setError] = useState("");

  function edit(index: number, key: "front" | "back" | "hint", value: string) {
    setItems((current) => current.map((item) =>
      item.index === index ? { ...item, [key]: value } : item
    ));
  }

  async function generate() {
    if (!unitId || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await generateCards(projectId, unitId, mode);
      setRunId(result.run_id);
      setItems(result.candidates.map((item) => ({ ...item, status: "pending" })));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось создать карточки");
    } finally {
      setBusy(false);
    }
  }

  async function save(item: Candidate) {
    if (!item.front.trim() || !item.back.trim() || saving !== null) return;
    setSaving(item.index);
    setError("");
    try {
      const card = await createGeneratedCard(projectId, {
        program_node_id: unitId,
        front: item.front.trim(),
        back: item.back.trim(),
        hint: item.hint?.trim() || null,
        source: item.source,
        state: "active",
        generation_run_id: runId,
        generation_candidate_index: item.index,
      });
      setItems((current) => current.map((candidate) =>
        candidate.index === item.index
          ? { ...candidate, status: "saved", savedId: card.id }
          : candidate
      ));
      onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось сохранить карточку");
    } finally {
      setSaving(null);
    }
  }

  return (
    <section className="cards-ai-creator">
      <p>ИИ предложит карточки по готовому ответу и привязанным материалам. Проверьте их перед сохранением.</p>
      <div className="cards-ai-controls">
        <label className="cards-select-field">
          Вопрос или билет
          <select value={unitId} disabled={busy || saving !== null}
            onChange={(event) => { setUnitId(event.target.value); setItems([]); }}>
            <option value="">Выберите вопрос</option>
            {units.filter((unit) => unit !== null).map((unit) =>
              <option key={unit!.id} value={unit!.id}>{unit!.path.join(" / ")} — {unit!.title}</option>
            )}
          </select>
        </label>
        <label className="cards-select-field">
          Режим
          <select value={mode} disabled={busy || saving !== null}
            onChange={(event) => { setMode(event.target.value as CardGenerationMode); setItems([]); }}>
            <option value="connections">Основные связи</option>
            <option value="understanding">На понимание</option>
          </select>
        </label>
        <Button onClick={() => void generate()} disabled={!unitId || busy || saving !== null}>
          {busy ? "Готовим карточки…" : "Предложить карточки"}
        </Button>
      </div>
      {error && <p className="cards-ai-error" role="alert">{error}</p>}
      <div className="cards-ai-list">
        {items.map((item) => (
          <article className="cards-ai-candidate" key={item.index}>
            <div className="cards-ai-candidate-head">
              <strong>Карточка {item.index + 1}</strong>
              <span>{item.source.kind === "reference" ? "Опора: ответ" : "Опора: фрагмент"}</span>
            </div>
            {item.status === "discarded" ? <p>Предложение отклонено.</p> : (
              <>
                <label>Вопрос
                  <textarea value={item.front} disabled={item.status === "saved"}
                    onChange={(event) => edit(item.index, "front", event.target.value)} />
                </label>
                <label>Ответ
                  <textarea value={item.back} disabled={item.status === "saved"}
                    onChange={(event) => edit(item.index, "back", event.target.value)} />
                </label>
                <label>Подсказка
                  <input value={item.hint ?? ""} disabled={item.status === "saved"}
                    onChange={(event) => edit(item.index, "hint", event.target.value)} />
                </label>
                <blockquote>{item.evidence_quote}</blockquote>
                <div className="cards-ai-actions">
                  {item.status === "saved" ? (
                    <Button variant="secondary" onClick={() => onOpenBank(item.savedId)}>Открыть в Банке</Button>
                  ) : (
                    <>
                      <Button onClick={() => void save(item)} disabled={saving !== null || !item.front.trim() || !item.back.trim()}>
                        {saving === item.index ? "Сохраняем…" : "Сохранить в Банк"}
                      </Button>
                      <Button variant="ghost" onClick={() =>
                        setItems((current) => current.map((candidate) =>
                          candidate.index === item.index ? { ...candidate, status: "discarded" } : candidate
                        ))
                      }>Отклонить</Button>
                    </>
                  )}
                </div>
              </>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
