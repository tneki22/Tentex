import { useEffect, useMemo, useRef } from "react";
import { CalendarDays, Files, ListTree, Search, Target } from "lucide-react";
import type { WebCandidateLink } from "../../../api/chat";
import type { ProjectChatManifestEntry } from "../../../api/projectChat";
import type { ProgramNodeRead } from "../../../api/projects";
import { OfflineNotice } from "../../../components/domain";
import { Button, ErrorState, LoadingState, Switch } from "../../../components/ui";
import { useAiRoleAvailability } from "../../../hooks/useAiRoleAvailability";
import { useProjectChat, type ProjectChatProgress } from "../../../hooks/useProjectChat";
import { buildProgramTree, flattenProgramTree } from "../../programTree";
import { ChatComposer, type ChatComposerHandle } from "./ChatComposer";
import { ChatHeader } from "./ChatHeader";
import { ChatModelControl } from "./ChatModelControl";
import { ChatTimeline } from "./ChatTimeline";
import { ContextChips, type ChipDef } from "./ContextChips";
import { SearchProcessLive } from "./SearchProcess";

// Оба вызова хода — структурированные ответы без потока (`source_search_chat.py`).
const SEARCH_MODEL_CAPABILITIES = ["structured_output"];

const CONTEXT_META: Array<{ flag: string; kind: string; title: string; icon: typeof Target; description: string }> = [
  { flag: "profile", kind: "profile", title: "Профиль цели", icon: Target,
    description: "Заполненные поля паспорта цели: предмет, цель, уровень, важное и исключения. Не включает дату экзамена." },
  { flag: "program", kind: "program_tree", title: "Программа", icon: ListTree,
    description: "Названия и номера текущих тем или вопросов, отметки о наличии источника и ходе подготовки. Не полный текст материалов." },
  { flag: "topic_queries", kind: "topic_queries", title: "Подсказки «Где искать»", icon: Search,
    description: "Запросы, предложенные при построении программы и сохранённые у её тем. Модель выбирает нужные и может переформулировать их." },
  { flag: "attached_materials", kind: "attached_materials", title: "Материалы проекта", icon: Files,
    description: "Только названия и исходные URL подключённых материалов. Полный текст файлов не передаётся." },
  { flag: "time_budget", kind: "time_budget", title: "Время до экзамена", icon: CalendarDays,
    description: "Дата экзамена и расчёт оставшихся учебных минут и дней по «Моей подготовке» или паспорту цели. Влияет на советы и порядок, не исключает большие источники." },
];

/** Готовые просьбы: подставляются в поле ввода, отправляет их сам пользователь. */
const QUICK_ACTIONS: Array<{ label: string; text: string }> = [
  { label: "Учебники", text: "Найди учебники и главы книг по программе" },
  { label: "Статьи и конспекты", text: "Найди статьи и конспекты лекций по темам программы" },
  { label: "Видеолекции", text: "Найди видеолекции по темам программы" },
  { label: "Онлайн-курсы", text: "Найди онлайн-курсы по предмету проекта целиком" },
  { label: "Задачи и упражнения", text: "Найди задачи и упражнения с решениями по темам программы" },
  { label: "Общие источники", text: "Найди общие источники по предмету: курсы, учебники, обзоры" },
  { label: "Где ещё не искали", text: "Продолжи поиск по темам, где ещё не искали" },
];

function contextChips(manifest: ProjectChatManifestEntry[] | undefined, variant: "exam" | "textbook" | "free"): ChipDef[] | null {
  if (!manifest) return null;
  return CONTEXT_META.filter((meta) => meta.flag !== "time_budget" || variant === "exam").map((meta) => {
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
      description: meta.description,
      preview: entry?.preview ?? [],
    };
  });
}

/** Кадры `progress` потока → пропсы живого блока «Процесс поиска». */
function liveProcess(progress: ProjectChatProgress | null) {
  const queries = (progress?.queries as string[] | undefined) ?? [];
  const found = progress?.found as number[] | undefined;
  return {
    stage: progress?.stage ?? "planning",
    reply: progress?.reply as string | undefined,
    queries: queries.map((query, index) => ({ query, found: found?.[index] })),
    candidates: (progress?.candidates as WebCandidateLink[] | undefined) ?? [],
    opening: progress?.opening as number | undefined,
    opened: progress?.opened as number | undefined,
  };
}

interface SourceSearchChatProps {
  projectId: string | null;
  nodes: ProgramNodeRead[];
  variant?: "exam" | "textbook" | "free" | "library";
  /** Пришли из подбора к теме: в поле — просьба о ней с номером темы. */
  initialTopicId?: string | null;
  /** Растёт с каждым «Найти в интернете»: поле ввода получает фокус, как только появится. */
  focusRequest?: number;
}

/**
 * Чат «Поиск в интернете» в Материалах. Модель выбирает запросы по программе и
 * подсказкам «Где искать», SearXNG ищет, лучшие страницы открываются ради объёма,
 * а ответ — карточки источников. Материалом найденное само не становится.
 */
export function SourceSearchChat({ projectId, nodes, variant = "free", initialTopicId = null, focusRequest = 0 }: SourceSearchChatProps) {
  const chat = useProjectChat({ projectId, channel: "source-search-chat", streaming: true });
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

  /* Поле ввода появляется только после загрузки сессии — фокус ждёт его. */
  const sessionId = chat.session?.id;
  const detailReady = Boolean(sessionId) && !chat.detailLoading;
  useEffect(() => {
    // Без прокрутки: блок уже плавно едет к центру экрана, фокус её не должен сбить.
    if (focusRequest > 0 && detailReady) composer.current?.focus({ preventScroll: true });
  }, [focusRequest, detailReady]);

  /* Переход «Найти в интернете» из темы: черновик с номером темы подставляется
     один раз, запрос не уходит сам — платный ход запускает человек. Номер нужен
     модели, чтобы найти тему в программе. */
  useEffect(() => {
    if (!initialTopicId || !sessionId || appliedTopic.current === initialTopicId) return;
    const node = flat.find((item) => item.id === initialTopicId);
    if (!node) return;
    appliedTopic.current = initialTopicId;
    chat.setDraft(`Найди материалы по теме ${node.number} «${node.title}»`);
    composer.current?.focus({ preventScroll: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTopicId, sessionId, flat]);

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
  const quickActions = variant === "library" ? [] : QUICK_ACTIONS;
  const ready = availability.state === "ready";
  const send = (text: string) => void chat.sendMessage(text);
  const insertDraft = (text: string) => {
    chat.setDraft(text);
    composer.current?.focus();
  };

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
                {variant === "library"
                  ? "Опишите, что хотите найти. Поиск учитывает только вашу просьбу и историю этого чата. Найденное само не добавляется в Библиотеку."
                  : "Напишите, что нужно: учебники, статьи, видео или задачи — по всему предмету или конкретной теме. Поиск учитывает программу и выбранный ниже контекст. Найденное само не добавляется в проект."}
              </p>
              {availability.state === "disabled" && (
                <OfflineNotice reason="disabled" alternative="Материалы можно добавить файлом или ссылкой." />
              )}
              {availability.state === "unavailable" && (
                <p className="program-chat-unavailable" role="status">{availability.reason}</p>
              )}
              {ready && quickActions.length > 0 && (
                <div className="program-chat-quick-starts" aria-label="Быстрый старт">
                  {quickActions.map((action) => (
                    <Button key={action.label} variant="secondary" onClick={() => insertDraft(action.text)}>
                      {action.label}
                    </Button>
                  ))}
                </div>
              )}
              <p className="chat-empty-context-note">Каждый поиск — два вызова модели и обычно 20–60 секунд.</p>
            </div>
          ) : (
            <ChatTimeline
              projectId={projectId ?? ""}
              messages={chat.messages}
              streamingMessageId={null}
              preparing={chat.sending}
              preparingContent={<SearchProcessLive {...liveProcess(chat.progress)} />}
              failure={chat.sendError ? { code: "source_search_send_error", detail: chat.sendError } : null}
              onRetry={() => send(chat.draft)}
              nodeTitles={topicLabels}
              onFollowUp={ready && !chat.sending ? send : undefined}
            />
          )}

          {chat.messages.length > 0 && ready && quickActions.length > 0 && (
            <div className="source-search-quick" aria-label="Готовые просьбы">
              {quickActions.map((action) => (
                <button key={action.label} type="button" className="source-search-chip" onClick={() => insertDraft(action.text)}>
                  {action.label}
                </button>
              ))}
            </div>
          )}

          {variant !== "library" ? <ContextChips
            label="Контекст и поиск"
            chips={contextChips(chat.contextPreview?.manifest, variant)}
            contextFlags={flags}
            onToggleFlag={chat.updateContextFlag}
            controls={
              <div className="source-search-settings">
                <Switch
                  label={variant === "exam" ? "Сначала вопросы с пробелами" : variant === "textbook"
                    ? "Сначала темы без источника и с непройденным уроком" : "Только темы без материала"}
                  hint={variant === "exam" ? "В общем поиске приоритет у вопросов без источника или без статуса «освоено». Прямую просьбу это не ограничивает."
                    : variant === "textbook" ? "Непройденный урок — сигнал для поиска, а не оценка знания. Прямую просьбу это не ограничивает."
                      : "Темы с привязанным материалом или страницами учебника не ищутся отдельно"}
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
          /> : <p className="chat-empty-context-note">Контекст: только ваш запрос и история этого чата.</p>}

          <ChatComposer
            ref={composer}
            value={chat.draft}
            onChange={chat.setDraft}
            onSend={() => send(chat.draft)}
            onStop={chat.stopMessage}
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
