import { useEffect, useState } from "react";
import { BookPlus, Sparkles } from "lucide-react";
import { decideCoverage, type CoverageDecisionAction, type EvidenceSummary } from "../../api/coverage";
import type { LessonBlockCommand, LessonBlockRead } from "../../api/lessons";
import { EvidenceInspector } from "../../components/domain/EvidenceInspector";
import { EvidencePassageList, inReadingOrder, primaryPassages } from "../../components/domain/EvidencePassageList";
import { placedInLesson } from "../../components/domain/LessonEvidenceDialog";
import { Button, EmptyState, StatusBadge } from "../../components/ui";
import { unavailableReason, useAiRoleAvailability } from "../../hooks/useAiRoleAvailability";
import { useTopicEvidence } from "../../hooks/useTopicEvidence";
import type { ProgramTreeNode } from "../programTree";

type AddCommand = Omit<LessonBlockCommand, "expected_revision">;

interface LessonSuggestedTabProps {
  projectId: string;
  topic: ProgramTreeNode;
  lessonId: string | null;
  blocks: LessonBlockRead[];
  busy: boolean;
  onAdd(command: AddCommand): Promise<boolean>;
  /** Несколько кусков подряд: следующий встаёт за предыдущим. */
  onAddMany(commands: AddCommand[]): Promise<boolean>;
  /** «Собрать с ИИ» из отмеченных кусков в порядке книги. */
  onBuildWithAi?(items: EvidenceSummary[]): void;
}

function addCommand(item: EvidenceSummary, topicId: string): AddCommand {
  return {
    operation: "add_fragments",
    material_id: item.material_id,
    from_fragment_id: item.from_fragment_id,
    to_fragment_id: item.to_fragment_id,
    program_node_id: topicId,
  };
}

/**
 * Предложенное исследованием — куски темы, которые вставляются целиком в выбранное
 * место урока; отмеченные встают подряд в порядке книги.
 */
export function LessonSuggestedTab({
  projectId,
  topic,
  lessonId,
  blocks,
  busy,
  onAdd,
  onAddMany,
  onBuildWithAi,
}: LessonSuggestedTabProps) {
  const evidence = useTopicEvidence(projectId, topic.id);
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const availability = useAiRoleAvailability("lesson_builder");
  const items = primaryPassages(evidence.groups);
  const refs = blocks.flatMap((block) => block.refs);
  const placed = (item: EvidenceSummary) => placedInLesson(item, refs);

  useEffect(() => setChecked(new Set()), [topic.id]);

  async function decide(action: CoverageDecisionAction, role?: "definition" | "explanation" | "example") {
    if (!evidence.evidence || !evidence.groups) return;
    setDecisionBusy(true);
    try {
      await decideCoverage(projectId, {
        request_key: crypto.randomUUID(),
        expected_coverage_revision: evidence.groups.coverage_revision,
        action,
        binding_ids: evidence.evidence.binding_ids,
        role,
      });
      await evidence.refresh();
    } finally {
      setDecisionBusy(false);
    }
  }

  async function addChecked() {
    const chosen = inReadingOrder(items.filter((item) => checked.has(item.id) && placed(item) !== "exact"), items);
    if (chosen.length === 0) return;
    if (await onAddMany(chosen.map((item) => addCommand(item, topic.id)))) setChecked(new Set());
  }

  function toggle(item: EvidenceSummary, value: boolean) {
    setChecked((current) => {
      const next = new Set(current);
      if (value) next.add(item.id);
      else next.delete(item.id);
      return next;
    });
  }

  if (!evidence.loading && evidence.groups && items.length === 0) {
    return <EmptyState title="Для темы нет предложений"><p>Исследование материалов ещё не нашло текста по этой теме.</p></EmptyState>;
  }

  const selected = evidence.evidence;
  return <div className="lesson-suggested">
    <div className="lesson-suggested-list">
      <div className="evidence-selection-bar">
        {checked.size > 0
          ? <>
            <span>Выбрано: {checked.size}</span>
            <Button variant="ghost" onClick={() => setChecked(new Set())}>Снять</Button>
            <Button disabled={!lessonId || busy} onClick={() => void addChecked()}><BookPlus size={14} />В урок</Button>
            {onBuildWithAi && <Button variant="secondary" disabled={busy || availability.state !== "ready"} title={unavailableReason(availability)} onClick={() => onBuildWithAi(inReadingOrder(items.filter((item) => checked.has(item.id)), items))}><Sparkles size={14} />Собрать с ИИ</Button>}
          </>
          : <>
            <span>{lessonId ? <>Тема: <strong>{topic.title}</strong></> : "Вставить можно после создания урока."}</span>
            {items.length > 1 && <Button variant="ghost" onClick={() => setChecked(new Set(items.filter((item) => placed(item) !== "exact").map((item) => item.id)))}>Выбрать все</Button>}
          </>}
      </div>
      {evidence.groups && <EvidencePassageList
        groups={evidence.groups}
        selectedId={evidence.selectedId}
        onSelect={(item) => evidence.select(item.id)}
        checkedIds={checked}
        onCheckedChange={lessonId ? toggle : undefined}
        badge={(item) => {
          const state = placed(item);
          return state && <StatusBadge tone={state === "exact" ? "success" : "warning"}>{state === "exact" ? "уже в уроке" : "те же страницы"}</StatusBadge>;
        }}
      />}
    </div>
    <EvidenceInspector
      evidence={selected}
      projectId={projectId}
      loading={evidence.loading}
      error={evidence.error}
      busy={busy || decisionBusy}
      onDecision={(action, role) => void decide(action, role)}
      onAddToLesson={lessonId && selected && placed(selected) !== "exact"
        ? () => void onAdd(addCommand(selected, topic.id))
        : undefined}
    />
  </div>;
}
