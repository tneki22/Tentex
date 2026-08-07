import { useState } from "react";
import { FileText, Image, Trash2, Upload } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Button, Card, ConfirmDialog, Disclosure, IconButton, PageHead } from "../components/ui";
import { QualityBadge } from "../components/domain";
import type { PageQuality } from "../components/domain";

/**
 * Библиотека — файлы установки, общие для всех проектов (FR-P5): один и тот же
 * учебник в двух проектах хранится и разбирается один раз.
 *
 * Глубина «эскизом»: SCREENS.md, раздел «Библиотека». Данные выдуманные.
 */

interface DemoFile {
  id: string;
  icon: LucideIcon;
  name: string;
  size: string;
  pages: string;
  quality: Array<{ quality: PageQuality; count: number }>;
  /** Проекты, которые ссылаются на файл. Пусто — никем не используется. */
  usage: string[];
  added: string;
  hash: string;
  blocks: number;
  fragments: number;
  /** Что осиротеет при удалении (FR-M10). */
  consequences: string[];
}

const DEMO_FILES: DemoFile[] = [
  {
    id: "lections",
    icon: FileText,
    name: "lections.pdf",
    size: "18,4 МБ",
    pages: "320 стр",
    quality: [{ quality: "native", count: 320 }],
    usage: ["Базы данных — экзамен", "Матанализ — учебник"],
    added: "12.06.2026",
    hash: "a41f37…b3f8",
    blocks: 412,
    fragments: 3180,
    consequences: [
      "Базы данных — экзамен: 214 привязок, 38 карточек",
      "Матанализ — учебник: 96 привязок, 4 эталонных ответа",
    ],
  },
  {
    id: "scan",
    icon: Image,
    name: "konspekt-scan.pdf",
    size: "64,0 МБ",
    pages: "46 стр",
    quality: [
      { quality: "ocr", count: 38 },
      { quality: "ocr_low", count: 8 },
    ],
    usage: [],
    added: "28.07.2026",
    hash: "7c02de…1a95",
    blocks: 51,
    fragments: 402,
    consequences: ["Файл не используется ни одним проектом — терять нечего"],
  },
  {
    id: "voprosy",
    icon: FileText,
    name: "voprosy.docx",
    size: "220 КБ",
    pages: "4 стр",
    quality: [{ quality: "native", count: 4 }],
    usage: ["Базы данных — экзамен"],
    added: "12.06.2026",
    hash: "e8b110…44c1",
    blocks: 40,
    fragments: 80,
    consequences: ["Базы данных — экзамен: 40 тем программы потеряют источник"],
  },
];

export function Library() {
  const [toDelete, setToDelete] = useState<DemoFile | null>(null);

  return (
    <div className="screen">
      <PageHead
        title="Библиотека"
        lead="14 файлов · 3 120 страниц · 1,8 ГБ. Файл хранится один раз, проекты на него ссылаются."
        actions={
          <Button variant="secondary" disabled title="Появится вместе с API">
            <Upload size={15} aria-hidden="true" /> Загрузить файл
          </Button>
        }
      />

      <div className="lib-list">
        {DEMO_FILES.map((file) => (
          <Card className="lib-row" key={file.id}>
            <div className="lib-row-main">
              <file.icon size={16} aria-hidden="true" className="lib-row-icon" />
              <span className="lib-row-name">{file.name}</span>
              <span className="lib-row-meta">{file.size}</span>
              <span className="lib-row-meta">{file.pages}</span>
              <span className="lib-row-quality">
                {file.quality.map((item) => (
                  <QualityBadge key={item.quality} quality={item.quality} count={item.count} />
                ))}
              </span>
              <span className="lib-row-usage">
                {file.usage.length > 0 ? (
                  file.usage.join(" · ")
                ) : (
                  <span className="lib-unused">не используется</span>
                )}
              </span>
              <IconButton label={`Удалить ${file.name}`} onClick={() => setToDelete(file)}>
                <Trash2 size={15} />
              </IconButton>
            </div>

            <Disclosure summary="Подробности файла">
              <div className="lib-row-detail">
                <span className="lib-row-meta">Добавлен {file.added}</span>
                <span className="lib-row-meta">Хеш {file.hash}</span>
                <span className="lib-row-meta">
                  Блоков {file.blocks} · фрагментов {file.fragments}
                </span>
              </div>
            </Disclosure>
          </Card>
        ))}
      </div>

      <p className="lib-note">
        «Не используется» — нейтральный факт, а не упрёк: файл мог быть загружен
        впрок или остаться от архивного проекта.
      </p>

      <ConfirmDialog
        open={toDelete !== null}
        onOpenChange={(open) => !open && setToDelete(null)}
        title={`Удалить ${toDelete?.name ?? "файл"}?`}
        confirmLabel="Удалить файл"
        destructive
        onConfirm={() => undefined}
      >
        <p className="dialog-lead">
          Файл общий для установки. Вместе с ним потеряется то, что на него ссылается:
        </p>
        <ul className="consequences">
          {toDelete?.consequences.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </ConfirmDialog>
    </div>
  );
}
