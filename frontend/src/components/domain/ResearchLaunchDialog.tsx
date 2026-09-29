import { useEffect, useMemo, useState } from "react";
import { BookOpen, CircleDollarSign, Layers3, RefreshCw } from "lucide-react";
import {
  getCoverageOverview,
  preflightCoverage,
  startCoverage,
  type CoverageOverview,
  type CoveragePlan,
  type CoveragePreflight,
  type CoverageRun,
} from "../../api/coverage";
import { listMaterials, type MaterialRead } from "../../api/materials";
import { getProject } from "../../api/projects";
import { Button, Checkbox, Dialog, Field, LoadingState, StatusBadge } from "../ui";
import { OfflineNotice } from "./OfflineNotice";
import { researchState, type ResearchState } from "./researchStatus";

interface ResearchLaunchDialogProps {
  open: boolean;
  projectId: string;
  initialMaterialIds?: string[];
  /** Блоки для повторной проверки после создания темы; запуск остаётся решением человека. */
  blockIds?: string[];
  forceIncremental?: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted?: (run: CoverageRun) => void;
  loadContext?: (
    projectId: string,
    signal: AbortSignal,
  ) => Promise<{ programRevision: number; materials: MaterialRead[] }>;
  preflightRequest?: typeof preflightCoverage;
  startRequest?: typeof startCoverage;
  /** Сводка покрытия для подписи «исследован»; без неё диалог работает как прежде. */
  loadResearch?: (projectId: string, signal: AbortSignal) => Promise<CoverageOverview | null>;
}

function loadDefaultResearch(projectId: string, signal: AbortSignal) {
  return getCoverageOverview(projectId, signal).catch(() => null);
}

/** Предел расхода выбирает человек: молча тратить деньги на обзор книги нельзя. */
const DEFAULT_COST_USD = "1.00";
const NUMBER = new Intl.NumberFormat("ru-RU");

function blockCount(value: number | undefined): string {
  if (value === undefined) return "… блоков";
  const last = value % 10;
  const teen = value % 100;
  const noun = last === 1 && teen !== 11 ? "блок" : last >= 2 && last <= 4 && (teen < 12 || teen > 14) ? "блока" : "блоков";
  return `${value} ${noun}`;
}

const ROLE_LABEL: Record<string, string> = {
  main: "основной",
  additional: "дополнительный",
  reference: "справочный",
};

async function loadDefaultContext(projectId: string, signal: AbortSignal) {
  const [project, materials] = await Promise.all([
    getProject(projectId, signal),
    listMaterials(projectId, signal),
  ]);
  return { programRevision: project.program.revision, materials };
}

/** Единый preflight/start-диалог для мастера, Материалов и Покрытия. */
export function ResearchLaunchDialog({
  open,
  projectId,
  initialMaterialIds,
  blockIds = [],
  forceIncremental = false,
  onOpenChange,
  onStarted,
  loadContext = loadDefaultContext,
  preflightRequest = preflightCoverage,
  startRequest = startCoverage,
  loadResearch = loadDefaultResearch,
}: ResearchLaunchDialogProps) {
  const [materials, setMaterials] = useState<MaterialRead[]>([]);
  const [programRevision, setProgramRevision] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [mode, setMode] = useState<CoveragePlan["mode"]>("initial");
  const [preflight, setPreflight] = useState<CoveragePreflight | null>(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const [costLimit, setCostLimit] = useState(DEFAULT_COST_USD);
  const [states, setStates] = useState<Map<string, ResearchState>>(new Map());

  useEffect(() => {
    if (!open || !projectId) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    Promise.all([loadContext(projectId, controller.signal), loadResearch(projectId, controller.signal)])
      .then(([{ programRevision: revision, materials: sourceRows }, overview]) => {
        if (controller.signal.aborted) return;
        const ready = sourceRows.filter((item) => item.status === "ready");
        const known = new Map<string, ResearchState>();
        for (const source of overview?.sources ?? []) {
          const state = researchState(source);
          if (state) known.set(source.id, state);
        }
        setStates(known);
        setMaterials(sourceRows);
        setProgramRevision(revision);
        const requested = initialMaterialIds?.filter((id) => ready.some((item) => item.id === id));
        const unexplored = ready.filter((item) => known.get(item.id)?.needed ?? true);
        const chosen = requested?.length ? requested : (unexplored.length ? unexplored : ready).map((item) => item.id);
        setSelected(chosen);
        setMode(forceIncremental || chosen.some((id) => known.get(id)?.researched) ? "incremental" : "initial");
        setRequestKey(crypto.randomUUID());
      })
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "Не удалось подготовить запуск");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [open, projectId, initialMaterialIds?.join(","), forceIncremental, loadContext, loadResearch]);

  const cost = Number(costLimit.replace(",", "."));
  const costValid = costLimit.trim() === "" || (Number.isFinite(cost) && cost > 0);

  // Отпечаток preflight зависит от области и моделей, но не от лимитов, поэтому
  // правка предела расхода не перезапрашивает проверку на каждый символ. Сами
  // вызовы и токены выводит сервер из готовых пакетов: плоские числа не знают
  // размера книги и останавливали обзор на середине учебника.
  const scope = useMemo<CoveragePlan>(() => ({
    material_ids: selected,
    context_material_ids: [],
    mode,
    ...(mode === "incremental" && blockIds.length ? { block_ids: blockIds } : {}),
    expected_program_revision: programRevision,
    limits: {},
  }), [programRevision, selected, mode, blockIds.join(",")]);

  const plan: CoveragePlan = costValid && costLimit.trim() !== ""
    ? { ...scope, limits: { max_cost_usd: cost } }
    : scope;

  useEffect(() => {
    if (!open || !projectId || selected.length === 0) {
      setPreflight(null);
      return;
    }
    const controller = new AbortController();
    setPreflight(null);
    void preflightRequest(projectId, scope, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setPreflight(value);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "Проверка запуска не удалась");
        }
      });
    return () => controller.abort();
  }, [open, projectId, scope, preflightRequest]);

  function toggleMaterial(id: string, checked: boolean) {
    setSelected((current) => checked ? [...current, id] : current.filter((item) => item !== id));
    setRequestKey(crypto.randomUUID());
    setError("");
  }

  function changeMode(next: CoveragePlan["mode"]) {
    setMode(next);
    setRequestKey(crypto.randomUUID());
    setError("");
  }

  async function start() {
    if (!preflight) return;
    setStarting(true);
    setError("");
    try {
      const run = await startRequest(projectId, plan, preflight.fingerprint, requestKey);
      onStarted?.(run);
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось запустить исследование");
    } finally {
      setStarting(false);
    }
  }

  const unavailable = materials.filter((item) => item.status !== "ready");
  const repeated = selected.filter((id) => states.get(id)?.researched);
  const model = preflight?.model_roles.overview;
  const researchModel = preflight?.model_roles.research;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Исследовать материалы"
      description="Обзор распределит выбранные блоки подготовленного текста. Углубление и синтез коллекции появятся следующим этапом."
      className="research-launch-dialog"
      footer={<>
        <Button variant="ghost" disabled={starting} onClick={() => onOpenChange(false)}>Отменить</Button>
        <Button disabled={!preflight?.execution_available || !preflight.blocks || selected.length === 0 || starting || !costValid} onClick={() => void start()}>
          {starting ? "Запускаем…" : `Начать обзор${preflight ? ` · ${preflight.blocks} бл.` : ""}`}
        </Button>
      </>}
    >
      {loading ? <LoadingState label="Проверяем источники" /> : <>
        <section className="research-launch-section">
          <header><BookOpen size={16} /><span><b>Область обзора</b><small>Роль источника не исключает его из выбора</small></span></header>
          <div className="research-launch-sources">
            {materials.filter((item) => item.status === "ready").map((material) => (
              <div className="research-launch-source" key={material.id}>
                <Checkbox
                  checked={selected.includes(material.id)}
                  onCheckedChange={(checked) => toggleMaterial(material.id, checked)}
                  label={material.display_name}
                />
                <StatusBadge tone="neutral">{ROLE_LABEL[material.source_role]}</StatusBadge>
                {states.get(material.id) && <small className={`materials-research-state is-${states.get(material.id)?.tone}`}>{states.get(material.id)?.label}</small>}
              </div>
            ))}
          </div>
          {unavailable.length > 0 && <p className="research-launch-note">Не готовы и не войдут автоматически: {unavailable.map((item) => item.display_name).join(", ")}.</p>}
          {repeated.length > 0 && mode === "initial" && <p className="research-launch-note is-warning">Уже исследованное будет прочитано заново целиком: {materials.filter((item) => repeated.includes(item.id)).map((item) => item.display_name).join(", ")}. Повторный обзор снова тратит вызовы модели.</p>}
        </section>

        <fieldset className="research-launch-mode">
          <legend>Что исследовать</legend>
          <label>
            <input type="radio" name="research-mode" checked={mode === "incremental"} onChange={() => changeMode("incremental")} />
            Только нужное · {blockCount(preflight?.blocks_needed)}
          </label>
          <label>
            <input type="radio" name="research-mode" checked={mode === "initial"} disabled={forceIncremental || blockIds.length > 0} onChange={() => changeMode("initial")} />
            Всё заново · {blockCount(preflight?.blocks_all)}
          </label>
          {mode === "incremental" && preflight?.blocks === 0 && <p>Нужных блоков нет. Выберите другой источник или полный повтор.</p>}
        </fieldset>

        <section className="research-launch-facts">
          <div><Layers3 size={16} /><span><small>Подготовленный текст</small><b>{preflight ? `${blockCount(preflight.blocks)} · от ${preflight.packets_at_least} вызовов` : "Проверяем…"}</b></span></div>
          <div><RefreshCw size={16} /><span><small>Модель обзора</small><b>{model?.model_id ?? "Не настроена"}</b></span></div>
          <div><CircleDollarSign size={16} /><span><small>Модель исследования</small><b>{researchModel?.model_id ?? "Не настроена"}</b></span></div>
        </section>

        <Field
          label="Предел расхода, $"
          hint="Запуск останавливается, как только следующая попытка выйдет за предел. Пустое поле — без денежного потолка."
          error={costValid ? undefined : "Введите положительное число или очистите поле"}
        >
          <input
            className="input"
            inputMode="decimal"
            value={costLimit}
            onChange={(event) => {
              setCostLimit(event.target.value);
              setRequestKey(crypto.randomUUID());
            }}
          />
        </Field>

        {preflight && !preflight.execution_available && (
          <OfflineNotice reason="disabled" alternative={`${(preflight.execution_issue ?? "Выберите модель для ролей прохода 2").replace(/\.?$/, ".")} Сохранённое покрытие останется доступно.`} />
        )}
        {preflight && preflight.prompt_overhead_tokens > 0 && (
          <p className="research-launch-note">
            Дерево тем уходит в модель с каждым вызовом: постоянная часть запроса — около {NUMBER.format(preflight.prompt_overhead_tokens)} токенов, на текст блоков остаётся {NUMBER.format(preflight.packet_input_tokens)}.
          </p>
        )}
        <p className="research-launch-boundary">«Файл разобран» означает, что Tentex подготовил текст. «Содержание исследовано» появится только после проверки блоков моделью.</p>
        {error && <p className="inline-error" role="alert">{error}</p>}
      </>}
    </Dialog>
  );
}
