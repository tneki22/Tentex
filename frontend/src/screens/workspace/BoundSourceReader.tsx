import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { SquareArrowOutUpRight, Unlink } from "lucide-react";
import type { BindingFragmentRead } from "../../api/bindings";
import type { MaterialPageRead } from "../../api/materials";
import { getMaterialPage, materialFragmentAssetUrl } from "../../api/materials";
import { ErrorState, LoadingState } from "../../components/ui";
import { StructuredPage } from "../../components/domain/material-viewer";

interface BoundSourceReaderProps {
  projectId: string;
  nodeId: string;
  /** Учебные привязки вопроса: `answers_file` сюда не попадает. */
  bindings: BindingFragmentRead[];
  busy: boolean;
  onUnbind: (bindingId: string) => void;
}

interface PageGroup {
  key: string;
  materialId: string;
  materialName: string;
  pageNumber: number;
  bindingByFragmentId: Map<string, string>;
}

interface MaterialGroup {
  materialId: string;
  materialName: string;
  pages: PageGroup[];
}

/**
 * Привязанное к вопросу — подряд и в том виде, в каком оно набрано в источнике.
 *
 * Ради этого привязки и существуют: открыть рядом с ответом и читать. Список
 * обрезанных строк по 160 символов этого не давал — формула превращалась в
 * мусор из символов, схема пропадала, заголовок ничем не отличался от абзаца.
 * Здесь тот же `StructuredPage`, что в просмотрщике: заголовки остаются
 * заголовками, список — списком, формула рисуется KaTeX или вырезкой
 * оригинала, схема — картинкой.
 */
export function BoundSourceReader({
  projectId,
  nodeId,
  bindings,
  busy,
  onUnbind,
}: BoundSourceReaderProps) {
  const groups = useMemo(() => groupBindings(bindings), [bindings]);
  const [pages, setPages] = useState<Record<string, MaterialPageRead>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Ключ запроса — список страниц, а не сами привязки: снятие одной привязки
  // не должно перезагружать уже прочитанные страницы.
  const pageKeys = groups
    .flatMap((group) => group.pages.map((page) => page.key))
    .join(",");

  useEffect(() => {
    const wanted = pageKeys ? pageKeys.split(",") : [];
    const missing = wanted.filter((key) => !(key in pages));
    if (missing.length === 0) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    Promise.all(
      missing.map((key) => {
        const [materialId, pageNumber] = key.split("#");
        return getMaterialPage(projectId, materialId, Number(pageNumber), controller.signal)
          .then((page) => [key, page] as const);
      }),
    )
      .then((loaded) => {
        if (controller.signal.aborted) return;
        setPages((current) => ({ ...current, ...Object.fromEntries(loaded) }));
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(caught instanceof Error ? caught.message : "Не удалось загрузить страницы");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // `pages` намеренно не в зависимостях: он же и обновляется этим эффектом.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, pageKeys]);

  if (error) return <ErrorState message={error} />;

  return (
    <div className="source-reader">
      {groups.map((group) => (
        <section className="source-reader-material" key={group.materialId}>
          <header className="source-reader-material-head">
            <h2>{group.materialName}</h2>
            <Link
              to={`/projects/${projectId}/materials/${group.materialId}`
                + `?page=${group.pages[0].pageNumber}&node=${nodeId}`}
            >
              <SquareArrowOutUpRight size={13} /> Открыть в материалах
            </Link>
          </header>
          {group.pages.map((page) => {
            const loaded = pages[page.key];
            if (!loaded) {
              return (
                <p className="source-reader-pending" key={page.key}>
                  Страница {page.pageNumber} загружается…
                </p>
              );
            }
            const fragments = loaded.fragments.filter(
              (fragment) => page.bindingByFragmentId.has(fragment.id),
            );
            if (fragments.length === 0) {
              return (
                <p className="source-reader-pending" key={page.key}>
                  Страница {page.pageNumber} изменилась после разбора — фрагменты не найдены.
                </p>
              );
            }
            return (
              <StructuredPage
                key={page.key}
                className="source-reader-page"
                page={{ ...loaded, fragments }}
                showOcrReview={false}
                assetUrl={(fragmentId) => materialFragmentAssetUrl(
                  projectId, page.materialId, fragmentId,
                )}
                renderFragmentOverlay={(fragment) => (
                  <button
                    type="button"
                    className="source-reader-unbind"
                    disabled={busy}
                    title="Это не по теме — снять привязку"
                    aria-label={`Снять привязку фрагмента: ${fragment.text.slice(0, 60)}`}
                    onClick={() => {
                      const bindingId = page.bindingByFragmentId.get(fragment.id);
                      if (bindingId) onUnbind(bindingId);
                    }}
                  >
                    <Unlink size={13} aria-hidden="true" />
                  </button>
                )}
              />
            );
          })}
        </section>
      ))}
      {loading && <LoadingState label="Загружаем страницы источника" />}
    </div>
  );
}

/**
 * Привязки — в дерево «файл → страница».
 *
 * Порядок файлов — по первому появлению в списке привязок, страницы внутри —
 * по возрастанию: так это и читается в самом источнике.
 */
function groupBindings(bindings: BindingFragmentRead[]): MaterialGroup[] {
  const materials = new Map<string, MaterialGroup>();
  const pagesByKey = new Map<string, PageGroup>();
  for (const binding of bindings) {
    let material = materials.get(binding.material_id);
    if (!material) {
      material = {
        materialId: binding.material_id,
        materialName: binding.material_name,
        pages: [],
      };
      materials.set(binding.material_id, material);
    }
    const key = `${binding.material_id}#${binding.page_number}`;
    let page = pagesByKey.get(key);
    if (!page) {
      page = {
        key,
        materialId: binding.material_id,
        materialName: binding.material_name,
        pageNumber: binding.page_number,
        bindingByFragmentId: new Map(),
      };
      pagesByKey.set(key, page);
      material.pages.push(page);
    }
    page.bindingByFragmentId.set(binding.fragment_id, binding.id);
  }
  for (const material of materials.values()) {
    material.pages.sort((left, right) => left.pageNumber - right.pageNumber);
  }
  return [...materials.values()];
}
