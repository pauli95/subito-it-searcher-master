// Console log in tempo reale: livelli colorati, filtri, pausa, segui.

import { api } from "../api.js";
import { on } from "../store.js";
import { btn, clear, debounce, fmtPrice, h, logBadge, logTone, panel, parseDate, richMessage } from "../ui.js";

const LEVELS = { info: "INFO", success: "OK", warning: "WARN", error: "ERR" };
const KINDS = { query: "ricerca", new_items: "nuovi", price_drop: "ribassi", sold: "venduti", error: "errori",
  scheduler: "monitor", notify: "notifiche", config: "config", search: "ricerche", system: "sistema" };
const MAX_LINES = 2000;

export default async function log(root) {
  const [initial, searches] = await Promise.all([api.get("/api/events?limit=500"), api.get("/api/searches")]);
  const events = [...initial];
  const names = Object.fromEntries(searches.map(s => [s.id, s.name]));
  const f = { level: "", kind: "", search: "", text: "" };
  let paused = false;
  let follow = true;
  let pending = 0;

  const levelSel = h("select", { class: "select", "aria-label": "Livello" }, h("option", { value: "" }, "tutti i livelli"),
    h("option", { value: "error" }, "solo errori"), h("option", { value: "warning" }, "avvisi ed errori"),
    h("option", { value: "success" }, "solo successi"));
  const kindSel = h("select", { class: "select", "aria-label": "Tipo" }, h("option", { value: "" }, "tutti i tipi"),
    Object.entries(KINDS).map(([k, l]) => h("option", { value: k }, l)));
  const searchSel = h("select", { class: "select", "aria-label": "Ricerca" }, h("option", { value: "" }, "tutte le ricerche"),
    searches.map(s => h("option", { value: s.id }, s.name)));
  const text = h("input", { class: "input", type: "search", placeholder: "grep…", "aria-label": "Cerca nel log" });
  const pauseBtn = btn("pausa", { sm: true });
  const followBtn = btn("segui ↓", { sm: true, kind: "ghost" });
  const clearBtn = btn("pulisci", { sm: true, kind: "ghost" });

  const consoleEl = h("div", { class: "console", role: "log", "aria-live": "off", tabindex: "0" });

  const matches = e => {
    if (f.level === "error" && e.level !== "error") return false;
    if (f.level === "warning" && !["warning", "error"].includes(e.level)) return false;
    if (f.level === "success" && e.level !== "success") return false;
    if (f.kind && e.kind !== f.kind) return false;
    if (f.search && String(e.search_id) !== f.search) return false;
    if (f.text && !e.message.toLowerCase().includes(f.text)) return false;
    return true;
  };

  const line = e => {
    const d = parseDate(e.time);
    const ts = d ? d.toLocaleTimeString("it-IT") : "";
    const items = (e.items || []).slice(0, 5).map(it => h("span", { class: "items" }, "  └ ",
      h("a", { href: it.link, target: "_blank", rel: "noopener noreferrer" }, it.title), ` ${fmtPrice(it.price)}`));
    return h("div", { class: `line ${e.level} ${logTone(e)}`, title: LEVELS[e.level] || e.level },
      h("span", { class: "ts", title: e.time }, ts),
      logBadge(e),
      h("span", { class: "msg" }, richMessage(e.message),
        e.search_id && names[e.search_id] && !e.message.includes(names[e.search_id]) ? h("span", { class: "muted" }, ` · ${names[e.search_id]}`) : null,
        items));
  };

  const scrollEnd = () => { if (follow) consoleEl.scrollTop = consoleEl.scrollHeight; };
  function renderAll() {
    clear(consoleEl);
    const shown = events.filter(matches);
    consoleEl.append(h("div", { class: "prompt-line" },
      `$ tail -f subito.log  # ${shown.length} righe${shown.length !== events.length ? ` di ${events.length}` : ""}`));
    shown.forEach(e => consoleEl.append(line(e)));
    scrollEnd();
  }

  consoleEl.addEventListener("scroll", () => {
    const atEnd = consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 30;
    if (atEnd !== follow) { follow = atEnd; followBtn.setAttribute("aria-pressed", String(follow)); }
  });
  followBtn.onclick = () => { follow = true; scrollEnd(); };
  pauseBtn.onclick = () => {
    paused = !paused;
    pauseBtn.textContent = paused ? "riprendi" : "pausa";
    pauseBtn.classList.toggle("primary", paused);
    if (!paused) { pending = 0; renderAll(); }
  };
  clearBtn.onclick = () => { events.length = 0; renderAll(); };

  const refilter = debounce(renderAll, 120);
  levelSel.addEventListener("change", () => { f.level = levelSel.value; renderAll(); });
  kindSel.addEventListener("change", () => { f.kind = kindSel.value; renderAll(); });
  searchSel.addEventListener("change", () => { f.search = searchSel.value; renderAll(); });
  text.addEventListener("input", () => { f.text = text.value.trim().toLowerCase(); refilter(); });

  root.append(panel("log", { flush: true,
    actions: [levelSel, kindSel, h("span", { class: "hide-mobile" }, searchSel), text, pauseBtn, followBtn, clearBtn],
    body: [consoleEl] }));
  renderAll();

  const off = on("event", e => {
    if (events.some(x => x.id === e.id)) return;
    events.push(e);
    if (events.length > MAX_LINES) events.splice(0, events.length - MAX_LINES);
    if (paused) {
      pending += 1;
      pauseBtn.textContent = `riprendi (${pending})`;
      return;
    }
    if (matches(e)) { consoleEl.append(line(e)); scrollEnd(); }
  });
  return off;
}
