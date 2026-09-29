import type { ReactNode } from "react";

/**
 * Схемы руководства — встроенный SVG, а не картинки: они перекрашиваются вместе
 * с темой и не теряют резкость. В странице подключаются строкой
 * `:::diagram имя`. Цвета — классы `.gd-*` в guide.css, значения из токенов.
 */

function Overview() {
  return (
    <svg viewBox="0 0 720 250" role="img" aria-label="Материалы дают Программу, Программа ведёт к занятиям, Покрытие измеряет связь в обе стороны">
      <defs>
        <marker id="gd-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>

      <g className="gd-node gd-info">
        <rect x="16" y="24" width="184" height="88" rx="16" />
        <text x="108" y="62" className="gd-title">Материалы</text>
        <text x="108" y="84" className="gd-sub">книги, конспекты, ссылки</text>
      </g>
      <g className="gd-node gd-accent">
        <rect x="268" y="24" width="184" height="88" rx="16" />
        <text x="360" y="62" className="gd-title">Программа</text>
        <text x="360" y="84" className="gd-sub">вопросы или темы</text>
      </g>
      <g className="gd-node gd-success">
        <rect x="520" y="24" width="184" height="88" rx="16" />
        <text x="612" y="62" className="gd-title">Занятия</text>
        <text x="612" y="84" className="gd-sub">уроки, карточки, план</text>
      </g>

      <path d="M204 68 H262" className="gd-arrow" markerEnd="url(#gd-arrow)" />
      <path d="M456 68 H514" className="gd-arrow" markerEnd="url(#gd-arrow)" />

      <path d="M108 116 V168 M612 116 V168" className="gd-arrow gd-dashed" />
      <path d="M360 116 V168" className="gd-arrow gd-dashed" />

      <g className="gd-node gd-warning">
        <rect x="16" y="168" width="688" height="60" rx="16" />
        <text x="360" y="194" className="gd-title">Покрытие</text>
        <text x="360" y="214" className="gd-sub">чем подтверждён каждый вопрос — и что в материалах осталось без темы</text>
      </g>
    </svg>
  );
}

/** Что живёт на уровне установки, а что внутри проекта. */
function Structure() {
  return (
    <svg viewBox="0 0 720 340" role="img" aria-label="В установке Tentex есть общая Библиотека и Параметры, а программа, привязки, занятия и прогресс принадлежат каждому проекту отдельно">
      <defs>
        <marker id="gd-arrow-s" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>

      <rect x="6" y="6" width="708" height="328" rx="22" className="gd-frame" />
      <text x="28" y="34" className="gd-label">Установка Tentex</text>

      <g className="gd-node gd-info">
        <rect x="28" y="60" width="210" height="122" rx="16" />
        <text x="133" y="92" className="gd-title">Библиотека</text>
        <text x="133" y="118" className="gd-sub">файлы материалов и их текст</text>
        <text x="133" y="138" className="gd-sub">общая для всех проектов</text>
        <text x="133" y="162" className="gd-sub">один файл — один разбор</text>
      </g>
      <g className="gd-node gd-warning">
        <rect x="28" y="198" width="210" height="122" rx="16" />
        <text x="133" y="230" className="gd-title">Параметры</text>
        <text x="133" y="256" className="gd-sub">провайдеры и ключи</text>
        <text x="133" y="276" className="gd-sub">модели, поиск, распознавание</text>
        <text x="133" y="296" className="gd-sub">копии и хранилище</text>
      </g>

      <g className="gd-node gd-accent">
        <rect x="300" y="60" width="190" height="260" rx="16" />
        <text x="395" y="92" className="gd-title">Проект A</text>
        <text x="395" y="122" className="gd-sub">роли материалов</text>
        <text x="395" y="150" className="gd-sub">программа</text>
        <text x="395" y="178" className="gd-sub">привязки и покрытие</text>
        <text x="395" y="206" className="gd-sub">уроки, конспекты, карточки</text>
        <text x="395" y="234" className="gd-sub">ответы и прогресс</text>
        <text x="395" y="262" className="gd-sub">план и чат</text>
        <text x="395" y="296" className="gd-sub">паспорт цели, настройки</text>
      </g>
      <g className="gd-node gd-success">
        <rect x="520" y="60" width="180" height="260" rx="16" />
        <text x="610" y="92" className="gd-title">Проект B</text>
        <text x="610" y="122" className="gd-sub">своя программа</text>
        <text x="610" y="150" className="gd-sub">свои привязки</text>
        <text x="610" y="178" className="gd-sub">свои занятия</text>
        <text x="610" y="206" className="gd-sub">свой прогресс</text>
        <text x="610" y="248" className="gd-sub">не пересекается</text>
        <text x="610" y="268" className="gd-sub">с проектом A</text>
      </g>

      <path d="M242 121 H294" className="gd-arrow gd-dashed" markerEnd="url(#gd-arrow-s)" />
      <path d="M242 96 H262 V44 H610 V54" className="gd-arrow gd-dashed" markerEnd="url(#gd-arrow-s)" />
      <text x="436" y="38" className="gd-label gd-label-mid">материал подключается к проекту, а не копируется</text>
    </svg>
  );
}

/** Три способа унести данные: пакет проекта, резервная копия и их отличие. */
function Transfer() {
  return (
    <svg viewBox="0 0 720 290" role="img" aria-label="Проект экспортируется в пакет и импортируется как новый проект; резервная копия переносит всю установку и заменяет её при восстановлении">
      <defs>
        <marker id="gd-arrow-t" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>

      <text x="16" y="22" className="gd-label">Один проект</text>
      <g className="gd-node gd-accent">
        <rect x="16" y="34" width="166" height="82" rx="16" />
        <text x="99" y="70" className="gd-title">Проект</text>
        <text x="99" y="92" className="gd-sub">на этой установке</text>
      </g>
      <g className="gd-node gd-info">
        <rect x="277" y="34" width="166" height="82" rx="16" />
        <text x="360" y="70" className="gd-title">.tentex-project</text>
        <text x="360" y="92" className="gd-sub">файл-пакет</text>
      </g>
      <g className="gd-node gd-success">
        <rect x="538" y="34" width="166" height="82" rx="16" />
        <text x="621" y="70" className="gd-title">Новый проект</text>
        <text x="621" y="92" className="gd-sub">рядом с имеющимися</text>
      </g>
      <path d="M186 75 H273" className="gd-arrow" markerEnd="url(#gd-arrow-t)" />
      <path d="M447 75 H534" className="gd-arrow" markerEnd="url(#gd-arrow-t)" />
      <text x="230" y="64" className="gd-label gd-label-mid">экспорт</text>
      <text x="491" y="64" className="gd-label gd-label-mid">импорт</text>

      <text x="16" y="158" className="gd-label">Вся установка</text>
      <g className="gd-node gd-warning">
        <rect x="16" y="170" width="166" height="82" rx="16" />
        <text x="99" y="206" className="gd-title">Установка</text>
        <text x="99" y="228" className="gd-sub">все проекты и Библиотека</text>
      </g>
      <g className="gd-node gd-info">
        <rect x="277" y="170" width="166" height="82" rx="16" />
        <text x="360" y="206" className="gd-title">.tentex-backup</text>
        <text x="360" y="228" className="gd-sub">резервная копия</text>
      </g>
      <g className="gd-node gd-danger">
        <rect x="538" y="170" width="166" height="82" rx="16" />
        <text x="621" y="206" className="gd-title">Установка</text>
        <text x="621" y="228" className="gd-sub">заменяется целиком</text>
      </g>
      <path d="M186 211 H273" className="gd-arrow" markerEnd="url(#gd-arrow-t)" />
      <path d="M447 211 H534" className="gd-arrow" markerEnd="url(#gd-arrow-t)" />
      <text x="230" y="200" className="gd-label gd-label-mid">копия</text>
      <text x="491" y="200" className="gd-label gd-label-mid">замена</text>
    </svg>
  );
}

interface WizardStep { label: string; hot?: boolean }

/** Ряд шагов мастера: боксы одной ширины на всю строку, «горячий» шаг — где рождается программа. */
function wizardRow(steps: WizardStep[], y: number, labelY: number, title: string, arrowId: string) {
  const gap = steps.length === 5 ? 20 : 16;
  const width = (700 - gap * (steps.length - 1)) / steps.length;
  return (
    <g key={title}>
      <text x="10" y={labelY} className="gd-label">{title}</text>
      {steps.map((step, index) => {
        const x = 10 + index * (width + gap);
        return (
          <g key={step.label}>
            <g className={`gd-node ${step.hot ? "gd-accent" : "gd-info"}`}>
              <rect x={x} y={y} width={width} height="52" rx="14" />
              <text x={x + width / 2} y={y + 31} className="gd-step">{index + 1} · {step.label}</text>
            </g>
            {index < steps.length - 1 && (
              <path d={`M${x + width + 2} ${y + 26} H${x + width + gap - 3}`} className="gd-arrow" markerEnd={`url(#${arrowId})`} />
            )}
          </g>
        );
      })}
    </g>
  );
}

/** Шаги трёх мастеров создания проекта. */
function Wizard() {
  return (
    <svg viewBox="0 0 720 300" role="img" aria-label="Шаги мастера: экзамен — пять шагов, учебник — пять шагов, свободное изучение — четыре шага">
      <defs>
        <marker id="gd-arrow-w" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>
      {wizardRow(
        [{ label: "Формат" }, { label: "Материалы" }, { label: "Загрузка", hot: true }, { label: "Паспорт" }, { label: "Проверка" }],
        30, 20, "Подготовка к экзамену", "gd-arrow-w",
      )}
      {wizardRow(
        [{ label: "Источники" }, { label: "Профиль" }, { label: "Проверка" }, { label: "Программа", hot: true }, { label: "Итог" }],
        130, 120, "Изучение по учебнику", "gd-arrow-w",
      )}
      {wizardRow(
        [{ label: "Цель" }, { label: "Материалы" }, { label: "Программа", hot: true }, { label: "Проверка" }],
        230, 220, "Свободное изучение", "gd-arrow-w",
      )}
    </svg>
  );
}

/** Программа — точка, от которой зависят остальные разделы проекта. */
function ProgramHub() {
  return (
    <svg viewBox="0 0 720 300" role="img" aria-label="Паспорт цели, оглавления материалов и ваши правки формируют программу, а от программы зависят уроки, привязки с покрытием, план, карточки и чат">
      <defs>
        <marker id="gd-arrow-h" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>

      <g className="gd-node gd-info">
        <rect x="8" y="18" width="184" height="66" rx="14" />
        <text x="100" y="47" className="gd-title gd-title-sm">Паспорт цели</text>
        <text x="100" y="67" className="gd-sub">зачем, уровень, срок</text>
      </g>
      <g className="gd-node gd-info">
        <rect x="8" y="118" width="184" height="66" rx="14" />
        <text x="100" y="147" className="gd-title gd-title-sm">Оглавления</text>
        <text x="100" y="167" className="gd-sub">карта ваших материалов</text>
      </g>
      <g className="gd-node gd-info">
        <rect x="8" y="218" width="184" height="66" rx="14" />
        <text x="100" y="247" className="gd-title gd-title-sm">Ваши решения</text>
        <text x="100" y="267" className="gd-sub">что принять, что убрать</text>
      </g>

      <g className="gd-node gd-accent">
        <rect x="268" y="102" width="184" height="98" rx="18" />
        <text x="360" y="143" className="gd-title">Программа</text>
        <text x="360" y="167" className="gd-sub">разделы, темы, подпункты</text>
      </g>

      <g className="gd-node gd-success">
        <rect x="528" y="18" width="184" height="66" rx="14" />
        <text x="620" y="47" className="gd-title gd-title-sm">Уроки</text>
        <text x="620" y="67" className="gd-sub">строятся по темам</text>
      </g>
      <g className="gd-node gd-warning">
        <rect x="528" y="118" width="184" height="66" rx="14" />
        <text x="620" y="147" className="gd-title gd-title-sm">Привязки и покрытие</text>
        <text x="620" y="167" className="gd-sub">считаются по темам</text>
      </g>
      <g className="gd-node gd-success">
        <rect x="528" y="218" width="184" height="66" rx="14" />
        <text x="620" y="247" className="gd-title gd-title-sm">План, карточки, чат</text>
        <text x="620" y="267" className="gd-sub">работают с темами</text>
      </g>

      <path d="M196 51 C232 51 232 138 262 138" className="gd-arrow" markerEnd="url(#gd-arrow-h)" />
      <path d="M196 151 H262" className="gd-arrow" markerEnd="url(#gd-arrow-h)" />
      <path d="M196 251 C232 251 232 164 262 164" className="gd-arrow" markerEnd="url(#gd-arrow-h)" />

      <path d="M458 138 C492 138 492 51 522 51" className="gd-arrow" markerEnd="url(#gd-arrow-h)" />
      <path d="M458 151 H522" className="gd-arrow" markerEnd="url(#gd-arrow-h)" />
      <path d="M458 164 C492 164 492 251 522 251" className="gd-arrow" markerEnd="url(#gd-arrow-h)" />
    </svg>
  );
}

const DIAGRAMS: Record<string, () => ReactNode> = {
  overview: Overview,
  structure: Structure,
  transfer: Transfer,
  wizard: Wizard,
  "program-hub": ProgramHub,
};

export function GuideDiagram({ name }: { name: string }) {
  const Diagram = DIAGRAMS[name];
  if (!Diagram) return <p className="guide-missing">Схема «{name}» ещё не нарисована.</p>;
  return <Diagram />;
}
