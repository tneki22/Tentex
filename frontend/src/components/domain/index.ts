/**
 * Доменные виджеты Tentex: сущности продукта, показанные одинаково на всех
 * экранах. От кита отличаются тем, что знают про предметную область — статус
 * темы, качество страницы, силу свидетельства, стоимость вызова.
 *
 * Правило: если одна и та же сущность рисуется на двух экранах, она живёт здесь.
 * Тон и формулировка выбираются один раз — иначе «освоен» окажется зелёным на
 * карте покрытия и синим в среде темы.
 */
export { AiFailureNotice } from "./AiFailureNotice";
export { AnswerScanPages } from "./AnswerScanPages";
export { AnswerMatchStatus } from "./AnswerMatchStatus";
export { answerScanGroups, scanPageCount } from "./answerPages";
export type { AnswerScanGroup } from "./answerPages";
export { AutoMatchDialog } from "./AutoMatchDialog";
// ConspectEditor/ConspectSummary НЕ реэкспортируются как значения: этот файл
// импортируется эагерно почти всеми экранами, и статический реэкспорт тянет
// Milkdown в стартовый бандл (rolldown это явно ловит: INEFFECTIVE_DYNAMIC_IMPORT).
// Компонент подключается только прямым `import("./ConspectEditor")` — так,
// как это уже делает ProjectWorkspace через React.lazy.
export type { ConspectEditorHandle, ConspectEditorProps } from "./ConspectEditor";
export type { ConspectSummaryProps } from "./ConspectSummary";
export { ChatModelPicker } from "./ChatModelPicker";
export type { ChatModelParameters, ReasoningEffort } from "./ChatModelPicker";
export { CostEstimate } from "./CostEstimate";
export { DictationButton } from "./DictationButton";
export { EvidenceCard } from "./EvidenceCard";
export { EvidenceDecisionMenu } from "./EvidenceDecisionMenu";
export { EvidenceInspector } from "./EvidenceInspector";
export { EvidenceStructuredReader } from "./EvidenceStructuredReader";
export { ImportProjectButton } from "./ImportProjectButton";
export { LessonEvidenceDialog } from "./LessonEvidenceDialog";
export { GoalLevelPicker, GOAL_LEVELS, goalLevelEffect } from "./GoalLevel";
export type { GoalLevelValue } from "./GoalLevel";
export { MachineMark } from "./MachineMark";
export { MaterialHint, MATERIAL_KIND_LABELS } from "./MaterialHint";
export { MaterialSuggestionList } from "./MaterialSuggestionList";
export { TopicMaterialFinder } from "./TopicMaterialFinder";
export type { FinderTopic } from "./TopicMaterialFinder";
export { LibraryMaterialPickerDialog } from "./LibraryMaterialPickerDialog";
export { MetricList } from "./MetricList";
export type { Metric } from "./MetricList";
export { OfflineNotice } from "./OfflineNotice";
export { PersonalMarkIcon, PERSONAL_MARK_OPTIONS } from "./PersonalMarkIcon";
export { ProviderModelPicker } from "./ProviderModelPicker";
export { ProjectChip, PROJECT_ICONS } from "./ProjectChip";
export type { ProjectColor, ProjectIconName } from "./ProjectChip";
export { ProjectNav } from "./ProjectNav";
export { ResearchLaunchDialog } from "./ResearchLaunchDialog";
export { ProgramSectionRow, ProgramTopicRow } from "./ProgramTreeRows";
export { LessonDocument } from "./lesson/LessonDocument";
export type { LessonDocumentMode } from "./lesson/LessonDocument";
export type { ProjectNavKey } from "./ProjectNav";
export { QualityBadge, PAGE_QUALITIES, qualityHint, qualityLabel } from "./QualityBadge";
export type { PageQuality } from "./QualityBadge";
export { ReferenceAnswerBadge, REFERENCE_ANSWER_STATUSES, referenceAnswerStatusLabel } from "./ReferenceAnswerBadge";
export { SourceChip } from "./SourceChip";
export type { ProgramSource } from "./SourceChip";
export { StepChip } from "./StepChip";
export type { NextStep, StepTone } from "./StepChip";
export { TaskRow } from "./TaskRow";
export type { BackgroundTask, TaskKind } from "./TaskRow";
export { TextbookProgramEditor } from "./program-editor/TextbookProgramEditor";
export type {
  TextbookProgramEditorActions,
  TextbookProgramView,
} from "./program-editor/TextbookProgramEditor";
export { ProgramTreePreview } from "./program-chat/ProgramTreePreview";
export { TopicStatusBadge, TOPIC_STATUSES, topicStatusLabel } from "./TopicStatusBadge";
export type { TopicStatus } from "./TopicStatusBadge";
export { PurposeDot, purposeLabel, purposeOf, type Purpose } from "./PurposeDot";
export {
  AnswerResultBadge,
  answerResultLabel,
  answerResultToken,
  answerResultOf,
  type AnswerResult,
} from "./AnswerResultBadge";
