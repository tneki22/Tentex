import { useState } from "react";
import { History, Plus } from "lucide-react";
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
  /** Persona/строгость/override модели — только у экзаменационного чата. */
  showModelControl?: boolean;
  session?: ChatSessionDetail | null;
  settingsError?: string;
  onSettingsChange?: (patch: ChatSettingsPatch) => void | Promise<void>;
  historyTitle?: string;
}

/** Компактная шапка вкладки «Чат»: история, новая сессия и настройки экзаменатора. */
export function ChatHeader({
  sessions, activeSessionId, session = null, settingsError = "",
  onSelectSession, onNewChat, onSettingsChange,
  showModelControl = true, historyTitle = "Чаты этого вопроса",
}: ChatHeaderProps) {
  const [historyOpen, setHistoryOpen] = useState(false);

  return (
    <header className="chat-panel-header">
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
        <Button variant="secondary" onClick={onNewChat}><Plus size={14} />Новый чат</Button>
        {showModelControl && session && onSettingsChange && (
          <ExaminerControl
            session={session}
            error={settingsError}
            onChange={onSettingsChange}
          />
        )}
      </div>
    </header>
  );
}
