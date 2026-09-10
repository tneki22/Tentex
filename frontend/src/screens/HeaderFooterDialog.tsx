import { AlertTriangle, ScanLine } from "lucide-react";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  applyLibraryHeaderFooter,
  applyMaterialHeaderFooter,
  libraryPageImageUrl,
  materialPageImageUrl,
  previewLibraryHeaderFooter,
  previewMaterialHeaderFooter,
  type HeaderFooterApplyRead,
  type HeaderFooterCandidateRead,
  type HeaderFooterKind,
} from "../api/materials";
import { Button, Checkbox, Dialog, Disclosure, EmptyState, ErrorState, LoadingState } from "../components/ui";

const GROUPS: Array<{ kind: HeaderFooterKind; title: string }> = [
  { kind: "header", title: "Верх страницы" },
  { kind: "footer", title: "Низ страницы" },
  { kind: "page_number", title: "Номера страниц" },
];

interface HeaderFooterDialogProps {
  open: boolean;
  projectId: string | null;
  material: { id: string; display_name: string };
  onOpenChange: (open: boolean) => void;
  onReload: () => Promise<void>;
  onApplied: (result: HeaderFooterApplyRead) => void;
}

function pageList(pages: number[]): string {
  return pages.join(", ");
}

function cropStyle(url: string, bbox: number[]): CSSProperties {
  const [x0, y0, x1, y1] = bbox;
  const width = Math.min(1, Math.max(0.0001, x1 - x0));
  const height = Math.min(1, Math.max(0.0001, y1 - y0));
  return {
    backgroundImage: `url("${url}")`,
    backgroundSize: `${100 / width}% ${100 / height}%`,
    backgroundPosition: `${width >= 1 ? 0 : (x0 / (1 - width)) * 100}% ${
      height >= 1 ? 0 : (y0 / (1 - height)) * 100
    }%`,
  };
}

/** Общий предпросмотр колонтитулов для Библиотеки и материала проекта. */
export function HeaderFooterDialog({
  open,
  projectId,
  material,
  onOpenChange,
  onReload,
  onApplied,
}: HeaderFooterDialogProps) {
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof previewLibraryHeaderFooter>> | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setPreview(null);
    setSelected(new Set());
    setError(null);
    const request = projectId === null
      ? previewLibraryHeaderFooter(material.id, controller.signal)
      : previewMaterialHeaderFooter(projectId, material.id, controller.signal);
    void request
      .then((value) => {
        if (controller.signal.aborted) return;
        setPreview(value);
        setSelected(new Set(value.candidates.map((candidate) => candidate.id)));
      })
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "Не удалось найти колонтитулы");
        }
      });
    return () => controller.abort();
  }, [open, projectId, material.id]);

  const bindingCount = useMemo(
    () => preview?.candidates
      .filter((candidate) => selected.has(candidate.id))
      .reduce((sum, candidate) => sum + candidate.binding_count, 0) ?? 0,
    [preview, selected],
  );

  function toggle(candidate: HeaderFooterCandidateRead, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(candidate.id);
      else next.delete(candidate.id);
      return next;
    });
  }

  async function apply() {
    if (!preview || selected.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      const command = {
        expected_revision: preview.revision,
        candidate_ids: [...selected],
      };
      const result = projectId === null
        ? await applyLibraryHeaderFooter(material.id, command)
        : await applyMaterialHeaderFooter(projectId, material.id, command);
      await onReload();
      onApplied(result);
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось удалить колонтитулы");
    } finally {
      setBusy(false);
    }
  }

  const imageUrl = (candidate: HeaderFooterCandidateRead) => projectId === null
    ? libraryPageImageUrl(material.id, candidate.representative_page)
    : materialPageImageUrl(projectId, material.id, candidate.representative_page);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      className="header-footer-dialog"
      title="Найти колонтитулы"
      description={`${material.display_name}. Повторяющиеся элементы ищутся локально в текущей версии PDF.`}
      footer={(
        <>
          <Button variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>Закрыть</Button>
          <Button disabled={busy || !preview || selected.size === 0} onClick={() => void apply()}>
            {busy ? "Удаляем…" : "Удалить выбранное из текста"}
          </Button>
        </>
      )}
    >
      <div className="header-footer-flow">
        <p className="header-footer-unchanged"><ScanLine size={16} aria-hidden="true" />Материал пока не изменён</p>
        {error && <ErrorState title="Действие не выполнилось" message={error} />}
        {!preview && !error && <LoadingState label="Сравниваем поля страниц" />}
        {preview?.candidates.length === 0 && (
          <EmptyState title="Повторяющиеся колонтитулы не найдены">
            <p>Текст материала не изменён. При необходимости исправьте отдельную страницу вручную.</p>
          </EmptyState>
        )}
        {preview && GROUPS.map((group) => {
          const candidates = preview.candidates.filter((candidate) => candidate.kind === group.kind);
          if (candidates.length === 0) return null;
          return (
            <section className="header-footer-group" key={group.kind}>
              <h3>{group.title}</h3>
              {candidates.map((candidate) => {
                const representative = candidate.occurrences.find(
                  (item) => item.page === candidate.representative_page,
                );
                return (
                  <article className="header-footer-candidate" key={candidate.id}>
                    <Checkbox
                      checked={selected.has(candidate.id)}
                      onCheckedChange={(checked) => toggle(candidate, checked)}
                      label={candidate.text || "Повторяющееся изображение"}
                      disabled={busy}
                    />
                    <div
                      className="header-footer-crop"
                      style={cropStyle(imageUrl(candidate), representative?.bbox ?? candidate.bbox)}
                      role="img"
                      aria-label={`Вырезка страницы ${candidate.representative_page}`}
                    />
                    <p className="header-footer-meta">
                      {candidate.pages.length} стр. · {candidate.fragment_count} фрагм.
                      {candidate.element_type === "image" ? " · изображение" : ""}
                    </p>
                    <Disclosure summary={`Страницы: ${candidate.pages.length}`}>
                      <p>{pageList(candidate.pages)}</p>
                    </Disclosure>
                  </article>
                );
              })}
            </section>
          );
        })}
        {bindingCount > 0 && (
          <p className="header-footer-warning" role="status">
            <AlertTriangle size={16} aria-hidden="true" />
            Выбранные фрагменты затрагивают привязки: {bindingCount}. После удаления они будут перенесены или помечены как осиротевшие.
          </p>
        )}
        <p className="header-footer-note">
          Будет создана новая версия; исходный файл и история сохранятся. Повторное распознавание исходника может вернуть эти колонтитулы — правило не сохраняется.
        </p>
      </div>
    </Dialog>
  );
}
