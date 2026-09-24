import { useEffect, useMemo, useRef } from "react";
import { Files, ListTree, Search, Target } from "lucide-react";
import type { ProjectChatManifestEntry } from "../../../api/projectChat";
import type { ProgramNodeRead } from "../../../api/projects";
import { OfflineNotice } from "../../../components/domain";
import { Button, ErrorState, LoadingState, Select, Switch } from "../../../components/ui";
import { useAiRoleAvailability } from "../../../hooks/useAiRoleAvailability";
import { useProjectChat } from "../../../hooks/useProjectChat";
import { buildProgramTree, flattenProgramTree } from "../../programTree";
import { ChatComposer, type ChatComposerHandle } from "./ChatComposer";
import { ChatHeader } from "./ChatHeader";
import { ChatModelControl } from "./ChatModelControl";
import { ChatTimeline } from "./ChatTimeline";
import { ContextChips, type ChipDef } from "./ContextChips";
import { parsePayload } from "./payload";

// Оба вызова хода — структурированные ответы без потока (`source_search_chat.py`).
const SEARCH_MODEL_CAPABILITIES = ["structured_output"];

const CONTEXT_META: Array<{ flag: string; kind: string; title: string; icon: typeof Target }> = [
  { flag: "profile", kind: "profile", title: "Профиль цели", icon: Target },
  { flag: "program", kind: "program_tree", title: "Программа", icon: ListTree },
  { flag: "topic_queries", kind: "topic_queries", title: "Запросы «Где искать»", icon: Search },
  { flag: "attached_materials", kind: "attached_materials", title: "Материалы проекта", icon: Files },
];

/** Готовые просьбы: отправляются как обычное сообщение и видны в ленте. */
const QUICK_ACTIONS: Array<{ label: string; text: string }> = [
  { label: "Учебники", text: "Найди учебники и главы книг по программе" },
  { label: "Статьи и конспекты", text: "Найди статьи и конспекты лекций по темам программы" },
  { label: "Видеолекции", text: "Найди видеолекции по темам программы" },
  { label: "Онлайн-курсы", text: "Найди онлайн-курсы по предмету проекта целиком" },
  { label: "Задачи и упражнения", text: "Найди задачи и упражнения с решениями по темам программы" },
  { label: "Общие источники", text: "Найди общие источники по предмету: курсы, учебники, обзоры" },
  { label: "Где ещё не искали", text: "Продолжи поиск по темам, где ещё не искали" },
];

function contextChips(manifest: ProjectChatManifestEntry[] | undefined): ChipDef[] | null {
  if (!manifest) return null;
  return CONTEXT_META.map((meta) => {
    const entry = manifest.find((item) => item.kind === meta.kind);
    const count = entry?.count ?? null;
    return {
      key: meta.flag,
      icon: meta.icon,
      title: count ? `${meta.title} · ${count}` : meta.title,
      flagKey: meta.flag,
      included: entry?.included ?? false,
      bytes: entry?.bytes ?? 0,
      count,
      reason: entry?.reason ?? null,
    };
  });
}

interface SourceSearchChatProps {
  projectId: string;
  nodes: ProgramNodeRead[];
  /** Пришли из подбора к теме: область — эта тема, в поле — просьба о ней. */
  initialTopicId?: string | null;
  /** Растёт с каждым «Найти в интернете»: поле ввода получает фокус, как только появится. */
  focusRequest?: number;
}

/**
 * Чат «Поиск в интернете» в Материалах. Модель выбирает запросы по программе и
 * подсказкам «Где искать», SearXNG ищет, лучшие страницы открываются ради объёма,
 * а ответ — карточки источников. Материалом найденное само не становится.
 */
export function SourceSearchChat({ projectId, nodes, initialTopicId = null, focusRequest = 0 }: SourceSearchChatProps) {
  const chat = useProjectChat({ projectId, channel: "source-search-chat" });
  const availability = useAiRoleAvailability("source_web_search", chat.session?.model_override);
  const composer = useRef<ChatComposerHandle>(null);
  const appliedTopic = useRef<string | null>(null);

  const flat = useMemo(() => {
    const current = nodes.filter((node) => node.is_in_current_program && !node.is_archived);
    try { return flattenProgramTree(buildProgramTree(current)); }
    catch { return []; }
  }, [nodes]);
  const topicLabels = useMemo(
    () => Object.fromEntries(flat.map((node) => [node.id, `${node.number} ${node.title}`])),
    [flat],
  );
  const studyNodeIds = useMemo(
    () => new Set(flat.filter((node) => node.node_type !== "section").map((node) => node.id)),
    [flat],
  );
  const searchedCount = useMemo(() => {
    const searched = new Set<string>();
    for (const message of chat.messages) {
      const payload = parsePayload(message);
      if (payload.kind !== "tool_result" || payload.data.output_kind !== "source_search_results") continue;
      const result = payload.data.result as { searches?: Array<{ node_ids: string[] }> };
      for (const search of result.searches ?? []) {
        for (const id of search.node_ids) if (studyNodeIds.has(id)) searched.add(id);
      }
    }
    return searched.size;
  }, [chat.messages, studyNodeIds]);

  /* Поле ввода появляется только после загрузки сессии — фокус ждёт его. */
  const sessionId = chat.session?.id;
  const detailReady = Boolean(sessionId) && !chat.detailLoading;
  useEffect(() => {
    // Без прокрутки: блок уже плавно едет к центру экрана, фокус её не должен сбить.
    if (focusRequest > 0 && detailReady) composer.current?.focus({ preventScroll: true });
  }, [focusRequest, detailReady]);

  /* Переход «Найти в интернете» из темы: область и черновик подставляются один
     раз, запрос не уходит сам — платный ход запускает человек. */
  useEffect(() => {
    if (!initialTopicId || !sessionId || appliedTopic.current === initialTopicId) return;
    const label = topicLabels[initialTopicId];
    if (!label) return;
    appliedTopic.current = initialTopicId;
    void chat.updateScope(initialTopicId);
    const title = flat.find((node) => node.id === initialTopicId)?.title ?? label;
    chat.setDraft(`Найди материалы по теме «${title}»`);
    composer.current?.focus({ preventScroll: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTopicId, sessionId, topicLabels]);

  if (chat.loadError) {
    return (
      <div className="chat-panel-error">
        <ErrorState title="Чат не открылся" message={chat.loadError} />
        <Button onClick={chat.reloadSessions}>Повторить</Button>
      </div>
    );
  }
  if (chat.sessions === null) return <LoadingState label="Загружаем чат" />;

  const flags = chat.session?.context_flags ?? {};
  const ready = availability.state === "ready";
  const send = (text: string) => void chat.sendMessage(text);
  const scopeOptions = flat.map((node) => ({
    value: node.id,
    label: `${node.number} ${node.title}`,
    description: node.node_type === "section" ? "раздел" : undefined,
  }));

  return (
    <div className="program-chat-workspace source-search-chat">
      <ChatHeader
        sessions={chat.sessions}
        activeSessionId={chat.activeSessionId}
        onSelectSession={chat.setActiveSessionId}
        onNewChat={() => void chat.startNewChat()}
        showResponseControl={false}
        historyTitle="Поиски в интернете"
      />

      {chat.detailLoading && <LoadingState label="Загружаем переписку" />}
      {chat.detailError && (
        <div className="chat-panel-error">
          <ErrorState title="Переписка не загрузилась" message={chat.detailError} />
          <Button onClick={chat.retryDetail}>Повторить</Button>
        </div>
      )}

      {chat.session && !chat.detailLoading && !chat.detailError && (
        <>
          {chat.messages.length === 0 ? (
            <div className="chat-empty-invite">
              <h2>Найдём материалы в интернете</h2>
              <p>
                Попросите, что нужно: учебники, статьи, видео или задачи — по всей программе,
                разделу или теме. ИИ составит запросы по программе и подсказкам «Где искать»,
                поисковик SearXNG найдёт страницы, а лучшие из них откроются, чтобы показать
                объём и суть. В проект найденное само не добавляется.
              </p>
              {availability.state === "disabled" && (
                <OfflineNotice reason="disabled" alternative="Материалы можно добавить файлом или ссылкой." />
              )}
              {availability.state === "unavailable" && (
                <p className="program-chat-unavailable" role="status">{availability.reason}</p>
              )}
              {ready && (
                <div className="program-chat-quick-starts" aria-label="Быстрый старт">
                  {QUICK_ACTIONS.map((action) => (
                    <Button key={action.label} variant="secondary" disabled={chat.sending} onClick={() => send(action.text)}>
                      {action.label}
                    </Button>
                  ))}
                </div>
              )}
              <p className="chat-empty-context-note">
                В запрос модели уходят цель, программа с подсказками «Где искать» и список
                материалов проекта — состав можно поменять ниже. Каждый ход — два вызова модели
                и 20–60 секунд.
              </p>
            </div>
          ) : (
            <ChatTimeline
              projectId={projectId}
              messages={chat.messages}
              streamingMessageId={null}
              preparing={chat.sending}
              preparingLabel="Ищу в интернете — обычно 20–60 секунд"
              failure={chat.sendError ? { code: "source_search_send_error", detail: chat.sendError } : null}
              onRetry={() => send(chat.draft)}
              nodeTitles={topicLabels}
              onFollowUp={ready && !chat.sending ? send : undefined}
            />
          )}

          <div className="source-search-toolbar">
            <Select
              className="source-search-scope"
              ariaLabel="Искать для"
              value={chat.session.section_scope_node_id}
              emptyOption="Вся программа"
              options={scopeOptions}
              onValueChange={(value) => void chat.updateScope(value)}
              disabled={flat.length === 0}
            />
            {studyNodeIds.size > 0 && (
              <span className="source-search-coverage">Искали по {searchedCount} из {studyNodeIds.size} тем</span>
            )}
            {chat.messages.length > 0 && ready && (
              <div className="source-search-quick" aria-label="Быстрые действия">
                {QUICK_ACTIONS.map((action) => (
                  <button key={action.label} type="button" className="source-search-chip" disabled={chat.sending} onClick={() => send(action.text)}>
                    {action.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <ContextChips
            label="Контекст и поиск"
            chips={contextChips(chat.contextPreview?.manifest)}
            contextFlags={flags}
            onToggleFlag={chat.updateContextFlag}
            controls={
              <div className="source-search-settings">
                <Switch
                  label="Только темы без материала"
                  hint="Темы с привязанным материалом или страницами учебника не ищутся отдельно"
                  checked={flags.only_missing ?? true}
                  onCheckedChange={(value) => chat.updateContextFlag("only_missing", value)}
                />
                <Switch
                  label="Искать и на английском"
                  hint="Модель сможет добавить англоязычные запросы"
                  checked={flags.english_sources ?? false}
                  onCheckedChange={(value) => chat.updateContextFlag("english_sources", value)}
                />
              </div>
            }
          />

          <ChatComposer
            ref={composer}
            value={chat.draft}
            onChange={chat.setDraft}
            onSend={() => send(chat.draft)}
            placeholder="Что найти? Например: видеолекции по планированию процессов"
            modelPicker={
              <ChatModelControl
                role="source_web_search"
                capabilities={SEARCH_MODEL_CAPABILITIES}
                value={chat.session.model_override}
                parameters={chat.session.model_parameters}
                contextBytes={chat.contextPreview?.total_bytes}
                messageCount={chat.messages.length}
                onChange={chat.updateModel}
              />
            }
            showModeIndicator={false}
            sending={chat.sending}
          />
        </>
      )}
    </div>
  );
}
