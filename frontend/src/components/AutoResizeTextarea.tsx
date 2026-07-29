import { useLayoutEffect, useRef } from "react";
import type { TextareaHTMLAttributes } from "react";

type AutoResizeTextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  maxHeight?: number;
};

export function AutoResizeTextarea({
  maxHeight = 360,
  value,
  style,
  ...props
}: AutoResizeTextareaProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "auto";
    const nextHeight = Math.min(element.scrollHeight, maxHeight);
    element.style.height = `${nextHeight}px`;
    element.style.overflowY = element.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [maxHeight, value]);

  return (
    <textarea
      {...props}
      ref={ref}
      value={value}
      rows={1}
      style={{ ...style, resize: "none" }}
    />
  );
}
