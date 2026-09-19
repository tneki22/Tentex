import { useState } from "react";
import type { CoverageLimits, CoverageRun } from "../../api/coverage";
import { Button, Dialog, Field } from "../../components/ui";

const NUMBER = new Intl.NumberFormat("ru-RU");

/** Какой именно предел остановил обзор: подпись берётся из stop_reason запуска. */
const LIMIT_TITLE: Record<string, string> = {
  budget_tokens: "токенов",
  budget_calls: "вызовов",
  budget_cost_usd: "расхода",
};

/** Новый потолок с запасом: продолжать с прежним числом бессмысленно. */
function suggestTokens(run: CoverageRun): number {
  const needed = Math.max(run.limits.max_total_tokens, run.costs.tokens) * 2;
  return Math.ceil(needed / 100_000) * 100_000;
}

interface ResumeBudgetDialogProps {
  open: boolean;
  run: CoverageRun;
  busy: boolean;
  onOpenChange: (open: boolean) => void;
  onResume: (limits: CoverageLimits) => void;
}

/**
 * Продолжение обзора после исчерпанного предела. Без нового потолка worker
 * останавливается на первом же вызове, и кнопка «Продолжить» выглядит сломанной.
 */
export function ResumeBudgetDialog({ open, run, busy, onOpenChange, onResume }: ResumeBudgetDialogProps) {
  const [tokens, setTokens] = useState(() => String(suggestTokens(run)));
  const [calls, setCalls] = useState(() => String(Math.max(run.limits.max_calls, run.costs.calls) * 2));
  const [cost, setCost] = useState(() => (run.limits.max_cost_usd ?? "").toString());
  const tokenValue = Number(tokens.replace(/\s/g, ""));
  const callValue = Number(calls.replace(/\s/g, ""));
  const costValue = Number(cost.replace(",", "."));
  const tokensValid = Number.isFinite(tokenValue) && tokenValue > run.costs.tokens;
  const callsValid = Number.isFinite(callValue) && callValue > run.costs.calls;
  const costValid = cost.trim() === "" || (Number.isFinite(costValue) && costValue > 0);
  const stopped = LIMIT_TITLE[run.stop_reason ?? ""] ?? "исследования";

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Предел исследования исчерпан"
      description={`Обзор остановился на пределе ${stopped}. Продолжить можно только с новым потолком — иначе следующий же вызов снова упрётся в него.`}
      footer={<>
        <Button variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>Отменить</Button>
        <Button
          disabled={busy || !tokensValid || !callsValid || !costValid}
          onClick={() => onResume({
            max_total_tokens: tokenValue,
            max_calls: callValue,
            max_cost_usd: cost.trim() === "" ? null : costValue,
          })}
        >
          {busy ? "Продолжаем…" : "Продолжить обзор"}
        </Button>
      </>}
    >
      <dl className="coverage-budget-facts">
        <div><dt>Вызовов</dt><dd>{run.costs.calls} из {run.limits.max_calls}</dd></div>
        <div><dt>Токенов</dt><dd>{NUMBER.format(run.costs.tokens)} из {NUMBER.format(run.limits.max_total_tokens)}</dd></div>
        <div><dt>Расход</dt><dd>${run.costs.cost_usd.toFixed(2)}{run.limits.max_cost_usd === null ? " (без потолка)" : ` из $${run.limits.max_cost_usd.toFixed(2)}`}</dd></div>
      </dl>
      <Field
        label="Новый предел токенов"
        hint="Считаются вход и ответ вместе с повторами шлюза."
        error={tokensValid ? undefined : `Нужно больше уже потраченных ${NUMBER.format(run.costs.tokens)}`}
      >
        <input className="input" inputMode="numeric" value={tokens} onChange={(event) => setTokens(event.target.value)} />
      </Field>
      <Field
        label="Новый предел вызовов"
        hint="Повтор по схеме и повтор транспорта — тоже вызовы."
        error={callsValid ? undefined : `Нужно больше уже сделанных ${run.costs.calls}`}
      >
        <input className="input" inputMode="numeric" value={calls} onChange={(event) => setCalls(event.target.value)} />
      </Field>
      <Field
        label="Предел расхода, $"
        hint="Пустое поле — без денежного потолка."
        error={costValid ? undefined : "Введите положительное число или очистите поле"}
      >
        <input className="input" inputMode="decimal" value={cost} onChange={(event) => setCost(event.target.value)} />
      </Field>
    </Dialog>
  );
}
