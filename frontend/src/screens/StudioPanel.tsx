import {
  AudioLines,
  BadgeQuestionMark,
  ChartNoAxesColumnIncreasing,
  ChevronRight,
  EllipsisVertical,
  FileChartColumn,
  GalleryHorizontalEnd,
  Network,
  NotebookPen,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  Presentation,
  StickyNote,
  TableProperties,
} from "lucide-react";
import type { ComponentType } from "react";
import { useState } from "react";
import { Dialog, IconButton, StatusBadge, Tooltip } from "../components/ui";
import { OfflineNotice } from "../components/domain";

interface StudioPanelProps {
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
  modelsEnabled: boolean;
  sourceCount: number;
  topicTitle: string;
}

interface StudioTool {
  id: string;
  label: string;
  settings: string;
  tone: number;
  icon: ComponentType<{ size?: number; "aria-hidden"?: "true" }>;
}

interface StudioArtifact {
  id: string;
  label: string;
  meta: string;
  icon: ComponentType<{ size?: number; "aria-hidden"?: "true" }>;
}

const STUDIO_TOOLS: StudioTool[] = [
  { id: "audio", label: "Аудиопересказ", settings: "Формат, язык, длина, инструкция и источники", tone: 2, icon: AudioLines },
  { id: "slides", label: "Презентация", settings: "Подробная или для докладчика, язык, длина и инструкция", tone: 8, icon: Presentation },
  { id: "mind-map", label: "Ментальная карта", settings: "Язык, фокус и выбранные источники", tone: 4, icon: Network },
  { id: "reports", label: "Отчёты", settings: "FAQ, учебное руководство, обзорный или свой формат", tone: 8, icon: FileChartColumn },
  { id: "cards", label: "Карточки", settings: "Количество, сложность, инструкция, Темы и источники", tone: 6, icon: GalleryHorizontalEnd },
  { id: "quiz", label: "Тест", settings: "Количество, сложность, инструкция, Темы и источники", tone: 7, icon: BadgeQuestionMark },
  { id: "infographic", label: "Инфографика", settings: "Подробность, ориентация, стиль, язык и инструкция", tone: 4, icon: ChartNoAxesColumnIncreasing },
  { id: "data-table", label: "Таблица данных", settings: "Язык, описание строк и колонок, источники", tone: 3, icon: TableProperties },
];

const DEMO_ARTIFACTS: StudioArtifact[] = [
  { id: "exam-map", label: "Экзаменационный тренажёр", meta: "8 источников · 11 ч. назад", icon: Network },
  { id: "transaction-note", label: "Заметка о транзакциях", meta: "Текущая тема · вчера", icon: NotebookPen },
];

export function StudioPanel({ expanded, onExpandedChange, modelsEnabled, sourceCount, topicTitle }: StudioPanelProps) {
  const [selectedTool, setSelectedTool] = useState<StudioTool | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<StudioArtifact | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);

  function renderTool(tool: StudioTool) {
    const ToolIcon = tool.icon;
    const button = (
      <button
        key={tool.id}
        type="button"
        className={`studio-tool is-tone-${tool.tone}`}
        aria-label={tool.label}
        onClick={() => setSelectedTool(tool)}
      >
        <span className="studio-tool-icon" aria-hidden="true">
          <ToolIcon size={expanded ? 18 : 20} aria-hidden="true" />
          <Plus className="studio-tool-plus" size={10} aria-hidden="true" />
        </span>
        {expanded && <><strong>{tool.label}</strong><ChevronRight size={16} aria-hidden="true" /></>}
      </button>
    );

    return expanded ? button : <Tooltip key={tool.id} label={tool.label} side="left">{button}</Tooltip>;
  }

  function renderArtifact(artifact: StudioArtifact) {
    const ArtifactIcon = artifact.icon;
    const button = (
      <button
        key={artifact.id}
        type="button"
        className="studio-artifact"
        aria-label={`${artifact.label}, ${artifact.meta}`}
        onClick={() => setSelectedArtifact(artifact)}
      >
        <ArtifactIcon size={expanded ? 20 : 18} aria-hidden="true" />
        {expanded && <><span><strong>{artifact.label}</strong><small>{artifact.meta}</small></span><EllipsisVertical size={16} aria-hidden="true" /></>}
      </button>
    );

    return expanded ? button : <Tooltip key={artifact.id} label={artifact.label} side="left">{button}</Tooltip>;
  }

  const noteButton = (
    <button type="button" className="studio-add-note" aria-label="Добавить заметку" onClick={() => setNoteOpen(true)}>
      <StickyNote size={expanded ? 18 : 20} aria-hidden="true" />
      <Plus className="studio-note-plus" size={11} aria-hidden="true" />
      {expanded && <span>Добавить заметку</span>}
    </button>
  );

  return (
    <aside className={`workspace-studio ${expanded ? "is-expanded" : "is-collapsed"}`} aria-label="Студия">
      <header className="studio-head">
        {expanded && <h2>Студия</h2>}
        <IconButton
          className="studio-toggle"
          label={expanded ? "Свернуть Студию" : "Развернуть Студию"}
          aria-expanded={expanded}
          onClick={() => onExpandedChange(!expanded)}
        >
          {expanded ? <PanelRightClose size={18} aria-hidden="true" /> : <PanelRightOpen size={18} aria-hidden="true" />}
        </IconButton>
      </header>

      <div className="studio-scroll">
        <div className="studio-tool-grid" aria-label="Генераторы Студии">
          {STUDIO_TOOLS.map(renderTool)}
        </div>

        <div className="studio-divider" />

        <div className="studio-history" aria-label="Недавние артефакты">
          {DEMO_ARTIFACTS.map(renderArtifact)}
        </div>
      </div>

      <footer className="studio-footer">
        {expanded ? noteButton : <Tooltip label="Добавить заметку" side="left">{noteButton}</Tooltip>}
      </footer>

      <Dialog
        open={Boolean(selectedTool)}
        onOpenChange={(open) => { if (!open) setSelectedTool(null); }}
        title={selectedTool?.label ?? "Генератор Студии"}
        description="Настройки зафиксированы, но генерация пока не подключена."
      >
        <div className="studio-placeholder-dialog">
          <StatusBadge tone="neutral">Прототип</StatusBadge>
          <dl>
            <div><dt>Тема</dt><dd>{topicTitle}</dd></div>
            <div><dt>Источники</dt><dd>{sourceCount > 0 ? `${sourceCount} доступно` : "Нет доступных источников"}</dd></div>
            <div><dt>Будущие настройки</dt><dd>{selectedTool?.settings}</dd></div>
          </dl>
          {!modelsEnabled && <OfflineNotice reason="disabled" alternative="Пока доступен только просмотр интерфейса будущей генерации." />}
        </div>
      </Dialog>

      <Dialog
        open={Boolean(selectedArtifact)}
        onOpenChange={(open) => { if (!open) setSelectedArtifact(null); }}
        title={selectedArtifact?.label ?? "Артефакт Студии"}
        description="История показана на демонстрационных данных и пока не сохраняется."
      >
        <div className="studio-placeholder-dialog">
          <StatusBadge tone="neutral">Демонстрационный артефакт</StatusBadge>
          <p>{selectedArtifact?.meta}</p>
          <p>Позднее здесь появятся просмотр, использованный запрос, источники, версии и экспорт.</p>
        </div>
      </Dialog>

      <Dialog
        open={noteOpen}
        onOpenChange={setNoteOpen}
        title="Добавить заметку"
        description="Кнопка уже находится на постоянном месте; сохранение Заметок подключится вместе со Студией."
      >
        <div className="studio-placeholder-dialog">
          <StatusBadge tone="neutral">Прототип</StatusBadge>
          <p>Заметка станет независимым Markdown-артефактом и не заменит «Мой конспект» выбранной Темы.</p>
        </div>
      </Dialog>
    </aside>
  );
}
