import { useRef, useState } from "react";
import { Link } from "react-router";
import {
  Archive,
  ArrowRight,
  Bot,
  CircleCheck,
  CircleHelp,
  HardDrive,
  Info,
  OctagonAlert,
  RefreshCw,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { Popover } from "../components/ui";
import { createBackup, verifyStorage } from "../api/storage";
import {
  probeWriteAccess,
  type StatusCommand,
  type StatusLevel,
  type SystemStatusItem,
  type SystemStorage,
} from "../api/system";
import { useSystemStatus } from "../hooks/useSystemStatus";

type Tone = "danger" | "warning" | "ok" | "pending";

const LEVEL_ICON: Record<StatusLevel, LucideIcon> = {
  danger: OctagonAlert,
  warning: TriangleAlert,
  unknown: CircleHelp,
  info: Info,
  ok: CircleCheck,
};

const TONE_ICON: Record<Tone, LucideIcon> = {
  danger: ShieldX,
  warning: ShieldAlert,
  ok: ShieldCheck,
  pending: Shield,
};

const TONE_TITLE: Record<Tone, string> = {
  danger: "Нужна помощь",
  warning: "Есть замечания",
  ok: "В порядке",
  pending: "Проверяем…",
};

function plural(count: number, one: string, few: string, many: string): string {
  const tail = count % 100;
  if (tail >= 11 && tail <= 14) return many;
  if (count % 10 === 1) return one;
  if (count % 10 >= 2 && count % 10 <= 4) return few;
  return many;
}

function formatBytes(value: number): string {
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let amount = value;
  let unit = units[0];
  for (const next of units) {
    unit = next;
    if (amount < 1024 || next === units[units.length - 1]) break;
    amount /= 1024;
  }
  const digits = amount >= 10 || unit === "Б" ? 0 : 1;
  return `${amount.toLocaleString("ru-RU", { maximumFractionDigits: digits })} ${unit}`;
}

const TIME = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" });
const DAY = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });

/** «только что», «5 мин назад», «сегодня в 12:04», «вчера в 03:00», «24 сент. в 03:00». */
function formatWhen(iso: string, now = new Date()): string {
  const date = new Date(iso);
  const minutes = Math.floor((now.getTime() - date.getTime()) / 60_000);
  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} мин назад`;
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const time = TIME.format(date);
  if (date.getTime() >= startOfToday) return `сегодня в ${time}`;
  if (date.getTime() >= startOfToday - 86_400_000) return `вчера в ${time}`;
  return `${DAY.format(date)} в ${time}`;
}

/** У молчащего воркера время — его последний отклик, у остальных — сбой. */
function failureMeta(item: SystemStatusItem): string | null {
  if (!item.last_failure_at) return null;
  const when = formatWhen(item.last_failure_at);
  if (item.code === "worker_offline") return `последний отклик ${when}`;
  if (item.occurrences && item.occurrences > 1) {
    return `${item.occurrences} ${plural(item.occurrences, "раз", "раза", "раз")} · последний ${when}`;
  }
  return `сбой ${when}`;
}

interface Notice {
  tone: "success" | "danger";
  text: string;
}

interface StatusRowProps {
  item: SystemStatusItem;
  busy: StatusCommand | null;
  onCommand: (command: StatusCommand) => void;
  onNavigate: () => void;
}

/** Строка сводки: что произошло — что сделать, справа переход или команда. */
function StatusRow({ item, busy, onCommand, onNavigate }: StatusRowProps) {
  const Icon = LEVEL_ICON[item.level];
  const meta = failureMeta(item);
  const target = item.target;
  return (
    <div className={`status-row is-${item.level}`}>
      <span className="status-row-icon"><Icon size={15} aria-hidden /></span>
      <p className="status-row-text">
        <b>{item.title}</b>
        {item.action && <span> — {item.action}</span>}
        {meta && <small>{meta}</small>}
      </p>
      {target?.kind === "link" && target.href && (
        <Link className="status-row-action" to={target.href} onClick={onNavigate}>
          {target.label}
          <ArrowRight size={13} aria-hidden="true" />
        </Link>
      )}
      {target?.kind === "command" && target.command && (
        <button
          type="button"
          className={item.level === "danger" || item.level === "warning" ? "status-row-action is-primary" : "status-row-action"}
          disabled={busy !== null}
          aria-busy={busy === target.command}
          onClick={() => onCommand(target.command!)}
        >
          {busy === target.command ? "Выполняем…" : target.label}
        </button>
      )}
    </div>
  );
}

interface StorageRowsProps {
  storage: SystemStorage;
  lowDisk: StatusLevel | null;
}

/** Две постоянные строки хранилища: место на диске и копии. */
function StorageRows({ storage, lowDisk }: StorageRowsProps) {
  const used = storage.used_bytes;
  const total = Math.max(storage.total_bytes, 1);
  // Доля Tentex на большом диске — доли процента; тонкая черта всё равно видна.
  const tentexShare = used === null || used === 0 ? 0 : Math.min(100, Math.max(1.5, (used / total) * 100));
  const freeShare = Math.min(100, (storage.free_bytes / total) * 100);
  const otherShare = Math.max(0, 100 - tentexShare - freeShare);
  const schedule = storage.automatic_enabled === null
    ? null
    : storage.automatic_enabled
      ? `ежедневно в ${storage.daily_time}, храним ${storage.retention_days} дн.`
      : "автокопии выключены";
  return (
    <div className="status-storage">
      <div className={`status-storage-row${lowDisk ? ` is-${lowDisk}` : ""}`}>
        <span className="status-storage-icon"><HardDrive size={15} aria-hidden="true" /></span>
        <div className="status-storage-text">
          <p>
            <span className="status-swatch is-tentex" aria-hidden="true" />
            <span>Tentex занимает </span><b>{used === null ? "—" : formatBytes(used)}</b>
            <span className="status-dot-sep" aria-hidden="true">·</span>
            <span>свободно </span><b className="status-free">{formatBytes(storage.free_bytes)}</b>
            <span className="status-faint"> из {formatBytes(storage.total_bytes)}</span>
          </p>
          <div
            className="status-meter"
            role="img"
            aria-label={`Tentex занимает ${used === null ? "неизвестно сколько" : formatBytes(used)}, свободно ${formatBytes(storage.free_bytes)} из ${formatBytes(storage.total_bytes)}`}
          >
            <span className="status-meter-tentex" style={{ width: `${tentexShare}%` }} />
            <span className="status-meter-other" style={{ width: `${otherShare}%` }} />
          </div>
        </div>
      </div>
      <div className="status-storage-row">
        <span className={storage.last_backup_at ? "status-storage-icon is-ok" : "status-storage-icon"}>
          <Archive size={15} aria-hidden="true" />
        </span>
        <div className="status-storage-text">
          <p>
            <span>Последняя копия </span>
            <b>{storage.last_backup_at ? formatWhen(storage.last_backup_at) : "ещё не создавалась"}</b>
            {storage.backup_in_progress && <span className="status-live"> · создаётся новая</span>}
          </p>
          {schedule && <small>{schedule}</small>}
        </div>
      </div>
    </div>
  );
}

interface SystemStatusWidgetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenBackgroundJobs: () => void;
}

/**
 * Кнопка и панель «Состояние»: сначала то, что требует действия, затем две
 * строки хранилища, затем дополнительные возможности. Данные —
 * `GET /api/system/status`; «в порядке» появляется только после настоящей
 * проверки, а не по умолчанию.
 */
export function SystemStatusWidget({ open, onOpenChange, onOpenBackgroundJobs }: SystemStatusWidgetProps) {
  const { status, unreachable, error, checking, checked, refresh, apply } = useSystemStatus();
  const [busy, setBusy] = useState<StatusCommand | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  // Панель закрывается ради «Фоновых задач» — фокус её кнопке не возвращаем.
  const handingOff = useRef(false);

  const attention = status?.items.filter((item) => item.section === "attention") ?? [];
  const storageItems = status?.items.filter((item) => item.section === "storage") ?? [];
  const capabilities = status?.items.filter((item) => item.section === "capabilities") ?? [];
  const lowDisk = attention.find((item) => item.code === "disk_low")?.level ?? null;

  const tone: Tone = unreachable || status?.overall === "attention"
    ? "danger"
    : error || status?.overall === "warning"
      ? "warning"
      : status?.overall === "ok"
        ? "ok"
        : "pending";
  const count = unreachable || error ? 1 : status?.attention_count ?? 0;
  const ToneIcon = TONE_ICON[tone];

  function changeOpen(next: boolean) {
    onOpenChange(next);
    if (next) refresh();
    else setNotice(null);
  }

  async function runCommand(command: StatusCommand) {
    if (command === "open_background_jobs") {
      handingOff.current = true;
      onOpenBackgroundJobs();
      return;
    }
    setBusy(command);
    setNotice(null);
    try {
      if (command === "probe_database") {
        const result = await probeWriteAccess();
        apply(result.status);
        setNotice(result.ok
          ? { tone: "success", text: "Запись в базу работает — сообщение снято." }
          : { tone: "danger", text: "Проверка не прошла: база всё ещё не принимает запись." });
      } else if (command === "create_backup") {
        await createBackup();
        setNotice({ tone: "success", text: "Копия создаётся — ход виден в «Фоновых задачах»." });
        refresh();
      } else if (command === "verify_storage") {
        await verifyStorage();
        setNotice({ tone: "success", text: "Проверка хранилища запущена — итог появится здесь." });
        refresh();
      }
    } catch (reason) {
      setNotice({ tone: "danger", text: reason instanceof Error ? reason.message : "Команда не выполнилась." });
    } finally {
      setBusy(null);
    }
  }

  const rowProps = { busy, onCommand: (command: StatusCommand) => void runCommand(command), onNavigate: () => changeOpen(false) };
  const subtitle = unreachable
    ? "Сервер Tentex не ответил"
    : status
      ? `${status.attention_count > 0 ? `${status.attention_count} ${plural(status.attention_count, "требует", "требуют", "требуют")} действия · ` : ""}проверено ${formatWhen(status.checked_at)}`
      : error
        ? "Сводка не загрузилась"
        : "Собираем сведения об установке";

  return (
    <Popover
      className="status-popover"
      align="end"
      open={open}
      onOpenChange={changeOpen}
      onCloseAutoFocus={(event) => {
        if (!handingOff.current) return;
        handingOff.current = false;
        event.preventDefault();
      }}
      trigger={
        <button type="button" className={`app-widget status-widget is-${tone}`}>
          <ToneIcon size={15} aria-hidden="true" />
          <b className="nav-label">Состояние</b>
          {checked && count > 0 && (
            <span className={`app-widget-value status-count is-${tone}`} aria-label={`${count} ${plural(count, "замечание", "замечания", "замечаний")}`}>
              {count}
            </span>
          )}
          {checked && count === 0 && tone === "ok" && <span className="app-widget-value is-ok">в порядке</span>}
          {checked && tone !== "pending" && tone !== "ok" && <span className={`app-widget-dot status-dot is-${tone}`} aria-hidden="true" />}
        </button>
      }
    >
      <div className="status-panel">
        <header className={`status-head is-${tone}`}>
          <span className="status-head-icon"><ToneIcon size={18} aria-hidden="true" /></span>
          <div className="status-head-text">
            <b>{TONE_TITLE[tone]}</b>
            <small>{subtitle}</small>
          </div>
          <button
            type="button"
            className="status-refresh"
            onClick={refresh}
            disabled={checking}
            aria-label="Проверить ещё раз"
            title="Проверить ещё раз"
          >
            <RefreshCw size={15} aria-hidden="true" className={checking ? "is-spinning" : undefined} />
          </button>
        </header>

        <div className="status-body">
          {notice && <p className={`status-notice is-${notice.tone}`} role="status">{notice.text}</p>}

          {unreachable && (
            <section className="status-group">
              <div className="status-row is-danger">
                <span className="status-row-icon"><OctagonAlert size={15} aria-hidden="true" /></span>
                <p className="status-row-text">
                  <b>Нет связи с локальным сервером</b>
                  <span> — проверьте, что Tentex запущен</span>
                </p>
                <button type="button" className="status-row-action is-primary" onClick={refresh} disabled={checking}>
                  {checking ? "Проверяем…" : "Повторить проверку"}
                </button>
              </div>
              <p className="status-empty">Хранилище и возможности проверим, когда сервер ответит.</p>
            </section>
          )}

          {error && !unreachable && (
            <section className="status-group">
              <div className="status-row is-unknown">
                <span className="status-row-icon"><CircleHelp size={15} aria-hidden="true" /></span>
                <p className="status-row-text">
                  <b>Не удалось получить сводку</b>
                  <span> — {error}</span>
                </p>
                <button type="button" className="status-row-action" onClick={refresh} disabled={checking}>
                  Повторить проверку
                </button>
              </div>
            </section>
          )}

          {!status && !unreachable && !error && (
            <div className="status-skeleton" aria-label="Проверяем установку">
              <span /><span /><span />
            </div>
          )}

          {status && (
            <>
              {attention.length > 0 && (
                <section className="status-group" aria-labelledby="status-attention">
                  <h4 className="status-group-title" id="status-attention">Требуют действия</h4>
                  <div className="status-list">
                    {attention.map((item) => <StatusRow key={item.code} item={item} {...rowProps} />)}
                  </div>
                </section>
              )}

              <section className="status-group" aria-labelledby="status-storage">
                <h4 className="status-group-title" id="status-storage">Хранилище</h4>
                {status.storage
                  ? <StorageRows storage={status.storage} lowDisk={lowDisk} />
                  : <p className="status-empty">Место на диске сейчас не проверить.</p>}
                {storageItems.length > 0 && (
                  <div className="status-list">
                    {storageItems.map((item) => <StatusRow key={item.code} item={item} {...rowProps} />)}
                  </div>
                )}
              </section>

              {capabilities.length > 0 && (
                <section className="status-group" aria-labelledby="status-capabilities">
                  <h4 className="status-group-title" id="status-capabilities">Возможности</h4>
                  <div className="status-list">
                    {capabilities.map((item) => <StatusRow key={item.code} item={item} {...rowProps} />)}
                  </div>
                </section>
              )}
            </>
          )}
        </div>

        <footer className="status-foot">
          <span className="status-foot-icon"><Bot size={15} aria-hidden="true" /></span>
          <span>Бот ещё в разработке</span>
          <span className="status-foot-tag">скоро</span>
        </footer>
      </div>
    </Popover>
  );
}
