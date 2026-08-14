/**
 * UI-кит: примитивы без знания о предметной области. Всё, что знает про темы,
 * привязки и покрытие, живёт в components/domain.
 *
 * Поведение всплывашек, диалогов, тумблеров и радиогрупп взято у Radix
 * Primitives (пакет `radix-ui`): позиционирование, фокус-ловушка, Esc, roving
 * tabindex и ARIA написаны и проверены там. Наше — только внешний вид через
 * токены. Это правило «готовое вместо своего» из AGENTS.md.
 */
export { Button } from "./Button";
export { Card } from "./Card";
export { Checkbox } from "./Checkbox";
export { ContextMenu } from "./ContextMenu";
export type { ContextMenuItem } from "./ContextMenu";
export { ConfirmDialog, Dialog } from "./Dialog";
export { Disclosure } from "./Disclosure";
export { EmptyState } from "./EmptyState";
export { ErrorState } from "./ErrorState";
export { Field } from "./Field";
export { IconButton } from "./IconButton";
export { Kbd } from "./Kbd";
export { LoadingState } from "./LoadingState";
export { Menu } from "./Menu";
export type { MenuItem } from "./Menu";
export { PageHead, PageHeadSlotProvider } from "./PageHead";
export { PanelResizeHandle } from "./PanelResizeHandle";
export { Popover } from "./Popover";
export { Progress } from "./Progress";
export { RadioCards } from "./RadioCards";
export type { RadioCardOption } from "./RadioCards";
export { SegmentedTabs } from "./SegmentedTabs";
export { Select } from "./Select";
export type { SelectOption } from "./Select";
export { StatusBadge } from "./StatusBadge";
export type { StatusTone } from "./StatusBadge";
export { Switch } from "./Switch";
export { Tooltip, TooltipProvider } from "./Tooltip";
