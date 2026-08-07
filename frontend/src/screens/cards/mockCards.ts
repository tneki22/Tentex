/** Выдуманные данные экрана «Карточки». На этапе 1 запросов к API нет. */

export type CardKind = "plan" | "atomic" | "condition" | "comparison" | "definition";

export const CARD_KIND_LABEL: Record<CardKind, string> = {
  plan: "опорный план",
  atomic: "короткий ответ",
  condition: "условие",
  comparison: "сравнение",
  definition: "термин",
};

export interface GradeOption {
  value: 1 | 2 | 3 | 4;
  label: string;
  interval: string;
  tone: "danger" | "warning" | "success" | "info";
}

export const GRADES: GradeOption[] = [
  { value: 1, label: "Не вспомнил", interval: "завтра", tone: "danger" },
  { value: 2, label: "Частично", interval: "через 3 дня", tone: "warning" },
  { value: 3, label: "Вспомнил", interval: "через 7 дней", tone: "success" },
  { value: 4, label: "Легко", interval: "через 15 дней", tone: "info" },
];

export interface CardSourceRef {
  kind: "reference" | "fragment" | "manual" | "machine" | "edited" | "lost";
  label: string;
  href?: string;
}

export interface StudyCard {
  id: string;
  questionId: string;
  kind: CardKind;
  front: string;
  back: string;
  keyIdea?: string;
  hint?: [string, string, string];
  sources: CardSourceRef[];
}

export interface QueueQuestion {
  id: string;
  section: string;
  title: string;
  due: string;
  cards: StudyCard[];
}

type CardText = [front: string, back: string, keyIdea?: string];

const referenceSources: CardSourceRef[] = [
  { kind: "reference", label: "Эталонный ответ" },
  { kind: "fragment", label: "Учебник · стр. 47", href: "materials" },
];

function question(
  id: string,
  section: string,
  title: string,
  due: string,
  texts: CardText[],
): QueueQuestion {
  const kinds: CardKind[] = ["plan", "atomic", "definition", "condition", "comparison"];
  return {
    id,
    section,
    title,
    due,
    cards: texts.map(([front, back, keyIdea], index) => ({
      id: `${id}-${index + 1}`,
      questionId: id,
      kind: kinds[index % kinds.length],
      front,
      back,
      keyIdea,
      hint: index === 0
        ? [
            `В ответе ${Math.max(2, Math.min(5, back.split(".").filter(Boolean).length))} ключевых пункта`,
            back.split(" ").slice(0, 5).join(" ") + "…",
            keyIdea ?? back.split(".")[0],
          ]
        : undefined,
      sources: index === texts.length - 1
        ? [{ kind: "edited", label: "Создано ИИ · изменено вами" }, referenceSources[0]]
        : referenceSources,
    })),
  };
}

export const QUEUE: QueueQuestion[] = [
  question("normal-forms", "Реляционная модель", "Нормальные формы", "просрочено на 1 день", [
    ["Назовите последовательность нормальных форм и назначение каждой", "1НФ обеспечивает атомарность. 2НФ устраняет частичные зависимости. 3НФ — транзитивные зависимости. НФБК требует, чтобы каждый детерминант был потенциальным ключом.", "Каждая следующая форма снимает свой класс избыточности."],
    ["Чем третья нормальная форма отличается от НФБК?", "3НФ допускает зависимость от детерминанта, если зависимый атрибут входит в потенциальный ключ. НФБК требует, чтобы любой детерминант был потенциальным ключом.", "НФБК строже третьей нормальной формы."],
    ["Какое требование устраняет 2НФ?", "Частичную зависимость неключевого атрибута от части составного ключа."],
    ["Когда отношение находится в 1НФ?", "Когда все значения атрибутов атомарны и нет повторяющихся групп."],
    ["Зачем нужна декомпозиция отношения?", "Чтобы уменьшить избыточность и аномалии обновления, сохранив данные и по возможности зависимости."],
    ["Что такое детерминант?", "Атрибут или набор атрибутов, от которого функционально зависит другой атрибут."],
  ]),
  question("indexes", "Физическая организация", "Индексы в СУБД", "на сегодня", [
    ["Назовите основные задачи индекса", "Ускорить поиск, соединение, сортировку и проверку ограничений ценой дополнительного места и стоимости записи."],
    ["Чем кластерный индекс отличается от некластерного?", "Кластерный определяет физический порядок строк; некластерный хранит отдельную структуру со ссылками на строки."],
    ["Когда индекс может ухудшить работу?", "При частых изменениях, низкой селективности и запросах, читающих большую долю таблицы."],
    ["Что показывает селективность индекса?", "Насколько хорошо ключ индекса сокращает множество подходящих строк."],
  ]),
  question("transactions", "Управление транзакциями", "Транзакции и свойства ACID", "на сегодня", [
    ["Расшифруйте свойства ACID", "Атомарность, согласованность, изоляция и долговечность."],
    ["Что гарантирует атомарность?", "Все операции транзакции применяются целиком либо не применяются вовсе."],
    ["Что означает согласованность?", "Транзакция переводит базу из одного допустимого состояния в другое."],
    ["Что означает изоляция?", "Параллельные транзакции не должны наблюдать недопустимые промежуточные эффекты друг друга."],
    ["Что гарантирует долговечность?", "Подтверждённые изменения сохраняются после сбоя."],
    ["Чем COMMIT отличается от ROLLBACK?", "COMMIT фиксирует изменения, ROLLBACK отменяет изменения текущей транзакции."],
    ["Зачем транзакции журнал?", "Для восстановления атомарности и долговечности после сбоя."],
  ]),
  question("logging", "Управление транзакциями", "Журнализация и восстановление", "на сегодня", [
    ["Назовите этапы восстановления после сбоя", "Анализ журнала, повтор подтверждённых изменений и отмена незавершённых."],
    ["Что требует правило WAL?", "Запись журнала должна попасть на устойчивый носитель раньше соответствующей страницы данных."],
    ["Зачем нужна контрольная точка?", "Она ограничивает участок журнала, который требуется просмотреть при восстановлении."],
    ["Что такое REDO?", "Повторное применение изменений подтверждённых транзакций."],
    ["Что такое UNDO?", "Компенсирующая отмена изменений незавершённых транзакций."],
  ]),
  question("keys", "Реляционная модель", "Потенциальные и внешние ключи", "на сегодня", [
    ["Чем потенциальный ключ отличается от первичного?", "Потенциальных ключей может быть несколько; один из них выбирают первичным."],
    ["Что обеспечивает внешний ключ?", "Ссылочную целостность между строками связанных отношений."],
    ["Какие действия возможны при удалении родительской строки?", "Запрет, каскадное удаление, установка NULL или значения по умолчанию."],
  ]),
  question("algebra", "Реляционная модель", "Операции реляционной алгебры", "новые", [
    ["Назовите базовые операции реляционной алгебры", "Выборка, проекция, объединение, разность, декартово произведение и переименование."],
    ["Чем выборка отличается от проекции?", "Выборка фильтрует строки, проекция выбирает столбцы."],
    ["Как выражается соединение?", "Как декартово произведение с последующей выборкой по условию."],
  ]),
  question("sql-ddl", "Основы баз данных", "Языки определения данных", "новые", [
    ["Какие команды относятся к DDL?", "CREATE, ALTER, DROP и другие команды определения структуры данных."],
    ["Чем DDL отличается от DML?", "DDL меняет схему, DML читает и изменяет сами данные."],
  ]),
  question("acid-isolation", "Управление транзакциями", "Уровни изоляции", "новые", [
    ["Какие аномалии запрещает Serializable?", "Грязное, неповторяемое и фантомное чтение; результат эквивалентен последовательному выполнению."],
  ]),
];

export const QUEUE_SUMMARY = QUEUE.map(({ id, title, section, due, cards }) => ({
  id,
  title,
  section,
  due,
  cards: cards.length,
}));

export interface RecentReview {
  id: string;
  front: string;
  question: string;
  result: 1 | 2 | 3 | 4;
  nextDue: string;
}

export const RECENT_REVIEWS: RecentReview[] = [
  { id: "recent-1", front: "Чем 3НФ отличается от НФБК?", question: "Нормальные формы", result: 2, nextDue: "через 3 дня" },
  { id: "recent-2", front: "Что гарантирует долговечность?", question: "Транзакции", result: 3, nextDue: "через 7 дней" },
  { id: "recent-3", front: "Что показывает селективность?", question: "Индексы", result: 1, nextDue: "завтра" },
  { id: "recent-4", front: "Чем DDL отличается от DML?", question: "Языки данных", result: 4, nextDue: "через 15 дней" },
];

export interface BankCard {
  id: string;
  front: string;
  back: string;
  question: string;
  section: string;
  kind: CardKind;
  state: "active" | "draft" | "suspended" | "lost-source";
  origin: "manual" | "machine" | "edited";
  source: string;
  lastResult: "ok" | "partial" | "fail" | null;
  nextDue: string | null;
}

const BANK_FROM_QUEUE: BankCard[] = QUEUE.flatMap((item) => item.cards.slice(0, 2).map((card, index): BankCard => ({
  id: card.id,
  front: card.front,
  back: card.back,
  question: item.title,
  section: item.section,
  kind: card.kind,
  state: index === 0 ? "active" as const : item.id === "sql-ddl" ? "draft" as const : "active" as const,
  origin: index === 0 ? "machine" as const : "manual" as const,
  source: card.sources[0]?.label ?? "Источника нет",
  lastResult: index === 0 ? "partial" as const : "ok" as const,
  nextDue: item.due === "новые" ? null : item.due,
})));

export const BANK: BankCard[] = [...BANK_FROM_QUEUE,
  { id: "lost-card", front: "Что такое детерминант?", back: "Набор атрибутов, определяющий другой атрибут.", question: "Нормальные формы", section: "Реляционная модель", kind: "definition", state: "lost-source", origin: "machine", source: "Источник удалён", lastResult: null, nextDue: null },
  { id: "paused-card", front: "Что такое REDO?", back: "Повтор подтверждённых изменений.", question: "Журнализация", section: "Управление транзакциями", kind: "definition", state: "suspended", origin: "edited", source: "Эталонный ответ", lastResult: "fail", nextDue: null },
];

export const CREATION_QUESTIONS = QUEUE.map((item, index) => ({
  id: item.id,
  section: item.section,
  title: item.title,
  existing: item.cards.length,
  hasReference: index !== 6,
  fragments: index === 6 ? 0 : Math.max(1, 5 - (index % 4)),
}));

export const DRAFT_PLAN = [
  { id: "normal-forms", title: "Нормальные формы", proposed: 7, breakdown: "1 план · 4 положения · 2 сравнения" },
  { id: "indexes", title: "Индексы в СУБД", proposed: 5, breakdown: "1 план · 3 положения · 1 сравнение" },
  { id: "transactions", title: "Транзакции и свойства ACID", proposed: 6, breakdown: "1 план · 4 положения · 1 условие" },
  { id: "logging", title: "Журнализация и восстановление", proposed: 4, breakdown: "1 план · 3 положения" },
  { id: "sql-ddl", title: "Языки определения данных", proposed: 0, breakdown: "нет эталона и материалов" },
];

export interface AiDraft {
  id: string;
  question: string;
  front: string;
  back: string;
  kind: CardKind;
  source: string;
  warning?: string;
}

export const AI_DRAFTS: AiDraft[] = [
  { id: "draft-1", question: "Нормальные формы", front: "Чем 3НФ отличается от НФБК?", back: "НФБК требует, чтобы каждый детерминант был потенциальным ключом; 3НФ допускает исключение для ключевого атрибута.", kind: "comparison", source: "Эталонный ответ · Учебник, стр. 47" },
  { id: "draft-2", question: "Нормальные формы", front: "Назовите четыре ступени нормализации", back: "1НФ → 2НФ → 3НФ → НФБК.", kind: "plan", source: "Эталонный ответ", warning: "Ответ слишком общий — проверьте назначение каждой ступени." },
  { id: "draft-3", question: "Индексы в СУБД", front: "Когда индекс не ускоряет выборку?", back: "При низкой селективности или чтении значительной доли таблицы.", kind: "condition", source: "Учебник, стр. 81" },
  { id: "draft-4", question: "Транзакции и свойства ACID", front: "Что обеспечивает свойство durability?", back: "Подтверждённые изменения переживают сбой системы.", kind: "definition", source: "Эталонный ответ", warning: "Возможный дубликат существующей карточки." },
];
