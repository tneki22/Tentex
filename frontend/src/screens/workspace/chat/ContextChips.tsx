import { FileQuestion, History, ListChecks, MessageSquareText, ScrollText } from "lucide-react";
import type { ChatContextFlags, ChatContextPreview } from "../../../api/chat";
import { Popover, Switch } from "../../../components/ui";

function bytesLabel(bytes: number): string {
  return bytes < 1024 ? `${bytes} Б` : `${(bytes / 1024).toFixed(1)} КБ`;
}

interface ChipDef {
  key: string;
  icon: typeof FileQuestion;
  title: string;
  flagKey: keyof ChatContextFlags | null;
  included: boolean;
  bytes: number;
  count: number | null;
  reason: string | null;
  futureNote?: string;
}

const REASON_LABELS: Record<string, string> = {
  excluded_by_user: "Исключено вручную",
  profile_empty: "В профиле проекта эти поля не заполнены",
  reference_missing: "У темы ещё нет эталонного ответа",
  not_implemented: "Пока не реализовано",
};

interface ContextChipsProps {
  preview: ChatContextPreview | null;
  contextFlags: ChatContextFlags;
  onToggleFlag: (key: keyof ChatContextFlags, value: boolean) => void;
}

/** Тихая строка чипов над композером — заменяет прежнюю текстовую «В запрос уходит: ...». */
export function ContextChips({ preview, contextFlags, onToggleFlag }: ContextChipsProps) {
  if (!preview) return null;
  const byKind = new Map(preview.manifest.map((entry) => [entry.kind, entry]));
  const fragmentEntries = preview.manifest.filter((entry) => entry.kind === "fragment");
  const fragmentCount = fragmentEntries.filter((entry) => entry.included).length;
  const node = byKind.get("program_node");
  const profile = byKind.get("profile");
  const reference = byKind.get("reference_answer");
  const attempts = byKind.get("attempts_digest");
  const sectionMemory = byKind.get("section_memory");

  const chips: ChipDef[] = [
    {
      key: "question", icon: FileQuestion, title: "Вопрос", flagKey: null,
      included: true, bytes: node?.bytes ?? 0, count: null, reason: null,
    },
    {
      key: "profile", icon: MessageSquareText, title: "Профиль", flagKey: "profile",
      included: Boolean(profile?.included), bytes: profile?.bytes ?? 0, count: null,
      reason: profile?.reason ?? null,
    },
    {
      key: "reference", icon: ScrollText, title: "Эталон", flagKey: "reference",
      included: Boolean(reference?.included), bytes: reference?.bytes ?? 0, count: null,
      reason: reference?.reason ?? null,
    },
    {
      key: "fragments", icon: ListChecks, title: `Материал · ${fragmentCount}`, flagKey: "fragments",
      included: fragmentCount > 0, bytes: fragmentEntries.reduce((sum, e) => sum + e.bytes, 0),
      count: fragmentCount, reason: fragmentEntries.length === 0 ? null : (fragmentEntries[0]?.reason ?? null),
    },
    {
      key: "attempts", icon: History, title: "Попытки", flagKey: "attempts",
      included: false, bytes: 0, count: null, reason: attempts?.reason ?? "not_implemented",
      futureNote: "Появится вместе с историей попыток раздела",
    },
    {
      key: "section_memory", icon: History, title: "История раздела", flagKey: "section_memory",
      included: false, bytes: 0, count: null, reason: sectionMemory?.reason ?? "not_implemented",
      futureNote: "Появится вместе со сжатой памятью раздела",
    },
  ];

  return (
    <div className="chat-context-chips" role="list" aria-label="Состав запроса">
      {chips.map((chip) => (
        <Popover
          key={chip.key}
          align="start"
          side="top"
          title={chip.title}
          trigger={
            <button
              type="button"
              role="listitem"
              className={`chat-context-chip ${chip.included ? "is-included" : "is-excluded"}`}
            >
              <chip.icon size={13} aria-hidden="true" />
              {chip.title}
            </button>
          }
        >
          <div className="chat-context-chip-detail">
            {chip.included ? (
              <p>Включено · {bytesLabel(chip.bytes)}</p>
            ) : (
              <p className="chat-context-chip-reason">
                Не включено{chip.reason ? ` — ${REASON_LABELS[chip.reason] ?? chip.reason}` : ""}
              </p>
            )}
            {chip.futureNote && <p className="chat-context-chip-future">{chip.futureNote}</p>}
            {chip.flagKey && !chip.futureNote && (
              <Switch
                checked={contextFlags[chip.flagKey]}
                onCheckedChange={(checked) => onToggleFlag(chip.flagKey as keyof ChatContextFlags, checked)}
                label={contextFlags[chip.flagKey] ? "Включено в запрос" : "Исключено из запроса"}
              />
            )}
          </div>
        </Popover>
      ))}
    </div>
  );
}
