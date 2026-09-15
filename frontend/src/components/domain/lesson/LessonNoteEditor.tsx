import { Crepe } from "@milkdown/crepe";
import { Milkdown, MilkdownProvider, useEditor } from "@milkdown/react";
import { CONSPECT_FEATURE_TEXT } from "../conspectEditorText";

function Editor({ initialMarkdown, onChange }: { initialMarkdown: string; onChange: (value: string) => void }) {
  useEditor((root) => {
    const crepe = new Crepe({ root, defaultValue: initialMarkdown, featureConfigs: CONSPECT_FEATURE_TEXT });
    crepe.on((api) => api.markdownUpdated((_ctx, markdown) => onChange(markdown)));
    return crepe;
    // Crepe неуправляемый: для другого блока родитель монтирует новый редактор.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <Milkdown />;
}

/** Один Crepe на выбранном пояснении; остальные блоки только для чтения. */
export function LessonNoteEditor({ blockId, markdown, onChange }: {
  blockId: string; markdown: string; onChange: (value: string) => void;
}) {
  return <div className="conspect-editor lesson-note-editor" aria-label="Пояснение урока">
    <MilkdownProvider key={blockId}><Editor initialMarkdown={markdown} onChange={onChange} /></MilkdownProvider>
  </div>;
}
