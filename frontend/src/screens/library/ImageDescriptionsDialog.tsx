import { ImageIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  estimateImageDescriptions,
  getImageInventory,
  libraryFragmentAssetUrl,
  startImageDescriptions,
  type ImageCandidateRead,
  type ImageDescriptionEstimateRead,
  type ImageInventoryRead,
} from "../../api/materials";
import { getOcrCloudModels, type OcrCloudModelRead } from "../../api/ocr";
import {
  Button,
  Checkbox,
  Dialog,
  Disclosure,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  Select,
} from "../../components/ui";
import { IMAGE_PROCESSING_LABEL, IMAGE_ROLE_LABEL, imageReasonText, usdLabel } from "./imageLabels";

interface ImageDescriptionsDialogProps {
  open: boolean;
  material: { id: string; display_name: string };
  onOpenChange: (open: boolean) => void;
  /** Задача поставлена: родителю — перечитать карточку и список задач. */
  onStarted: () => void;
}

const modelKey = (model: { provider_id: string; model_id: string }) =>
  `${model.provider_id}::${model.model_id}`;

/**
 * «Описать изображения» готового материала: ничего не платится, пока человек
 * не увидел, что уйдёт, что сомнительно и сколько это стоит. Сомнительные
 * изображения отправляются только отмеченными вручную.
 */
export function ImageDescriptionsDialog({
  open,
  material,
  onOpenChange,
  onStarted,
}: ImageDescriptionsDialogProps) {
  const [inventory, setInventory] = useState<ImageInventoryRead | null>(null);
  const [models, setModels] = useState<OcrCloudModelRead[]>([]);
  const [model, setModel] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [estimate, setEstimate] = useState<ImageDescriptionEstimateRead | null>(null);
  const [confirmUnknown, setConfirmUnknown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(false);

  const chosenModel = useMemo(() => {
    const found = models.find((item) => modelKey(item) === model);
    return found ? { provider_id: found.provider_id, model_id: found.model_id } : null;
  }, [models, model]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setInventory(null);
    setEstimate(null);
    setError(null);
    setStarted(false);
    setConfirmUnknown(false);
    void Promise.all([
      getImageInventory(material.id, null, controller.signal),
      getOcrCloudModels(controller.signal).catch(() => [] as OcrCloudModelRead[]),
    ])
      .then(([value, candidates]) => {
        if (controller.signal.aborted) return;
        setInventory(value);
        setModels(candidates.filter((item) => item.suitable));
        setModel(value.provider_id && value.model_id
          ? modelKey({ provider_id: value.provider_id, model_id: value.model_id })
          : null);
        setSelected(new Set(value.targets.map((item) => item.id)));
      })
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "Не удалось собрать список изображений");
        }
      });
    return () => controller.abort();
  }, [open, material.id]);

  // Оценка — по явному списку и модели; повторы одного выреза не оплачиваются.
  useEffect(() => {
    if (!open || !inventory || selected.size === 0) {
      setEstimate(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void estimateImageDescriptions(
        material.id,
        { target_ids: [...selected], ...(chosenModel ?? {}) },
        controller.signal,
      )
        .then((value) => {
          if (!controller.signal.aborted) setEstimate(value);
        })
        .catch(() => undefined);
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [open, inventory, selected, chosenModel, material.id]);

  function toggle(candidate: ImageCandidateRead, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(candidate.id);
      else next.delete(candidate.id);
      return next;
    });
  }

  async function start() {
    if (!inventory || selected.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      await startImageDescriptions(material.id, {
        target_ids: [...selected],
        ...(chosenModel ?? {}),
        expected_revision: inventory.revision,
        max_cost_usd: estimate?.cost_upper_usd ?? null,
        confirm_unknown_price: confirmUnknown,
      });
      setStarted(true);
      onStarted();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось поставить описание");
    } finally {
      setBusy(false);
    }
  }

  const priceBlocked = estimate !== null && !estimate.price_known && !confirmUnknown;
  const activeJob = Boolean(inventory?.active_job_id);

  const row = (candidate: ImageCandidateRead, checkable: boolean) => (
    <article className="image-candidate" key={candidate.id}>
      {checkable ? (
        <Checkbox
          checked={selected.has(candidate.id)}
          onCheckedChange={(checked) => toggle(candidate, checked)}
          label={`Стр. ${candidate.page_number}${candidate.caption ? ` · ${candidate.caption}` : ""}`}
          disabled={busy || started || !candidate.selectable}
        />
      ) : (
        <p className="image-candidate-title">
          Стр. {candidate.page_number}{candidate.caption ? ` · ${candidate.caption}` : ""}
        </p>
      )}
      {candidate.fragment_id && candidate.has_asset ? (
        <img
          className="image-candidate-crop"
          src={libraryFragmentAssetUrl(material.id, candidate.fragment_id)}
          alt={`Изображение со страницы ${candidate.page_number}`}
          loading="lazy"
        />
      ) : (
        <div className="image-candidate-crop image-candidate-crop-missing" aria-hidden="true">
          <ImageIcon size={20} />
        </div>
      )}
      <p className="image-candidate-meta">
        {IMAGE_ROLE_LABEL[candidate.role]} · {IMAGE_PROCESSING_LABEL[candidate.processing]}
        {imageReasonText(candidate.reasons) ? ` · ${imageReasonText(candidate.reasons)}` : ""}
      </p>
    </article>
  );

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      className="image-descriptions-dialog"
      title="Описать изображения"
      description={`${material.display_name}. Модель опишет выбранные схемы и рисунки; описание попадёт в поиск и чат с пометкой «сделано моделью».`}
      footer={(
        <>
          <Button variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>
            {started ? "Готово" : "Закрыть"}
          </Button>
          {!started && (
            <Button
              disabled={busy || !inventory || selected.size === 0 || priceBlocked || activeJob}
              onClick={() => void start()}
            >
              {busy ? "Ставим…" : `Описать (${selected.size})`}
            </Button>
          )}
        </>
      )}
    >
      <div className="image-descriptions-flow">
        {error && <ErrorState title="Действие не выполнилось" message={error} />}
        {!inventory && !error && <LoadingState label="Собираем изображения текущей версии" />}
        {started && (
          <p className="inspector-note" role="status">
            Описание поставлено в очередь. Прогресс — в «Задачах»; когда оно закончится,
            появится новая версия материала.
          </p>
        )}
        {activeJob && !started && (
          <p className="inspector-warning" role="status">
            У материала уже идёт обработка — дождитесь её окончания.
          </p>
        )}
        {inventory && !started && (
          <>
            <Field label="Модель описаний" hint="Модель, которая принимает изображения">
              <Select
                ariaLabel="Модель описаний"
                value={model}
                disabled={busy}
                placeholder="Модель не выбрана"
                options={models.map((item) => ({
                  value: modelKey(item),
                  label: item.display_name || item.model_id,
                  description: `${item.provider_label}${
                    item.price_per_page_usd === null ? " · цена неизвестна" : ""
                  }`,
                }))}
                onValueChange={setModel}
              />
            </Field>

            {inventory.targets.length + inventory.doubtful.length === 0 && (
              <EmptyState title="Описывать нечего">
                <p>У всех изображений уже есть описание, либо они служебные или исправлены вручную.</p>
              </EmptyState>
            )}

            {inventory.targets.length > 0 && (
              <section className="image-candidate-group">
                <h3>Уйдут на описание</h3>
                {inventory.targets.map((item) => row(item, true))}
              </section>
            )}

            {inventory.doubtful.length > 0 && (
              <section className="image-candidate-group">
                <h3>Сомнительные — только если отметить</h3>
                {inventory.doubtful.map((item) => row(item, true))}
              </section>
            )}

            {inventory.excluded.length > 0 && (
              <Disclosure summary={`Не отправляются: ${inventory.excluded.length}`}>
                <div className="image-candidate-group">
                  {inventory.excluded.map((item) => row(item, false))}
                </div>
              </Disclosure>
            )}

            {estimate && (
              <p className="inspector-estimate">
                {estimate.requests} запр.
                {estimate.reused_by_hash > 0 ? ` (повторов без оплаты: ${estimate.reused_by_hash})` : ""}
                {estimate.price_known
                  ? ` · обычно ${usdLabel(estimate.cost_typical_usd)} · не дороже ${usdLabel(estimate.cost_upper_usd)}`
                  : " · цена модели неизвестна"}
              </p>
            )}
            {estimate && !estimate.price_known && (
              <Checkbox
                checked={confirmUnknown}
                onCheckedChange={setConfirmUnknown}
                label="Запустить без оценки цены"
                disabled={busy}
              />
            )}
            {inventory.vector_index_stale && (
              <p className="inspector-note">
                Смысловой индекс знает прежнюю версию материала — после описания добавьте
                материал в индекс заново.
              </p>
            )}
            <p className="header-footer-note">
              Будет создана одна новая версия; ручные правки страниц не трогаются, прежняя
              версия остаётся в истории.
            </p>
          </>
        )}
      </div>
    </Dialog>
  );
}
