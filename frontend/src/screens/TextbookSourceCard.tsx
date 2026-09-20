import { Check, Save } from "lucide-react";
import { useEffect, useState } from "react";
import type { MaterialRead, MaterialUpdateCommand, SourceRole } from "../api/materials";
import { Button, Field } from "../components/ui";

interface SourceDraft {
  displayName: string;
  sourceRole: SourceRole;
  priority: string;
  instruction: string;
}

function draftFrom(material: MaterialRead): SourceDraft {
  return {
    /* Пустое поле означает «своего имени нет»: иначе обычное сохранение роли
       молча закрепило бы за проектом псевдоним, и Библиотека перестала бы
       переименовывать материал. */
    displayName: material.project_display_name ?? "",
    sourceRole: material.source_role,
    priority: String(material.priority),
    instruction: material.instruction ?? "",
  };
}

function sameDraft(left: SourceDraft, right: SourceDraft): boolean {
  return left.displayName === right.displayName
    && left.sourceRole === right.sourceRole
    && left.priority === right.priority
    && left.instruction === right.instruction;
}

interface TextbookSourceCardProps {
  material: MaterialRead;
  busy: boolean;
  onSave: (materialId: string, command: MaterialUpdateCommand) => Promise<MaterialRead | null>;
}

// По образцу MaterialFileTab.tsx: локальный черновик, ресинк только по смене
// material.id (а не на каждый рендер), явная кнопка «Сохранить». PATCH на
// каждое нажатие клавиши плюс опрос статуса раз в 1200 мс раньше приводили
// к тому, что набранный текст переписывался ответом на более ранний запрос.
export function TextbookSourceCard({ material, busy, onSave }: TextbookSourceCardProps) {
  const [draft, setDraft] = useState<SourceDraft>(() => draftFrom(material));
  const [savedId, setSavedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(draftFrom(material));
    // Ресинк только по смене файла: опрос статуса и чужие сохранения не
    // должны стирать набранный текст.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [material.id]);

  const priority = Number(draft.priority);
  const priorityValid = draft.priority.trim() !== "" && Number.isInteger(priority) && priority >= 0;
  const dirty = !sameDraft(draft, draftFrom(material));
  const justSaved = savedId === material.id && !dirty;

  async function save() {
    if (!priorityValid || saving) return;
    setSaving(true);
    try {
      const result = await onSave(material.id, {
        display_name: draft.displayName.trim() || null,
        source_role: draft.sourceRole,
        priority,
        instruction: draft.instruction.trim() || null,
      });
      if (result) {
        setDraft(draftFrom(result));
        setSavedId(material.id);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="textbook-source-settings"
      onKeyDown={(event) => {
        if (event.key === "Escape") setDraft(draftFrom(material));
      }}
    >
      <Field label="Название в этом проекте" hint="Очистите поле, чтобы снова использовать название из Библиотеки">
        <input
          value={draft.displayName}
          disabled={saving || busy}
          onChange={(event) => setDraft((current) => ({ ...current, displayName: event.target.value }))}
          placeholder={material.library_display_name}
        />
      </Field>
      <Field label="Роль источника">
        <select
          value={draft.sourceRole}
          disabled={saving || busy}
          onChange={(event) => setDraft((current) => ({ ...current, sourceRole: event.target.value as SourceRole }))}
        >
          <option value="main">Основной</option>
          <option value="additional">Дополнительный</option>
          <option value="reference">Справочный</option>
        </select>
      </Field>
      <Field label="Приоритет" error={priorityValid ? undefined : "Укажите целое число от 0"}>
        <input
          type="number"
          min="0"
          value={draft.priority}
          disabled={saving || busy}
          onChange={(event) => setDraft((current) => ({ ...current, priority: event.target.value }))}
        />
      </Field>
      <Field label="Как использовать">
        <textarea
          value={draft.instruction}
          disabled={saving || busy}
          onChange={(event) => setDraft((current) => ({ ...current, instruction: event.target.value }))}
          placeholder="Например, отсюда брать определения"
        />
      </Field>
      <div className="textbook-source-save">
        <Button variant="secondary" disabled={saving || busy || !dirty || !priorityValid} onClick={() => void save()}>
          {justSaved ? <><Check size={14} aria-hidden="true" /> Сохранено</> : <><Save size={14} aria-hidden="true" /> Сохранить</>}
        </Button>
      </div>
    </div>
  );
}
