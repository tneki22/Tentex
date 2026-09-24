import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { ChevronDown, Globe } from "lucide-react";
import type { ProgramNodeRead } from "../../api/projects";
import { SourceSearchChat, type SourceSearchChatHandle } from "../workspace/chat/SourceSearchChat";

export interface MaterialsWebSearchHandle {
  /** Раскрыть блок, поставить его по центру экрана и перевести фокус в поле ввода. */
  reveal: () => void;
}

interface MaterialsWebSearchProps {
  projectId: string;
  nodes: ProgramNodeRead[];
  /** Пришли по ссылке `?search=1`: блок открыт сразу. */
  initiallyOpen?: boolean;
  initialTopicId?: string | null;
}

/** Блок «Поиск в интернете» под списком материалов: отделён линией, по умолчанию свёрнут. */
export const MaterialsWebSearch = forwardRef<MaterialsWebSearchHandle, MaterialsWebSearchProps>(
  function MaterialsWebSearch({ projectId, nodes, initiallyOpen = false, initialTopicId = null }, forwardedRef) {
    const [open, setOpen] = useState(initiallyOpen);
    const section = useRef<HTMLElement>(null);
    const chat = useRef<SourceSearchChatHandle>(null);

    /* Чат монтируется только при раскрытии, поэтому прокрутка и фокус ждут кадр,
       в котором блок уже занял своё место. */
    function center() {
      window.requestAnimationFrame(() => {
        section.current?.scrollIntoView({ behavior: "smooth", block: "center" });
        window.setTimeout(() => chat.current?.focus(), 250);
      });
    }

    useImperativeHandle(forwardedRef, () => ({
      reveal: () => {
        setOpen(true);
        center();
      },
    }), []);

    return (
      <section ref={section} className={`materials-web-search${open ? " is-open" : ""}`} aria-label="Поиск в интернете">
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
          <div className="materials-web-search-body">
            <SourceSearchChat ref={chat} projectId={projectId} nodes={nodes} initialTopicId={initialTopicId} />
          </div>
        )}
      </section>
    );
  },
);
