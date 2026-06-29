// frontend/src/main.tsx
// Browser entry point: mounts the provider stack and the app into #root.
// The bare CSS import is what pulls Tailwind's compiled layers into the
// bundle; it must run before first paint, hence its position here.

import React from "react";
import ReactDOM from "react-dom/client";

import App from "@/App";
import { AppProviders } from "@/providers/AppProviders";

import "./index.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found in index.html");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <AppProviders>
      <App />
    </AppProviders>
  </React.StrictMode>,
);
