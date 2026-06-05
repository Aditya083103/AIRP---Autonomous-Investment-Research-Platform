// frontend/src/main.tsx
// Placeholder — replaced with full implementation in Phase 6 (T-053+)
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";

const root = document.getElementById("root");
if (!root) throw new Error("Root element #root not found in index.html");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
