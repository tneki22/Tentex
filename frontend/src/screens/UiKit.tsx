import { useState } from "react";
import type { CSSProperties } from "react";
import { Bookmark, Highlighter, Inbox, MoreHorizontal, Star, Trash2 } from "lucide-react";
import {
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  ContextMenu,
  Dialog,
  Disclosure,
  EmptyState,
  ErrorState,
  Field,
  IconButton,
  Kbd,
  LoadingState,
  Menu,
  PageHead,
  Popover,
  Progress,
  RadioCards,
  SegmentedTabs,
  StatusBadge,
  Switch,
  Tooltip,
} from "../components/ui";
import {
  CostEstimate,
  GOAL_LEVELS,
  GoalLevelPicker,
  MachineMark,
  MetricList,
  OfflineNotice,
  PAGE_QUALITIES,
  ProjectChip,
  ProviderModelPicker,
  QualityBadge,
  REFERENCE_ANSWER_STATUSES,
  ReferenceAnswerBadge,
  SourceChip,
  StepChip,
  TaskRow,
  TOPIC_STATUSES,
  TopicStatusBadge,
  goalLevelEffect,
} from "../components/domain";
import type { GoalLevelValue, ProjectColor } from "../components/domain";
import type { AiModelRead, AiModelSelection, AiProviderRead } from "../api/ai";

/** Поверхности и текст показываются парами «за что отвечает — как называется». */
const SURFACE_TOKENS = [
  ["--canvas", "фон приложения"],
  ["--paper", "карточка, панель"],
  ["--surface-hover", "заливка под курсором"],
  ["--surface-sunken", "вдавленное: поле, код"],
] as const;

const INK_TOKENS = [
  ["--ink", "основной текст"],
  ["--ink-soft", "вторичный"],
  ["--muted", "подписи"],
  ["--faint", "четвертичный"],
] as const;

const ACCENT_TOKENS = [
  ["--accent", "акцент"],
  ["--tone-success", "подтверждено"],
  ["--tone-warning", "верь осторожно"],
  ["--tone-danger", "необратимое"],
  ["--tone-info", "привязано"],
] as const;

const PICKER_PROVIDERS: AiProviderRead[] = [{
  id: "demo-provider",
  label: "OpenRouter",
  catalog_profile: "openrouter",
  base_url: "https://openrouter.ai/api/v1",
  has_api_key: true,
  is_favorite: true,
  model_count: 1,
  last_test_status: "connected",
  last_tested_at: null,
  last_catalog_refresh_at: null,
  updated_at: "2026-08-14T00:00:00Z",
}];

const PICKER_MODELS: AiModelRead[] = [{
  provider_id: "demo-provider",
  model_id: "openai/gpt-demo",
  display_name: "GPT Demo",
  context_length: 128_000,
  max_completion_tokens: 16_000,
  supported_parameters: ["response_format"],
  input_modalities: ["text"],
  output_modalities: ["text"],
  reasoning: { supported_efforts: ["low", "high"] },
  default_parameters: {},
  manual_overrides: {},
  prompt_price_usd: 0.000001,
  completion_price_usd: 0.000004,
  knowledge_cutoff: null,
  expiration_date: null,
  pricing_snapshot_at: "2026-08-14T00:00:00Z",
  catalog_snapshot_at: "2026-08-14T00:00:00Z",
  is_manually_added: false,
  favorite_order: 0,
  is_available: true,
}];

const TYPE_SCALE = [
  ["--text-3xl", "36 · заголовок экрана"],
  ["--text-xl", "23 · заголовок раздела"],
  ["--text-lg", "19 · подзаголовок"],
  ["--text-md", "16 · подводка"],
  ["--text-base", "15 · основной текст"],
  ["--text-sm", "13 · подпись"],
  ["--text-xs", "12 · метка, служебное"],
] as const;

const SPACE_SCALE = ["1", "2", "3", "4", "5", "6", "8", "10", "12", "16"] as const;
const PROJECT_COLORS: ProjectColor[] = [1, 2, 3, 4, 5, 6, 7, 8];

type DemoTab = "gaps" | "unsorted";
type DemoWay = "outline" | "pass1" | "catalog";

function Swatch({ token, note }: { token: string; note: string }) {
  return (
    <div className="kit-swatch">
      <i style={{ "--swatch": `var(${token})` } as CSSProperties} />
      <b>{note}</b>
      <span>{token}</span>
    </div>
  );
}

/**
 * Витрина дизайн-системы. Нужна на этапе 1: проектируя экран, здесь видно, из
 * чего его собрать и по каким правилам, не читая исходники.
 *
 * Два слоя показываются раздельно: примитивы кита ничего не знают о предметной
 * области, доменные виджеты знают про темы, качество страниц и стоимость вызовов.
 */
export function UiKit() {
  const [tab, setTab] = useState<DemoTab>("gaps");
  const [level, setLevel] = useState<GoalLevelValue>("application");
  const [way, setWay] = useState<DemoWay>("outline");
  const [reminders, setReminders] = useState(true);
  const [excluded, setExcluded] = useState(false);
  const [dialog, setDialog] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [minutes, setMinutes] = useState("40");
  const [suggested, setSuggested] = useState(true);
  const [modelSelection, setModelSelection] = useState<AiModelSelection | null>({
    provider_id: "demo-provider",
    model_id: "openai/gpt-demo",
  });

  return (
    <div className="kit-page">
      <PageHead
        placement="topbar"
        eyebrow="Служебное"
        title="Дизайн-система"
        lead="Два слоя: примитивы кита и доменные виджеты Tentex. Поведение всплывашек, диалогов, тумблеров и радиогрупп — Radix Primitives; вид — наши токены. Полное описание системы — DESIGN.md."
      />

      <section className="kit-section">
        <h2>Цвет</h2>
        <p className="kit-hint">
          Все цвета живут в <code>tokens.css</code> и заданы через <code>light-dark()</code> —
          вторая тема получается сама. Акцент кобальтовый: он не спорит с зелёным
          «подтверждено» и красным «необратимое».
        </p>
        <div className="kit-stack">
          <div className="kit-swatches">
            {SURFACE_TOKENS.map(([token, note]) => (
              <Swatch key={token} token={token} note={note} />
            ))}
          </div>
          <div className="kit-swatches">
            {INK_TOKENS.map(([token, note]) => (
              <Swatch key={token} token={token} note={note} />
            ))}
          </div>
          <div className="kit-swatches">
            {ACCENT_TOKENS.map(([token, note]) => (
              <Swatch key={token} token={token} note={note} />
            ))}
          </div>
        </div>
        <p className="kit-hint" style={{ marginTop: "var(--space-4)" }}>
          Отдельная группа — цвета проектов. Они разнесены с акцентом и тонами
          статусов: иначе фиолетовый проект читался бы как статус.
        </p>
        <div className="kit-row">
          {PROJECT_COLORS.map((color) => (
            <ProjectChip key={color} icon="book-open" color={color} />
          ))}
        </div>
      </section>

      <section className="kit-section">
        <h2>Кегль</h2>
        <p className="kit-hint">
          Onest — гротеск, нарисованный сразу с кириллицей. Основной текст 15px:
          на плотной таблице покрытия мельче читать нечем.
        </p>
        <div>
          {TYPE_SCALE.map(([token, note]) => (
            <div className="kit-type-row" key={token}>
              <code>{token}</code>
              <span style={{ fontSize: `var(${token})` }}>{note}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="kit-section">
        <h2>Ритм</h2>
        <p className="kit-hint">Шаг сетки 4px. Отступы берутся из шкалы, а не на глаз.</p>
        <div className="kit-scale">
          {SPACE_SCALE.map((step) => (
            <div key={step}>
              <i style={{ "--step": `var(--space-${step})` } as CSSProperties} />
              <span>{step}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="kit-section">
        <h2>Кнопки и подсказки</h2>
        <p className="kit-hint">
          Три уровня действия. Наведи курсор: главная приподнимается и даёт тень
          акцента, вторая — тень поверхности, третья проявляет заливку.
        </p>
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
          <Tooltip label="Подсказка появляется через 400 мс" side="top">
            <Button variant="secondary">Наведи и подожди</Button>
          </Tooltip>
          <Menu
            label="Действия над проектом"
            trigger={
              <IconButton label="Ещё">
                <MoreHorizontal size={16} />
              </IconButton>
            }
            items={[
              { label: "Архивировать", onSelect: () => undefined },
              { label: "Экспорт проекта", onSelect: () => undefined },
              {
                label: "Удалить проект",
                icon: <Trash2 size={14} />,
                onSelect: () => setConfirm(true),
                destructive: true,
              },
            ]}
          />
          <ContextMenu
            label="Действия с узлом программы"
            trigger={<Button variant="secondary">Правой кнопкой</Button>}
            items={[
              { label: "Переименовать", onSelect: () => undefined },
              { label: "Добавить внутрь", items: [{ label: "Тему", onSelect: () => undefined }, { label: "Подпункт", onSelect: () => undefined }] },
              { label: "Убрать из программы", icon: <Trash2 size={14} />, onSelect: () => undefined, destructive: true },
            ]}
          />
        </div>
      </section>

      <section className="kit-section">
        <h2>Всплывашки и диалоги</h2>
        <p className="kit-hint">
          Позиционирование, фокус-ловушка, Esc и клик мимо — Radix. Всплывашка
          немодальная: под ней можно продолжать работать. Диалог модальный и
          называет действие словом, а не «OK».
        </p>
        <div className="kit-row">
          <Popover
            side="top"
            title="Фоновые задачи"
            trigger={<Button variant="secondary">Всплывашка</Button>}
          >
            <TaskRow
              task={{
                id: "demo",
                kind: "pass2",
                subject: "lections.pdf",
                unit: "блок",
                done: 640,
                total: 1500,
                etaMinutes: 12,
                state: "running",
              }}
              onPause={() => undefined}
            />
          </Popover>
          <Button variant="secondary" onClick={() => setDialog(true)}>
            Диалог
          </Button>
          <Button variant="secondary" onClick={() => setConfirm(true)}>
            Подтверждение удаления
          </Button>
          <span className="kit-hint" style={{ margin: 0 }}>
            Палитра поиска — <Kbd>Ctrl K</Kbd> из любого места
          </span>
        </div>

        <Dialog
          open={dialog}
          onOpenChange={setDialog}
          title="Пересобрать программу?"
          description="Пересборка ничего не удаляет: покажет диф и предложит добавить, объединить или переставить."
        >
          <ul className="consequences">
            <li>Новых тем: 4</li>
            <li>Похожих на существующие: 2</li>
            <li>Не найдено в новой версии: 1 — уйдёт в «вне текущей программы»</li>
          </ul>
        </Dialog>

        <ConfirmDialog
          open={confirm}
          onOpenChange={setConfirm}
          title="Удалить lections.pdf?"
          confirmLabel="Удалить файл"
          destructive
          onConfirm={() => undefined}
        >
          <p className="dialog-lead">Файл общий для установки. Потеряется то, что на него ссылается:</p>
          <ul className="consequences">
            <li>Базы данных — экзамен: 214 привязок, 38 карточек</li>
            <li>Матанализ — учебник: 96 привязок</li>
          </ul>
        </ConfirmDialog>
      </section>

      <section className="kit-section">
        <h2>Выбор</h2>
        <p className="kit-hint">
          Карточками выбирают шаблон проекта и способ получения программы. Стрелки
          переключают. Недоступный вариант не прячется, а пишет причину: скрытый
          вариант выглядит как отсутствие функции.
        </p>
        <RadioCards
          label="Способ получения программы"
          layout="rows"
          value={way}
          onChange={setWay}
          options={[
            {
              value: "outline",
              title: "По оглавлению",
              description: "Офлайн, за секунды, без единого токена",
            },
            {
              value: "pass1",
              title: "Из материала (проход 1)",
              description: "Модель перечисляет темы каждой главы",
              extra: (
                <CostEstimate calls={30} cost={0.42} minutes={4} pricesFrom="12.05.2026" />
              ),
            },
            {
              value: "catalog",
              title: "Из каталога",
              description: "Типовая программа предмета",
              unavailableReason: "требует внешней модели — сейчас выключена",
            },
          ]}
        />
      </section>

      <section className="kit-section">
        <h2>Переключатели и поля</h2>
        <p className="kit-hint">
          Тумблер включает режим и срабатывает сразу, без «Сохранить», — поэтому
          подпись называет состояние. Флажок — выбор в наборе. Поле умеет метку
          машинного значения: правка её снимает.
        </p>
        <div className="kit-panel kit-form">
          <Switch
            checked={reminders}
            onCheckedChange={setReminders}
            label="Напоминания в Telegram"
            hint="Утренняя сводка и вечерний добор"
          />
          <Checkbox
            checked={excluded}
            onCheckedChange={setExcluded}
            label="Исключить тему из программы"
          />
          <Field
            label="Минут в день"
            hint="От 5 до 240. Значение уезжает в планировщик"
            suggested={suggested}
            action={
              <Button variant="ghost" onClick={() => setSuggested(true)}>
                Предложить заполнение
              </Button>
            }
          >
            <input
              type="number"
              value={minutes}
              min={5}
              max={240}
              onChange={(event) => {
                setMinutes(event.target.value);
                setSuggested(false);
              }}
            />
          </Field>
          <Field label="Название проекта" required error="Назови проект">
            <input placeholder="Например: Базы данных — экзамен" />
          </Field>
        </div>
      </section>

      <section className="kit-section">
        <h2>Статусы и качество</h2>
        <p className="kit-hint">
          Пять статусов темы и три флага качества страницы. Тон закреплён за
          смыслом здесь и больше нигде не выбирается. «Нет материала» нейтрален:
          у проекта из входа C так выглядят все темы на старте.
        </p>
        <div className="kit-row">
          {TOPIC_STATUSES.map((status) => (
            <TopicStatusBadge key={status} status={status} />
          ))}
        </div>
        <div className="kit-row" style={{ marginTop: "var(--space-3)" }}>
          {REFERENCE_ANSWER_STATUSES.map((status) => (
            <ReferenceAnswerBadge key={status} status={status} />
          ))}
        </div>
        <div className="kit-row" style={{ marginTop: "var(--space-3)" }}>
          {PAGE_QUALITIES.map((quality) => (
            <QualityBadge key={quality} quality={quality} count={quality === "native" ? 320 : 8} />
          ))}
          <StatusBadge tone="info">привязано</StatusBadge>
          <StatusBadge tone="danger">разбор упал</StatusBadge>
        </div>
      </section>

      <section className="kit-section">
        <h2>Происхождение и обратимость</h2>
        <p className="kit-hint">
          Откуда взялся узел программы — и чем он сделан. Всё машинное помечено,
          несёт свой источник и отменяется одним нажатием: без этого пользователь
          обнаружит изменение, о происхождении которого не узнать.
        </p>
        <div className="kit-row">
          <SourceChip source={{ kind: "outline" }} />
          <SourceChip source={{ kind: "pass1", pages: "стр. 45–61" }} />
          <SourceChip source={{ kind: "catalog", layer: 1 }} />
          <SourceChip source={{ kind: "import" }} />
          <SourceChip source={{ kind: "manual" }} />
          <SourceChip source={{ kind: "none" }} />
        </div>
        <div className="kit-row" style={{ marginTop: "var(--space-3)" }}>
          <MachineMark origin="проход 2" onUndo={() => undefined} undoLabel="Снять привязку" />
          <MachineMark origin="предложено моделью" />
        </div>
      </section>

      <section className="kit-section">
        <h2>Следующий шаг</h2>
        <p className="kit-hint">
          Одна формулировка на все поверхности: полоса действий, карточка проекта,
          пустое состояние, кнопка в боте. «На сегодня всё» — не кнопка: система не
          выдумывает занятие, которого нет.
        </p>
        <div className="kit-row">
          <StepChip step={{ text: "На сегодня: 12 повторений · 3 новых", to: "/projects", tone: "accent" }} />
          <StepChip step={{ text: "Разбор lections.pdf упал", to: "/library", tone: "danger" }} />
          <StepChip step={{ text: "На сегодня всё · следующее повторение завтра", tone: "quiet" }} />
        </div>
        <div className="kit-row" style={{ marginTop: "var(--space-3)" }}>
          <StepChip
            size="large"
            step={{ text: "Заниматься — 25 минут", to: "/projects", tone: "accent" }}
          />
        </div>
      </section>

      <section className="kit-section">
        <h2>Метрики и стоимость</h2>
        <p className="kit-hint">
          Метрики набираются текстом: полоса к 100% читалась бы как «надо дойти до
          конца», а покрытие материала ниже 100% — результат работы, а не дефект.
          Выключенная модулем метрика не показывается и не подменяется нулём.
          Полоса остаётся у прогресса работы — у него конец действительно есть.
        </p>
        <div className="kit-panel kit-stack">
          <MetricList
            layout="grid"
            metrics={[
              { label: "программа покрыта", value: "72%" },
              { label: "пройдено", value: "18 из 25" },
              { label: "подтверждено", value: "9 из 25" },
              { label: "долг по плану", value: null },
            ]}
          />
          <Progress value={640} max={1500} label="Проход 2" />
          <CostEstimate
            calls={94}
            cost={2.1}
            minutes={18}
            pricesFrom="12.05.2026"
            units="1500 блоков ÷ 16"
          />
        </div>
      </section>

      <section className="kit-section">
        <h2>Уровень цели</h2>
        <p className="kit-hint">
          Ставится пачкой по разделу. Рядом всегда написано, что он меняет: иначе
          четыре слова выглядят одинаково важными.
        </p>
        <GoalLevelPicker value={level} onChange={setLevel} label="Раздел 4. Транзакции" />
        <p className="goal-effect">
          «{GOAL_LEVELS.find((item) => item.value === level)?.label}»: {goalLevelEffect(level)}
        </p>
      </section>

      <section className="kit-section">
        <h2>Выбор провайдера и модели</h2>
        <p className="kit-hint">
          Сначала сужает каталог по провайдеру, затем показывает только совместимые модели.
          Звезда означает быстрый ярлык, а не значение по умолчанию.
        </p>
        <div className="kit-panel">
          <ProviderModelPicker
            providers={PICKER_PROVIDERS}
            models={PICKER_MODELS}
            value={modelSelection}
            onChange={setModelSelection}
          />
        </div>
      </section>

      <section className="kit-section">
        <h2>Работа без внешних моделей</h2>
        <p className="kit-hint">
          Два состояния с разным тоном. Выключено пользователем — законный режим,
          нейтрально. Провайдер молчит — предупреждение, но всё ещё штатное
          состояние, а не авария на весь экран.
        </p>
        <div className="kit-stack">
          <OfflineNotice
            reason="disabled"
            alternative="Программа собирается по оглавлению и импортом."
          />
          <OfflineNotice reason="unreachable" alternative="Повторения и карточки работают как обычно." />
        </div>
      </section>

      <section className="kit-section">
        <h2>Вкладки и раскрытие</h2>
        <p className="kit-hint">
          Сегментированный переключатель: бегунок едет под выбранную вкладку,
          стрелки и Home/End работают. Раскрытие анимирует высоту содержимого.
        </p>
        <SegmentedTabs
          label="Покрытие"
          value={tab}
          onChange={setTab}
          className="kit-tabs-demo"
          tabs={[
            { value: "gaps", label: "Пробелы" },
            { value: "unsorted", label: "Неразобранное" },
          ]}
        />
        <div style={{ marginTop: "var(--space-4)" }}>
          <Disclosure summary={`Что показывает «${tab === "gaps" ? "Пробелы" : "Неразобранное"}»`}>
            <p className="kit-hint" style={{ margin: 0 }}>
              {tab === "gaps"
                ? "Темы, под которые в материалах ничего не нашлось: не хватает источников."
                : "Содержательные блоки вне программы: в материале есть то, чего ты не собирался учить."}
            </p>
          </Disclosure>
        </div>
      </section>

      <section className="kit-section">
        <h2>Состояния экрана</h2>
        <p className="kit-hint">Загрузка, ошибка и пустота — три обязательных состояния.</p>
        <div className="kit-stack">
          <LoadingState label="Загружаем рабочую область" placement="page" />
          <LoadingState label="Разбираем материал" />
          <ErrorState message="Файл повреждён на странице 14." />
          <EmptyState title="Материалов пока нет" icon={<Inbox size={24} />}>
            <p>Это нормальное состояние проекта, а не ошибка.</p>
          </EmptyState>
        </div>
      </section>

      <section className="kit-section">
        <h2>Карточки</h2>
        <p className="kit-hint">
          Базовая поверхность под списки. Кликабельная приподнимается на 2px —
          обычная стоит на месте.
        </p>
        <div className="kit-grid">
          <Card>
            <h3>Обычная</h3>
            <p className="kit-hint" style={{ margin: 0 }}>
              Ничего не происходит: карточка просто держит содержимое.
            </p>
          </Card>
          <Card onClick={() => undefined}>
            <h3>Кликабельная</h3>
            <p className="kit-hint" style={{ margin: 0 }}>
              Наведи курсор — карточка поднимется и получит тень.
            </p>
          </Card>
        </div>
      </section>

      <p className="kit-hint" style={{ marginTop: "var(--space-10)" }}>
        Иконка <Star size={13} style={{ verticalAlign: "-2px" }} /> и остальные — из
        lucide-react, размер 15–16 для интерфейса. Markdown, изменяемые панели и
        голосовой ввод приедут из <code>virtex/</code>, когда их потребует конкретный
        экран: среда темы, просмотрщик источника, устный ответ.
      </p>
    </div>
  );
}
