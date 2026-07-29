import { Bookmark, Highlighter, Star } from "lucide-react";
import { useState } from "react";
import { AutoResizeTextarea } from "../components/AutoResizeTextarea";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PanelResizeHandle } from "../components/PanelResizeHandle";
import { ProgressiveMarkdown } from "../components/ProgressiveMarkdown";
import {
  AnimatedDisclosure,
  Button,
  Drawer,
  EmptyState,
  ErrorState,
  IconButton,
  LoadingState,
  Popover,
  SegmentedTabs,
  StatusBadge,
  Toast,
} from "../components/ui";
import { MIN_LEFT, usePanelLayout } from "../hooks/usePanelLayout";
import { screenById } from "../app/screens";

const SAMPLE_MARKDOWN = [
  "**Нормальная форма** — свойство отношения, а не таблицы.",
  "",
  "1. 1НФ: все значения атомарны",
  "2. 2НФ: нет частичных зависимостей",
  "3. 3НФ: нет транзитивных зависимостей",
  "",
  "> Проверка идёт по функциональным зависимостям, а не по внешнему виду данных.",
].join("\n");

type DemoTab = "gaps" | "unsorted";

/**
 * Витрина UI-кита, перенесённого из virtex. Нужна на этапе 1: когда экран
 * проектируется, здесь видно, из чего его можно собрать, не читая исходники.
 */
export function UiKit() {
  const screen = screenById("ui-kit");
  const [tab, setTab] = useState<DemoTab>("gaps");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [toastVisible, setToastVisible] = useState(false);
  const [note, setNote] = useState("Текстовое поле растёт под текст.\nПопробуй добавить строк.");
  const [replayKey, setReplayKey] = useState(0);
  const panels = usePanelLayout();

  return (
    <div className="kit-page">
      <p className="eyebrow">{screen.group}</p>
      <h1>{screen.title}</h1>
      <p className="lead">{screen.summary}</p>

      <section className="kit-section">
        <h2>Кнопки</h2>
        <div className="kit-row">
          <Button>Пересобрать программу</Button>
          <Button variant="secondary">Импорт билетов</Button>
          <Button variant="ghost">Показать диф</Button>
          <Button disabled>Недоступно</Button>
          <IconButton label="В закладки">
            <Bookmark size={16} />
          </IconButton>
          <IconButton label="Подсветить фрагмент" aria-pressed="true">
            <Highlighter size={16} />
          </IconButton>
        </div>
      </section>

      <section className="kit-section">
        <h2>Статусы</h2>
        <div className="kit-row">
          <StatusBadge>нет материала</StatusBadge>
          <StatusBadge tone="info">привязано</StatusBadge>
          <StatusBadge tone="success">подтверждено</StatusBadge>
          <StatusBadge tone="warning">просрочено</StatusBadge>
          <StatusBadge tone="danger">пробел</StatusBadge>
        </div>
      </section>

      <section className="kit-section">
        <h2>Вкладки</h2>
        <SegmentedTabs
          label="Покрытие"
          value={tab}
          onChange={setTab}
          tabs={[
            { value: "gaps", label: "Пробелы" },
            { value: "unsorted", label: "Неразобранное" },
          ]}
        />
        <p className="lead" style={{ marginTop: 14 }}>
          Выбрано: {tab === "gaps" ? "Пробелы" : "Неразобранное"}. Стрелки, Home и End работают
          с клавиатуры.
        </p>
      </section>

      <section className="kit-section">
        <h2>Состояния экрана</h2>
        <LoadingState label="Разбираем материал" />
        <ErrorState message="Файл повреждён на странице 14." />
        <EmptyState title="Материалов пока нет" icon={<Star size={20} />}>
          <p className="lead">Это нормальное состояние проекта, а не ошибка.</p>
        </EmptyState>
      </section>

      <section className="kit-section">
        <h2>Раскрывашка и всплывашка</h2>
        <AnimatedDisclosure title="Чего не хватает до следующего статуса" defaultOpen>
          <p className="lead">Нужен эталонный ответ и одна успешная попытка.</p>
        </AnimatedDisclosure>
        <Popover label="Подсказка по статусу" className="kit-row" >
          <p className="lead" style={{ padding: 14, margin: 0 }}>
            Всплывающая поверхность: рамка, фон и тень из токенов.
          </p>
        </Popover>
      </section>

      <section className="kit-section">
        <h2>Постепенный показ Markdown</h2>
        <ProgressiveMarkdown key={replayKey} text={SAMPLE_MARKDOWN} />
        <div className="kit-row" style={{ marginTop: 14 }}>
          <Button variant="secondary" onClick={() => setReplayKey((value) => value + 1)}>
            Проиграть заново
          </Button>
        </div>
      </section>

      <section className="kit-section">
        <h2>Поле ввода</h2>
        <AutoResizeTextarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          style={{ width: "100%" }}
        />
      </section>

      <section className="kit-section">
        <h2>Панели с перетаскиваемой границей</h2>
        <div
          className="kit-panel-demo"
          style={{ "--left": `${panels.layout.left}px` } as React.CSSProperties}
        >
          <div>Левая панель · {Math.round(panels.layout.left)}px</div>
          <PanelResizeHandle
            label="Ширина левой панели"
            value={panels.layout.left}
            min={MIN_LEFT}
            max={panels.limits.leftMax}
            onChange={(value) => panels.setSide("left", value)}
            onPointerStart={(event) => panels.startResize("left", event)}
            onReset={panels.reset}
          />
          <div>Центр. Тяни границу мышью или стрелками, двойной клик — сброс.</div>
        </div>
      </section>

      <section className="kit-section">
        <h2>Наложения</h2>
        <div className="kit-row">
          <Button variant="secondary" onClick={() => setDrawerOpen((value) => !value)}>
            {drawerOpen ? "Закрыть панель" : "Открыть панель"}
          </Button>
          <Button variant="secondary" onClick={() => setDialogOpen(true)}>
            Диалог подтверждения
          </Button>
          <Button variant="secondary" onClick={() => setToastVisible((value) => !value)}>
            {toastVisible ? "Убрать уведомление" : "Показать уведомление"}
          </Button>
        </div>
      </section>

      <Drawer label="Боковая панель" open={drawerOpen}>
        <h2>Фрагменты темы</h2>
        <p className="lead">Выдвижная панель для деталей, которые не помещаются на экране.</p>
        <Button variant="secondary" onClick={() => setDrawerOpen(false)}>
          Закрыть
        </Button>
      </Drawer>

      {dialogOpen && (
        <ConfirmDialog
          eyebrow="Программа"
          title="Пересобрать программу?"
          description="Существующие узлы не удаляются: пересборка показывает диф и добавляет новое."
          cancelLabel="Отмена"
          confirmLabel="Пересобрать"
          onCancel={() => setDialogOpen(false)}
          onConfirm={() => setDialogOpen(false)}
        />
      )}

      {toastVisible && <Toast message="Привязка сохранена" />}
    </div>
  );
}
