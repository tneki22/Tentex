import { BookPlus, ExternalLink } from "lucide-react";
import type { CoverageDecisionAction, EvidenceDetail } from "../../api/coverage";
import { Button, ErrorState, LoadingState, StatusBadge } from "../ui";
import { EvidenceDecisionMenu } from "./EvidenceDecisionMenu";

const ROLE_LABELS: Record<string, string> = {
  definition: "определение",
  explanation: "объяснение",
  example: "пример",
  exercise: "практика",
  reference: "справка",
};
const ORIGIN_LABELS: Record<string, string> = {
  manual: "ручная связь",
  search: "ручной поиск",
  lesson: "добавление в урок",
  pass_two: "проход 2",
  overview: "первичный обзор",
  research: "исследование темы",
  synthesis: "сводка исследования",
  answers_file: "файл эталонных ответов",
  outline: "диапазон оглавления",
};

interface EvidenceInspectorProps {
  evidence: EvidenceDetail | null;
  loading?: boolean;
  error?: string;
  busy?: boolean;
  onDecision?(action: CoverageDecisionAction, role?: "definition" | "explanation" | "example"): void;
  onAddToLesson?(): void;
  onOpenSource?(): void;
}

/** Постоянный инспектор опоры: решение всегда относится к видимому точному тексту. */
export function EvidenceInspector({
  evidence,
  loading = false,
  error = "",
  busy = false,
  onDecision,
  onAddToLesson,
  onOpenSource,
}: EvidenceInspectorProps) {
  if (error) return <div className="evidence-inspector"><ErrorState message={error} /></div>;
  if (loading && !evidence) {
    return <div className="evidence-inspector"><LoadingState label="Открываем точный текст" /></div>;
  }
  if (!evidence) {
    return <div className="evidence-inspector is-empty"><p>Выберите опору слева.</p></div>;
  }
  return (
    <aside className="evidence-inspector" aria-label="Точный текст опоры">
      <header className="evidence-inspector-head">
        <div>
          <small>{evidence.topic_title}</small>
          <h3>{evidence.material_name}</h3>
          <p>Стр. {evidence.page_from}{evidence.page_to !== evidence.page_from ? `–${evidence.page_to}` : ""}</p>
        </div>
        {onDecision && <EvidenceDecisionMenu evidence={evidence} busy={busy} onAction={onDecision} />}
      </header>
      <div className="evidence-inspector-statuses">
        {evidence.preferred && <StatusBadge tone="info">читать первой</StatusBadge>}
        {evidence.status === "confirmed" && <StatusBadge tone="success">подтверждено</StatusBadge>}
        {evidence.stale && <StatusBadge tone="warning">источник изменился</StatusBadge>}
        {evidence.legacy && <StatusBadge tone="neutral">роль не определена</StatusBadge>}
      </div>
      <blockquote>{evidence.text}</blockquote>
      {evidence.description && <p className="evidence-inspector-description">{evidence.description}</p>}
      <dl className="evidence-inspector-facts">
        <div><dt>Роль</dt><dd>{evidence.roles.map((role) => ROLE_LABELS[role] ?? role).join(", ") || "не определена"}</dd></div>
        <div><dt>Происхождение</dt><dd>{ORIGIN_LABELS[evidence.origin ?? evidence.mechanism] ?? "исследование покрытия"}</dd></div>
        <div><dt>Связанные темы</dt><dd>{evidence.linked_topics.map((topic) => topic.title).join(" · ") || "только эта тема"}</dd></div>
      </dl>
      <footer>
        {onOpenSource && <Button variant="secondary" onClick={onOpenSource}><ExternalLink size={14} />Открыть страницу</Button>}
        {onAddToLesson && <Button disabled={busy || evidence.stale || !evidence.available} onClick={onAddToLesson}><BookPlus size={14} />Добавить в урок</Button>}
      </footer>
    </aside>
  );
}
