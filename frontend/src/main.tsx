import "@fontsource-variable/manrope";
import "@fontsource-variable/literata";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/ui-kit.css";
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
