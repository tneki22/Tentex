import { useState } from "react";
import { decideCoverage, type CoverageDecisionAction, type EvidenceSummary } from "../../api/coverage";
import type { LessonBlockCommand, LessonBlockRead } from "../../api/lessons";
import { EvidenceCard } from "../../components/domain/EvidenceCard";
import { EvidenceInspector } from "../../components/domain/EvidenceInspector";
import { EmptyState, StatusBadge } from "../../components/ui";
import { useTopicEvidence } from "../../hooks/useTopicEvidence";
import type { ProgramTreeNode } from "../programTree";

interface LessonSuggestedTabProps {
  projectId: string;
  topic: ProgramTreeNode;
  lessonId: string | null;
  blocks: LessonBlockRead[];
  busy: boolean;
  onAdd(command: Omit<LessonBlockCommand, "expected_revision">): Promise<boolean>;
}

function inclusion(evidence: EvidenceSummary, blocks: LessonBlockRead[]): "exact" | "overlap" | null {
  const refs = blocks.flatMap((block) => block.refs)
    .filter((ref) => ref.material_id === evidence.material_id);
  if (refs.some((ref) => ref.from_fragment_id === evidence.fragment_ids[0]
    && ref.to_fragment_id === evidence.fragment_ids.at(-1))) return "exact";
  if (refs.some((ref) => ref.page_from <= evidence.page_to && ref.page_to >= evidence.page_from)) {
    return "overlap";
  }
  return null;
}

/** Предложенное проходом 2 остаётся ручным выбором с точным местом вставки панели. */
export function LessonSuggestedTab({
  projectId,
  topic,
  lessonId,
  blocks,
  busy,
  onAdd,
}: LessonSuggestedTabProps) {
  const evidence = useTopicEvidence(projectId, topic.id);
  const [decisionBusy, setDecisionBusy] = useState(false);
  const items = evidence.groups ? [
    ...evidence.groups.starter,
    ...evidence.groups.explanations,
    ...evidence.groups.practice,
    ...evidence.groups.depth,
  ] : [];

  async function decide(action: CoverageDecisionAction, role?: "definition" | "explanation" | "example") {
    if (!evidence.evidence || !evidence.groups) return;
    setDecisionBusy(true);
    try {
      await decideCoverage(projectId, {
        request_key: crypto.randomUUID(),
        expected_coverage_revision: evidence.groups.coverage_revision,
        action,
        binding_id: evidence.evidence.binding_id,
        role,
      });
      await evidence.refresh();
    } finally {
      setDecisionBusy(false);
    }
  }

  function addSelected() {
    const selected = evidence.evidence;
    if (!selected) return;
    void onAdd({
      operation: "add_fragments",
      material_id: selected.material_id,
      from_fragment_id: selected.fragment_ids[0],
      to_fragment_id: selected.fragment_ids.at(-1),
      program_node_id: topic.id,
    });
  }

  if (!evidence.loading && items.length === 0) return <EmptyState title="Для темы нет предложений"><p>Проход 2 ещё не нашёл актуального содержания для этой темы.</p></EmptyState>;

  return <div className="lesson-suggested">
    <div className="lesson-suggested-list">
      {lessonId
        ? <p>Тема куска: <strong>{topic.title}</strong></p>
        : <p>Предложения можно просмотреть сейчас, а вставить — после создания урока.</p>}
      {items.map((item) => {
        const state = inclusion(item, blocks);
        return <div className="lesson-suggested-item" key={item.id}>
          <EvidenceCard evidence={item} selected={evidence.selectedId === item.id} onSelect={() => evidence.select(item.id)} />
          {state && <StatusBadge tone={state === "exact" ? "success" : "warning"}>{state === "exact" ? "уже в уроке" : "пересекается"}</StatusBadge>}
        </div>;
      })}
    </div>
    <EvidenceInspector
      evidence={evidence.evidence}
      loading={evidence.loading}
      error={evidence.error}
      busy={busy || decisionBusy}
      onDecision={(action, role) => void decide(action, role)}
      onAddToLesson={lessonId && evidence.evidence && inclusion(evidence.evidence, blocks) !== "exact"
        ? addSelected
        : undefined}
    />
  </div>;
}
