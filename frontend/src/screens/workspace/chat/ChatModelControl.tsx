import type { AiModelSelection } from "../../../api/ai";
import type { ChatModelOverride } from "../../../api/chat";
import { ChatModelPicker, type ChatModelParameters } from "../../../components/domain";
import { useAiCatalog } from "../../../hooks/useAiCatalog";

interface ChatModelControlProps {
  /** Роль, чьи настройки служат запасным значением: её потолок ответа и «Auto». */
  role: string;
  capabilities: string[];
  value: ChatModelOverride | null;
  parameters: Record<string, unknown>;
  contextBytes?: number;
  messageCount: number;
  disabled?: boolean;
  onChange: (
    value: AiModelSelection | null,
    parameters: ChatModelParameters,
  ) => void | Promise<void>;
}

/**
 * Обвязка выбора модели для чата: каталог и значения роли по умолчанию.
 * Оба чата берут её целиком — расходятся только ролью и требованиями к модели.
 */
export function ChatModelControl({
  role,
  capabilities,
  value,
  parameters,
  contextBytes,
  messageCount,
  disabled,
  onChange,
}: ChatModelControlProps) {
  const catalog = useAiCatalog();
  if (!catalog) return null;

  const roleSetting = catalog.roles.find((item) => item.role === role);
  const roleMaxTokens = Number(roleSetting?.parameters.max_output_tokens);

  return (
    <ChatModelPicker
      providers={catalog.providers}
      models={catalog.models}
      value={value as AiModelSelection | null}
      parameters={parameters as ChatModelParameters}
      capabilities={capabilities}
      contextBytes={contextBytes}
      messageCount={messageCount}
      defaultMaxOutputTokens={Number.isFinite(roleMaxTokens) ? roleMaxTokens : 3000}
      disabled={disabled}
      onChange={onChange}
    />
  );
}
