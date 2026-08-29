import { useState } from "react";
import { History, Plus } from "lucide-react";
import type { ChatSessionDetail, ChatSessionSummary, ChatSettingsPatch } from "../../../api/chat";
import { Button, IconButton, Popover } from "../../../components/ui";
import { ExaminerControl } from "./ExaminerControl";

function sessionTime(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

interface ChatHeaderProps {
  question: string;
  sessions: ChatSessionSummary[];
  activeSessionId: string | null;
  session: ChatSessionDetail | null;
  settingsError: string;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onSettingsChange: (patch: ChatSettingsPatch) => void | Promise<void>;
}

/** Шапка вкладки «Чат»: область/вопрос слева, история и Экзаменатор справа. */
export function ChatHeader({
  question, sessions, activeSessionId, session, settingsError,
  onSelectSession, onNewChat, onSettingsChange,
}: ChatHeaderProps) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const active = sessions.find((item) => item.id === activeSessionId);

  return (
    <header className="chat-panel-header">
      <div className="chat-panel-heading">
        <p className="chat-panel-question">{question}</p>
        <span className="chat-panel-title">{active?.title ?? "…"}</span>
      </div>
      <div className="chat-panel-header-actions">
        <Popover
          open={historyOpen}
          onOpenChange={setHistoryOpen}
          title="Чаты этого вопроса"
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
                <span className="chat-history-title">{item.title}</span>
                <span className="chat-history-meta">{sessionTime(item.updated_at)} · {item.message_count} сообщ.</span>
              </button>
            ))}
          </div>
        </Popover>
        <Button variant="secondary" onClick={onNewChat}><Plus size={14} />Новый чат</Button>
        {session && (
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
