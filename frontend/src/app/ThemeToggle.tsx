import { Monitor, Moon, Sun } from "lucide-react";
import { IconButton } from "../components/ui";
import { useTheme } from "../hooks/useTheme";

const LABEL = {
  system: "Тема: как в системе",
  light: "Тема: светлая",
  dark: "Тема: тёмная",
} as const;

export function ThemeToggle() {
  const { preference, cycle } = useTheme();
  const Icon = preference === "light" ? Sun : preference === "dark" ? Moon : Monitor;

  return (
    <IconButton label={LABEL[preference]} onClick={cycle}>
      <Icon size={16} />
    </IconButton>
  );
}
