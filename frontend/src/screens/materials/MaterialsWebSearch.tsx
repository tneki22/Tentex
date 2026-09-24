import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { ChevronDown, Globe } from "lucide-react";
import type { ProgramNodeRead } from "../../api/projects";
import { SourceSearchChat } from "../workspace/chat/SourceSearchChat";

export interface MaterialsWebSearchHandle {
  /** Раскрыть блок, поставить его по центру экрана и перевести фокус в поле ввода. */
  reveal: () => void;
}

interface MaterialsWebSearchProps {
  projectId: string;
  nodes: ProgramNodeRead[];
  /** Пришли из подбора к теме: область чата — эта тема. */
  initialTopicId?: string | null;
}

/** Блок «Поиск в интернете» под списком материалов: отделён линией, по умолчанию свёрнут. */
export const MaterialsWebSearch = forwardRef<MaterialsWebSearchHandle, MaterialsWebSearchProps>(
  function MaterialsWebSearch({ projectId, nodes, initialTopicId = null }, forwardedRef) {
    const [open, setOpen] = useState(false);
    // Каждый вызов reveal — новый запрос прокрутки и фокуса, даже если блок уже открыт.
    const [revealRequest, setRevealRequest] = useState(0);
    const body = useRef<HTMLDivElement>(null);

    useImperativeHandle(forwardedRef, () => ({
      reveal: () => {
        setOpen(true);
        setRevealRequest((value) => value + 1);
      },
    }), []);

    /* Тело чата почти во весь экран и фиксированной высоты: по центру ставится оно,
       а не весь блок с заголовком, — и сразу после раскрытия, без ожидания переписки. */
    useEffect(() => {
      if (revealRequest > 0) body.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, [revealRequest]);

    return (
      <section className={`materials-web-search${open ? " is-open" : ""}`} aria-label="Поиск в интернете">
        <button
          type="button"
          className="materials-web-search-toggle"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <Globe size={16} aria-hidden="true" />
          <span>
            <strong>Поиск в интернете</strong>
            <small>Учебники, статьи и видео по программе — найденное можно скачать и добавить сюда</small>
          </span>
          <span className="materials-web-search-state">{open ? "Свернуть" : "Развернуть"}</span>
          <ChevronDown className="materials-web-search-chevron" size={16} aria-hidden="true" />
        </button>
        {open && (
          <div ref={body} className="materials-web-search-body">
            <SourceSearchChat
              projectId={projectId}
              nodes={nodes}
              initialTopicId={initialTopicId}
              focusRequest={revealRequest}
            />
          </div>
        )}
      </section>
    );
  },
);
