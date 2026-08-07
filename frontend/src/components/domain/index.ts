/**
 * Доменные виджеты Tentex: сущности продукта, показанные одинаково на всех
 * экранах. От кита отличаются тем, что знают про предметную область — статус
 * темы, качество страницы, силу свидетельства, стоимость вызова.
 *
 * Правило: если одна и та же сущность рисуется на двух экранах, она живёт здесь.
 * Тон и формулировка выбираются один раз — иначе «освоен» окажется зелёным на
 * карте покрытия и синим в среде темы.
 */
export { CostEstimate } from "./CostEstimate";
export { GoalLevelPicker, GOAL_LEVELS, goalLevelEffect } from "./GoalLevel";
export type { GoalLevelValue } from "./GoalLevel";
export { MachineMark } from "./MachineMark";
export { MetricList } from "./MetricList";
export type { Metric } from "./MetricList";
export { OfflineNotice } from "./OfflineNotice";
export { ProjectChip, PROJECT_ICONS } from "./ProjectChip";
export type { ProjectColor, ProjectIconName } from "./ProjectChip";
export { QualityBadge, PAGE_QUALITIES } from "./QualityBadge";
export type { PageQuality } from "./QualityBadge";
export { SourceChip } from "./SourceChip";
export type { ProgramSource } from "./SourceChip";
export { StepChip } from "./StepChip";
export type { NextStep, StepTone } from "./StepChip";
export { TaskRow } from "./TaskRow";
export type { BackgroundTask, TaskKind } from "./TaskRow";
export { TopicStatusBadge, TOPIC_STATUSES, topicStatusLabel } from "./TopicStatusBadge";
export type { TopicStatus } from "./TopicStatusBadge";
