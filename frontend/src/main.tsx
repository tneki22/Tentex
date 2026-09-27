import "@fontsource-variable/onest";
import "katex/dist/katex.min.css";
/* Только структурная тема Crepe (без цвета) — палитру задаёт conspects.css
 * поверх токенов Tentex, поэтому она должна лечь до них и ничего не красить. */
import "@milkdown/crepe/theme/common/style.css";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import { BackgroundProvider } from "./app/Background";
/* Порядок важен: значения → сброс → примитивы кита → доменные виджеты → оболочка */
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/ui-kit.css";
import "./styles/chart.css";
import "./styles/domain.css";
import "./styles/markdown.css";
import "./styles/cards.css";
import "./styles/chat.css";
import "./styles/library-viewer.css";
import "./styles/ocr.css";
import "./styles/retrieval.css";
import "./styles/conspects.css";
import "./styles/preparation.css";
import "./styles/lessons.css";
import "./styles/coverage.css";
import "./styles/storage.css";
import "./styles/system-status.css";
import "./styles/layout.css";
import "./styles/background.css";

const container = document.getElementById("root");
if (!container) throw new Error("Не найден #root");

createRoot(container).render(
  <BrowserRouter>
    <BackgroundProvider><App /></BackgroundProvider>
  </BrowserRouter>,
);
