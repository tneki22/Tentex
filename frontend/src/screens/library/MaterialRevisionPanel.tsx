import { History, Undo2 } from "lucide-react";
import { useState } from "react";
import type {
  LibraryMaterialDetailRead,
  MaterialRevisionRead,
  RevisionOrigin,
} from "../../api/materials";
import { Button, ConfirmDialog, StatusBadge } from "../../components/ui";

const ORIGIN_LABEL: Record<RevisionOrigin, string> = {
  imported: "Первичная обработка",
  parse: "Повторное распознавание",
  manual_edit: "Исправление страницы",
  ai_cleanup: "Уборка текста",
  source_refresh: "Обновление снимка",
  restore: "Восстановление версии",
};

/** Происхождение читается фразой, а не значением поля: «Исправление страницы 12». */
function originText(revision: MaterialRevisionRead): string {
  const base = ORIGIN_LABEL[revision.origin];
  const scope = revision.scope as { kind?: string; page?: number; page_from?: number; page_to?: number; restored_from?: number };
  if (revision.origin === "manual_edit" && typeof scope.page === "number") {
    return `${base} ${scope.page}`;
  }
  if (revision.origin === "restore" && typeof scope.restored_from === "number") {
    return `${base} ${scope.restored_from}`;
  }
  if (revision.origin === "parse" && scope.kind === "range") {
    return `${base}: страницы ${scope.page_from}–${scope.page_to}`;
  }
  if (revision.origin === "parse" && scope.kind === "needs_review") {
    if (revision.parser_mode === "fast") return `${base}: часть документа`;
    return `${base}: страницы, которые нужно проверить`;
  }
  return base;
}

function summaryText(revision: MaterialRevisionRead): string {
  const summary = revision.summary as Record<string, number | undefined>;
  const parts: string[] = [];
  if (summary.page_count) parts.push(`${summary.page_count} стр.`);
  if (revision.parser_mode !== "fast" && summary.review_page_count) parts.push(`нужно проверить: ${summary.review_page_count}`);
  if (summary.changed_pages) parts.push(`изменено: ${summary.changed_pages}`);
  return parts.join(" · ");
}

interface MaterialRevisionPanelProps {
  material: LibraryMaterialDetailRead;
  revisions: MaterialRevisionRead[];
  selected: number | null;
  busy: boolean;
  onSelect: (revision: number | null) => void;
  onRestore: (revision: number) => void;
}

export function MaterialRevisionPanel({
  material,
  revisions,
  selected,
  busy,
  onSelect,
  onRestore,
}: MaterialRevisionPanelProps) {
  const [confirm, setConfirm] = useState<number | null>(null);
  const current = material.active_parse_revision;

  if (revisions.length === 0) {
    return (
      <div className="inspector-content">
        <p className="inspector-note">
          История появится после первой подготовки материала: каждая обработка,
          правка и восстановление становятся отдельной версией.
        </p>
      </div>
    );
  }

  return (
    <div className="inspector-content">
      <p className="inspector-note">
        Версии не перезаписывают друг друга. Прежнюю можно открыть для чтения и
        восстановить как новую — номера при этом только растут.
      </p>

      <div className="revision-list" role="list">
        {revisions.map((revision) => {
          const isOpen = (selected ?? current) === revision.revision;
          return (
            <button
              type="button"
              role="listitem"
              key={revision.revision}
              className={`revision-row ${isOpen ? "is-open" : ""}`.trim()}
              aria-current={isOpen ? "true" : undefined}
              onClick={() => onSelect(revision.revision === current ? null : revision.revision)}
            >
              <span className="revision-head">
                <b>Версия {revision.revision}</b>
                {revision.revision === current
                  ? <StatusBadge tone="success">Текущая</StatusBadge>
                  : isOpen && <StatusBadge tone="info">Открыта</StatusBadge>}
              </span>
              <span className="revision-origin">{originText(revision)}</span>
              <span className="revision-meta">
                {new Date(revision.created_at).toLocaleString("ru-RU", {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
                {summaryText(revision) ? ` · ${summaryText(revision)}` : ""}
              </span>
            </button>
          );
        })}
      </div>

      {selected !== null && selected !== current && (
        <div className="inspector-actions">
          <Button variant="secondary" disabled={busy} onClick={() => setConfirm(selected)}>
            <Undo2 size={14} aria-hidden="true" /> Восстановить как новую
          </Button>
          <Button variant="ghost" onClick={() => onSelect(null)}>
            <History size={14} aria-hidden="true" /> Вернуться к текущей
          </Button>
        </div>
      )}

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={`Восстановить версию ${confirm ?? ""} как новую?`}
        confirmLabel="Восстановить"
        onConfirm={() => {
          if (confirm !== null) onRestore(confirm);
          setConfirm(null);
        }}
      >
        <p className="dialog-lead">
          История сохранится: версия {confirm} станет основой для версии {current + 1},
          а не заменит текущую.
        </p>
        {material.usage.length > 0 && (
          <ul className="consequences">
            {material.usage.map((usage) => (
              <li key={`${usage.project_id}-${usage.display_name}`}>
                {usage.project_name}: материал «{usage.display_name}» получит восстановленный текст.
              </li>
            ))}
          </ul>
        )}
      </ConfirmDialog>
    </div>
  );
}
