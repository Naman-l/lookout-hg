import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./fonts.css";
import "./tokens.css";
import "./app.css";
import "./ds/ds.css";
import "./shell.css";
import "./phone.css";
import { App } from "./App";
import { MeProvider } from "./api/useMe";

// A tab left open across a deploy asks for files the server no longer has: reload once onto the new build instead of going blank (LOOKOUT QA #32).
const reloadOnce = () => {
  try { if (sessionStorage.getItem("lookout.reloaded") === location.pathname) return; sessionStorage.setItem("lookout.reloaded", location.pathname); } catch { /* no storage: still reload */ }
  location.reload();
};
window.addEventListener("vite:preloadError", (e) => { e.preventDefault(); reloadOnce(); });
window.addEventListener("error", (e) => { const t = e.target as HTMLElement | null; if (t && (t.tagName === "SCRIPT" || t.tagName === "LINK") && /\/assets\//.test((t as HTMLScriptElement).src || (t as HTMLLinkElement).href || "")) reloadOnce(); }, true);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <MeProvider>
        <App />
      </MeProvider>
    </BrowserRouter>
  </StrictMode>,
);

// Installed use: keep the last-read screens readable when the connection drops. Production builds only.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => { navigator.serviceWorker.register("/sw.js").catch(() => {}); });
}
