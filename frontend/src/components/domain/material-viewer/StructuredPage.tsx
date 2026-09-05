import katex from "katex";
import type { CSSProperties, HTMLAttributes, ReactNode } from "react";
import type {
  MaterialFragmentRead,
  MaterialPageRead,
  RecognitionSource,
} from "../../../api/materials";
import { QualityBadge } from "../QualityBadge";

interface StructuredPageProps {
  page: MaterialPageRead;
  showOcrReview?: boolean;
  /** Подсветка совпадений поиска. Пустая строка — ничего не подсвечивать. */
  /** Словоформы для подсветки — их считает поиск, здесь морфологии нет. */
  terms?: string[];
  /** Ссылка на картинку фрагмента: у проекта и Библиотеки маршруты разные. */
  assetUrl?: (fragmentId: string) => string;
  /** Фрагмент, к которому нужно прокрутить и который выделен. */
  focusedFragmentId?: string | null;
  /** Проектный потребитель добавляет сюда привязки; в Библиотеке их нет. */
  renderFragmentOverlay?: (fragment: MaterialFragmentRead) => ReactNode;
  fragmentProps?: (fragment: MaterialFragmentRead) => HTMLAttributes<HTMLDivElement> | undefined;
  /** Ссылка на растр исходной страницы: с ней над каждым фрагментом можно
      показать вырезку оригинала, а расшифровку — под ней. */
  pageImageUrl?: string;
  /** Показывать вырезки исходной фотографии над распознанным текстом. */
  showSourceCrops?: boolean;
  /** Сохранить геометрию исходной страницы по координатам OCR. */
  preserveLayout?: boolean;
  className?: string;
}

/**
 * Подготовленный текст страницы со своей структурой: заголовки остаются
 * заголовками, пункт списка получает висячий отступ по уровню, таблица —
 * настоящей таблицей, картинка — картинкой на своём месте.
 *
 * Компонент нейтрален: ни привязок, ни тем, ни проекта. Проектный просмотрщик
 * навешивает своё через `renderFragmentOverlay` и `fragmentProps`.
 */
export function StructuredPage({
  page,
  showOcrReview = true,
  terms = [],
  assetUrl,
  focusedFragmentId = null,
  renderFragmentOverlay,
  fragmentProps,
  pageImageUrl,
  showSourceCrops = false,
  preserveLayout = false,
  className = "",
}: StructuredPageProps) {
  const withCrops = showSourceCrops && Boolean(pageImageUrl);
  const spatial = preserveLayout && page.width > 0 && page.height > 0;
  return (
    <article className={`structured-page ${withCrops ? "with-crops" : ""} ${spatial ? "is-spatial" : ""} ${className}`.trim()}>
      <header className="structured-page-head">
        <span>Страница {page.page_number}</span>
        <QualityBadge quality={page.quality} showReview={showOcrReview} />
      </header>
      <div
        className={spatial ? "structured-page-canvas" : "structured-page-flow"}
        style={spatial ? { aspectRatio: `${page.width} / ${page.height}` } : undefined}
      >
        {page.fragments.map((fragment) => {
          const extra = fragmentProps?.(fragment) ?? {};
          const classNames = [
            "structured-fragment",
            fragment.id === focusedFragmentId ? "is-focused" : "",
            extra.className ?? "",
          ].filter(Boolean).join(" ");
          const spatialStyle: CSSProperties | undefined = spatial && hasArea(fragment.bbox)
            ? {
                left: `${fragment.bbox[0] * 100}%`,
                top: `${fragment.bbox[1] * 100}%`,
                width: `${(fragment.bbox[2] - fragment.bbox[0]) * 100}%`,
                height: `${(fragment.bbox[3] - fragment.bbox[1]) * 100}%`,
              }
            : undefined;
          return (
            <div
              {...extra}
              className={classNames}
              data-element-kind={fragment.element_kind}
              data-recognition-source={fragment.recognition_source}
              key={fragment.id}
              id={`fragment-${fragment.id}`}
              style={{ ...extra.style, ...spatialStyle }}
            >
              {renderFragmentOverlay?.(fragment)}
              {withCrops && pageImageUrl && hasArea(fragment.bbox) && (
                <SourceCrop pageImageUrl={pageImageUrl} bbox={fragment.bbox} page={page} />
              )}
              <FragmentBody
                fragment={fragment}
                page={page}
                terms={terms}
                assetUrl={assetUrl}
                suppressImage={withCrops}
                preserveLayout={spatial}
              />
              <RecognitionMeta fragment={fragment} showConfidence={showOcrReview && !spatial} />
            </div>
          );
        })}
        {page.fragments.length === 0 && (
          <p className="structured-page-empty">На этой странице не нашлось текста.</p>
        )}
      </div>
    </article>
  );
}

function FragmentBody({
  fragment,
  page,
  terms,
  assetUrl,
  suppressImage = false,
  preserveLayout = false,
}: {
  fragment: MaterialFragmentRead;
  /** Нужна для масштаба вырезок: доля страницы задаёт их размер на экране. */
  page: MaterialPageRead;
  terms: string[];
  assetUrl?: (fragmentId: string) => string;
  /** Вырезку оригинала уже показывает `SourceCrop` — свои картинки не дублируем. */
  suppressImage?: boolean;
  preserveLayout?: boolean;
}) {
  if (fragment.element_kind === "image") {
    const transcript = fragment.text.trim();
    const hasTranscript = fragment.recognition_source !== "native"
      && transcript.length > 0
      && !/^\[?(изображение|image)\]?$/iu.test(transcript);
    if (suppressImage) {
      // Фото фрагмента уже над текстом — здесь только расшифровка, если есть.
      return hasTranscript ? <p>{renderInlineMath(transcript, terms)}</p> : null;
    }
    if (!fragment.has_asset || !assetUrl) {
      return hasTranscript ? <p>{renderInlineMath(transcript, terms)}</p> : null;
    }
    if (preserveLayout) {
      return <img className="structured-image" src={assetUrl(fragment.id)} alt="Изображение из документа" loading="lazy" />;
    }
    return (
      <figure className="structured-figure">
        <img
          className="structured-image"
          src={assetUrl(fragment.id)}
          alt="Изображение из документа"
          loading="lazy"
        />
        {hasTranscript && (
          <details className="structured-transcript">
            <summary>Распознанный текст</summary>
            <p className="structured-transcript-note">Может содержать ошибки, особенно в формулах.</p>
            <p>{renderInlineMath(transcript, terms)}</p>
          </details>
        )}
      </figure>
    );
  }
  if (fragment.element_kind === "heading") {
    const level = fragment.structure_level ?? 1;
    if (level <= 1) return <h2>{renderInlineMath(fragment.text, terms)}</h2>;
    if (level === 2) return <h3>{renderInlineMath(fragment.text, terms)}</h3>;
    return <h4>{renderInlineMath(fragment.text, terms)}</h4>;
  }
  if (fragment.element_kind === "list") {
    return (
      <p
        className="structured-list-item"
        style={{ "--list-level": fragment.structure_level ?? 1 } as CSSProperties}
      >
        {renderInlineMath(fragment.text, terms)}
      </p>
    );
  }
  if (fragment.element_kind === "formula") {
    return (
      <Formula
        fragment={fragment}
        page={page}
        assetUrl={suppressImage ? undefined : assetUrl}
        preserveLayout={preserveLayout}
      />
    );
  }
  if (fragment.element_kind === "table") {
    if (preserveLayout && fragment.has_asset && assetUrl) {
      return <img className="structured-image" src={assetUrl(fragment.id)} alt="Таблица из документа" loading="lazy" />;
    }
    return (
      <>
        <MarkdownTable markdown={fragment.text} />
        {!suppressImage && fragment.has_asset && assetUrl && (
          <details className="structured-source-crop">
            <summary>Оригинальный фрагмент таблицы</summary>
            <img
              src={assetUrl(fragment.id)}
              alt="Оригинальный фрагмент таблицы"
              loading="lazy"
              style={cropStyle(fragment.bbox, page)}
            />
          </details>
        )}
      </>
    );
  }
  return <p>{renderInlineMath(fragment.text, terms)}</p>;
}

/** Ниже этого распознаванию нельзя верить без сверки с оригиналом. */
const LOW_CONFIDENCE = 0.75;

/**
 * Отметка «сюда надо посмотреть» под фрагментом.
 *
 * Названия движка здесь нет намеренно: режим у всей страницы один, и он
 * написан один раз наверху. Подпись под каждым блоком не сообщала ничего
 * нового, зато шла через всю страницу частоколом. Осталось только то, что
 * относится к конкретному фрагменту и требует действия.
 */
function RecognitionMeta({
  fragment,
  showConfidence,
}: {
  fragment: MaterialFragmentRead;
  showConfidence: boolean;
}) {
  if (!showConfidence || fragment.confidence === null) return null;
  if (fragment.confidence >= LOW_CONFIDENCE) return null;
  return (
    <small className="structured-recognition is-low">
      сверьте с оригиналом · уверенность {Math.round(fragment.confidence * 100)}%
    </small>
  );
}

/** У фрагмента есть, что вырезать: непустая площадь бокса. */
function hasArea(bbox: number[]): boolean {
  const [x0, y0, x1, y1] = bbox;
  return x1 - x0 > 0.01 && y1 - y0 > 0.005;
}

// Совсем узкую вырезку всё же немного увеличиваем, иначе она нечитаема. У
// сопровождающего фото порог низкий: рядом лежит расшифровка, и разбирать
// колонтитул по буквам не нужно. У формулы и таблицы вырезка и есть
// содержание, поэтому порог выше.
const MIN_PHOTO_WIDTH_PERCENT = 10;
const MIN_CONTENT_WIDTH_PERCENT = 32;
// Потолок высоты вырезки в процентах от ширины колонки. Узкая и очень высокая
// область (боковая колонка, длинная фигурная скобка) иначе растёт вниз без
// предела и выдавливает с экрана сам текст.
const MAX_CROP_HEIGHT_PERCENT = 60;

/**
 * Ширина вырезки: во столько же процентов колонки, во сколько область занимает
 * страницу.
 *
 * Прежде вырезка всегда бралась во всю ширину, и номер страницы или строчка
 * колонтитула раздувались до размеров иллюстрации — одинокая цифра «8»
 * занимала экран целиком. Доля от страницы — это и есть тот масштаб, в котором
 * область видел бы читатель: на всю колонку выходят только настоящие
 * иллюстрации и широкие блоки текста.
 */
function cropWidthPercent(bbox: number[], page: MaterialPageRead, floor: number): number {
  const share = Math.min(1, Math.max(0.0001, bbox[2] - bbox[0]));
  const height = Math.min(1, Math.max(0.0001, bbox[3] - bbox[1]));
  const ratio = (share * page.width) / (height * page.height);
  const widthPercent = Math.min(100, Math.max(share * 100, floor));
  if (!Number.isFinite(ratio) || ratio <= 0) return widthPercent;
  return Math.min(widthPercent, MAX_CROP_HEIGHT_PERCENT * ratio);
}

/** Стиль исходной вырезки формулы или таблицы: тот же масштаб, что у фото. */
function cropStyle(bbox: number[], page: MaterialPageRead): CSSProperties {
  return { width: `${cropWidthPercent(bbox, page, MIN_CONTENT_WIDTH_PERCENT).toFixed(2)}%` };
}

/**
 * Вырезка исходной фотографии под один фрагмент: тот же кадр страницы, обрезанный
 * по нормализованному боксу. Растр один на страницу, кроим его через background —
 * лишних сетевых запросов на каждый фрагмент нет.
 */
function SourceCrop({
  pageImageUrl,
  bbox,
  page,
}: {
  pageImageUrl: string;
  bbox: number[];
  page: MaterialPageRead;
}) {
  const [x0, y0, x1, y1] = bbox;
  const width = Math.min(1, Math.max(0.0001, x1 - x0));
  const height = Math.min(1, Math.max(0.0001, y1 - y0));
  const ratio = (width * page.width) / (height * page.height);
  const style: CSSProperties = {
    backgroundImage: `url("${pageImageUrl}")`,
    backgroundSize: `${100 / width}% ${100 / height}%`,
    backgroundPosition: `${width >= 1 ? 0 : (x0 / (1 - width)) * 100}% ${
      height >= 1 ? 0 : (y0 / (1 - height)) * 100
    }%`,
    aspectRatio: Number.isFinite(ratio) && ratio > 0 ? `${ratio}` : undefined,
    width: `${cropWidthPercent(bbox, page, MIN_PHOTO_WIDTH_PERCENT).toFixed(2)}%`,
  };
  return (
    <div
      className="structured-source-photo"
      style={style}
      role="img"
      aria-label="Вырезка исходной страницы"
    />
  );
}

/**
 * Распознаватель формул (PP-FormulaNet) и markdown часто оборачивают LaTeX в
 * разделители `$$…$$`, `\[…\]`, `\(…\)` или `$…$`. KaTeX ждёт голое выражение,
 * поэтому внешнюю обёртку снимаем — иначе валидная формула молча падала в
 * запасной вид сырым текстом.
 */
function latexFromFragment(text: string): string {
  let value = text.trim();
  const wrappers: [string, string][] = [
    ["$$", "$$"],
    ["\\[", "\\]"],
    ["\\(", "\\)"],
    ["$", "$"],
  ];
  for (const [open, close] of wrappers) {
    if (
      value.length >= open.length + close.length
      && value.startsWith(open)
      && value.endsWith(close)
    ) {
      return value.slice(open.length, value.length - close.length).trim();
    }
  }
  return value;
}

const DISPLAY_MATH = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]/g;

/**
 * Разложить элемент-формулу на отдельные выносные формулы.
 *
 * Внешняя модель нередко присылает систему из трёх уравнений одним элементом,
 * каждое в своих `$$`. Прежде такой элемент уходил в KaTeX целиком: внешняя
 * пара `$$` снималась, внутренние оставались — и совершенно валидная система
 * падала в запасной вид сырым текстом с долларами. Здесь она разбирается на
 * части, каждая из которых рисуется своей строкой.
 *
 * `leftover` — то, что осталось за пределами формул. Если там есть слова,
 * элемент вообще не выносная формула, а абзац с формулами внутри.
 */
function displayMathRuns(text: string): { runs: string[]; leftover: string } {
  const runs: string[] = [];
  let leftover = "";
  let cursor = 0;
  for (const match of text.matchAll(DISPLAY_MATH)) {
    leftover += text.slice(cursor, match.index);
    const body = (match[1] ?? match[2] ?? "").trim();
    if (body) runs.push(body);
    cursor = match.index + match[0].length;
  }
  leftover += text.slice(cursor);
  return { runs, leftover: leftover.trim() };
}

function Formula({
  fragment,
  page,
  assetUrl,
  preserveLayout = false,
}: {
  fragment: MaterialFragmentRead;
  page: MaterialPageRead;
  assetUrl?: (fragmentId: string) => string;
  preserveLayout?: boolean;
}) {
  const source = fragment.text.trim();
  const { runs, leftover } = displayMathRuns(source);
  // Формула вперемешку с пояснением — это абзац, а не выносная формула:
  // рисуем как текст, иначе пояснение пришлось бы выбросить.
  if (runs.length > 0 && leftover) return <p>{renderInlineMath(source, [])}</p>;
  const pieces = runs.length > 0 ? runs : [latexFromFragment(source)];
  try {
    const html = pieces
      .map((latex) => {
        if (!formulaLooksReliable(latex, fragment.recognition_source)) {
          throw new Error("Suspicious formula");
        }
        if (preserveLayout && latex.length > 220) {
          throw new Error("Formula does not fit its OCR box");
        }
        return katex.renderToString(latex, {
          displayMode: true,
          throwOnError: true,
          strict: "ignore",
          trust: false,
        });
      })
      .join("");
    return <div className="structured-formula" dangerouslySetInnerHTML={{ __html: html }} />;
  } catch {
    if (fragment.has_asset && assetUrl) {
      return (
        <div className="structured-formula-fallback" data-formula-status="source-crop">
          <img
            src={assetUrl(fragment.id)}
            alt="Оригинальный фрагмент формулы"
            loading="lazy"
            style={preserveLayout ? undefined : cropStyle(fragment.bbox, page)}
          />
          {!preserveLayout && (
            <details>
              <summary>LaTeX требует проверки</summary>
              <code>{fragment.text}</code>
            </details>
          )}
        </div>
      );
    }
    return (
      <div className="structured-formula-fallback" data-formula-status="raw-latex">
        <code>{fragment.text}</code>
      </div>
    );
  }
}

/**
 * \u0421\u0442\u043e\u0438\u0442 \u043b\u0438 \u0432\u043e\u043e\u0431\u0449\u0435 \u043e\u0442\u0434\u0430\u0432\u0430\u0442\u044c \u044d\u0442\u0443 \u0441\u0442\u0440\u043e\u043a\u0443 \u0432 KaTeX.
 *
 * \u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u043d\u0430 \u043f\u043e\u0432\u0442\u043e\u0440\u044f\u0435\u043c\u043e\u0441\u0442\u044c \u0430\u0434\u0440\u0435\u0441\u043d\u0430\u044f: \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u044b\u0439 \u0440\u0430\u0441\u043f\u043e\u0437\u043d\u0430\u0432\u0430\u0442\u0435\u043b\u044c \u0444\u043e\u0440\u043c\u0443\u043b \u0443\u043c\u0435\u0435\u0442
 * \u0432\u044b\u0434\u0430\u0442\u044c \u0441\u0438\u043d\u0442\u0430\u043a\u0441\u0438\u0447\u0435\u0441\u043a\u0438 \u0432\u0435\u0440\u043d\u044b\u0439, \u043d\u043e \u0431\u0435\u0441\u0441\u043c\u044b\u0441\u043b\u0435\u043d\u043d\u044b\u0439 LaTeX \u2014 \u043e\u0434\u0438\u043d \u0438 \u0442\u043e\u0442 \u0436\u0435 \u0442\u043e\u043a\u0435\u043d \u043f\u043e
 * \u043a\u0440\u0443\u0433\u0443. \u041e\u0442\u0432\u0435\u0442 \u0432\u043d\u0435\u0448\u043d\u0435\u0439 \u043c\u043e\u0434\u0435\u043b\u0438 \u0442\u0430\u043a \u043d\u0435 \u043b\u043e\u043c\u0430\u0435\u0442\u0441\u044f, \u0437\u0430\u0442\u043e \u0437\u0430\u043a\u043e\u043d\u043d\u0430\u044f \u0441\u0438\u0441\u0442\u0435\u043c\u0430 \u0443\u0440\u0430\u0432\u043d\u0435\u043d\u0438\u0439
 * \u0438\u0437 \u0434\u0435\u0441\u044f\u0442\u043a\u0430 \u043e\u0434\u0438\u043d\u0430\u043a\u043e\u0432\u044b\u0445 `\mathrm{Q}` \u043f\u043e\u0434 \u044d\u0442\u043e \u043f\u0440\u0430\u0432\u0438\u043b\u043e \u043f\u043e\u043f\u0430\u0434\u0430\u043b\u0430 \u0438 \u0443\u0445\u043e\u0434\u0438\u043b\u0430 \u0432 \u0441\u044b\u0440\u043e\u0439
 * \u0442\u0435\u043a\u0441\u0442 \u043d\u0430 \u0440\u043e\u0432\u043d\u043e\u043c \u043c\u0435\u0441\u0442\u0435. \u041f\u043e\u044d\u0442\u043e\u043c\u0443 \u043f\u043e\u0432\u0442\u043e\u0440\u044f\u0435\u043c\u043e\u0441\u0442\u044c \u0441\u043f\u0440\u0430\u0448\u0438\u0432\u0430\u0435\u0442\u0441\u044f \u0442\u043e\u043b\u044c\u043a\u043e \u0443 \u0441\u0432\u043e\u0435\u0433\u043e OCR.
 *
 * \u041e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0438\u0435 \u043f\u0440\u0438\u0437\u043d\u0430\u043a\u043e\u0432 LaTeX (`\`, `^`, `_`, \u0441\u043a\u043e\u0431\u043e\u043a) \u2014 \u0442\u043e\u0436\u0435 \u043e\u0442\u043a\u0430\u0437: \u0442\u0430\u043a
 * \u0432\u044b\u0433\u043b\u044f\u0434\u0438\u0442 \u043b\u0438\u043d\u0435\u0430\u0440\u0438\u0437\u043e\u0432\u0430\u043d\u043d\u044b\u0439 \u0442\u0435\u043a\u0441\u0442\u043e\u0432\u044b\u0439 \u0441\u043b\u043e\u0439 PDF (\u00abp = CR MCK\u2212R N\u2212M CK N\u00bb), \u0438
 * \u0440\u0438\u0441\u043e\u0432\u0430\u0442\u044c \u0435\u0433\u043e \u0444\u043e\u0440\u043c\u0443\u043b\u043e\u0439 \u043d\u0435\u043b\u044c\u0437\u044f. \u0420\u044f\u0434\u043e\u043c \u043b\u0435\u0436\u0438\u0442 \u0432\u044b\u0440\u0435\u0437\u043a\u0430 \u043e\u0440\u0438\u0433\u0438\u043d\u0430\u043b\u0430, \u043e\u043d\u0430 \u0438 \u043d\u0443\u0436\u043d\u0430.
 */
function formulaLooksReliable(latex: string, source: RecognitionSource): boolean {
  const compact = latex.replace(/\s+/g, "");
  if (compact.length === 0 || compact.length > 4000) return false;
  if (/[\u3400-\u9fff\ufffd]/u.test(compact) || compact.includes("$")) return false;
  if (!/[\\^_{}]/.test(compact)) return false;
  if (source !== "ocr") return true;
  const tokens = compact.match(/\\[A-Za-z]+|[A-Za-z]+|\d+|[^A-Za-z\d]/g) ?? [];
  if (tokens.length < 120) return true;
  return new Set(tokens).size / tokens.length >= 0.08;
}

const INLINE_MATH = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$|\\\(([\s\S]+?)\\\)/g;

function renderInlineMath(text: string, terms: string[]): ReactNode {
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(INLINE_MATH)) {
    const start = match.index;
    if (start > cursor) parts.push(highlight(text.slice(cursor, start), terms));
    const source = match[1] ?? match[2] ?? match[3] ?? "";
    // `$$…$$` — выносная формула даже посреди абзаца. В строчном режиме KaTeX
    // отказывается рисовать `\tag{}`, а номер формулы модель ставит именно им.
    const display = match[1] !== undefined;
    try {
      const html = katex.renderToString(source, {
        displayMode: display,
        throwOnError: true,
        strict: "ignore",
        trust: false,
      });
      parts.push(
        <span
          className={display ? "structured-display-math" : "structured-inline-math"}
          dangerouslySetInnerHTML={{ __html: html }}
          key={`${start}-${match[0]}`}
        />,
      );
    } catch {
      parts.push(match[0]);
    }
    cursor = start + match[0].length;
  }
  if (cursor === 0) return highlight(text, terms);
  if (cursor < text.length) parts.push(highlight(text.slice(cursor), terms));
  return parts;
}

function splitMarkdownRow(row: string): string[] {
  const cells: string[] = [];
  let cell = "";
  let escaped = false;
  for (const character of row.trim().replace(/^\|/, "").replace(/\|$/, "")) {
    if (escaped) {
      cell += character;
      escaped = false;
    } else if (character === "\\") {
      escaped = true;
    } else if (character === "|") {
      cells.push(cell.trim());
      cell = "";
    } else {
      cell += character;
    }
  }
  cells.push(cell.trim());
  return cells;
}

export function MarkdownTable({ markdown }: { markdown: string }) {
  // Строка таблицы — любая с вертикальной чертой внутри, а не только та, что с
  // неё начинается: внешняя модель часто пишет «№ | Функция | Первообразная»
  // без крайних чёрточек, и требование ведущей `|` выбрасывало такую таблицу
  // целиком в абзац.
  const lines = markdown.split("\n").filter((line) => line.includes("|"));
  const rows = lines.map(splitMarkdownRow);
  const divider = rows.findIndex(
    (row) => row.length > 1 && row.every((cell) => /^:?-{2,}:?$/.test(cell)),
  );
  if (divider !== 1 || rows.length < 2) return <p>{markdown}</p>;
  const [head] = rows;
  const body = rows.slice(2);
  return (
    <div className="structured-table-scroll" role="region" aria-label="Таблица из документа" tabIndex={0}>
      <table className="structured-table">
        <thead>
          <tr>{head.map((cell, index) => <th scope="col" key={`${index}-${cell}`}>{cell}</th>)}</tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Подсветить в тексте все вхождения любой из словоформ.
 *
 * Формы приходят от поиска, потому что здесь нет морфологии: лемма «миля» не
 * найдёт «Мили» подстрокой, а форма из текста — найдёт. Вхождения ищутся все:
 * раньше подсвечивалось только первое, и счётчик совпадений расходился с тем,
 * что видно на странице.
 */
export function highlight(text: string, terms: string[]) {
  const needles = terms
    .map((term) => term.trim().toLocaleLowerCase("ru"))
    .filter((term) => term.length > 0);
  if (needles.length === 0) return text;
  const haystack = text.toLocaleLowerCase("ru");
  const parts: ReactNode[] = [];
  let cursor = 0;
  while (cursor < text.length) {
    let at = -1;
    let length = 0;
    for (const needle of needles) {
      const found = haystack.indexOf(needle, cursor);
      // Из двух совпадений в одной точке берём длинное: «мили» важнее «мил».
      if (found < 0 || (at >= 0 && (found > at || needle.length <= length))) continue;
      at = found;
      length = needle.length;
    }
    if (at < 0) break;
    if (at > cursor) parts.push(text.slice(cursor, at));
    parts.push(<mark key={at}>{text.slice(at, at + length)}</mark>);
    cursor = at + length;
  }
  if (parts.length === 0) return text;
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}
