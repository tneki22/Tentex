import type { TopicStatus } from "../components/domain";

export type WorkspaceVariant = "exam" | "textbook";
export type WorkspaceNodeType = "section" | "topic" | "subpoint";
export type WorkspaceSourceRole = "primary" | "additional" | "reference";
export type WorkspaceBindingStatus = "manual" | "confirmed" | "machine" | "removed";
export type WorkspaceSourceQuality = "native" | "ocr" | "ocr_low";

export interface WorkspaceSourceRef {
  id: string;
  materialName: string;
  role: WorkspaceSourceRole;
  pageLabel: string;
  fragmentCount: number;
  fragmentText: string;
  surroundingText?: string;
  bindingStatus: WorkspaceBindingStatus;
  quality: WorkspaceSourceQuality;
  available?: boolean;
}

export interface WorkspaceAttemptDemo {
  id: string;
  kind: "reading" | "card" | "free-answer" | "sql";
  happenedAt: string;
  durationMinutes: number;
  resultLabel: string;
  usedHint?: boolean;
  nextDueLabel?: string;
}

export interface WorkspaceNode {
  id: string;
  number: string;
  type: WorkspaceNodeType;
  title: string;
  purpose?: string;
  status: TopicStatus;
  sources: WorkspaceSourceRef[];
  answer?: string;
  conspect: string;
  attempts: WorkspaceAttemptDemo[];
  children?: WorkspaceNode[];
  isDraft?: boolean;
}

export interface WorkspaceProjectDemo {
  id: string;
  variant: WorkspaceVariant;
  name: string;
  deadlineDays?: number;
  planEnabled: boolean;
  modelsEnabled: boolean;
  lessonsEnabled: boolean;
  pass2Progress?: { done: number; total: number };
  nodes: WorkspaceNode[];
}

const examNodes: WorkspaceNode[] = [
  {
    id: "basics",
    number: "1",
    type: "section",
    title: "Основы баз данных",
    status: "studied",
    sources: [],
    conspect: "",
    attempts: [],
    children: [
      {
        id: "db-purpose",
        number: "1",
        type: "topic",
        title: "Назначение и основные компоненты системы управления базами данных",
        status: "studied",
        sources: [{
          id: "exam-db-purpose",
          materialName: "Конспект к экзамену.pdf",
          role: "primary",
          pageLabel: "стр. 4",
          fragmentCount: 1,
          fragmentText: "Система управления базами данных отделяет прикладную программу от физического способа хранения и предоставляет единый интерфейс доступа.",
          bindingStatus: "manual",
          quality: "native",
        }],
        answer: "Система управления базами данных — это комплекс программных средств для создания, хранения, поиска и согласованного изменения данных. Она отделяет прикладную программу от физического способа хранения и предоставляет единый интерфейс доступа.\n\nК основным компонентам относят процессор запросов, менеджер хранения, менеджер транзакций, каталог метаданных и средства восстановления. Вместе они обеспечивают целостность, параллельную работу пользователей и независимость данных.",
        conspect: "СУБД скрывает физическое хранение и отвечает за запросы, транзакции, целостность и восстановление.",
        attempts: [],
      },
      {
        id: "data-models",
        number: "2",
        type: "topic",
        title: "Модели данных: иерархическая, сетевая и реляционная",
        status: "has-material",
        sources: [{
          id: "exam-data-models",
          materialName: "Учебник — Базы данных.pdf",
          role: "primary",
          pageLabel: "стр. 31",
          fragmentCount: 1,
          fragmentText: "Иерархическая модель организует записи как дерево, сетевая допускает несколько родителей, а реляционная представляет данные отношениями.",
          bindingStatus: "confirmed",
          quality: "native",
        }],
        answer: "Модель данных определяет способ представления объектов, связей и допустимых операций. Иерархическая модель организует записи как дерево с одним родителем, сетевая допускает несколько родителей, а реляционная представляет данные отношениями — таблицами из кортежей и атрибутов.\n\nРеляционная модель получила наибольшее распространение благодаря декларативным запросам, строгой математической основе и независимости логической схемы от физического хранения.",
        conspect: "",
        attempts: [],
      },
      {
        id: "db-architecture",
        number: "3",
        type: "topic",
        title: "Трёхуровневая архитектура ANSI/SPARC и независимость данных",
        status: "no-material",
        sources: [],
        answer: "Архитектура ANSI/SPARC разделяет описание базы на внешний, концептуальный и внутренний уровни. Внешний уровень содержит пользовательские представления, концептуальный — общую логическую схему, внутренний — физическое размещение.\n\nЛогическая независимость позволяет менять концептуальную схему с минимальным влиянием на представления, а физическая — менять хранение без изменения логической схемы.",
        conspect: "",
        attempts: [],
      },
      {
        id: "data-languages",
        number: "4",
        type: "topic",
        title: "Языки определения и манипулирования данными",
        status: "no-material",
        sources: [],
        conspect: "",
        attempts: [],
      },
    ],
  },
  {
    id: "relational",
    number: "2",
    type: "section",
    title: "Реляционная модель",
    status: "studied",
    sources: [],
    conspect: "",
    attempts: [],
    children: [
      {
        id: "relational-concepts",
        number: "5",
        type: "topic",
        title: "Основные понятия реляционной модели: отношение, кортеж, домен",
        status: "has-material",
        sources: [{
          id: "exam-relational-concepts",
          materialName: "Учебник — Базы данных.pdf",
          role: "primary",
          pageLabel: "стр. 58",
          fragmentCount: 1,
          fragmentText: "Отношение — множество кортежей одинаковой структуры, а домен задаёт множество допустимых значений атрибута.",
          bindingStatus: "confirmed",
          quality: "native",
        }],
        answer: "Отношение — множество кортежей одинаковой структуры. Кортеж задаёт одно значение каждого атрибута, а домен определяет допустимое множество атомарных значений атрибута. Порядок строк и столбцов не является частью математического отношения.",
        conspect: "",
        attempts: [],
      },
      {
        id: "keys",
        number: "6",
        type: "topic",
        title: "Потенциальные, первичные и внешние ключи",
        status: "drilled",
        sources: [{
          id: "exam-keys",
          materialName: "Методические указания.pdf",
          role: "additional",
          pageLabel: "стр. 12",
          fragmentCount: 1,
          fragmentText: "Потенциальный ключ — минимальный набор атрибутов, однозначно определяющий кортеж.",
          bindingStatus: "manual",
          quality: "native",
        }],
        answer: "Потенциальный ключ — минимальный набор атрибутов, однозначно определяющий кортеж. Один из потенциальных ключей выбирают первичным. Внешний ключ ссылается на потенциальный ключ другого или того же отношения и поддерживает ссылочную целостность.",
        conspect: "Ключ должен быть уникальным и минимальным. Внешний ключ допускает связь между отношениями.",
        attempts: [],
      },
      {
        id: "relational-algebra",
        number: "7",
        type: "topic",
        title: "Операции реляционной алгебры",
        status: "has-material",
        sources: [{
          id: "exam-relational-algebra",
          materialName: "Учебник — Базы данных.pdf",
          role: "primary",
          pageLabel: "стр. 74",
          fragmentCount: 1,
          fragmentText: "Базовые операции реляционной алгебры включают выборку, проекцию, объединение, разность и декартово произведение.",
          bindingStatus: "confirmed",
          quality: "native",
        }],
        answer: "Базовые операции реляционной алгебры включают выборку, проекцию, объединение, разность, декартово произведение и переименование. Через них выражаются соединение, пересечение и деление. Результатом каждой операции снова является отношение.",
        conspect: "",
        attempts: [],
      },
      {
        id: "normalization",
        number: "8",
        type: "topic",
        title: "Нормализация отношений. Первая, вторая и третья нормальные формы",
        status: "studied",
        sources: [{
          id: "exam-normalization",
          materialName: "Методические указания.pdf",
          role: "additional",
          pageLabel: "стр. 27",
          fragmentCount: 2,
          fragmentText: "Нормализация устраняет избыточность и аномалии изменения с помощью декомпозиции отношений.",
          bindingStatus: "manual",
          quality: "native",
        }],
        answer: "Нормализация устраняет избыточность и аномалии изменения с помощью декомпозиции отношений. Первая нормальная форма требует атомарности значений. Вторая устраняет частичные зависимости неключевых атрибутов от части составного ключа. Третья устраняет транзитивные зависимости неключевых атрибутов от ключа.\n\nДекомпозиция должна сохранять зависимости и обеспечивать соединение без потерь, иначе восстановление исходного отношения может породить ложные кортежи.",
        conspect: "1НФ — атомарность. 2НФ — нет зависимости от части составного ключа. 3НФ — нет транзитивной зависимости от ключа.",
        attempts: [],
      },
    ],
  },
];

const textbookNodes: WorkspaceNode[] = [
  {
    id: "vector-foundations",
    number: "1",
    type: "section",
    title: "Основы векторного поиска",
    purpose: "Понять, как данные превращаются в векторы и по каким правилам сравниваются объекты.",
    status: "studied",
    sources: [],
    conspect: "",
    attempts: [],
    children: [
      {
        id: "vector-representations",
        number: "1.1",
        type: "topic",
        title: "Векторные представления и пространство признаков",
        status: "studied",
        sources: [
          {
            id: "vectors-book",
            materialName: "Архитектура систем баз данных.pdf",
            role: "primary",
            pageLabel: "стр. 241–246",
            fragmentCount: 3,
            fragmentText: "Векторное представление сопоставляет объекту точку в многомерном пространстве. Близость точек используется как приближение смысловой или структурной близости исходных объектов.",
            surroundingText: "Размерность и способ построения представления зависят от модели. Для индекса важны не отдельные координаты, а выбранная функция расстояния и распределение векторов.",
            bindingStatus: "confirmed",
            quality: "native",
          },
          {
            id: "vectors-notes",
            materialName: "Практика векторного поиска.md",
            role: "additional",
            pageLabel: "раздел 2",
            fragmentCount: 2,
            fragmentText: "Перед построением индекса проверьте размерность, нормализацию и соответствие метрики тому, как обучалась модель представлений.",
            surroundingText: "Косинусное сходство часто реализуют через скалярное произведение нормализованных векторов.",
            bindingStatus: "manual",
            quality: "native",
          },
        ],
        conspect: "Вектор — не сам объект, а его положение в пространстве признаков. Метрика должна соответствовать способу обучения представлений.",
        attempts: [
          { id: "vectors-read", kind: "reading", happenedAt: "2 августа, 19:10", durationMinutes: 18, resultLabel: "Отмечено как разобранное" },
          { id: "vectors-card", kind: "card", happenedAt: "3 августа, 11:40", durationMinutes: 6, resultLabel: "3 из 4 без подсказки", nextDueLabel: "Следующее повторение 7 августа" },
        ],
      },
      {
        id: "distance-metrics",
        number: "1.2",
        type: "topic",
        title: "Косинусная близость, скалярное произведение и L2",
        status: "has-material",
        sources: [{
          id: "metrics-book",
          materialName: "Архитектура систем баз данных.pdf",
          role: "primary",
          pageLabel: "стр. 247–253",
          fragmentCount: 4,
          fragmentText: "Косинусная близость сравнивает направление векторов, L2 — геометрическое расстояние, а скалярное произведение учитывает и направление, и длину.",
          surroundingText: "После нормализации косинусная близость и скалярное произведение задают одинаковый порядок соседей.",
          bindingStatus: "confirmed",
          quality: "native",
        }],
        conspect: "",
        attempts: [],
      },
      {
        id: "ann-basics",
        number: "1.3",
        type: "topic",
        title: "Зачем нужен приближённый поиск ближайших соседей",
        status: "studied",
        sources: [{
          id: "ann-book",
          materialName: "Архитектура систем баз данных.pdf",
          role: "primary",
          pageLabel: "стр. 254–260",
          fragmentCount: 2,
          fragmentText: "Полный перебор обеспечивает точный результат, но его стоимость растёт вместе с числом векторов и размерностью. ANN-индексы обменивают небольшую потерю полноты на предсказуемое время поиска.",
          bindingStatus: "confirmed",
          quality: "native",
        }],
        conspect: "",
        attempts: [],
      },
    ],
  },
  {
    id: "ann-indexes",
    number: "2",
    type: "section",
    title: "Индексы приближённого поиска",
    purpose: "Научиться выбирать структуру индекса и объяснять компромисс между скоростью, памятью и качеством поиска.",
    status: "studied",
    sources: [],
    conspect: "",
    attempts: [],
    children: [
      {
        id: "hnsw",
        number: "2.1",
        type: "topic",
        title: "HNSW: построение графа и параметры поиска",
        status: "has-material",
        sources: [{
          id: "hnsw-method",
          materialName: "Векторные базы данных — методичка.pdf",
          role: "primary",
          pageLabel: "стр. 22–29",
          fragmentCount: 5,
          fragmentText: "HNSW строит многослойный граф близости. Поиск начинается на разреженном верхнем слое и уточняется при переходе к нижним слоям.",
          surroundingText: "Параметр efSearch увеличивает число рассматриваемых кандидатов: полнота растёт вместе со временем запроса. Фрагмент распознан со скана и требует сверки.",
          bindingStatus: "machine",
          quality: "ocr_low",
        }],
        conspect: "",
        attempts: [],
      },
      {
        id: "ivfflat",
        number: "2.2",
        type: "topic",
        title: "IVF и IVFFlat: кластеризация пространства",
        status: "studied",
        sources: [{
          id: "ivf-method",
          materialName: "Векторные базы данных — методичка.pdf",
          role: "primary",
          pageLabel: "стр. 44–55",
          fragmentCount: 6,
          fragmentText: "IVFFlat делит пространство на кластеры и при запросе просматривает только несколько ближайших списков. Число probes управляет компромиссом между полнотой и скоростью.",
          surroundingText: "Индекс требует обучающей выборки для центроидов и чувствителен к распределению данных после построения.",
          bindingStatus: "confirmed",
          quality: "ocr",
        }],
        conspect: "",
        attempts: [{ id: "ivf-read", kind: "reading", happenedAt: "4 августа, 20:05", durationMinutes: 24, resultLabel: "Отмечено как разобранное" }],
      },
      {
        id: "index-tuning",
        number: "2.3",
        type: "subpoint",
        title: "Настройка индекса под ограничения памяти и задержки",
        status: "no-material",
        sources: [],
        conspect: "",
        attempts: [],
      },
      {
        id: "hybrid-search",
        number: "2.4",
        type: "subpoint",
        title: "Гибридный поиск: фильтры, BM25 и векторы",
        status: "no-material",
        sources: [{
          id: "hybrid-unavailable",
          materialName: "Практика векторного поиска.md",
          role: "reference",
          pageLabel: "раздел 7",
          fragmentCount: 2,
          fragmentText: "",
          bindingStatus: "confirmed",
          quality: "native",
          available: false,
        }],
        conspect: "",
        attempts: [],
      },
    ],
  },
];

const examProject: WorkspaceProjectDemo = {
  id: "demo",
  variant: "exam",
  name: "Базы данных — экзамен",
  deadlineDays: 14,
  planEnabled: true,
  modelsEnabled: false,
  lessonsEnabled: false,
  nodes: examNodes,
};

const textbookProject: WorkspaceProjectDemo = {
  id: "vector-indexes",
  variant: "textbook",
  name: "Индексы в векторных базах данных",
  planEnabled: false,
  modelsEnabled: false,
  lessonsEnabled: true,
  pass2Progress: { done: 96, total: 214 },
  nodes: textbookNodes,
};

export function resolveWorkspaceProject(projectId: string): WorkspaceProjectDemo {
  return projectId === textbookProject.id ? textbookProject : { ...examProject, id: projectId };
}
