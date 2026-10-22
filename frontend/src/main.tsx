import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ToastHost } from "./components/ui";
import "./styles/fonts.css";
import "./styles/tokens.css";
import "./styles/base.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastHost><App /></ToastHost>
  </StrictMode>,
);
