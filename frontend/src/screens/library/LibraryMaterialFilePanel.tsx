import { Download, ExternalLink, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import {
  librarySourceUrl,
  type LibraryMaterialDetailRead,
  type MaterialPurpose,
  type MaterialRevisionRead,
} from "../../api/materials";
import { Button, ConfirmDialog, Disclosure, StatusBadge } from "../../components/ui";

const PURPOSE: Record<MaterialPurpose, string> = {
  exam_structure: "список вопросов",
  reference_answers: "эталонные ответы",
  study_source: "учебный источник",
};

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} КБ`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} МБ`;
  return `${(bytes / 1024 ** 3).toFixed(1)} ГБ`;
}

interface LibraryMaterialFilePanelProps {
  material: LibraryMaterialDetailRead;
  revisions: MaterialRevisionRead[];
  selectedRevision: number | null;
  compareRevision: number | null;
  busy: boolean;
  onSelectRevision: (revision: number | null) => void;
  onCompareRevision: (revision: number | null) => void;
  onAddToProject: () => void;
  onRefreshSource: () => void;
  onDelete: () => void;
}

export function LibraryMaterialFilePanel({
  material,
  revisions,
  selectedRevision,
  compareRevision,
  busy,
  onSelectRevision,
  onCompareRevision,
  onAddToProject,
  onRefreshSource,
  onDelete,
}: LibraryMaterialFilePanelProps) {
  const [refreshOpen, setRefreshOpen] = useState(false);
  const isYoutube = material.presentation_kind === "youtube";

  return (
    <div className="inspector-content">
      <section className="inspector-section">
        <h4>Файл</h4>
        <dl className="inspector-facts">
          <div><dt>Имя</dt><dd title={material.original_name}>{material.original_name}</dd></div>
          <div><dt>Размер</dt><dd>{sizeLabel(material.size_bytes)}</dd></div>
          {material.page_count !== null && (
            <div><dt>Страниц</dt><dd>{material.page_count}</dd></div>
          )}
          {material.source_url && (
            <div>
              <dt>Источник</dt>
              <dd>
                <a href={material.source_url} target="_blank" rel="noreferrer" title={material.source_url}>
                  {material.source_url}
                  <ExternalLink size={12} aria-hidden="true" />
                </a>
              </dd>
            </div>
          )}
          {material.retrieved_at && (
            <div>
              <dt>Получен</dt>
              <dd>{new Date(material.retrieved_at).toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short" })}</dd>
            </div>
          )}
          <div><dt>Добавлен</dt><dd>{new Date(material.created_at).toLocaleDateString("ru-RU")}</dd></div>
          <div><dt>Хранение</dt><dd>Локально, в папке установки</dd></div>
        </dl>

        <div className="inspector-actions">
          {/* Ссылка, а не кнопка: скачивание — это переход по адресу файла,
              и браузер должен видеть его как ссылку. */}
          <a
            className="secondary-button"
            href={librarySourceUrl(material.id)}
            download={material.original_name}
          >
            <Download size={14} aria-hidden="true" /> Скачать исходник
          </a>
          {material.capabilities.can_refresh_source && (
            <Button variant="ghost" disabled={busy} onClick={() => setRefreshOpen(true)}>
              <RefreshCw size={14} aria-hidden="true" />
              {isYoutube ? "Обновить субтитры" : "Обновить снимок"}
            </Button>
          )}
        </div>
      </section>

      <section className="inspector-section">
        <h4>Версии разбора</h4>
        <p className="inspector-note">
          Каждый запуск «Быстро» или «Учебник» сохраняется отдельно. Откройте
          одну версию либо сравните две версии текста на текущей странице.
        </p>
        {revisions.length === 0 ? (
          <p className="inspector-note">Версии появятся после первой обработки.</p>
        ) : (
          <div className="revision-list" role="list">
            {revisions.map((revision) => {
              const openRevision = selectedRevision ?? material.active_parse_revision;
              const isOpen = revision.revision === openRevision;
              const isCompared = revision.revision === compareRevision;
              const mode = revision.parser_mode === "textbook"
                ? "Учебник"
                : revision.parser_mode === "fast"
                  ? "Быстро · гибридный OCR"
                  : "Ручная или восстановленная версия";
              return (
                <div
                  key={revision.revision}
                  className={`revision-row ${isOpen ? "is-open" : ""} ${isCompared ? "is-compared" : ""}`.trim()}
                  role="listitem"
                >
                  <span className="revision-head">
                    <b>Версия {revision.revision}</b>
                    {revision.is_current
                      ? <StatusBadge tone="success">Текущая</StatusBadge>
                      : isCompared
                        ? <StatusBadge tone="info">Сравнение</StatusBadge>
                        : isOpen && <StatusBadge tone="neutral">Открыта</StatusBadge>}
                  </span>
                  <span className="revision-origin">{mode}</span>
                  <span className="revision-meta">
                    {new Date(revision.created_at).toLocaleString("ru-RU", {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                  </span>
                  <div className="revision-inline-actions">
                    <Button
                      variant="ghost"
                      disabled={isOpen}
                      onClick={() => onSelectRevision(
                        revision.revision === material.active_parse_revision ? null : revision.revision,
                      )}
                    >
                      {isOpen ? "Открыта" : "Открыть"}
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={isOpen}
                      onClick={() => onCompareRevision(isCompared ? null : revision.revision)}
                    >
                      {isCompared ? "Закрыть сравнение" : "Сравнить"}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="inspector-section">
        <h4>Где используется</h4>
        {material.usage.length === 0 ? (
          <p className="inspector-note">
            Материал не подключён ни к одному проекту. Это нормально: файл может
            лежать в Библиотеке впрок.
          </p>
        ) : (
          <ul className="inspector-usage">
            {material.usage.map((usage) => (
              <li key={`${usage.project_id}-${usage.display_name}`}>
                <Link to={`/projects/${usage.project_id}/materials/${material.id}`}>
                  {usage.project_name}
                </Link>
                <small>
                  «{usage.display_name}» · {usage.purposes.map((item) => PURPOSE[item]).join(", ")}
                </small>
              </li>
            ))}
          </ul>
        )}
        <Button variant="secondary" disabled={busy} onClick={onAddToProject}>
          <Plus size={14} aria-hidden="true" /> Подключить к проекту
        </Button>
      </section>

      <Disclosure summary="Технические сведения">
        <dl className="inspector-facts is-technical">
          <div><dt>ID</dt><dd><code>{material.id}</code></dd></div>
          <div><dt>MIME</dt><dd><code>{material.media_type}</code></dd></div>
          <div><dt>SHA-256</dt><dd><code>{material.sha256.slice(0, 16)}…</code></dd></div>
          <div><dt>Активная версия</dt><dd>{material.active_parse_revision || "нет"}</dd></div>
          <div><dt>Блоков · фрагментов</dt><dd>{material.block_count} · {material.fragment_count}</dd></div>
        </dl>
      </Disclosure>

      <section className="inspector-section is-danger">
        <h4>Удаление</h4>
        <p className="inspector-note">
          Удаляется общий файл вместе со всеми версиями, страницами и фрагментами.
          Отключить материал от одного проекта можно внутри этого проекта.
        </p>
        <Button variant="ghost" className="is-danger" disabled={busy} onClick={onDelete}>
          <Trash2 size={14} aria-hidden="true" /> Удалить материал везде
        </Button>
      </section>

      <ConfirmDialog
        open={refreshOpen}
        onOpenChange={setRefreshOpen}
        title={isYoutube ? "Обновить субтитры?" : "Обновить снимок страницы?"}
        confirmLabel="Обновить"
        onConfirm={() => {
          setRefreshOpen(false);
          onRefreshSource();
        }}
      >
        <p className="dialog-lead">
          Tentex заново обратится к источнику и сохранит результат новой версией.
          Прежний снимок останется на месте и продолжит читаться без сети.
        </p>
        {material.usage.length > 0 && (
          <p>Новый текст увидят {material.usage.length} подключённых проекта.</p>
        )}
      </ConfirmDialog>
    </div>
  );
}
