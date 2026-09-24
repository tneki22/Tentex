import type { ReactNode } from "react";
import { Check, ExternalLink, Search } from "lucide-react";
import type { WebCandidateLink } from "../../../api/chat";
import { Disclosure } from "../../../components/ui";
import { plural } from "../../preparation/model";

/** Этапы хода в порядке сервера (`TurnEvent` в `source_search_chat.py`). */
const STAGES = ["planning", "searching", "opening", "picking"] as const;

export interface SearchProcessQuery {
  query: string;
  /** Сколько страниц вернул поисковик; до ответа поисковика — нет. */
  found?: number;
  /** «видео», «темы 3.1, 3.2» — пояснения к запросу. */
  notes?: string[];
}

interface SearchProcessBodyProps {
  stage: string;
  reply?: string;
  queries: SearchProcessQuery[];
  candidates: WebCandidateLink[];
  /** Сколько страниц открываем ради объёма и сколько открылось. */
  opening?: number;
  opened?: number;
}

function stepState(stage: string, step: (typeof STAGES)[number]): "done" | "active" | "pending" {
  if (stage === "done") return "done";
  const current = STAGES.indexOf(stage as (typeof STAGES)[number]);
  const index = STAGES.indexOf(step);
  if (index < current) return "done";
  return index === current ? "active" : "pending";
}

function Step({ state, label, children }: { state: "done" | "active" | "pending"; label: string; children?: ReactNode }) {
  if (state === "pending") return null;
  return (
    <li className={`search-process-step is-${state}`}>
      <span className="search-process-mark" aria-hidden="true">
        {state === "done" ? <Check size={12} /> : <span className="search-process-spinner" />}
      </span>
      <div className="search-process-step-body">
        <span className="search-process-label">{label}</span>
        {children}
      </div>
    </li>
  );
}

function SearchProcessBody({ stage, reply, queries, candidates, opening, opened }: SearchProcessBodyProps) {
  const found = queries.reduce((sum, item) => sum + (item.found ?? 0), 0);
  const openedCount = opened ?? candidates.filter((item) => item.opened).length;
  const planning = stepState(stage, "planning");
  const searching = stepState(stage, "searching");
  const openingState = stepState(stage, "opening");
  return (
    <ol className="search-process-steps">
      <Step state={planning} label={planning === "done" ? `Запросы к поисковику · ${queries.length}` : "Составляю запросы по программе"}>
        {reply && <p className="search-process-reply">{reply}</p>}
        {queries.length > 0 && (
          <ul className="web-search-queries">
            {queries.map((item) => (
              <li key={item.query}>
                <Search size={12} aria-hidden="true" />
                <span>«{item.query}»</span>
                {item.notes?.map((note) => <small key={note}>{note}</small>)}
                {item.found !== undefined && <small>найдено {item.found}</small>}
              </li>
            ))}
          </ul>
        )}
      </Step>
      <Step
        state={searching}
        label={searching === "done" ? `Страниц в выдаче: ${candidates.length || found}` : "Ищу в SearXNG"}
      >
        {candidates.length > 0 && (
          <ul className="search-process-links">
            {candidates.map((item) => (
              <li key={item.url}>
                <a href={item.url} target="_blank" rel="noreferrer noopener" title={item.title}>
                  {item.title}<ExternalLink size={11} aria-hidden="true" />
                </a>
                <small>{item.host}{item.opened ? " · открыта" : ""}</small>
              </li>
            ))}
          </ul>
        )}
      </Step>
      <Step
        state={openingState}
        label={openingState === "done"
          ? `Открыто страниц: ${openedCount}`
          : `Открываю ${opening ?? "лучшие"} страниц, чтобы узнать объём и суть`}
      />
      <Step state={stepState(stage, "picking")} label="Отбираю лучшее" />
    </ol>
  );
}

/** Живой ход: этапы раскрыты и появляются по мере работы. */
export function SearchProcessLive(props: SearchProcessBodyProps) {
  return (
    <section className="search-process is-live" aria-label="Процесс поиска" aria-live="polite">
      <h3 className="search-process-title">Процесс поиска</h3>
      <SearchProcessBody {...props} />
    </section>
  );
}

/** Готовый ход: тот же журнал, свёрнутый под ответом. */
export function SearchProcessSummary(props: Omit<SearchProcessBodyProps, "stage">) {
  const pages = props.candidates.length;
  const summary = [
    "Процесс поиска",
    `${props.queries.length} ${plural(props.queries.length, "запрос", "запроса", "запросов")}`,
    pages > 0 ? `${pages} ${plural(pages, "страница", "страницы", "страниц")}` : null,
  ].filter(Boolean).join(" · ");
  return (
    <Disclosure summary={summary} className="search-process">
      <SearchProcessBody {...props} stage="done" />
    </Disclosure>
  );
}
