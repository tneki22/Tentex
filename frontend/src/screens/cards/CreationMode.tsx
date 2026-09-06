import { useEffect, useState } from "react";
import { FileText, PencilLine, Sparkles } from "lucide-react";
import {
  getFragmentCardPrefill,
  type CardRead,
  type FragmentPrefillRead,
} from "../../api/cards";
import { Button, ErrorState, LoadingState, PageHead } from "../../components/ui";
import { CardEditor } from "./CardEditor";

export type CreationPath = "manual" | "ai" | "fragment";

interface CreationModeProps {
  projectId: string;
  units: CardRead["unit"][];
  initialPath?: CreationPath | null;
  initialUnitId?: string | null;
  fragmentId?: string | null;
  onOpenBank: (cardId?: string) => void;
  onChanged: () => void;
}

export function CreationMode({
  projectId,
  units,
  initialPath = null,
  initialUnitId = null,
  fragmentId = null,
  onOpenBank,
  onChanged,
}: CreationModeProps) {
  const [path, setPath] = useState<CreationPath | null>(
    fragmentId ? "fragment" : initialPath,
  );
  const [prefill, setPrefill] = useState<FragmentPrefillRead | null>(null);
  const [loading, setLoading] = useState(Boolean(fragmentId));
  const [error, setError] = useState("");

  useEffect(() => {
    if (!fragmentId) return;
    const controller = new AbortController();
    setLoading(true);
    void getFragmentCardPrefill(projectId, fragmentId, controller.signal)
      .then(setPrefill)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Фрагмент недоступен");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [fragmentId, projectId]);

  if (loading) return <LoadingState label="Готовим карточку из фрагмента…" />;
  if (error) return <ErrorState title="Не удалось открыть фрагмент" message={error} />;

  return (
    <div className="creation-mode">
      <PageHead
        eyebrow="Ручное создание"
        title={path ? "Новая карточка" : "Создание карточек"}
        actions={path && <Button variant="ghost" onClick={() => setPath(null)}>К способам</Button>}
      />
      {!path ? (
        <div className="creation-paths">
          <button type="button" onClick={() => setPath("manual")}>
            <PencilLine size={22} />
            <strong>Вручную</strong>
            <span>Лицевая и обратная стороны, подсказка и проверяемый источник.</span>
          </button>
          <button type="button" onClick={() => setPath("fragment")}>
            <FileText size={22} />
            <strong>Из фрагмента</strong>
            <span>Откройте Материалы и нажмите «В карточку» у нужного Фрагмента.</span>
          </button>
          <button type="button" disabled aria-disabled="true">
            <Sparkles size={22} />
            <strong>С помощью ИИ</strong>
            <span>Функция будет спроектирована позже.</span>
          </button>
        </div>
      ) : path === "ai" ? (
        <section className="cards-ai-placeholder">
          <Sparkles size={24} />
          <h2>Создание с ИИ пока недоступно</h2>
          <p>Сначала проверим ручной редактор и карточки из Фрагмента, затем отдельно спроектируем генерацию.</p>
          <Button onClick={() => setPath("manual")}>Создать вручную</Button>
        </section>
      ) : path === "fragment" && !prefill ? (
        <section className="fragment-creator">
          <FileText size={24} />
          <h2>Создайте карточку прямо из Материалов</h2>
          <p>У Фрагмента выберите действие «В карточку»: текст станет обратной стороной, а ссылка на страницу сохранится источником.</p>
        </section>
      ) : (
        <CardEditor
          projectId={projectId}
          units={units}
          initialUnitId={prefill?.proposed_program_node_id ?? initialUnitId}
          initialBack={prefill?.back}
          initialSource={
            prefill
              ? {
                  kind: "fragment",
                  fragmentId: prefill.fragment_id,
                  label: prefill.source.label,
                }
              : { kind: "none" }
          }
          onSaved={(card, addAnother) => {
            onChanged();
            if (!addAnother) onOpenBank(card.id);
          }}
        />
      )}
    </div>
  );
}
