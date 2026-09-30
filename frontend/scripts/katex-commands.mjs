// Список команд, которые понимает KaTeX фронтенда, для экспорта уроков в LaTeX
// (`backend/app/lessons/export/katex_commands.txt`). Формула с командой вне списка
// в уроке рисуется исходником — и в .tex идёт исходником, а не роняет сборку.
// Запуск после обновления katex: node scripts/katex-commands.mjs > ../backend/app/lessons/export/katex_commands.txt
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const source = readFileSync(require.resolve("katex/dist/katex.mjs"), "utf8");
const names = new Set();
// Имена команд в исходнике — строковые литералы вида "\\frac".
for (const match of source.matchAll(/["']\\\\([A-Za-z]+)\*?["']/g)) names.add(match[1]);
// Окружения `\begin{…}` проверяются по имени окружения, а не команды.
for (const match of source.matchAll(/names:\s*\[([^\]]*)\]/g)) {
  for (const item of match[1].matchAll(/["']([A-Za-z]+\*?)["']/g)) names.add(`env:${item[1]}`);
}
const version = require("katex/package.json").version;
process.stdout.write(`# KaTeX ${version}: команды и окружения (env:…), по одной в строке.\n`);
process.stdout.write([...names].sort().join("\n") + "\n");
