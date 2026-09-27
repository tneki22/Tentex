import { ArrowDown, ArrowUp, FileText, LibraryBig, Pencil, RefreshCw, ScanSearch, Trash2, UserRoundCog } from "lucide-react";
import type { MaterialRead, SourceRole } from "../../api/materials";
import type { ContextMenuItem } from "../../components/ui";
import { SOURCE_ROLE_OPTIONS } from "./materialLabels";

export interface MaterialMenuActions {
  onOpen: (material: MaterialRead) => void;
  onOpenLibrary: (material: MaterialRead) => void;
  /** Есть только в проекте учебника и свободного изучения. */
  onResearch?: (material: MaterialRead) => void;
  onProcess: (material: MaterialRead) => void;
  onRole: (material: MaterialRead, role: SourceRole) => void;
  /** Сдвиг в списке: −1 — выше, +1 — ниже. Порядок строк и есть приоритет. */
  onMove: (material: MaterialRead, offset: -1 | 1) => void;
  onRename: (material: MaterialRead) => void;
  onRemove: (material: MaterialRead) => void;
}

function processLabel(material: MaterialRead): string {
  if (material.source_kind === "typst") return "Собрать заново";
  return material.status === "ready_to_process" ? "Подготовить текст" : "Разобрать заново";
}

/** Меню строки материала по правой кнопке — одно для таблицы и каталога. */
export function materialMenuItems(
  material: MaterialRead,
  place: { index: number; total: number },
  actions: MaterialMenuActions,
): ContextMenuItem[] {
  const running = material.status === "queued" || material.status === "processing";
  const items: ContextMenuItem[] = [
    { label: "Открыть", icon: <FileText size={15} />, onSelect: () => actions.onOpen(material) },
    { label: "Открыть в Библиотеке", icon: <LibraryBig size={15} />, onSelect: () => actions.onOpenLibrary(material) },
  ];
  if (actions.onResearch) {
    const research = actions.onResearch;
    items.push({
      label: "Исследовать",
      icon: <ScanSearch size={15} />,
      disabled: material.status !== "ready",
      onSelect: () => research(material),
    });
  }
  items.push({
    label: processLabel(material),
    icon: <RefreshCw size={15} />,
    disabled: running,
    onSelect: () => actions.onProcess(material),
  });
  // У списка вопросов и ответов роль не выбирают: она следует из назначения.
  if (material.purposes.includes("study_source")) {
    items.push({
      label: "Роль",
      icon: <UserRoundCog size={15} />,
      items: SOURCE_ROLE_OPTIONS.map((option) => ({
        label: option.label,
        checked: material.source_role === option.value,
        disabled: material.source_role === option.value,
        onSelect: () => actions.onRole(material, option.value),
      })),
    });
  }
  items.push(
    { label: "Поднять выше", icon: <ArrowUp size={15} />, disabled: place.index <= 0, onSelect: () => actions.onMove(material, -1) },
    { label: "Опустить ниже", icon: <ArrowDown size={15} />, disabled: place.index >= place.total - 1, onSelect: () => actions.onMove(material, 1) },
    { label: "Переименовать в проекте", icon: <Pencil size={15} />, onSelect: () => actions.onRename(material) },
    { label: "Убрать из проекта", icon: <Trash2 size={15} />, destructive: true, onSelect: () => actions.onRemove(material) },
  );
  return items;
}
