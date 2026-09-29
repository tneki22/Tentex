import { BookPlus, ExternalLink } from "lucide-react";
import type { CoverageDecisionAction, EvidenceDetail } from "../../api/coverage";
import { Button, ErrorState, LoadingState, StatusBadge } from "../ui";
import { pagesLabel, ROLE_LABELS } from "./EvidenceCard";
import { EvidenceDecisionMenu } from "./EvidenceDecisionMenu";
import { EvidenceStructuredReader } from "./EvidenceStructuredReader";

const ORIGIN_LABELS: Record<string, string> = {
  manual: "ручная связь",
  search: "ручной поиск",
  lesson: "добавление в урок",
  pass_two: "исследование материалов",
  overview: "исследование материалов",
  research: "исследование темы",
  synthesis: "сводка исследования",
  answers_file: "файл эталонных ответов",
  outline: "диапазон оглавления",
};

interface EvidenceInspectorProps {
  evidence: EvidenceDetail | null;
  /** С проектом кусок читается целиком страницами; без него — текстом (витрина). */
  projectId?: string;
  loading?: boolean;
  error?: string;
  busy?: boolean;
  onDecision?(action: CoverageDecisionAction, role?: "definition" | "explanation" | "example"): void;
  onAddToLesson?(): void;
  onOpenSource?(): void;
}

/** Постоянный инспектор куска: решение всегда относится к видимому тексту целиком. */
export function EvidenceInspector({
  evidence,
  projectId,
  loading = false,
  error = "",
  busy = false,
  onDecision,
  onAddToLesson,
  onOpenSource,
}: EvidenceInspectorProps) {
  if (error) return <div className="evidence-inspector"><ErrorState message={error} /></div>;
  if (loading && !evidence) {
    return <div className="evidence-inspector"><LoadingState label="Открываем текст куска" /></div>;
  }
  if (!evidence) {
    return <div className="evidence-inspector is-empty"><p>Выберите кусок слева.</p></div>;
  }
  return (
    <aside className="evidence-inspector" aria-label="Текст куска">
      <header className="evidence-inspector-head">
        <div>
          <small>{evidence.material_name} · {pagesLabel(evidence.page_from, evidence.page_to)}</small>
          <h3>{evidence.title || evidence.topic_title}</h3>
        </div>
        {onDecision && <EvidenceDecisionMenu evidence={evidence} busy={busy} onAction={onDecision} />}
      </header>
      <div className="evidence-inspector-statuses">
        {evidence.preferred && <StatusBadge tone="info">открывается первым</StatusBadge>}
        {evidence.status === "confirmed" && <StatusBadge tone="success">подтверждено</StatusBadge>}
        {evidence.stale && <StatusBadge tone="warning">источник изменился</StatusBadge>}
        {evidence.legacy && <StatusBadge tone="neutral">из урока или оглавления</StatusBadge>}
      </div>
      {projectId
        ? <div className="evidence-inspector-text"><EvidenceStructuredReader projectId={projectId} evidence={evidence} /></div>
        : <blockquote>{evidence.text}</blockquote>}
      <dl className="evidence-inspector-facts">
        <div><dt>Роль</dt><dd>{evidence.roles.map((role) => ROLE_LABELS[role] ?? role).join(", ") || "не определена"}</dd></div>
        <div><dt>Откуда</dt><dd>{ORIGIN_LABELS[evidence.origin ?? evidence.mechanism] ?? "исследование материалов"}</dd></div>
        <div><dt>Другие темы</dt><dd>{evidence.linked_topics.map((topic) => topic.title).join(" · ") || "только эта тема"}</dd></div>
      </dl>
      <footer>
        {onOpenSource && <Button variant="secondary" onClick={onOpenSource}><ExternalLink size={14} />Открыть страницу</Button>}
        {onAddToLesson && <Button disabled={busy || evidence.stale || !evidence.available} onClick={onAddToLesson}><BookPlus size={14} />Добавить в урок</Button>}
      </footer>
    </aside>
  );
}
