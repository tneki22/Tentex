import type { WorkspaceNode } from "../workspaceDemo";

export type LessonStatus = "draft" | "ready" | "archived";
export type LessonGrounding = "project-sources" | "mixed" | "model-only";
export type LessonAuthorship = "manual" | "model" | "mixed";
export type LessonLayoutPreset = "flow" | "media-left" | "media-right" | "two-equal" | "wide" | "full-width-practice";

export interface LessonSourceRefDemo {
  fragmentId: string | null;
  material: string | null;
  page: number | null;
  quality: "native" | "ocr" | "ocr_low" | null;
  origin: "project-fragment" | "model-knowledge";
  availability: "available" | "missing" | "review";
}

export type LessonBlockDemo =
  | { id: string; type: "rich-text"; paragraphs: string[]; sourceRefs: LessonSourceRefDemo[] }
  | { id: string; type: "callout"; tone: "neutral" | "info" | "warning"; title: string; body: string; sourceRefs: LessonSourceRefDemo[] }
  | { id: string; type: "image"; alt: string; caption: string; assetState: "available" | "missing"; sourceRefs: LessonSourceRefDemo[] }
  | { id: string; type: "diagram"; title: string; preview: string; alt: string; sourceRefs: LessonSourceRefDemo[] }
  | { id: string; type: "sql-activity"; activityId: string; prompt: string; dialect: "SQLite"; sourceRefs: LessonSourceRefDemo[] };

export interface LessonRowDemo { id: string; preset: LessonLayoutPreset; blocks: LessonBlockDemo[] }
export interface LessonSectionDemo { id: string; title: string; objective: string; rows: LessonRowDemo[] }
export interface LessonDocumentDemo { schemaVersion: 1; sections: LessonSectionDemo[] }
export interface LessonDemo {
  id: string; projectId: string; topicIds: string[]; title: string; goal: string; status: LessonStatus;
  difficulty: "intro" | "basic" | "advanced"; estimatedMinutes: number; grounding: LessonGrounding;
  authorship: LessonAuthorship; requiresReview: boolean; document: LessonDocumentDemo;
}

const projectSource: LessonSourceRefDemo = { fragmentId: "ivf-method", material: "Векторные базы данных — методичка.pdf", page: 47, quality: "ocr", origin: "project-fragment", availability: "available" };
const lowQualitySource: LessonSourceRefDemo = { fragmentId: "ivf-scan", material: "Векторные базы данных — методичка.pdf", page: 51, quality: "ocr_low", origin: "project-fragment", availability: "review" };
const modelSource: LessonSourceRefDemo = { fragmentId: null, material: null, page: null, quality: null, origin: "model-knowledge", availability: "available" };
const missingSource: LessonSourceRefDemo = { fragmentId: "lost-index-note", material: "Практика настройки индекса.md", page: 8, quality: "native", origin: "project-fragment", availability: "missing" };

const ivfDocument: LessonDocumentDemo = {
  schemaVersion: 1,
  sections: [{
    id: "ivf-basics", title: "Как IVFFlat сокращает поиск", objective: "Объяснить роль центроидов и параметра probes.", rows: [
      { id: "ivf-text", preset: "flow", blocks: [{ id: "ivf-intro", type: "rich-text", paragraphs: ["IVFFlat делит векторы на списки вокруг центроидов. Запрос сначала находит ближайшие центроиды, а затем сравнивает себя только с векторами в выбранных списках.", "Так полный перебор заменяется контролируемым компромиссом между задержкой и полнотой результата."], sourceRefs: [projectSource] }] },
      { id: "ivf-definition", preset: "flow", blocks: [{ id: "ivf-callout", type: "callout", tone: "info", title: "Определение", body: "nprobe — число списков, которые IVFFlat просматривает для одного запроса.", sourceRefs: [lowQualitySource] }] },
      { id: "ivf-media", preset: "media-left", blocks: [{ id: "ivf-image", type: "image", alt: "Схема векторов вокруг трёх центроидов", caption: "Центроиды задают списки кандидатов для поиска.", assetState: "available", sourceRefs: [projectSource] }, { id: "ivf-explain", type: "rich-text", paragraphs: ["Чем больше списков выбранo, тем выше полнота, но тем больше сравнений выполняется. Значение nlist определяет детализацию разбиения ещё на этапе построения."], sourceRefs: [modelSource] }] },
      { id: "ivf-diagram", preset: "wide", blocks: [{ id: "ivf-diagram-block", type: "diagram", title: "Путь запроса", preview: "запрос → ближайшие центроиды → nprobe списков → кандидаты", alt: "Линейная схема пути запроса IVFFlat", sourceRefs: [projectSource] }] },
      { id: "ivf-columns", preset: "two-equal", blocks: [{ id: "ivf-fast", type: "rich-text", paragraphs: ["Малый nprobe: быстрее, но часть близких соседей может остаться в непроверенных списках."], sourceRefs: [projectSource] }, { id: "ivf-full", type: "rich-text", paragraphs: ["Большой nprobe: ближе к полному перебору, но с большей задержкой."], sourceRefs: [modelSource] }] },
      { id: "ivf-sql", preset: "full-width-practice", blocks: [{ id: "ivf-sql-block", type: "sql-activity", activityId: "ivf-probes", dialect: "SQLite", prompt: "Выберите значение nprobe для индекса с ограничением задержки 40 мс и объясните компромисс.", sourceRefs: [projectSource] }] },
    ],
  }],
};

export const LESSON_DEMOS: LessonDemo[] = [
  { id: "ivf-structure", projectId: "vector-indexes", topicIds: ["ivfflat"], title: "Устройство IVFFlat", goal: "Понять путь запроса через списки индекса.", status: "ready", difficulty: "basic", estimatedMinutes: 18, grounding: "project-sources", authorship: "manual", requiresReview: false, document: ivfDocument },
  { id: "ivf-tuning-practice", projectId: "vector-indexes", topicIds: ["ivfflat"], title: "Настройка IVFFlat: практика", goal: "Выбирать nlist и nprobe под ограничение задержки.", status: "ready", difficulty: "advanced", estimatedMinutes: 12, grounding: "mixed", authorship: "mixed", requiresReview: false, document: { ...ivfDocument, sections: [{ ...ivfDocument.sections[0], title: "Настройка параметров" }] } },
  { id: "index-tuning-draft", projectId: "vector-indexes", topicIds: ["index-tuning"], title: "Ограничения памяти и задержки", goal: "Собрать черновик настройки индекса.", status: "draft", difficulty: "basic", estimatedMinutes: 15, grounding: "model-only", authorship: "model", requiresReview: true, document: { schemaVersion: 1, sections: [{ id: "tuning", title: "Черновик настройки", objective: "Сверить решение с источниками.", rows: [{ id: "tuning-row", preset: "flow", blocks: [{ id: "tuning-text", type: "rich-text", paragraphs: ["Оцените память, задержку и ожидаемую полноту до выбора параметров."], sourceRefs: [missingSource] }] }] }] } },
];

export function lessonsForTopic(topicId: string, lessons = LESSON_DEMOS) { return lessons.filter((lesson) => lesson.status !== "archived" && lesson.topicIds.includes(topicId)); }
export function lessonById(lessonId: string, lessons = LESSON_DEMOS) { return lessons.find((lesson) => lesson.id === lessonId); }

function descendantIds(node: WorkspaceNode): string[] { return [node.id, ...(node.children ?? []).flatMap(descendantIds)]; }
export function lessonCountsForNode(node: WorkspaceNode, lessons = LESSON_DEMOS) {
  const ids = descendantIds(node); const matching = lessons.filter((lesson) => lesson.status !== "archived" && lesson.topicIds.some((id) => ids.includes(id)));
  return { draft: matching.filter((lesson) => lesson.status === "draft").length, ready: matching.filter((lesson) => lesson.status === "ready").length, total: matching.length };
}

export function createManualLesson(projectId: string, topicId: string, topicTitle: string): LessonDemo {
  return { id: crypto.randomUUID(), projectId, topicIds: [topicId], title: `Новый урок: ${topicTitle}`, goal: "Сформулируйте цель урока.", status: "draft", difficulty: "intro", estimatedMinutes: 15, grounding: "project-sources", authorship: "manual", requiresReview: false, document: { schemaVersion: 1, sections: [{ id: crypto.randomUUID(), title: "Новый раздел", objective: "Сформулируйте результат изучения.", rows: [{ id: crypto.randomUUID(), preset: "flow", blocks: [{ id: crypto.randomUUID(), type: "rich-text", paragraphs: ["Начните с главной мысли этого урока."], sourceRefs: [] }] }] }] } };
}

function validateLessonDemo() {
  const ids = new Set<string>();
  for (const lesson of LESSON_DEMOS) {
    if (ids.has(lesson.id)) throw new Error(`Повторяется id урока: ${lesson.id}`); ids.add(lesson.id);
    for (const section of lesson.document.sections) for (const row of section.rows) {
      if (!row.blocks.length) throw new Error(`Пустая строка урока: ${lesson.id}`);
      for (const block of row.blocks) {
        if (block.type === "image" || block.type === "diagram") if (!block.alt.trim()) throw new Error(`Нет alt у блока: ${block.id}`);
        if (block.type === "sql-activity" && row.preset !== "full-width-practice") throw new Error(`SQL должен быть на всю ширину: ${block.id}`);
      }
    }
  }
}
if (import.meta.env.DEV) validateLessonDemo();
