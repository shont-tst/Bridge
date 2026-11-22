import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

// iPhone and iPad: when the keyboard opens, Safari scrolls the page under a sheet, and a text box's cursor is then
// drawn away from the text. Sheets fit the part of the screen the keyboard leaves instead, and the page stays put.
const vv = window.visualViewport;
if (vv) {
  const fit = () => {
    const root = document.documentElement.style;
    root.setProperty("--vv-h", `${vv.height}px`);
    root.setProperty("--vv-top", `${vv.offsetTop}px`);
  };
  vv.addEventListener("resize", fit);
  vv.addEventListener("scroll", fit);
  fit();
}
document.addEventListener("focusin", (e) => {
  const box = e.target as HTMLElement;
  if (!box.matches?.("textarea, input:not([type=checkbox], [type=radio], [type=range])") || !box.closest(".sheet")) return;
  window.setTimeout(() => {
    window.scrollTo(0, 0);
    box.scrollIntoView({ block: "nearest" });
  }, 350); // once the keyboard is up
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
