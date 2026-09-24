import { useState } from "react";
import { History, Minus, Plus } from "lucide-react";
import type { ChatSessionDetail, ChatSettingsPatch } from "../../../api/chat";
import { Button, IconButton, Popover } from "../../../components/ui";
import { ExaminerControl } from "./ExaminerControl";

function sessionTime(iso: string, now = new Date()): string {
  const value = new Date(iso);
  const time = new Intl.DateTimeFormat("ru-RU", { timeStyle: "short" }).format(value);
  if (value.toDateString() === now.toDateString()) return `Сегодня, ${time}`;
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(value);
}

/** Минимум, нужный шапке от строки истории — экзаменационный и program-чат
 * несут разные полные типы (program-сессия не привязана к одному вопросу). */
export interface ChatHeaderSessionSummary {
  id: string;
  updated_at: string;
  message_count: number;
}

interface ChatHeaderProps {
  sessions: ChatHeaderSessionSummary[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  /** Настройки ответа для экзамена или учебного режима. */
  showResponseControl?: boolean;
  session?: ChatSessionDetail | null;
  settingsError?: string;
  onSettingsChange?: (patch: ChatSettingsPatch) => void | Promise<void>;
  historyTitle?: string;
  zoom?: number;
  onZoomChange?: (zoom: number) => void;
}

/** Компактная шапка вкладки «Чат»: история, новая сессия и настройки экзаменатора. */
export function ChatHeader({
  sessions, activeSessionId, session = null, settingsError = "",
  onSelectSession, onNewChat, onSettingsChange,
  showResponseControl = true, historyTitle = "Чаты этого вопроса",
  zoom, onZoomChange,
}: ChatHeaderProps) {
  const [historyOpen, setHistoryOpen] = useState(false);

  return (
    <header className="chat-panel-header">
      {zoom !== undefined && onZoomChange && <div className="chat-reading-zoom" role="group" aria-label="Масштаб текста чата">
        <IconButton label="Уменьшить масштаб чата" disabled={zoom <= 0.8} onClick={() => onZoomChange(Math.max(0.8, +(zoom - 0.1).toFixed(1)))}><Minus size={14} /></IconButton>
        <span aria-live="polite">{Math.round(zoom * 100)}%</span>
        <IconButton label="Увеличить масштаб чата" disabled={zoom >= 1.2} onClick={() => onZoomChange(Math.min(1.2, +(zoom + 0.1).toFixed(1)))}><Plus size={14} /></IconButton>
      </div>}
      <div className="chat-panel-header-actions">
        <Popover
          open={historyOpen}
          onOpenChange={setHistoryOpen}
          title={historyTitle}
          trigger={<IconButton label="История чатов"><History size={15} /></IconButton>}
        >
          <div className="chat-history-list">
            {sessions.map((item) => (
              <button
                type="button"
                key={item.id}
                className={`chat-history-item ${item.id === activeSessionId ? "is-active" : ""}`}
                onClick={() => { onSelectSession(item.id); setHistoryOpen(false); }}
              >
                <span className="chat-history-meta">{sessionTime(item.updated_at)} · {item.message_count} сообщ.</span>
              </button>
            ))}
          </div>
        </Popover>
        <Button variant="secondary" className="chat-new-session" aria-label="Новый чат" onClick={onNewChat}><Plus size={14} /><span>Новый чат</span></Button>
        {showResponseControl && session && onSettingsChange && (
          session.mode === "exam" ? <ExaminerControl session={session} error={settingsError} onChange={onSettingsChange} />
          : <StudyDepthControl session={session} onChange={onSettingsChange} />
        )}
      </div>
    </header>
  );
}

const STUDY_DEPTHS = [
  { label: "Кратко", max: 700, detail: "Суть и ключевые выводы · до 700 токенов" },
  { label: "Обычно", max: 1500, detail: "Объяснение с примерами · до 1500 токенов" },
  { label: "Подробно", max: 3000, detail: "Шаги, связи и ограничения · до 3000 токенов" },
];

/** Предел ответа и инструкция тьютора читают один параметр роли; остальные параметры модели сохраняются. */
function StudyDepthControl({ session, onChange }: { session: ChatSessionDetail; onChange: (patch: ChatSettingsPatch) => void | Promise<void> }) {
  const [open, setOpen] = useState(false);
  const max = Number(session.model_parameters.max_output_tokens ?? 3000);
  const active = STUDY_DEPTHS.find((item) => item.max === max);
  return <Popover open={open} onOpenChange={setOpen} title="Глубина ответа" align="end"
    trigger={<button type="button" className="chat-depth-trigger" aria-label={`Глубина ответа: ${active?.label ?? `${max} токенов`}`}>
      <span className="chat-depth-full">{active?.label ?? `${max} токенов`}</span><span className="chat-depth-short" aria-hidden="true">{active?.label.slice(0, 1) ?? "Г"}</span>
    </button>}>
    <div className="chat-depth-options">
      {STUDY_DEPTHS.map((item) => <button type="button" key={item.max} aria-pressed={max === item.max}
        onClick={() => { void onChange({ model_parameters: { ...session.model_parameters, max_output_tokens: item.max } }); setOpen(false); }}>
        <strong>{item.label}</strong><small>{item.detail}</small>
      </button>)}
    </div>
  </Popover>;
}
