import type { AnswerFormPayload, ChatMessageRead } from "../../../api/chat";

export type ParsedPayload =
  | { kind: "none" }
  | { kind: "answer_form"; data: AnswerFormPayload }
  | { kind: "unknown" };

function isAnswerFormPayload(value: unknown): value is AnswerFormPayload {
  const record = value as Record<string, unknown>;
  return (
    Boolean(record) &&
    typeof record.question === "string" &&
    typeof record.ordinal === "number" &&
    typeof record.submitted_at === "string" &&
    typeof record.text === "string"
  );
}

/** Разбор по дискриминанту `payload_kind`. Вердикт, задание и интерактив — итерация 1b/2. */
export function parsePayload(message: ChatMessageRead): ParsedPayload {
  if (message.payload_kind === "answer_form" && isAnswerFormPayload(message.payload)) {
    return { kind: "answer_form", data: message.payload };
  }
  if (message.payload_kind === "none") return { kind: "none" };
  return { kind: "unknown" };
}
