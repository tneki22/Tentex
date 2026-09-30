import type { LessonSummaryRead } from "../../api/lessons";
import type { ProgramTreeNode } from "../programTree";

export const STUDY_TYPES = new Set(["topic", "subpoint"]);

export interface LessonCounts {
  drafts: number;
  ready: number;
  needsReview: number;
}

export function isVisible(node: { is_in_current_program: boolean; is_archived: boolean }): boolean {
  return node.is_in_current_program && !node.is_archived;
}

/** Изучаемые узлы поддерева в порядке программы — для чекбокса раздела и «Выбрать темы без уроков». */
export function studyNodesOf(nodes: ProgramTreeNode[]): ProgramTreeNode[] {
  const result: ProgramTreeNode[] = [];
  const visit = (items: ProgramTreeNode[]) => {
    for (const node of items) {
      if (!isVisible(node)) continue;
      if (STUDY_TYPES.has(node.node_type)) result.push(node);
      visit(node.children);
    }
  };
  visit(nodes);
  return result;
}

export function countsByNode(lessons: LessonSummaryRead[]): Map<string, LessonCounts> {
  const counts = new Map<string, LessonCounts>();
  for (const lesson of lessons) {
    for (const nodeId of lesson.program_node_ids) {
      const current = counts.get(nodeId) ?? { drafts: 0, ready: 0, needsReview: 0 };
      if (lesson.status === "draft") current.drafts += 1;
      if (lesson.status === "ready") current.ready += 1;
      if (lesson.needs_review && lesson.status !== "archived") current.needsReview += 1;
      counts.set(nodeId, current);
    }
  }
  return counts;
}

export function sumCounts(nodes: ProgramTreeNode[], counts: Map<string, LessonCounts>): LessonCounts {
  return studyNodesOf(nodes).reduce<LessonCounts>((total, node) => {
    const item = counts.get(node.id);
    return item
      ? { drafts: total.drafts + item.drafts, ready: total.ready + item.ready, needsReview: total.needsReview + item.needsReview }
      : total;
  }, { drafts: 0, ready: 0, needsReview: 0 });
}

/** Знак состояния из записки: `— ● ✓N ⚠`. */
export function lessonStateMark(counts: LessonCounts | undefined): { mark: string; tone: string; label: string } {
  if (!counts || counts.drafts + counts.ready === 0) return { mark: "—", tone: "is-none", label: "Нет урока" };
  if (counts.needsReview > 0) return { mark: "⚠", tone: "is-review", label: "Требует проверки" };
  if (counts.ready > 0) return { mark: `✓ ${counts.ready}`, tone: "is-ready", label: `Готовых уроков: ${counts.ready}` };
  return { mark: "●", tone: "is-draft", label: "Черновик" };
}

export function errorText(caught: unknown, fallback: string): string {
  return caught instanceof Error && caught.message ? caught.message : fallback;
}
