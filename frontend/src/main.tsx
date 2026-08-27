import "@fontsource-variable/onest";
import "katex/dist/katex.min.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
/* Порядок важен: значения → сброс → примитивы кита → доменные виджеты → оболочка */
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/ui-kit.css";
import "./styles/domain.css";
import "./styles/lessons.css";
import "./styles/cards.css";
import "./styles/chat.css";
import "./styles/library-viewer.css";
import "./styles/ocr.css";
import "./styles/layout.css";

const container = document.getElementById("root");
if (!container) throw new Error("Не найден #root");

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
