import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import {
  AlertTriangle,
  ArrowLeft,
  BookOpenText,
  FileStack,
  CheckCircle2,
  CircleDashed,
  Pause,
  Play,
  ScanSearch,
  XCircle,
} from "lucide-react";
import { controlCoverageRun, type CoverageBucket, type CoverageLimits } from "../../api/coverage";
import { getProject, type ProjectDetail } from "../../api/projects";
import { ProjectNav, ResearchLaunchDialog } from "../../components/domain";
import { Button, Card, EmptyState, ErrorState, LoadingState, PageHead, Progress, StatusBadge, Tooltip } from "../../components/ui";
import { StackedBar, type BarSegment } from "../../components/ui/chart";
import { useCoverage } from "../../hooks/useCoverage";
import { ResumeBudgetDialog } from "./ResumeBudgetDialog";

const NUMBER = new Intl.NumberFormat("ru-RU");

const BUCKETS: Array<{ key: CoverageBucket; label: string; token: string }> = [
  { key: "linked", label: "Связаны с программой", token: "--accent" },
  { key: "mixed_resolved", label: "Смешанные разобраны", token: "--tone-info" },
  { key: "outside_program", label: "Вне программы", token: "--project-color-5" },
  { key: "service", label: "Служебные", token: "--muted" },
  { key: "unresolved", label: "Ждут уточнения", token: "--tone-warning" },
  { key: "processing", label: "Сейчас в работе", token: "--chart-fact" },
  { key: "pending", label: "Ещё не рассмотрены", token: "--line-strong" },
  { key: "error", label: "Ошибка обработки", token: "--tone-danger" },
  { key: "stale", label: "Устарели", token: "--chart-plan" },
];

const LIMIT_LABEL: Record<string, string> = {
  docx_tables_not_enumerated: "Таблицы DOCX могут отсутствовать в подготовленном тексте",
  markdown_fenced_heading_risk: "# внутри fenced code может быть принят за заголовок",
  youtube_timestamps_not_preserved: "Таймкоды YouTube пока не сохраняются",
  bbox_reliability_not_preserved: "Точность координат областей пока не переносится между версиями",
};

const RUNNING_STATES = new Set(["queued", "running"]);

/** Код остановки читает worker, человеку нужна фраза и следующий шаг. */
const STOP_REASON: Record<string, string> = {
  budget_tokens: "Достигнут предел по токенам запуска",
  budget_calls: "Достигнут предел по числу вызовов",
  budget_cost_usd: "Достигнут денежный предел запуска",
  budget_limit: "Достигнут предел запуска",
  snapshot_changed: "Источник, программа или цель изменились после запуска",
  user_pause: "Обзор остановлен вручную",
  user_cancelled: "Обзор отменён",
  executor_unavailable: "Для роли обзора не выбрана модель",
  execution_error: "Сбой при обращении к модели",
  lease_lost: "Запуск перехватил другой процесс",
  work_exhausted: "Все блоки области рассмотрены",
};

const BUDGET_REASONS = new Set(["budget_tokens", "budget_calls", "budget_cost_usd", "budget_limit"]);

/** Машинная причина остаётся в receipt; на экране стоит фраза, по которой понятно, что делать. */
const REASON_LABEL: Record<string, string> = {
  unsupported_evidence: "Опора не нашлась в прочитанном тексте",
  invalid_schema: "Ответ модели не соответствует схеме решения",
  missing_or_duplicate_target: "Решения по этому блоку в ответе нет или их два",
  fragment_accounting: "Учтены не все фрагменты блока",
  range_accounting: "Диапазоны внутри фрагмента не сходятся",
  unread_remainder: "Часть блока осталась непрочитанной",
  unresolved_remainder: "Остаток блока не отнесён ни к чему",
  unresolved_reason: "Модель не назвала причину неопределённости",
  visual_unavailable: "Нужен визуальный разбор, он подключается позже",
  range_with_parts: "Диапазон блоков пришёл вместе с разбором по частям",
  parts_missing: "Модель приняла решение, но не перечислила фрагменты",
  decision_too_large: "Ответ по блоку не помещается в допустимый размер",
  interval_unresolved: "Часть длинного блока осталась нерешённой",
  manual_conflict: "Ваше ручное решение изменилось во время обзора",
  unknown_topic: "Модель назвала тему, которой нет в программе",
  link_accounting: "Часть блока отнесена к теме, но связь не подтверждена опорой",
  disposition_without_link: "Назначение части блока не совпало с её связью",
  link_scope: "Связь ведёт за пределы блока или программы",
  heading_content: "Заголовок предложен как раскрытие темы",
  outcome_dispositions: "Исход блока не сходится с назначением его частей",
  content_without_target: "Опора взята не из самого блока",
  reference_roles: "У упоминания указана роль раскрытия",
  mixed_parts: "Смешанный исход без двух разных частей",
  unsupported_finding: "Предложение по программе не подкреплено опорой",
  duplicate_evidence_key: "Две разные опоры с одним ключом",
  target_scope: "Решение пришло не по тому блоку",
  empty_or_missing_fragment: "Фрагмент блока пуст или не прочитан",
};

const BUCKET_REASON: Record<string, string> = {
  stale: "Источник изменился после обзора",
  error: "Обработка блока завершилась ошибкой",
  unresolved: "Не хватило проверяемой опоры или контекста",
};

function reasonText(bucket: string, reason: string | null): string {
  const code = (reason ?? "").replace(/^invalid_decision:/, "");
  return REASON_LABEL[code] ?? BUCKET_REASON[bucket] ?? "Блок требует внимания";
}

const ISSUE_ORDER: CoverageBucket[] = ["error", "unresolved", "stale"];
const BUCKET_TITLE: Record<string, string> = {
  error: "ошибки обработки",
  unresolved: "ждут уточнения",
  stale: "устарели",
};

/** Число тем без названий нечитаемо: «6 тем» не говорит, каких именно. */
function TopicNames({ titles, total }: { titles: string[]; total: number }) {
  if (titles.length === 0) return null;
  const shown = titles.slice(0, 3);
  const rest = total - shown.length;
  return (
    <Tooltip label={titles.join(" · ") + (total > titles.length ? " …" : "")}>
      <p className="coverage-topic-names">{shown.join(" · ")}{rest > 0 ? ` и ещё ${rest}` : ""}</p>
    </Tooltip>
  );
}

/** Первый рабочий экран прохода 2: полный учёт подготовленного текста без обещания И4. */
export function CoverageOverviewScreen() {
  const { projectId } = useParams();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [projectError, setProjectError] = useState("");
  const [launchOpen, setLaunchOpen] = useState(false);
  const [controlBusy, setControlBusy] = useState(false);
  const [resumeOpen, setResumeOpen] = useState(false);
  const coverage = useCoverage(projectId);

  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    void getProject(projectId, controller.signal)
      .then(setProject)
      .catch((caught) => {
        if (!controller.signal.aborted) setProjectError(caught instanceof Error ? caught.message : "Не удалось открыть проект");
      });
    return () => controller.abort();
  }, [projectId]);

  const segments = useMemo<BarSegment[]>(() => BUCKETS.map((bucket) => ({
    value: coverage.overview?.distribution[bucket.key] ?? 0,
    token: bucket.token,
    label: bucket.label,
    soft: bucket.key === "pending" || bucket.key === "stale",
  })), [coverage.overview]);

  if (!projectId) return <ErrorState title="Проект не выбран" message="Откройте Покрытие из учебникового проекта." />;
  if (projectError) return <ErrorState title="Не удалось открыть Покрытие" message={projectError} />;
  if (!project || coverage.loading) return <LoadingState placement="page" label="Собираем обзор покрытия" />;
  if (project.project.workspace_variant !== "textbook") {
    return <ErrorState title="Покрытие пока доступно учебниковым проектам" message="Экзаменационные Ответы остались отдельным экраном." />;
  }
  if (coverage.error || !coverage.overview) {
    return <ErrorState title="Не удалось загрузить покрытие" message={coverage.error}><Button onClick={() => void coverage.refresh()}>Повторить</Button></ErrorState>;
  }

  const { overview, run, issues, issueTotal, issueCounts } = coverage;
  const runTotal = run?.primary.total ?? overview.total;
  const inspected = run?.primary.inspected ?? (
    overview.distribution.linked
    + overview.distribution.mixed_resolved
    + overview.distribution.outside_program
    + overview.distribution.service
    + overview.distribution.unresolved
  );
  const active = Boolean(run && RUNNING_STATES.has(run.state));
  const budgetStop = Boolean(run && run.stop_reason && BUDGET_REASONS.has(run.stop_reason));
  const stoppedWithProblem = Boolean(run && ["failed", "cancelled"].includes(run.state));
  const runTitle = active
    ? "Модель распределяет блоки"
    : run?.state === "completed"
      ? "Первичный обзор завершён"
      : run?.state === "paused"
        ? "Первичный обзор на паузе"
        : stoppedWithProblem
          ? "Обзор остановлен до завершения"
          : "Подготовленный текст ждёт обзора";
  const percentage = overview.material_ratio.value === null
    ? null
    : Math.round(overview.material_ratio.value * 100);
  const emptyScope = overview.sources.length === 0
    ? { title: "В проекте нет источников", body: "Добавьте учебник или конспект в «Материалах» — исследовать пока нечего." }
    : overview.total === 0
      ? { title: "Подготовленного текста ещё нет", body: "Источники подключены, но ни один файл не разобран на блоки. Дождитесь разбора в «Материалах»." }
      : null;

  async function control(action: "pause" | "resume" | "cancel", limits?: CoverageLimits) {
    if (!run) return;
    setControlBusy(true);
    try {
      await controlCoverageRun(projectId!, run, action, limits);
      setResumeOpen(false);
      await coverage.refresh();
    } finally {
      setControlBusy(false);
    }
  }

  return (
    <div className="coverage-screen">
      <aside className="project-side-panel">
        <header className="project-side-title">
          <Tooltip label="Вернуться в рабочую область">
            <Link className="workspace-back-button" to={`/projects/${projectId}`} aria-label="Вернуться в рабочую область"><ArrowLeft size={15} /></Link>
          </Tooltip>
          <strong>{project.project.name}</strong>
        </header>
        <nav className="coverage-local-nav" aria-label="Разделы покрытия">
          <span className="is-active"><ScanSearch size={15} /><span>Обзор</span></span>
        </nav>
        <ProjectNav projectId={projectId} active="coverage" textbook modules={project.project.enabled_modules} className="project-side-nav" />
      </aside>

      <main className="coverage-main">
        <PageHead
          eyebrow="Покрытие"
          title="Обзор"
          lead="Первичный обзор показывает, что произошло с каждым блоком подготовленного текста. Углубление и синтез коллекции ещё не выполняются."
          actions={<>
            {run?.state === "running" && <Button variant="secondary" disabled={controlBusy} onClick={() => void control("pause")}><Pause size={15} />Пауза</Button>}
            {run?.state === "paused" && !run.stale && (
              <Button
                variant="secondary"
                disabled={controlBusy}
                onClick={() => budgetStop ? setResumeOpen(true) : void control("resume")}
              >
                <Play size={15} />{budgetStop ? "Продолжить с новым пределом" : "Продолжить"}
              </Button>
            )}
            {run?.state === "paused" && <Button variant="ghost" disabled={controlBusy} onClick={() => void control("cancel")}><XCircle size={15} />Отменить запуск</Button>}
            <Button onClick={() => setLaunchOpen(true)}><ScanSearch size={15} />Исследовать материалы</Button>
          </>}
        />

        <section className="coverage-status-strip" aria-label="Состояние первичного обзора">
          <div className="coverage-stage">
            <span className={active ? "is-active" : stoppedWithProblem ? "is-danger" : run?.state === "paused" ? "is-warning" : ""}>
              {active ? <CircleDashed size={19} /> : stoppedWithProblem ? <AlertTriangle size={19} /> : run?.state === "paused" ? <Pause size={19} /> : <CheckCircle2 size={19} />}
            </span>
            <div><small>{active ? "Сейчас происходит" : run ? "Последний запуск" : "Исследование не запускалось"}</small><strong>{runTitle}</strong>{run?.stop_reason && run.stop_reason !== "work_exhausted" && <small>{STOP_REASON[run.stop_reason] ?? `Причина: ${run.stop_reason}`}{budgetStop && run ? `: ${NUMBER.format(run.costs.tokens)} из ${NUMBER.format(run.limits.max_total_tokens)} токенов, ${run.costs.calls} из ${run.limits.max_calls} вызовов, $${run.costs.cost_usd.toFixed(2)}${run.limits.max_cost_usd === null ? "" : ` из $${run.limits.max_cost_usd.toFixed(2)}`}.` : "."} Сохранённые решения доступны.</small>}{run?.stale && <small>Источник изменился после запуска: продолжить прежний обзор нельзя — отмените его и запустите заново.</small>}</div>
          </div>
          <div className="coverage-progress-copy"><strong>{runTotal > 0 ? `${inspected} из ${runTotal}` : "—"}</strong><span>блоков выбранной области рассмотрено</span></div>
          {runTotal > 0 && <Progress value={inspected} max={runTotal} label={`Рассмотрено ${inspected} из ${runTotal} блоков выбранной области`} />}
        </section>

        <section className="coverage-distribution" aria-labelledby="coverage-distribution-title">
          <header><div><h2 id="coverage-distribution-title">Весь набор блоков</h2><p>Распределение важнее одного процента: нерешённое и непросмотренное здесь не спрятаны.</p></div><strong>{overview.total}</strong></header>
          {emptyScope ? <EmptyState className="coverage-empty" title={emptyScope.title} icon={<FileStack size={26} />}><p>{emptyScope.body}</p><Link to={`/projects/${projectId}/materials`}>Открыть Материалы</Link></EmptyState> : <>
            <StackedBar segments={segments} total={overview.total} size="large" ariaLabel="Распределение всех блоков материала" />
            <div className="coverage-legend">
              {BUCKETS.map((bucket) => <div key={bucket.key}><i style={{ background: `var(${bucket.token})` }} /><span>{bucket.label}</span><strong>{overview.distribution[bucket.key]}</strong></div>)}
            </div>
          </>}
        </section>

        <section className="coverage-metric-grid">
          <Card className="coverage-metric-card is-program">
            <small>Программа обеспечена содержанием</small>
            <strong>{overview.topics.with_content} <span>из {overview.topics.total} тем</span></strong>
            {overview.topics.total === 0
              ? <p>Программа пуста: относить блоки не к чему. Соберите темы в разделе «Программа» и запустите обзор снова.</p>
              : <p>Только content-связи. Упоминания не превращают тему в обеспеченную.{overview.topics.legacy > 0 && ` Тем со связями до прохода 2, где назначение неизвестно: ${overview.topics.legacy}.`}</p>}
            <TopicNames titles={overview.content_titles} total={overview.topics.with_content} />
          </Card>
          <Card className="coverage-metric-card is-material">
            <small>{overview.material_ratio.label}</small>
            <strong>{percentage === null ? "Нет данных" : `${percentage}%`} {percentage !== null && <span>{overview.material_ratio.numerator} из {overview.material_ratio.denominator}</span>}</strong>
            <p>Нерешённых — {overview.distribution.unresolved}; нерассмотренных — {overview.distribution.pending + overview.distribution.processing}; устаревших — {overview.distribution.stale}.</p>
          </Card>
          <Card className="coverage-metric-card is-reading">
            <small>Основа чтения</small>
            <strong>{overview.topics.reading_basis} <span>тем</span></strong>
            <p>Есть проверенное определение или объяснение. Пример сам по себе сюда не входит.</p>
            <TopicNames titles={overview.reading_titles} total={overview.topics.reading_basis} />
          </Card>
        </section>

        <section className="coverage-sources" aria-labelledby="coverage-sources-title">
          <header><div><h2 id="coverage-sources-title">Источники проекта</h2><p>Разбор файла подготавливает текст; исследование проверяет его содержание относительно программы. Область последнего запуска отмечена отдельно.</p></div></header>
          <div className="coverage-source-list">
            {overview.sources.map((source) => {
              const reviewed = source.total - source.distribution.pending - source.distribution.processing - source.distribution.error - source.distribution.stale;
              return <article key={source.id}>
                <div className="coverage-source-heading"><BookOpenText size={17} /><span><strong>{source.name}</strong><small>Ревизия {source.revision} · {reviewed} из {source.total} рассмотрено</small></span>{run && <StatusBadge tone={source.in_latest_run ? "info" : "neutral"}>{source.in_latest_run ? "в области запуска" : "вне запуска"}</StatusBadge>}<Link to={`/projects/${projectId}/materials/${source.id}`}>Открыть текст</Link></div>
                <StackedBar segments={BUCKETS.map((bucket) => ({ value: source.distribution[bucket.key], token: bucket.token, label: bucket.label, soft: bucket.key === "pending" }))} total={source.total} ariaLabel={`Распределение блоков ${source.name}`} />
                {source.known_limits.length > 0 && <div className="coverage-diagnostics"><AlertTriangle size={14} /><span>{source.known_limits.map((limit) => LIMIT_LABEL[limit] ?? limit).join("; ")}.</span></div>}
              </article>;
            })}
          </div>
        </section>

        <section className="coverage-issues" aria-labelledby="coverage-issues-title">
          <header><div><h2 id="coverage-issues-title">Где нужна помощь</h2><p>Технический сбой можно повторить, нерешённый блок — уточнить на следующем слое, устаревший — перепроверить после изменения источника.</p></div><StatusBadge tone={issueCounts.error ? "danger" : issueCounts.unresolved ? "warning" : "neutral"}>{issueTotal}</StatusBadge></header>
          {issueTotal > 0 && <p className="coverage-issue-summary">{ISSUE_ORDER.filter((bucket) => issueCounts[bucket]).map((bucket) => `${BUCKET_TITLE[bucket]} — ${issueCounts[bucket]}`).join(" · ")}.</p>}
          {issueTotal === 0 ? <p className="coverage-no-issues">Ошибок и нерешённых блоков нет.</p> : <div className="coverage-issue-list">
            {issues.map((block) => <article key={block.block_id}>
              <span className={`coverage-issue-icon is-${block.bucket}`}><AlertTriangle size={15} /></span>
              <div><strong>{block.title || `Блок на стр. ${block.page_from}`}</strong><small>{block.material_name} · стр. {block.page_from}{block.page_to !== block.page_from ? `–${block.page_to}` : ""}</small><p>{reasonText(block.bucket, block.reason)}{block.reason && <code>{block.reason}</code>}</p></div>
              <Link to={`/projects/${projectId}/materials/${block.material_id}?page=${block.page_from}`}>К первичному тексту</Link>
            </article>)}
            {issueTotal > issues.length && <p className="coverage-no-issues">Показаны первые {issues.length}; всего требуют внимания {issueTotal}.</p>}
          </div>}
        </section>
      </main>

      {run && (
        <ResumeBudgetDialog
          open={resumeOpen}
          run={run}
          busy={controlBusy}
          onOpenChange={setResumeOpen}
          onResume={(limits) => void control("resume", limits)}
        />
      )}

      <ResearchLaunchDialog
        open={launchOpen}
        projectId={projectId}
        onOpenChange={setLaunchOpen}
        onStarted={() => void coverage.refresh()}
      />
    </div>
  );
}
