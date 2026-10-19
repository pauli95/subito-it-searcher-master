// Shell dell'applicazione: router, sidebar, tema, scorciatoie, barra comandi.

import { handleAlertEvent } from "./alerts.js";
import { api } from "./api.js";
import { openPalette } from "./palette.js";
import { connectLive, emit, loadMeta, on, refreshCounts, refreshMonitor, store } from "./store.js";
import { clear, download, empty, fmtIn, fmtTime, h, toast } from "./ui.js";

const ROUTES = {
  dashboard: () => import("./views/dashboard.js"),
  ricerche: () => import("./views/searches.js"),
  "ricerche/form": () => import("./views/search-form.js"),
  annunci: () => import("./views/ads.js"),
  monitor: () => import("./views/monitor.js"),
  notifiche: () => import("./views/notifications.js"),
  log: () => import("./views/log.js"),
  impostazioni: () => import("./views/settings.js"),
};

const view = document.getElementById("view");
// viste "a schermo intero": la pagina non scorre, scorrono solo i pannelli (su desktop, vedi app.css)
const FIT = new Set(["dashboard", "annunci"]);
let cleanup = null;
let renderToken = 0;

export function navigate(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "") || "dashboard";
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  const params = Object.fromEntries(new URLSearchParams(query));
  let key = parts[0] || "dashboard";
  if (key === "ricerche" && parts[1]) {
    key = "ricerche/form";
    params.id = parts[1] === "nuova" ? null : parts[1];
  }
  return { key, path: parts.join("/") || "dashboard", params };
}

async function route() {
  const { key, path, params } = parseHash();
  const token = ++renderToken;
  if (cleanup) { try { cleanup(); } catch (e) { console.error(e); } cleanup = null; }
  document.getElementById("prompt-path").textContent = path;
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("active", a.dataset.route === key.split("/")[0]));
  document.getElementById("app").classList.remove("nav-open");
  document.title = `${path} · Subito Searcher`;
  view.classList.toggle("fit", FIT.has(key));
  document.getElementById("app").classList.toggle("fit-mode", FIT.has(key));
  const loader = ROUTES[key];
  clear(view);
  if (!loader) {
    view.append(empty("404", "Pagina inesistente", h("a", { href: "#/dashboard" }, "torna alla dashboard")));
    return;
  }
  view.append(h("div", { class: "panel" }, h("div", { class: "panel-body" }, h("div", { class: "skeleton" }))));
  try {
    const mod = await loader();
    if (token !== renderToken) return;
    clear(view);
    cleanup = (await mod.default(view, params)) || null;
  } catch (e) {
    if (token !== renderToken) return;
    console.error(e);
    clear(view);
    view.append(empty("Errore", e.message || String(e), h("button", { class: "btn", onclick: route }, "Riprova")));
  }
  if (token === renderToken) view.focus({ preventScroll: true });
}

// ------------------------------------------------------------------ LED di stato
function setLed(id, cls, text) {
  const led = document.getElementById(id);
  led.className = `led ${cls}`;
  document.getElementById(`${id}-text`).textContent = text;
}

const MONITOR_LED = {
  running: ["ok", "attivo"], checking: ["ok pulse", "controllo"], paused: ["warn", "in pausa"],
  cooldown: ["warn pulse", "bloccato"], stopped: ["", "fermo"],
};

on("status", s => {
  const [cls, text] = MONITOR_LED[s.state] || ["", s.state];
  setLed("led-monitor", cls, text);
});
on("live", state => {
  setLed("led-live", { on: "ok", connecting: "warn pulse", off: "err" }[state], { on: "on", connecting: "…", off: "off" }[state]);
  if (state === "on") refreshMonitor().catch(() => {});
});
on("counts", ({ newAds, health }) => {
  const badge = document.getElementById("nav-new");
  badge.textContent = newAds;
  badge.classList.toggle("hidden", !newAds);
  if (health.alerts.length) setLed("led-health", "err", "attenzione");
  else if (health.errors_total) setLed("led-health", "warn", `${health.errors_total} errori`);
  else setLed("led-health", "ok", "ok");
});

// ------------------------------------------------------------------ indicatore nella barra in alto
// Sempre visibile, in tutte le sezioni:
//   controllo in corso  -> spinner + "controllo 'TV'…" e linea che scorre sotto la barra
//   appena finito       -> "✓ aggiornato 14:42 · 2 nuovi" evidenziato per qualche secondo
//   altrimenti          -> conto alla rovescia al prossimo controllo (o stato del monitor)
const FLASH_MS = 6000;
const narrow = matchMedia("(max-width: 900px)");
let flash = null;   // {until, new, errors, names:Set, time}

function renderActivity() {
  const el = document.getElementById("activity");
  const iconEl = document.getElementById("activity-icon");
  const text = document.getElementById("activity-text");
  const names = [...store.running.values()].map(r => r.name);
  const s = store.monitor;
  let cls = "";
  let icon = "";
  let msg;
  let short;          // versione per schermi stretti
  if (names.length) {
    cls = "busy";
    icon = h("span", { class: "spinner" });
    msg = `controllo ${names.map(n => `'${n}'`).join(", ")}…`;
    short = "controllo…";
  } else if (flash && Date.now() < flash.until) {
    cls = flash.errors && !flash.new ? "warn" : "done";
    icon = flash.errors && !flash.new ? "!" : "✓";
    const found = flash.new ? `${flash.new} ${flash.new === 1 ? "nuovo" : "nuovi"}` : "nessun nuovo annuncio";
    const parts = [`aggiornato ${fmtTime(flash.time).slice(0, 5)}`, found];
    if (flash.errors) parts.push(`${flash.errors} ${flash.errors === 1 ? "errore" : "errori"}`);
    msg = parts.join(" · ");
    short = flash.new ? found : flash.errors ? "errore" : "aggiornato";
  } else if (!s) {
    msg = short = "…";
  } else if (!s.running) {
    cls = "idle";
    icon = "■";
    msg = "monitor fermo";
    short = "fermo";
  } else if (s.state === "cooldown") {
    cls = "warn";
    icon = "!";
    msg = `pausa di sicurezza fino alle ${fmtTime(s.cooldown_until).slice(0, 5)}`;
    short = "pausa";
  } else if (s.state === "paused") {
    cls = "idle";
    icon = "⏸";
    msg = "in pausa (fascia oraria)";
    short = "in pausa";
  } else {
    icon = "⏱";
    const next = s.next_check && new Date(s.next_check) > Date.now() ? fmtIn(s.next_check) : "a breve";
    msg = `prossimo controllo ${next}` + (s.last_check ? ` · ultimo ${fmtTime(s.last_check).slice(0, 5)}` : "");
    short = next;
  }
  el.title = msg;
  if (narrow.matches) msg = short;
  el.className = `activity ${cls}`;
  document.querySelector(".topbar").classList.toggle("busy", cls === "busy");
  clear(iconEl).append(icon);
  if (text.textContent !== msg) text.textContent = msg;
}

const refreshMonitorSoon = (() => {
  let t;
  return () => { clearTimeout(t); t = setTimeout(() => refreshMonitor().catch(() => {}), 300); };
})();

on("activity", renderActivity);
on("status", renderActivity);
const CYCLE_GAP_MS = 20000;   // tra due ricerche dello stesso giro passano pochi secondi (pausa di cortesia)
on("event", e => {
  // un giro (più ricerche di seguito) produce un solo riepilogo: si azzera solo quando ne inizia uno nuovo
  if (e.phase === "start" && (!flash || Date.now() - flash.time > CYCLE_GAP_MS)) flash = { new: 0, errors: 0, until: 0, time: new Date() };
  if (e.phase !== "end") return;
  if (!flash) flash = { new: 0, errors: 0 };
  flash.new += e.kind === "new_items" ? (e.count || 0) : 0;
  flash.errors += e.kind === "error" ? 1 : 0;
  flash.time = new Date();
  flash.until = Date.now() + FLASH_MS;
  // la classe "done" riparte da capo: l'animazione di conferma si vede a ogni aggiornamento
  const el = document.getElementById("activity");
  el.classList.remove("done", "warn");
  void el.offsetWidth;
  renderActivity();
  document.getElementById("activity-live").textContent = document.getElementById("activity").title;
  refreshMonitorSoon();   // prossimo controllo e ultimo controllo aggiornati subito, non al giro SSE successivo
});
setInterval(renderActivity, 1000);

const refreshCountsSoon = (() => {
  let t;
  return () => { clearTimeout(t); t = setTimeout(() => refreshCounts().catch(() => {}), 600); };
})();

on("event", e => {
  if (["new_items", "price_drop", "sold", "error", "query", "search"].includes(e.kind)) refreshCountsSoon();
  if (e.level === "error" && !location.hash.startsWith("#/log")) {
    store.unreadErrors += 1;
    const b = document.getElementById("nav-err");
    b.textContent = store.unreadErrors;
    b.classList.remove("hidden");
  }
  if (e.kind === "new_items" && !location.hash.startsWith("#/annunci")) toast(e.message, "success", 6000);
  if (e.alert) handleAlertEvent(e);
});

window.addEventListener("hashchange", () => {
  if (location.hash.startsWith("#/log")) {
    store.unreadErrors = 0;
    document.getElementById("nav-err").classList.add("hidden");
  }
  route();
});

// ------------------------------------------------------------------ tema e menu
function currentTheme() {
  return document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
}
export function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch {}
  emit("theme", next);
}
document.getElementById("theme-btn").addEventListener("click", toggleTheme);

const menuBtn = document.getElementById("menu-btn");
menuBtn.addEventListener("click", () => {
  const open = document.getElementById("app").classList.toggle("nav-open");
  menuBtn.setAttribute("aria-expanded", String(open));
});
document.getElementById("app").addEventListener("click", e => {
  const app = document.getElementById("app");
  if (app.classList.contains("nav-open") && !e.target.closest(".sidebar") && !e.target.closest("#menu-btn")) {
    app.classList.remove("nav-open");
  }
});

// ------------------------------------------------------------------ scorciatoie
document.getElementById("palette-btn").addEventListener("click", () => openPalette(commands));
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    openPalette(commands);
    return;
  }
  const typing = e.target.closest("input, textarea, select, [contenteditable]");
  if (typing || e.ctrlKey || e.metaKey || e.altKey || document.querySelector("dialog[open], .palette")) return;
  const go = { d: "#/dashboard", r: "#/ricerche", a: "#/annunci", m: "#/monitor", l: "#/log", n: "#/ricerche/nuova" }[e.key];
  if (go) { e.preventDefault(); navigate(go); }
});

// ------------------------------------------------------------------ comandi (Ctrl+K)
async function runAction(fn, okMsg) {
  try { await fn(); if (okMsg) toast(okMsg, "success"); } catch (e) { toast(e.message, "error"); }
}

export async function commands() {
  const base = [
    { label: "Nuova ricerca", group: "ricerche", run: () => navigate("#/ricerche/nuova") },
    { label: "Esegui tutte le ricerche ora", group: "ricerche", run: () => runAction(() => api.post("/api/run-all"), "Esecuzione avviata: l'esito arriva nel log") },
    { label: "Segna tutti gli annunci come visti", group: "annunci", run: () => runAction(async () => { await api.post("/api/seen"); refreshCounts(); }, "Annunci segnati come visti") },
    { label: "Avvia monitor", group: "monitor", run: () => runAction(async () => emit("status", await api.post("/api/monitor/start")), "Monitor avviato") },
    { label: "Ferma monitor", group: "monitor", run: () => runAction(async () => emit("status", await api.post("/api/monitor/stop")), "Monitor fermato") },
    { label: "Esporta tutti gli annunci (CSV)", group: "annunci", run: () => runAction(async () => download("annunci-subito.csv", await api.blob("/api/ads/export.csv"))) },
    { label: "Esporta le ricerche (JSON)", group: "ricerche", run: () => runAction(async () => download("ricerche-subito.json", await api.blob("/api/searches/export"))) },
    { label: "Crea backup del database", group: "sistema", run: () => runAction(() => api.post("/api/backups"), "Backup creato") },
    { label: "Cambia tema chiaro/scuro", group: "sistema", run: toggleTheme },
    { label: "Vai a: Dashboard", group: "vai", run: () => navigate("#/dashboard"), hint: "d" },
    { label: "Vai a: Ricerche", group: "vai", run: () => navigate("#/ricerche"), hint: "r" },
    { label: "Vai a: Annunci", group: "vai", run: () => navigate("#/annunci"), hint: "a" },
    { label: "Vai a: Annunci nuovi", group: "vai", run: () => navigate("#/annunci?status=new") },
    { label: "Vai a: Preferiti", group: "vai", run: () => navigate("#/annunci?status=favorite") },
    { label: "Vai a: Monitor", group: "vai", run: () => navigate("#/monitor"), hint: "m" },
    { label: "Vai a: Notifiche", group: "vai", run: () => navigate("#/notifiche") },
    { label: "Vai a: Log", group: "vai", run: () => navigate("#/log"), hint: "l" },
    { label: "Vai a: Impostazioni", group: "vai", run: () => navigate("#/impostazioni") },
  ];
  try {
    const searches = await api.get("/api/searches");
    for (const s of searches) {
      base.push({ label: `Esegui ora: ${s.name}`, group: "ricerca", run: () => runAction(() => api.post(`/api/searches/${s.id}/run`), `'${s.name}' eseguita`) });
      base.push({ label: `Modifica: ${s.name}`, group: "ricerca", run: () => navigate(`#/ricerche/${s.id}`) });
      base.push({ label: `Annunci di: ${s.name}`, group: "ricerca", run: () => navigate(`#/annunci?search=${s.id}`) });
    }
  } catch { /* la palette funziona anche senza l'elenco */ }
  return base;
}

// ------------------------------------------------------------------ errori imprevisti: visibili, non silenziosi
window.addEventListener("error", e => toast(`Errore dell'interfaccia: ${e.message}`, "error", 10000));
window.addEventListener("unhandledrejection", e => toast(`Errore dell'interfaccia: ${e.reason?.message || e.reason}`, "error", 10000));

// ------------------------------------------------------------------ avvio
(async function init() {
  try {
    const meta = await loadMeta();
    document.getElementById("version").textContent = `v${meta.version}`;
  } catch (e) {
    toast(e.message, "error", 0);
  }
  connectLive();
  refreshMonitor().catch(() => {});
  refreshCounts().catch(() => {});
  setInterval(() => refreshCounts().catch(() => {}), 60000);
  route();
})();
