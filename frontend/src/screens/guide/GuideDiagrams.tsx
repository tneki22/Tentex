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

/** Три входа в одну общую Библиотеку и подключение к проекту. */
function AddPaths() {
  return (
    <svg viewBox="0 0 720 300" role="img" aria-label="Материал можно добавить в Библиотеку заранее, в мастере создания проекта или в разделе Материалы проекта; файл хранится в Библиотеке один раз и подключается к проекту с ролью">
      <defs>
        <marker id="gd-arrow-a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>

      <g className="gd-node gd-info">
        <rect x="8" y="20" width="212" height="70" rx="14" />
        <text x="114" y="50" className="gd-title gd-title-sm">Библиотека заранее</text>
        <text x="114" y="71" className="gd-sub">без проекта, когда удобно</text>
      </g>
      <g className="gd-node gd-info">
        <rect x="8" y="115" width="212" height="70" rx="14" />
        <text x="114" y="145" className="gd-title gd-title-sm">Мастер создания</text>
        <text x="114" y="166" className="gd-sub">на шаге с материалами</text>
      </g>
      <g className="gd-node gd-info">
        <rect x="8" y="210" width="212" height="70" rx="14" />
        <text x="114" y="240" className="gd-title gd-title-sm">Материалы проекта</text>
        <text x="114" y="261" className="gd-sub">кнопка «Добавить материал»</text>
      </g>

      <g className="gd-node gd-accent">
        <rect x="290" y="88" width="180" height="124" rx="18" />
        <text x="380" y="132" className="gd-title">Библиотека</text>
        <text x="380" y="158" className="gd-sub">файл хранится один раз</text>
        <text x="380" y="178" className="gd-sub">и разбирается один раз</text>
      </g>

      <g className="gd-node gd-success">
        <rect x="560" y="88" width="152" height="124" rx="18" />
        <text x="636" y="132" className="gd-title">Проект</text>
        <text x="636" y="158" className="gd-sub">роль и приоритет</text>
        <text x="636" y="178" className="gd-sub">программа, привязки</text>
      </g>

      <path d="M224 55 C262 55 262 132 284 132" className="gd-arrow" markerEnd="url(#gd-arrow-a)" />
      <path d="M224 150 H284" className="gd-arrow" markerEnd="url(#gd-arrow-a)" />
      <path d="M224 245 C262 245 262 168 284 168" className="gd-arrow" markerEnd="url(#gd-arrow-a)" />
      <path d="M474 150 H554" className="gd-arrow" markerEnd="url(#gd-arrow-a)" />
      <text x="514" y="138" className="gd-label gd-label-mid">подключение</text>
    </svg>
  );
}

/** Файл → страницы → элементы → блоки и фрагменты → то, что на них держится. */
function TextBlocks() {
  const nodes = [
    { title: "Файл", a: "PDF, DOCX, фото,", b: "текст, запись", tone: "gd-info" },
    { title: "Страницы", a: "лист PDF или", b: "весь файл целиком", tone: "gd-info" },
    { title: "Элементы", a: "заголовки, абзацы,", b: "таблицы, формулы", tone: "gd-accent" },
    { title: "Блоки", a: "раздел от заголовка", b: "до следующего", tone: "gd-accent" },
  ];
  const consumers = ["Поиск", "Привязки к темам", "Чат и цитаты", "Уроки"];
  return (
    <svg viewBox="0 0 720 260" role="img" aria-label="Файл делится на страницы, страницы на элементы, элементы складываются в блоки и фрагменты, на которых держатся поиск, привязки к темам, чат и уроки">
      <defs>
        <marker id="gd-arrow-b" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>

      {nodes.map((node, index) => {
        const x = 10 + index * 184;
        return (
          <g key={node.title}>
            <g className={`gd-node ${node.tone}`}>
              <rect x={x} y="14" width="148" height="80" rx="14" />
              <text x={x + 74} y="42" className="gd-title gd-title-sm">{node.title}</text>
              <text x={x + 74} y="64" className="gd-sub gd-sub-sm">{node.a}</text>
              <text x={x + 74} y="80" className="gd-sub gd-sub-sm">{node.b}</text>
            </g>
            {index < nodes.length - 1 && (
              <path d={`M${x + 152} 54 H${x + 180}`} className="gd-arrow" markerEnd="url(#gd-arrow-b)" />
            )}
          </g>
        );
      })}

      <text x="10" y="132" className="gd-label">На этих единицах держатся</text>
      <path d="M636 98 V150 M84 150 H636" className="gd-arrow gd-dashed" />
      {consumers.map((title, index) => {
        const x = 10 + index * 184;
        return (
          <g key={title}>
            <path d={`M${x + 74} 150 V172`} className="gd-arrow gd-dashed" markerEnd="url(#gd-arrow-b)" />
            <g className="gd-node gd-success">
              <rect x={x} y="176" width="148" height="56" rx="14" />
              <text x={x + 74} y="210" className="gd-step">{title}</text>
            </g>
          </g>
        );
      })}
    </svg>
  );
}

/** Рекомендуемый порядок: быстро и для всех, потом точно и только где нужно. */
function TwoPasses() {
  const steps = [
    { title: "Быстро", a: "все файлы за минуты", b: "на вашем компьютере", tone: "gd-info" },
    { title: "Оглавление", a: "список вопросов,", b: "карта учебника", tone: "gd-info" },
    { title: "Программа", a: "проект создан,", b: "материалы в нём", tone: "gd-accent" },
    { title: "Облако", a: "формулы, таблицы,", b: "схемы, рисунки", tone: "gd-warning" },
    { title: "Проверка", a: "сравнение", b: "с оригиналом", tone: "gd-success" },
  ];
  return (
    <svg viewBox="0 0 720 170" role="img" aria-label="Сначала быстрый разбор всех файлов даёт оглавление и основу для программы, потом облако точечно читает формулы, таблицы и рисунки, затем проверка сравнением с оригиналом">
      <defs>
        <marker id="gd-arrow-p" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>
      {steps.map((step, index) => {
        const x = 10 + index * 143;
        return (
          <g key={step.title}>
            <g className={`gd-node ${step.tone}`}>
              <rect x={x} y="12" width="128" height="86" rx="14" />
              <text x={x + 64} y="40" className="gd-title gd-title-sm">{step.title}</text>
              <text x={x + 64} y="64" className="gd-sub gd-sub-sm">{step.a}</text>
              <text x={x + 64} y="80" className="gd-sub gd-sub-sm">{step.b}</text>
            </g>
            {index < steps.length - 1 && (
              <path d={`M${x + 131} 55 H${x + 140}`} className="gd-arrow" markerEnd="url(#gd-arrow-p)" />
            )}
          </g>
        );
      })}
      <path d="M10 118 H401" className="gd-arrow" />
      <text x="205" y="144" className="gd-label gd-label-mid">Сначала база: быстро и для всех</text>
      <path d="M439 118 H710" className="gd-arrow" />
      <text x="574" y="144" className="gd-label gd-label-mid">Потом точность: там, где нужна</text>
    </svg>
  );
}

/** Один ход поиска в интернете. */
function SearchTurn() {
  const steps = [
    { title: "Просьба", a: "вы пишете, что", b: "нужно найти", tone: "gd-info" },
    { title: "План", a: "модель составляет", b: "до 6 запросов", tone: "gd-accent" },
    { title: "Поиск", a: "SearXNG ищет,", b: "открывает страницы", tone: "gd-info" },
    { title: "Отбор", a: "модель выбирает", b: "до 10 источников", tone: "gd-accent" },
    { title: "Карточки", a: "ссылка, суть,", b: "чем полезно", tone: "gd-success" },
  ];
  return (
    <svg viewBox="0 0 720 170" role="img" aria-label="Ход поиска: просьба, план запросов от модели, поиск и чтение страниц, отбор источников моделью, карточки с ссылками">
      <defs>
        <marker id="gd-arrow-q" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>
      {steps.map((step, index) => {
        const x = 10 + index * 143;
        return (
          <g key={step.title}>
            <g className={`gd-node ${step.tone}`}>
              <rect x={x} y="12" width="128" height="86" rx="14" />
              <text x={x + 64} y="40" className="gd-title gd-title-sm">{step.title}</text>
              <text x={x + 64} y="64" className="gd-sub gd-sub-sm">{step.a}</text>
              <text x={x + 64} y="80" className="gd-sub gd-sub-sm">{step.b}</text>
            </g>
            {index < steps.length - 1 && (
              <path d={`M${x + 131} 55 H${x + 140}`} className="gd-arrow" markerEnd="url(#gd-arrow-q)" />
            )}
          </g>
        );
      })}
      <path d="M217 102 V120 H503 V102" className="gd-arrow gd-dashed" />
      <text x="360" y="146" className="gd-label gd-label-mid">два вызова модели · обычно 20–60 секунд</text>
    </svg>
  );
}

/** Три полосы очереди разборов: сколько задач идёт одновременно. */
function Lanes() {
  const lanes = [
    { title: "Быстро", sub: "ваш процессор", tone: "gd-info", y: 16, slots: 1, queue: 3 },
    { title: "Облако", sub: "до 4 страниц в каждом", tone: "gd-warning", y: 96, slots: 2, queue: 2 },
  ];
  return (
    <svg viewBox="0 0 720 256" role="img" aria-label="Одновременно идёт один быстрый разбор, два облачных и до восьми задач ИИ; остальные ждут в очереди">
      {lanes.map((lane) => (
        <g key={lane.title}>
          <g className={`gd-node ${lane.tone}`}>
            <rect x="8" y={lane.y} width="200" height="64" rx="14" />
            <text x="108" y={lane.y + 28} className="gd-title gd-title-sm">{lane.title}</text>
            <text x="108" y={lane.y + 47} className="gd-sub gd-sub-sm">{lane.sub}</text>
          </g>
          {Array.from({ length: lane.slots }, (_, index) => (
            <g key={`s${index}`} className={`gd-node ${lane.tone}`}>
              <rect x={236 + index * 92} y={lane.y + 10} width="80" height="44" rx="10" />
              <text x={276 + index * 92} y={lane.y + 37} className="gd-step">идёт</text>
            </g>
          ))}
          {Array.from({ length: lane.queue }, (_, index) => (
            <g key={`q${index}`}>
              <rect x={236 + lane.slots * 92 + 18 + index * 84} y={lane.y + 10} width="72" height="44" rx="10" className="gd-queue" />
              <text x={272 + lane.slots * 92 + 18 + index * 84} y={lane.y + 37} className="gd-label gd-label-mid">ждёт</text>
            </g>
          ))}
        </g>
      ))}
      <g className="gd-node gd-accent">
        <rect x="8" y="176" width="200" height="64" rx="14" />
        <text x="108" y="204" className="gd-title gd-title-sm">Задачи ИИ</text>
        <text x="108" y="223" className="gd-sub gd-sub-sm">ждут ответа модели</text>
      </g>
      {Array.from({ length: 8 }, (_, index) => (
        <g key={`a${index}`} className="gd-node gd-accent">
          <rect x={236 + index * 58} y="186" width="48" height="44" rx="10" />
          <text x={260 + index * 58} y="213" className="gd-step">{index + 1}</text>
        </g>
      ))}
    </svg>
  );
}

/** Из чего состоит рабочая область проекта. */
function WorkspaceLayout() {
  const zones = [
    { x: 208, title: "Зона 1", tabs: ["Ответ", "Источники"] },
    { x: 372, title: "Зона 2", tabs: ["Чат"] },
    { x: 536, title: "Зона 3", tabs: ["Мой конспект"] },
  ];
  return (
    <svg viewBox="0 0 720 330" role="img" aria-label="Рабочая область: слева программа и разделы проекта, сверху название темы, индикаторы и учёт времени, справа до трёх рабочих зон, в каждой свои вкладки">
      <rect x="6" y="6" width="708" height="318" rx="20" className="gd-frame" />
      <g className="gd-node gd-info">
        <rect x="18" y="18" width="176" height="294" rx="14" />
        <text x="106" y="50" className="gd-title gd-title-sm">Слева</text>
        <text x="106" y="82" className="gd-sub gd-sub-sm">поиск и фильтры</text>
        <text x="106" y="112" className="gd-step">Программа</text>
        <text x="106" y="132" className="gd-sub gd-sub-sm">разделы, темы, вопросы</text>
        <text x="106" y="152" className="gd-sub gd-sub-sm">с отметками состояния</text>
        <text x="106" y="222" className="gd-step">Разделы проекта</text>
        <text x="106" y="244" className="gd-sub gd-sub-sm">Материалы · Ответы</text>
        <text x="106" y="262" className="gd-sub gd-sub-sm">Уроки · Покрытие</text>
        <text x="106" y="280" className="gd-sub gd-sub-sm">Настройки</text>
      </g>
      <g className="gd-node gd-accent">
        <rect x="208" y="18" width="496" height="62" rx="14" />
        <text x="456" y="45" className="gd-title gd-title-sm">Сверху: выбранная тема</text>
        <text x="456" y="65" className="gd-sub gd-sub-sm">название · индикаторы · учёт времени · «N из M» · разделить · вынести</text>
      </g>
      {zones.map((zone) => (
        <g key={zone.title} className="gd-node gd-success">
          <rect x={zone.x} y="94" width="152" height="190" rx="14" />
          <text x={zone.x + 76} y="124" className="gd-title gd-title-sm">{zone.title}</text>
          <text x={zone.x + 76} y="146" className="gd-label gd-label-mid">вкладки</text>
          {zone.tabs.map((tab, index) => (
            <g key={tab}>
              <rect x={zone.x + 16} y={158 + index * 38} width="120" height="28" rx="8" className="gd-tab" />
              <text x={zone.x + 76} y={177 + index * 38} className="gd-sub gd-sub-sm">{tab}</text>
            </g>
          ))}
        </g>
      ))}
      <text x="456" y="308" className="gd-label gd-label-mid">до трёх зон рядом · любую зону можно вынести в отдельное окно браузера</text>
    </svg>
  );
}

/** Откуда берутся привязки и где они работают. */
function BindingFlow() {
  const sources = [
    { title: "Файл ответов", sub: "по заголовкам", tone: "gd-info" },
    { title: "Вручную", sub: "вы привязали", tone: "gd-info" },
    { title: "Поиск", sub: "нашли и привязали", tone: "gd-info" },
    { title: "Исследование", sub: "выбрал ИИ", tone: "gd-warning" },
    { title: "Урок", sub: "вы добавили кусок", tone: "gd-info" },
  ];
  const users = [
    { title: "Ответ и Источник", sub: "читать рядом", y: 24 },
    { title: "Чат", sub: "опора для ответа", y: 86 },
    { title: "Уроки", sub: "материал для сборки", y: 148 },
    { title: "Покрытие", sub: "чем закрыта тема", y: 210 },
  ];
  return (
    <svg viewBox="0 0 720 300" role="img" aria-label="Привязку создают файл ответов, ручной выбор, поиск, исследование ИИ и урок; она связывает тему с местом в тексте и работает в ответе, чате, уроках и покрытии">
      <defs>
        <marker id="gd-arrow-b" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>
      {sources.map((item, index) => (
        <g key={item.title}>
          <g className={`gd-node ${item.tone}`}>
            <rect x="8" y={10 + index * 56} width="184" height="46" rx="12" />
            <text x="100" y={31 + index * 56} className="gd-step">{item.title}</text>
            <text x="100" y={47 + index * 56} className="gd-sub gd-sub-sm">{item.sub}</text>
          </g>
          <path d={`M196 ${33 + index * 56} C232 ${33 + index * 56} 226 ${112 + index * 19} 262 ${112 + index * 19}`} className="gd-arrow" markerEnd="url(#gd-arrow-b)" />
        </g>
      ))}
      <g className="gd-node gd-accent">
        <rect x="266" y="82" width="188" height="136" rx="18" />
        <text x="360" y="120" className="gd-title">Привязка</text>
        <text x="360" y="144" className="gd-sub">тема + точное место</text>
        <text x="360" y="162" className="gd-sub">в тексте материала</text>
        <text x="360" y="190" className="gd-sub gd-sub-sm">ручная · подтверждена</text>
        <text x="360" y="206" className="gd-sub gd-sub-sm">или машинная</text>
      </g>
      {users.map((item, index) => (
        <g key={item.title}>
          <path d={`M458 ${112 + index * 25} C494 ${112 + index * 25} 488 ${47 + index * 62} 522 ${47 + index * 62}`} className="gd-arrow" markerEnd="url(#gd-arrow-b)" />
          <g className="gd-node gd-success">
            <rect x="526" y={item.y} width="186" height="46" rx="12" />
            <text x="619" y={item.y + 21} className="gd-step">{item.title}</text>
            <text x="619" y={item.y + 37} className="gd-sub gd-sub-sm">{item.sub}</text>
          </g>
        </g>
      ))}
    </svg>
  );
}

/** Как работает исследование материалов. */
function ResearchFlow() {
  const steps = [
    { title: "Программа", a: "темы вашего", b: "проекта", tone: "gd-accent" },
    { title: "Блоки", a: "готовый текст", b: "материала", tone: "gd-info" },
    { title: "ИИ читает", a: "пакетами", b: "соседних блоков", tone: "gd-warning" },
    { title: "Проверка", a: "сервер сверяет", b: "каждое место", tone: "gd-info" },
    { title: "Результат", a: "куски, пробелы,", b: "неразобранное", tone: "gd-success" },
  ];
  return (
    <svg viewBox="0 0 720 170" role="img" aria-label="Исследование: программа и блоки материала попадают к ИИ, тот читает их пакетами, сервер проверяет каждое решение, результат показывается кусками, пробелами и неразобранным">
      <defs>
        <marker id="gd-arrow-r" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>
      {steps.map((step, index) => {
        const x = 10 + index * 143;
        return (
          <g key={step.title}>
            <g className={`gd-node ${step.tone}`}>
              <rect x={x} y="12" width="128" height="86" rx="14" />
              <text x={x + 64} y="40" className="gd-title gd-title-sm">{step.title}</text>
              <text x={x + 64} y="64" className="gd-sub gd-sub-sm">{step.a}</text>
              <text x={x + 64} y="80" className="gd-sub gd-sub-sm">{step.b}</text>
            </g>
            {index < steps.length - 1 && (
              <path d={`M${x + 131} 55 H${x + 140}`} className="gd-arrow" markerEnd="url(#gd-arrow-r)" />
            )}
          </g>
        );
      })}
      <path d="M217 102 V120 H503 V102" className="gd-arrow gd-dashed" />
      <text x="360" y="146" className="gd-label gd-label-mid">запускаете вы сами · сначала бесплатная проверка объёма и цены</text>
    </svg>
  );
}

/** Три способа собрать урок и что происходит дальше. */
function LessonPaths() {
  const paths = [
    { title: "Быстрый урок", sub: "по оглавлению, без модели", y: 16 },
    { title: "Вручную", sub: "страницы, текст, медиа", y: 96 },
    { title: "С ИИ", sub: "план, шаги, задания", y: 176 },
  ];
  return (
    <svg viewBox="0 0 720 300" role="img" aria-label="Урок можно собрать быстро по оглавлению, вручную или с ИИ; получается черновик, его переводят в статус Готов, а читают и проходят в рабочей области; готовый урок можно дополнить ИИ и выгрузить в файл">
      <defs>
        <marker id="gd-arrow-lp" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>
      {paths.map((path) => (
        <g key={path.title} className="gd-node gd-info">
          <rect x="8" y={path.y} width="200" height="64" rx="14" />
          <text x="108" y={path.y + 28} className="gd-title gd-title-sm">{path.title}</text>
          <text x="108" y={path.y + 47} className="gd-sub gd-sub-sm">{path.sub}</text>
        </g>
      ))}
      <g className="gd-node gd-accent">
        <rect x="272" y="82" width="170" height="112" rx="18" />
        <text x="357" y="124" className="gd-title">Урок</text>
        <text x="357" y="148" className="gd-sub">сначала черновик,</text>
        <text x="357" y="166" className="gd-sub">потом «Готов»</text>
      </g>
      <g className="gd-node gd-success">
        <rect x="506" y="82" width="206" height="112" rx="18" />
        <text x="609" y="124" className="gd-title">Рабочая область</text>
        <text x="609" y="148" className="gd-sub">читать, задания,</text>
        <text x="609" y="166" className="gd-sub">«Урок пройден»</text>
      </g>
      <path d="M212 48 C244 48 240 120 266 120" className="gd-arrow" markerEnd="url(#gd-arrow-lp)" />
      <path d="M212 128 H266" className="gd-arrow" markerEnd="url(#gd-arrow-lp)" />
      <path d="M212 208 C244 208 240 152 266 152" className="gd-arrow" markerEnd="url(#gd-arrow-lp)" />
      <path d="M446 138 H500" className="gd-arrow" markerEnd="url(#gd-arrow-lp)" />
      <path d="M357 198 V234 M357 234 H609 M609 234 V198" className="gd-arrow gd-dashed" />
      <text x="483" y="262" className="gd-label gd-label-mid">по пути: «Дополнить с ИИ» · «Добавить практику» · экспорт</text>
    </svg>
  );
}

/** Как собирается урок с ИИ: что делается локально, а что зовёт модель. */
function LessonAiFlow() {
  const steps = [
    { title: "Область", a: "паспорт урока,", b: "тема, уровень", tone: "gd-info" },
    { title: "Куски", a: "оглавление,", b: "опоры, поиск", tone: "gd-info" },
    { title: "План", a: "понятия и шаги", b: "(один вызов)", tone: "gd-warning" },
    { title: "Шаги", a: "по вызову на", b: "каждый шаг", tone: "gd-warning" },
    { title: "Рецензент", a: "глазами", b: "новичка", tone: "gd-warning" },
    { title: "Задания", a: "4 или 8,", b: "с ключами", tone: "gd-warning" },
  ];
  return (
    <svg viewBox="0 0 720 190" role="img" aria-label="Сначала без модели собираются паспорт урока и куски материала, затем модель составляет план, пишет шаги, рецензирует и добавляет задания; результат становится новым черновиком">
      <defs>
        <marker id="gd-arrow-la" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>
      {steps.map((step, index) => {
        const x = 6 + index * 118;
        return (
          <g key={step.title}>
            <g className={`gd-node ${step.tone}`}>
              <rect x={x} y="12" width="106" height="86" rx="14" />
              <text x={x + 53} y="40" className="gd-title gd-title-sm">{step.title}</text>
              <text x={x + 53} y="64" className="gd-sub gd-sub-sm">{step.a}</text>
              <text x={x + 53} y="80" className="gd-sub gd-sub-sm">{step.b}</text>
            </g>
            {index < steps.length - 1 && (
              <path d={`M${x + 109} 55 H${x + 115}`} className="gd-arrow" markerEnd="url(#gd-arrow-la)" />
            )}
          </g>
        );
      })}
      <path d="M12 106 V116 H230 V106" className="gd-arrow gd-dashed" />
      <text x="121" y="140" className="gd-label gd-label-mid">без модели, бесплатно</text>
      <path d="M248 106 V116 H714 V106" className="gd-arrow gd-dashed" />
      <text x="481" y="140" className="gd-label gd-label-mid">вызовы модели: число и цена видны до запуска</text>
      <text x="360" y="176" className="gd-label gd-label-mid">на выходе новый черновик: вы проверяете его и нажимаете «Готов»</text>
    </svg>
  );
}

/** Из чего состоит экран «Моя подготовка». */
function PrepScreen() {
  const tiles = ["Время", "Вопросы", "Сданные ответы"];
  const tabs = ["Календарь подготовки", "История", "Аналитика"];
  return (
    <svg viewBox="0 0 720 372" role="img" aria-label="Экран Моей подготовки сверху вниз: шапка со статусами и кнопкой Начать день, баннер экзамена, три карточки сводки, очередь на сегодня, периоды подготовки и три вкладки: календарь, история, аналитика; слева последние события и достижения">
      <rect x="6" y="6" width="708" height="360" rx="20" className="gd-frame" />
      <g className="gd-node gd-info">
        <rect x="18" y="18" width="150" height="336" rx="14" />
        <text x="93" y="50" className="gd-title gd-title-sm">Слева</text>
        <text x="93" y="86" className="gd-step">Последние</text>
        <text x="93" y="104" className="gd-step">события</text>
        <text x="93" y="150" className="gd-step">Твои первые</text>
        <text x="93" y="168" className="gd-step">шаги · 5</text>
        <text x="93" y="228" className="gd-sub gd-sub-sm">разделы проекта</text>
        <text x="93" y="246" className="gd-sub gd-sub-sm">Материалы · Ответы</text>
        <text x="93" y="264" className="gd-sub gd-sub-sm">Моя подготовка</text>
        <text x="93" y="282" className="gd-sub gd-sub-sm">Карточки</text>
      </g>
      <g className="gd-node gd-accent">
        <rect x="182" y="18" width="522" height="46" rx="12" />
        <text x="443" y="46" className="gd-step">Шапка: статусы плана · «Начать день» · «Распределить вопросы»</text>
      </g>
      <g className="gd-node gd-warning">
        <rect x="182" y="74" width="522" height="42" rx="12" />
        <text x="443" y="100" className="gd-step">Баннер экзамена: дата · дней осталось · времени на подготовку</text>
      </g>
      {tiles.map((tile, index) => (
        <g key={tile} className="gd-node gd-info">
          <rect x={182 + index * 178} y="126" width="166" height="70" rx="12" />
          <text x={265 + index * 178} y="156" className="gd-title gd-title-sm">{tile}</text>
          <text x={265 + index * 178} y="177" className="gd-sub gd-sub-sm">7 или 14 дней</text>
        </g>
      ))}
      <g className="gd-node gd-success">
        <rect x="182" y="206" width="522" height="42" rx="12" />
        <text x="443" y="232" className="gd-step">Сегодня: вопросы и билеты на день</text>
      </g>
      <g className="gd-node gd-accent">
        <rect x="182" y="258" width="522" height="38" rx="12" />
        <text x="443" y="282" className="gd-step">Периоды подготовки: блоки от сегодня до экзамена</text>
      </g>
      {tabs.map((tab, index) => (
        <g key={tab} className="gd-node gd-success">
          <rect x={182 + index * 178} y="306" width="166" height="48" rx="12" />
          <text x={265 + index * 178} y="335" className="gd-sub gd-sub-sm">{tab}</text>
        </g>
      ))}
    </svg>
  );
}

/** Откуда берутся карточки и что с ними происходит при повторении. */
function CardsFlow() {
  const paths = [
    { title: "Вручную", sub: "обе стороны и источник", y: 16 },
    { title: "Из фрагмента", sub: "«В карточку» в Материалах", y: 88 },
    { title: "С помощью ИИ", sub: "предложения на проверку", y: 160 },
  ];
  const grades = ["Не вспомнил", "Частично", "Вспомнил", "Легко"];
  return (
    <svg viewBox="0 0 720 300" role="img" aria-label="Карточку создают вручную, из фрагмента материала или с помощью ИИ; все они попадают в Банк, из Банка идут в сеанс повторения, где вы оцениваете себя от Не вспомнил до Легко; оценки попадают в аналитику и подборку Сложные">
      <defs>
        <marker id="gd-arrow-cf" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M1 1 L9 5 L1 9" className="gd-arrow-head" />
        </marker>
      </defs>
      {paths.map((path) => (
        <g key={path.title} className="gd-node gd-info">
          <rect x="8" y={path.y} width="200" height="58" rx="14" />
          <text x="108" y={path.y + 25} className="gd-title gd-title-sm">{path.title}</text>
          <text x="108" y={path.y + 44} className="gd-sub gd-sub-sm">{path.sub}</text>
        </g>
      ))}
      <g className="gd-node gd-accent">
        <rect x="282" y="62" width="150" height="100" rx="18" />
        <text x="357" y="104" className="gd-title">Банк</text>
        <text x="357" y="128" className="gd-sub">все карточки</text>
        <text x="357" y="146" className="gd-sub gd-sub-sm">поиск, правка, фильтры</text>
      </g>
      <g className="gd-node gd-warning">
        <rect x="506" y="62" width="206" height="100" rx="18" />
        <text x="609" y="104" className="gd-title">Сеанс</text>
        <text x="609" y="128" className="gd-sub">на сегодня · сложные</text>
        <text x="609" y="146" className="gd-sub">выбранные · все</text>
      </g>
      <path d="M212 45 C246 45 244 100 276 100" className="gd-arrow" markerEnd="url(#gd-arrow-cf)" />
      <path d="M212 117 H276" className="gd-arrow" markerEnd="url(#gd-arrow-cf)" />
      <path d="M212 189 C246 189 244 134 276 134" className="gd-arrow" markerEnd="url(#gd-arrow-cf)" />
      <path d="M436 112 H500" className="gd-arrow" markerEnd="url(#gd-arrow-cf)" />
      <path d="M609 166 V186 H493 V204" className="gd-arrow" markerEnd="url(#gd-arrow-cf)" />
      {grades.map((grade, index) => (
        <g key={grade} className="gd-node gd-success">
          <rect x={282 + index * 108} y="208" width="98" height="40" rx="10" />
          <text x={331 + index * 108} y="233" className="gd-sub gd-sub-sm">{grade}</text>
        </g>
      ))}
      <text x="497" y="274" className="gd-label gd-label-mid">ваши оценки идут в аналитику и подборку «Сложные»</text>
    </svg>
  );
}

const DIAGRAMS: Record<string, () => ReactNode> = {
  overview: Overview,
  structure: Structure,
  transfer: Transfer,
  wizard: Wizard,
  "program-hub": ProgramHub,
  "add-paths": AddPaths,
  "text-blocks": TextBlocks,
  "two-passes": TwoPasses,
  "search-turn": SearchTurn,
  lanes: Lanes,
  workspace: WorkspaceLayout,
  bindings: BindingFlow,
  research: ResearchFlow,
  "lesson-paths": LessonPaths,
  "lesson-ai": LessonAiFlow,
  "prep-screen": PrepScreen,
  "cards-flow": CardsFlow,
};

export function GuideDiagram({ name }: { name: string }) {
  const Diagram = DIAGRAMS[name];
  if (!Diagram) return <p className="guide-missing">Схема «{name}» ещё не нарисована.</p>;
  return <Diagram />;
}
