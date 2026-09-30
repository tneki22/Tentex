import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { PageFlowMode } from "./types";

/** Ширина листа задана в CSS сцены; высота слота ленты считается от неё. */
const SHEET_WIDTH = 680;
/** Просвет между листами ленты: в нём же стоит номер страницы. */
const SHEET_GAP = 30;
/** Сколько страниц рисуется за краями окна, чтобы прокрутка не упиралась в пустоту. */
const OVERSCAN = 2;
/** Насколько страниц вперёд греется кэш браузера при листании. */
const PREFETCH_AHEAD = 2;
/** Пауза прокрутки, после которой лента объявляет новую текущую страницу. */
const REPORT_DELAY_MS = 120;
/** Прогрев соседей отложен: он не должен соперничать за сеть с открываемой страницей. */
const PREFETCH_DELAY_MS = 90;

interface PageFlowProps {
  mode: PageFlowMode;
  page: number;
  pageCount: number;
  zoom: number;
  /** Отношение высоты страницы к ширине: по нему считается высота слота ленты. */
  aspect: number;
  imageUrl(page: number): string;
  pageLabel(page: number): string;
  /** Рамки распознанных областей — только у страницы, для которой они загружены. */
  overlay?(page: number): ReactNode;
  onPageChange(page: number): void;
  /** Замер «вписать страницу» идёт по области прокрутки, а не по всей сцене. */
  scrollRef?(node: HTMLDivElement | null): void;
}

/**
 * Растровые страницы материала — постранично или лентой.
 *
 * Обе раскладки живут в одном компоненте не для экономии строк: лист, прогрев
 * соседних страниц и подмена картинки без пустого кадра у них общие, и разъехаться
 * им нельзя. Отличается только то, что лента показывает несколько слотов сразу
 * и сама сообщает, какая страница сейчас перед глазами.
 */
export function PageFlow(props: PageFlowProps) {
  const { mode, page, pageCount, imageUrl, pageLabel, overlay, zoom } = props;
  // Соотношение сторон берётся у первой же загруженной картинки: карточка
  // материала знает его только после разбора, а лента должна считать высоту
  // слотов сразу, иначе полоса прокрутки врёт на неразобранном документе.
  const [measured, setMeasured] = useState<number | null>(null);
  const aspect = measured ?? props.aspect;
  /* Замер берётся у первой загруженной картинки и больше не пересматривается:
     страницы одного документа расходятся на доли пикселя, и подстройка высоты
     слота под каждую новую дёргала бы ленту под курсором. */
  const measure = useCallback((value: number) => {
    setMeasured((current) => current ?? value);
  }, []);

  if (mode === "scroll" && pageCount > 1) {
    return <PageStream {...props} aspect={aspect} onMeasure={measure} />;
  }

  return (
    <div className="viewer-sheet-scroll" ref={props.scrollRef}>
      <PagePrefetch imageUrl={imageUrl} page={page} pageCount={pageCount} />
      <PageSheet
        src={imageUrl(page)}
        alt={pageLabel(page)}
        zoom={zoom}
        overlay={overlay?.(page)}
        onMeasure={measure}
      />
    </div>
  );
}

interface PageStreamProps extends PageFlowProps {
  onMeasure(aspect: number): void;
}

/** Лента: вертикальная прокрутка по всему документу с окном отрисовки. */
function PageStream({
  page,
  pageCount,
  zoom,
  aspect,
  imageUrl,
  pageLabel,
  overlay,
  onPageChange,
  onMeasure,
  scrollRef,
}: PageStreamProps) {
  const viewport = useRef<HTMLDivElement | null>(null);
  const stream = useRef<HTMLDivElement | null>(null);
  const slot = Math.max(160, Math.round(SHEET_WIDTH * zoom * aspect) + SHEET_GAP);
  const [range, setRange] = useState({ first: 1, last: 1 });
  /* Какая страница «сейчас» по мнению ленты. Держится в ref, а не в состоянии:
     на неё смотрит и обработчик прокрутки, и эффект перехода, и лишний рендер
     между ними ничего не добавляет. */
  const current = useRef(page);
  const report = useRef<number | null>(null);
  const announce = useRef(onPageChange);
  announce.current = onPageChange;

  const attach = useCallback((node: HTMLDivElement | null) => {
    viewport.current = node;
    scrollRef?.(node);
  }, [scrollRef]);

  const sync = useCallback(() => {
    const node = viewport.current;
    if (!node) return;
    const top = node.scrollTop;
    const height = node.clientHeight;
    const first = Math.floor(top / slot) + 1;
    const visible = Math.ceil(height / slot);
    // Вызывается на каждое событие прокрутки, поэтому состояние трогается
    // только когда окно действительно сдвинулось: иначе это рендер на кадр.
    setRange((value) => {
      const next = {
        first: Math.max(1, first - OVERSCAN),
        last: Math.min(pageCount, first + visible + OVERSCAN),
      };
      return value.first === next.first && value.last === next.last ? value : next;
    });
    /* Щуп не уходит дальше половины слота: на мелком масштабе окно выше листа,
       и проба «на треть экрана» показывала бы следующую страницу как текущую. */
    const probe = top + Math.min(height * 0.35, slot * 0.5);
    const dominant = Math.min(pageCount, Math.max(1, Math.floor(probe / slot) + 1));
    if (dominant === current.current) return;
    current.current = dominant;
    // Номер страницы тянет за собой текст, разбор и сравнение. Во время броска
    // прокрутки это десятки запросов подряд, поэтому наружу уходит только
    // страница, на которой прокрутка остановилась.
    if (report.current !== null) clearTimeout(report.current);
    report.current = window.setTimeout(() => announce.current(current.current), REPORT_DELAY_MS);
  }, [slot, pageCount]);

  useEffect(() => () => {
    if (report.current !== null) clearTimeout(report.current);
  }, []);

  useEffect(sync, [sync]);

  // Переход извне: поле номера, оглавление, найденный фрагмент.
  useEffect(() => {
    if (page === current.current) return;
    current.current = page;
    const node = viewport.current;
    if (!node) return;
    node.scrollTo({ top: (stream.current?.offsetTop ?? 0) + (page - 1) * slot });
    // Окно отрисовки пересчитывается тут же, а не по событию прокрутки: событие
    // приходит следующим кадром, и до него на месте новой страницы пустота.
    sync();
  }, [page, slot, sync]);

  /* Масштаб меняет высоту слота, а вместе с ней и весь расчёт прокрутки.
     Без переустановки позиции лента уезжает на десятки страниц от читаемой. */
  const previousSlot = useRef(slot);
  useLayoutEffect(() => {
    if (previousSlot.current === slot) return;
    previousSlot.current = slot;
    const node = viewport.current;
    if (!node) return;
    node.scrollTop = (stream.current?.offsetTop ?? 0) + (current.current - 1) * slot;
    sync();
  }, [slot, sync]);

  const visible = useMemo(() => {
    const pages: number[] = [];
    for (let number = range.first; number <= range.last; number += 1) pages.push(number);
    return pages;
  }, [range.first, range.last]);

  return (
    <div className="viewer-sheet-scroll is-stream" ref={attach} onScroll={sync}>
      <PagePrefetch imageUrl={imageUrl} page={range.last} pageCount={pageCount} />
      <div className="viewer-stream" ref={stream} style={{ height: pageCount * slot }}>
        <div
          className="viewer-stream-window"
          style={{ transform: `translateY(${(range.first - 1) * slot}px)` }}
        >
          {visible.map((number) => (
            <div className="viewer-stream-slot" key={number} style={{ height: slot }}>
              <PageSheet
                src={imageUrl(number)}
                alt={pageLabel(number)}
                zoom={zoom}
                fit
                overlay={overlay?.(number)}
                onMeasure={onMeasure}
              />
              <span className="viewer-stream-number" aria-hidden="true">{number}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

interface PageSheetProps {
  src: string;
  alt: string;
  zoom: number;
  /** В ленте высота листа задана слотом, и картинка вписывается в него. */
  fit?: boolean;
  overlay?: ReactNode;
  onMeasure(aspect: number): void;
}

/** Лист с растром страницы: подмена картинки идёт без пустого кадра между ними. */
function PageSheet({ src, alt, zoom, fit = false, overlay, onMeasure }: PageSheetProps) {
  const { painted, pending } = useSettledImage(src);
  return (
    <div
      className={[
        "viewer-sheet",
        fit ? "is-fitted" : "",
        pending ? "is-pending" : "",
      ].filter(Boolean).join(" ")}
      style={{ "--viewer-zoom": zoom } as CSSProperties}
    >
      <img
        src={painted}
        alt={alt}
        decoding="async"
        onLoad={(event) => {
          const image = event.currentTarget;
          if (image.naturalWidth > 0) onMeasure(image.naturalHeight / image.naturalWidth);
        }}
      />
      {overlay}
    </div>
  );
}

/**
 * Адрес, который сейчас можно рисовать.
 *
 * Пока новая страница не готова, на экране остаётся предыдущая: `<img>` со
 * сменённым `src` иначе показывает пустой лист ровно на время загрузки, и
 * именно это читается как рывок при листании. `decode()` ждёт готовности к
 * отрисовке, а не только байтов, поэтому подмена происходит одним кадром.
 */
function useSettledImage(src: string) {
  const [painted, setPainted] = useState(src);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (src === painted) {
      setPending(false);
      return;
    }
    let cancelled = false;
    setPending(true);
    const image = new Image();
    image.src = src;
    const settle = () => {
      if (cancelled) return;
      setPainted(src);
      setPending(false);
    };
    // Отказ decode() — это битая или пропавшая картинка. Показываем её как есть:
    // застрявшая чужая страница врёт сильнее, чем честный сломанный лист.
    void image.decode().then(settle, settle);
    return () => {
      cancelled = true;
    };
  }, [src, painted]);

  return { painted, pending };
}

/**
 * Прогрев соседних страниц.
 *
 * Листают почти всегда подряд, и следующая страница нужна раньше, чем её
 * попросят. Ответ сервера кэшируется на год по адресу с меткой растра, поэтому
 * прогретая страница открывается уже без сети — и назад тоже.
 */
function PagePrefetch({
  imageUrl,
  page,
  pageCount,
}: {
  imageUrl(page: number): string;
  page: number;
  pageCount: number;
}) {
  const held = useRef<HTMLImageElement[]>([]);
  // Адрес приходит новой функцией на каждый рендер родителя. В зависимостях
  // эффекта это перезапускало бы таймер чаще, чем он успевает сработать, и
  // прогрев не случался бы ни разу.
  const build = useRef(imageUrl);
  build.current = imageUrl;

  useEffect(() => {
    const targets: number[] = [];
    for (let step = 1; step <= PREFETCH_AHEAD; step += 1) {
      if (page + step <= pageCount) targets.push(page + step);
    }
    if (page > 1) targets.push(page - 1);
    // Запрос живёт, пока жив объект Image: ссылки держим до следующей страницы,
    // иначе сборщик мусора отменяет прогрев ровно там, где он и нужен.
    const timer = window.setTimeout(() => {
      held.current = targets.map((number) => {
        const image = new Image();
        image.src = build.current(number);
        return image;
      });
    }, PREFETCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [page, pageCount]);

  return null;
}
