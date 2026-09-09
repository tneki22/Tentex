/** Проверка доступности модели и стоимости до запуска распределения. */
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Button, Dialog, ErrorState, LoadingState } from "../../components/ui";
import { preparation, revisions, errorText, type Overview, type Schema } from "../../api/preparation";

/** Предложение ИИ всегда возвращается в календарь черновиком. */
export function AiDistributionDialog({ overview, onClose, onStarted }: { overview: Overview; onClose: () => void; onStarted: (jobId: string) => void }) {
  const [preview, setPreview] = useState<Schema["PreparationAiPreflightRead"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const command = { action: "distribute" as const, instruction: "", confirmed: false, automatic: false, ...revisions(overview) };
  useEffect(() => {
    let active = true;
    preparation.preflight(overview.project_id, command).then(value => { if (active) setPreview(value); }).catch(caught => { if (active) setError(errorText(caught)); });
    return () => { active = false; };
  }, [overview.project_id, overview.plan.revision, overview.settings.revision]);
  const start = async () => {
    setBusy(true); setError(null);
    try {
      const result = await preparation.ai(overview.project_id, { ...command, confirmed: true });
      if (result.job_id) onStarted(result.job_id);
      else setError(result.reason ?? "Модель сейчас недоступна.");
    } catch (caught) { setError(errorText(caught)); } finally { setBusy(false); }
  };
  const knownCost = preview?.calls.every(call => call.estimated_cost_usd != null);
  const cost = preview?.calls.reduce((sum, call) => sum + Number(call.estimated_cost_usd ?? 0), 0) ?? 0;
  return <Dialog open title="Распределить вопросы с ИИ" onOpenChange={open => { if (!open && !busy) onClose(); }} description="ИИ предложит даты для вопросов без назначения. Готовый черновик появится в календаре."
    footer={<><Button variant="ghost" disabled={busy} onClick={onClose}>Закрыть</Button><Button disabled={busy || !preview || preview.calls.length === 0} onClick={() => void start()}>{busy ? "Запускаем…" : "Получить предложение"}</Button></>}>
    {error && <ErrorState title="Распределение пока недоступно" message={error} />}
    {!preview && !error && <LoadingState label="Проверяем модель и стоимость" />}
    {preview && <div className="prep-form">
      <p>Вызовов модели: {preview.calls.length}. {knownCost ? `Оценка стоимости: $${cost.toFixed(4)}.` : "Стоимость провайдером не указана."}</p>
      {preview.calls.length === 0 && <p>Все вопросы уже назначены. Изменить даты можно вручную в календаре.</p>}
      <p className="prep-note">Существующие назначения сохраняются. День экзамена, отдых и занятые даты исключены.</p>
      <details><summary>Что будет передано модели · {preview.context.length} узлов программы</summary><ul>{preview.context.map(node => <li key={node.id}>{node.title}</li>)}</ul></details>
    </div>}
    {error && <Link to="/settings?section=ai">Открыть настройки моделей</Link>}
  </Dialog>;
}
