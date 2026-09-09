import { useEffect, useMemo, useState } from "react";
import { BookOpen, Save } from "lucide-react";
import {
  createCard,
  updateCard,
  type CardCreate,
  type CardRead,
} from "../../api/cards";
import { Button, Field, StatusBadge } from "../../components/ui";

interface EditorSource {
  kind: "none" | "fragment" | "reference";
  fragmentId?: string | null;
  referenceRevision?: number | null;
  label?: string;
}

interface CardEditorProps {
  projectId: string;
  units: CardRead["unit"][];
  card?: CardRead | null;
  initialUnitId?: string | null;
  initialBack?: string;
  initialSource?: EditorSource;
  onSaved: (card: CardRead, addAnother: boolean) => void;
  onCancel?: () => void;
}

function sourceCommand(source: EditorSource): CardCreate["source"] {
  return {
    kind: source.kind,
    fragment_id: source.kind === "fragment" ? source.fragmentId ?? null : null,
    reference_revision:
      source.kind === "reference" ? source.referenceRevision ?? null : null,
  };
}

export function CardEditor({
  projectId,
  units,
  card = null,
  initialUnitId = null,
  initialBack = "",
  initialSource = { kind: "none" },
  onSaved,
  onCancel,
}: CardEditorProps) {
  const [unitId, setUnitId] = useState(card?.program_node_id ?? initialUnitId ?? "");
  const [front, setFront] = useState(card?.front ?? "");
  const [back, setBack] = useState(card?.back ?? initialBack);
  const [hint, setHint] = useState(card?.hint ?? "");
  const [source, setSource] = useState<EditorSource>(
    card
      ? {
          kind: card.source.kind,
          fragmentId: card.source.fragment_id,
          referenceRevision: card.source.reference_revision,
          label: card.source.label,
        }
      : initialSource,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const selectedUnit = useMemo(
    () => units.find((unit) => unit?.id === unitId) ?? null,
    [unitId, units],
  );

  useEffect(() => {
    if (source.kind === "reference" && !selectedUnit?.reference_revision) {
      setSource({ kind: "none" });
    }
  }, [selectedUnit?.reference_revision, source.kind]);

  async function save(addAnother: boolean) {
    if (!front.trim() || !back.trim()) return;
    setSaving(true);
    setError("");
    try {
      const result = card
        ? await updateCard(projectId, card.id, {
            expected_revision: card.revision,
            program_node_id: unitId || null,
            front: front.trim(),
            back: back.trim(),
            hint: hint.trim() || null,
            source: sourceCommand(source),
          })
        : await createCard(projectId, {
            program_node_id: unitId || null,
            front: front.trim(),
            back: back.trim(),
            hint: hint.trim() || null,
            source: sourceCommand(source),
            state: "active",
          });
      onSaved(result, addAnother);
      if (addAnother && !card) {
        setFront("");
        setBack("");
        setHint("");
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось сохранить карточку");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card-editor-layout">
      <form
        className="card-editor-form"
        onSubmit={(event) => {
          event.preventDefault();
          void save(false);
        }}
      >
        <label className="cards-select-field">
          <span>Вопрос или билет</span>
          <select value={unitId} onChange={(event) => setUnitId(event.target.value)}>
            <option value="">Без вопроса</option>
            {units.filter(Boolean).map((unit) => (
              <option value={unit?.id} key={unit?.id}>
                {[...(unit?.path ?? []), unit?.title].filter(Boolean).join(" · ")}
              </option>
            ))}
          </select>
        </label>
        <Field label="Лицевая сторона">
          <textarea
            value={front}
            onChange={(event) => setFront(event.target.value)}
            placeholder="Что нужно вспомнить?"
            rows={4}
          />
        </Field>
        <Field label="Обратная сторона">
          <textarea
            value={back}
            onChange={(event) => setBack(event.target.value)}
            placeholder="Короткий точный ответ"
            rows={7}
          />
        </Field>
        <Field label="Подсказка · необязательно">
          <textarea
            value={hint}
            onChange={(event) => setHint(event.target.value)}
            placeholder="Направление мысли, но не готовый ответ"
            rows={2}
          />
        </Field>
        <label className="cards-select-field">
          <span>Источник</span>
          <select
            value={source.kind}
            onChange={(event) => {
              const kind = event.target.value as EditorSource["kind"];
              setSource(
                kind === "reference"
                  ? {
                      kind,
                      referenceRevision: selectedUnit?.reference_revision,
                    }
                  : kind === "fragment"
                    ? source
                    : { kind: "none" },
              );
            }}
          >
            <option value="none">Вручную</option>
            {source.kind === "fragment" && (
              <option value="fragment">{source.label ?? "Фрагмент материала"}</option>
            )}
            {selectedUnit?.reference_revision && (
              <option value="reference">Эталонный ответ</option>
            )}
          </select>
        </label>
        {error && <p className="cards-form-error" role="alert">{error}</p>}
        <div className="card-editor-actions">
          {onCancel && <Button variant="ghost" type="button" onClick={onCancel}>Отменить</Button>}
          {!card && (
            <Button
              variant="secondary"
              type="button"
              disabled={saving || !front.trim() || !back.trim()}
              onClick={() => void save(true)}
            >
              Сохранить и добавить ещё
            </Button>
          )}
          <Button disabled={saving || !front.trim() || !back.trim()} type="submit">
            <Save size={15} /> {saving ? "Сохраняем…" : "Сохранить"}
          </Button>
        </div>
      </form>

      <aside className="card-editor-preview" aria-label="Предпросмотр карточки">
        <span className="card-editor-preview-label">Предпросмотр</span>
        <article>
          <header>
            <StatusBadge tone={unitId ? "info" : "neutral"}>
              {selectedUnit?.title ?? "Без вопроса"}
            </StatusBadge>
          </header>
          <h3>{front || "Лицевая сторона"}</h3>
          <div className="card-editor-preview-answer">
            <BookOpen size={16} />
            <p>{back || "Здесь появится обратная сторона карточки."}</p>
          </div>
          {hint && <small>Подсказка: {hint}</small>}
          <footer>{source.label ?? (source.kind === "reference" ? "Эталонный ответ" : "Вручную")}</footer>
        </article>
      </aside>
    </div>
  );
}
