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
export { CostEstimate } from "./CostEstimate";
export { GoalLevelPicker, GOAL_LEVELS, goalLevelEffect } from "./GoalLevel";
export type { GoalLevelValue } from "./GoalLevel";
export { MachineMark } from "./MachineMark";
export { LibraryMaterialPickerDialog } from "./LibraryMaterialPickerDialog";
export { MetricList } from "./MetricList";
export type { Metric } from "./MetricList";
export { OfflineNotice } from "./OfflineNotice";
export { PersonalMarkIcon, PERSONAL_MARK_OPTIONS } from "./PersonalMarkIcon";
export { ProviderModelPicker } from "./ProviderModelPicker";
export { ProjectChip, PROJECT_ICONS } from "./ProjectChip";
export type { ProjectColor, ProjectIconName } from "./ProjectChip";
export { ProjectNav } from "./ProjectNav";
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
export { TopicStatusBadge, TOPIC_STATUSES, topicStatusLabel } from "./TopicStatusBadge";
export type { TopicStatus } from "./TopicStatusBadge";
