import { useState } from "react";
import { Check, Copy, ExternalLink } from "lucide-react";
import type { SourceSearchResult, WebSourceItem, WebSourceKind } from "../../../api/chat";
import { Button, StatusBadge } from "../../../components/ui";
import { SearchProcessSummary } from "./SearchProcess";

const KIND_LABELS: Record<WebSourceKind, string> = {
  textbook: "Учебник",
  lecture: "Лекция",
  article: "Статья",
  video: "Видео",
  course: "Курс",
  problems: "Задачи",
  catalog: "Страница со ссылками на файлы",
  other: "Страница",
};

const LEVEL_LABELS: Record<NonNullable<WebSourceItem["level"]>, string> = {
  beginner: "для начинающих",
  intermediate: "средний уровень",
  advanced: "продвинутый уровень",
};

const CATEGORY_LABELS: Record<string, string> = { videos: "видео", science: "научное" };

/** Объём словами; число страниц и минуты — из прочитанной страницы, не от модели. */
function volumeText(item: WebSourceItem): string | null {
  const volume = item.volume;
  if (volume.kind === "video") return volume.duration ? `видео · ${volume.duration}` : "видео";
  if (volume.kind === "pdf") {
    if (volume.pages) return `PDF · ${volume.pages} стр.`;
    if (volume.size_bytes) return `PDF · ${Math.max(1, Math.round(volume.size_bytes / 1024 / 1024))} МБ`;
    return "PDF";
  }
  if (volume.minutes) return `≈ ${volume.minutes} мин чтения`;
  return null;
}

interface SourceSearchResultsProps {
  result: SourceSearchResult;
  /** «3.3 Планирование процессорного времени» по id узла программы. */
  topicLabels?: Record<string, string>;
  onFollowUp?: (text: string) => void;
}

/** Ход чата «Поиск в интернете»: запросы и отобранные источники. Кнопки «Добавить»
 * нет намеренно: поиск чаще находит страницу со ссылками, а не сам файл. */
export function SourceSearchResults({ result, topicLabels = {}, onFollowUp }: SourceSearchResultsProps) {
  const hidden = result.hidden_attached + result.hidden_seen;
  return (
    <div className="web-search-result">
      {result.searches.length > 0 && (
        <SearchProcessSummary
          reply={result.plan_reply}
          queries={result.searches.map((search) => {
            const topics = search.node_ids.map((id) => topicLabels[id]?.split(" ", 1)[0]).filter(Boolean);
            return {
              query: search.query,
              found: search.found,
              notes: [
                CATEGORY_LABELS[search.category],
                topics.length > 0 ? `темы ${topics.join(", ")}` : undefined,
              ].filter((note): note is string => Boolean(note)),
            };
          })}
          candidates={result.candidates ?? []}
        />
      )}
      {result.summary && <p className="web-search-summary">{result.summary}</p>}
      {result.items.length > 0 && (
        <ul className="external-sources web-sources">
          {result.items.map((item) => <SourceRow key={item.url} item={item} topicLabels={topicLabels} />)}
        </ul>
      )}
      {(hidden > 0 || result.unresponsive_engines.length > 0) && (
        <p className="external-source-note">
          {result.hidden_attached > 0 && `Уже в проекте: ${result.hidden_attached}. `}
          {result.hidden_seen > 0 && `Показано раньше в этом чате: ${result.hidden_seen}. `}
          {result.unresponsive_engines.length > 0 && `Не ответили поисковики: ${result.unresponsive_engines.join(", ")}.`}
        </p>
      )}
      {result.items.length > 0 && (
        <p className="external-source-note">
          Чтобы взять источник в проект, скачайте файл или скопируйте ссылку и нажмите «Добавить материал» вверху страницы.
        </p>
      )}
      {onFollowUp && result.follow_ups.length > 0 && (
        <div className="web-search-follow-ups" aria-label="Что ещё поискать">
          {result.follow_ups.map((text) => (
            <Button key={text} variant="secondary" onClick={() => onFollowUp(text)}>{text}</Button>
          ))}
        </div>
      )}
    </div>
  );
}

function SourceRow({ item, topicLabels }: { item: WebSourceItem; topicLabels: Record<string, string> }) {
  const [copied, setCopied] = useState(false);
  const volume = volumeText(item);
  const meta = [item.host, volume, item.author, item.level ? LEVEL_LABELS[item.level] : null].filter(Boolean);
  const topics = item.node_ids.map((id) => topicLabels[id]).filter(Boolean);
  const fileLinks = item.volume.file_links ?? 0;

  async function copy() {
    try {
      await navigator.clipboard.writeText(item.url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <li className={`external-source web-source is-${item.kind}`}>
      <div className="external-source-head">
        <a href={item.url} target="_blank" rel="noreferrer noopener" className="external-source-title">
          {item.title}<ExternalLink size={13} aria-hidden="true" />
        </a>
        <StatusBadge tone={item.kind === "catalog" ? "warning" : item.kind === "video" ? "info" : "neutral"}>
          {KIND_LABELS[item.kind] ?? KIND_LABELS.other}
        </StatusBadge>
      </div>
      <span className="external-source-host">
        {meta.join(" · ")}
        {fileLinks > 0 && ` · ссылок на файлы: ${fileLinks}`}
      </span>
      {item.why && <p className="web-source-line"><b>Чем полезно.</b> {item.why}</p>}
      {item.gist && <p className="web-source-line"><b>Суть.</b> {item.gist}</p>}
      <div className="web-source-foot">
        {topics.length > 0 && (
          <ul className="web-source-topics" aria-label="Темы программы">
            {topics.map((label) => <li key={label} title={label}>{label}</li>)}
          </ul>
        )}
        <div className="web-source-actions">
          <a className="text-button" href={item.url} target="_blank" rel="noreferrer noopener">
            <ExternalLink size={14} aria-hidden="true" />Открыть
          </a>
          <Button variant="ghost" onClick={() => void copy()}>
            {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
            {copied ? "Скопировано" : "Копировать ссылку"}
          </Button>
        </div>
      </div>
    </li>
  );
}
