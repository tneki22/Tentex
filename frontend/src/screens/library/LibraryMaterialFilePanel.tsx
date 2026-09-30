import { Download, ExternalLink, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import {
  libraryRenderedUrl,
  librarySourceUrl,
  type LibraryMaterialDetailRead,
  type MaterialPurpose,
} from "../../api/materials";
import { Button, ConfirmDialog, Disclosure, Field } from "../../components/ui";

const PURPOSE: Record<MaterialPurpose, string> = {
  exam_structure: "список вопросов",
  reference_answers: "ответы",
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
  busy: boolean;
  onAddToProject: () => void;
  onRefreshSource: () => void;
  onDelete: () => void;
  subjects: string[];
  onSaveMetadata: (command: { display_name?: string; subject?: string | null }) => Promise<boolean>;
}

/**
 * Вкладка «Файл»: сам файл, его подключения к проектам и удаление. Версий
 * разбора здесь нет намеренно — они целиком живут в соседней вкладке
 * «Версии», вместе со сравнением и восстановлением.
 */
export function LibraryMaterialFilePanel({
  material,
  busy,
  onAddToProject,
  onRefreshSource,
  onDelete,
  subjects,
  onSaveMetadata,
}: LibraryMaterialFilePanelProps) {
  const [refreshOpen, setRefreshOpen] = useState(false);
  const [displayName, setDisplayName] = useState(material.display_name);
  const [subject, setSubject] = useState(material.subject ?? "");
  const [saveError, setSaveError] = useState("");
  const pendingSubject = useRef<string | null>(null);
  useEffect(() => {
    setDisplayName(material.display_name);
    setSubject(material.subject ?? "");
  }, [material.display_name, material.subject]);
  const isYoutube = material.presentation_kind === "youtube";
  const nameDirty = displayName.trim() !== material.display_name;

  async function saveSubject(value: string) {
    const normalized = value.trim();
    if (normalized === (material.subject ?? "") || pendingSubject.current === normalized) return;
    pendingSubject.current = normalized;
    setSaveError("");
    const saved = await onSaveMetadata({ subject: normalized || null });
    pendingSubject.current = null;
    if (!saved) {
      setSubject(material.subject ?? "");
      setSaveError("Предмет не сохранён. Попробуйте ещё раз.");
    }
  }

  async function saveName() {
    if (!displayName.trim()) return;
    setSaveError("");
    const saved = await onSaveMetadata({ display_name: displayName.trim() });
    if (!saved) {
      setDisplayName(material.display_name);
      setSaveError("Название не сохранено. Попробуйте ещё раз.");
    }
  }

  return (
    <div className="inspector-content">
      <section className="inspector-section">
        <h4>Файл</h4>
        <div className="inspector-metadata-form">
          <Field label="Название в Библиотеке" required>
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
          </Field>
          <Field label="Предмет" hint="Широкая дисциплина, например «Физика»">
            <input
              list={`library-subjects-${material.id}`}
              value={subject}
              onChange={(event) => {
                const next = event.target.value;
                setSubject(next);
                if (subjects.includes(next)) void saveSubject(next);
              }}
              onBlur={() => void saveSubject(subject)}
              onKeyDown={(event) => {
                if (event.key === "Enter") { event.preventDefault(); void saveSubject(subject); }
              }}
            />
            <datalist id={`library-subjects-${material.id}`}>
              {subjects.map((item) => <option key={item} value={item} />)}
            </datalist>
          </Field>
          <Button
            variant="secondary"
            disabled={busy || !displayName.trim() || !nameDirty}
            onClick={() => void saveName()}
          >
            <Save size={14} aria-hidden="true" /> Сохранить название
          </Button>
          {saveError && <p className="inline-error" role="alert">{saveError}</p>}
        </div>
        <dl className="inspector-facts">
          <div><dt>Исходное имя</dt><dd title={material.original_name}>{material.original_name}</dd></div>
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
          <div><dt>Хранение</dt><dd><code>{material.storage_path}</code></dd></div>
        </dl>

        <div className="inspector-actions">
          {/* Ссылка, а не кнопка: скачивание — это переход по адресу файла,
              и браузер должен видеть его как ссылку. */}
          <a
            className="secondary-button"
            href={librarySourceUrl(material.id)}
            download={material.original_name}
          >
            <Download size={14} aria-hidden="true" />
            {material.presentation_kind === "typst" ? "Скачать проект" : "Скачать исходник"}
          </a>
          {/* У Typst исходник и читаемый документ — разные файлы: ZIP проекта
              и PDF сборки. Оба нужны, поэтому обе ссылки стоят рядом. */}
          {material.typst?.has_rendered_pdf && (
            <a
              className="secondary-button"
              href={libraryRenderedUrl(material.id)}
              download={`${material.original_name.replace(/\.typ$/i, "")}.pdf`}
            >
              <Download size={14} aria-hidden="true" /> Скачать PDF
            </a>
          )}
          {material.capabilities.can_refresh_source && (
            <Button variant="ghost" disabled={busy} onClick={() => setRefreshOpen(true)}>
              <RefreshCw size={14} aria-hidden="true" />
              {isYoutube ? "Обновить субтитры" : "Обновить снимок"}
            </Button>
          )}
        </div>
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
