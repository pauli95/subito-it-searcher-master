// Utilità di interfaccia: costruzione DOM sicura (mai innerHTML con dati), toast, dialog, formattazione.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "html") throw new Error("html non consentito");
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function clear(el) { while (el.firstChild) el.firstChild.remove(); return el; }

// icone SVG costruite via DOM (percorsi statici)
const ICONS = {
  play: "M7 4v16l13-8z",
  stop: "M6 6h12v12H6z",
  plus: "M12 5v14M5 12h14",
  edit: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  trash: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6",
  ext: "M14 3h7v7M10 14 21 3M21 14v7H3V3h7",
  star: "m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
  eyeoff: "M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6 0 10 7 10 7a17 17 0 0 1-3.2 3.9M6.6 6.6C3.8 8.4 2 12 2 12s4 7 10 7a9.6 9.6 0 0 0 4.4-1.1",
  check: "M4 12l5 5L20 6",
  refresh: "M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5",
  download: "M12 3v12M7 10l5 5 5-5M4 21h16",
  upload: "M12 21V9M7 14l5-5 5 5M4 3h16",
  x: "M6 6l12 12M18 6 6 18",
  chart: "M4 20V10M10 20V4M16 20v-6M22 20H2",
  power: "M12 2v10M18.4 6.6a9 9 0 1 1-12.8 0",
};

export function icon(name) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  // dimensione predefinita = corpo del testo; .btn e .nav la ridefiniscono in CSS
  svg.setAttribute("width", "1em");
  svg.setAttribute("height", "1em");
  svg.setAttribute("class", "ico");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", ICONS[name] || "");
  svg.append(path);
  return svg;
}

export function btn(label, opts = {}) {
  const { kind = "", icon: ic, onclick, title, type = "button", sm = false, disabled = false } = opts;
  const cls = ["btn", kind, sm ? "sm" : "", !label && ic ? "icon" : ""].filter(Boolean).join(" ");
  return h("button", { class: cls, type, title: title || null, "aria-label": !label ? title : null, onclick, disabled },
    ic ? icon(ic) : null, label || null);
}

/** Esegue fn mostrando lo stato di attesa sul bottone. */
export async function busy(button, fn) {
  button.classList.add("busy");
  button.disabled = true;
  try { return await fn(); } finally { button.classList.remove("busy"); button.disabled = false; }
}

export function panel(title, { actions = [], body = [], flush = false, cls = "" } = {}) {
  return h("section", { class: `panel ${cls}` },
    h("div", { class: "panel-head" }, h("h2", {}, title), actions.length ? h("div", { class: "actions" }, actions) : null),
    h("div", { class: `panel-body${flush ? " flush" : ""}` }, body));
}

export function field(label, control, help, extraClass = "") {
  const id = control.id || `f-${Math.random().toString(36).slice(2, 9)}`;
  control.id = id;
  return h("div", { class: `field ${extraClass}` },
    h("label", { for: id }, label), control, help ? h("div", { class: "help" }, help) : null);
}

export function switchEl(checked, onchange, label) {
  const input = h("input", { type: "checkbox", role: "switch" });
  input.checked = !!checked;
  if (onchange) input.addEventListener("change", () => onchange(input.checked, input));
  return { el: h("label", { class: "switch" }, input, h("span", { class: "track" }), label ? h("span", {}, label) : null), input };
}

export function led(state) {
  return h("span", { class: `led ${state || ""}` });
}

export function empty(title, text, action) {
  return h("div", { class: "empty" }, h("div", { class: "big" }, title), text ? h("div", {}, text) : null,
    action ? h("div", { style: { marginTop: "14px" } }, action) : null);
}

// ------------------------------------------------------------------ toast
export function toast(message, type = "info", ms = 4500) {
  const close = btn("", { icon: "x", kind: "ghost", sm: true, title: "Chiudi" });
  const el = h("div", { class: `toast ${type}`, role: type === "error" ? "alert" : "status" }, h("div", {}, message), close);
  close.classList.add("toast-close");
  close.onclick = () => el.remove();
  document.getElementById("toasts").append(el);
  if (ms) setTimeout(() => el.remove(), ms);
}

// ------------------------------------------------------------------ dialog
export function dialog(title, body, actions, { wide = false } = {}) {
  const dlg = h("dialog", { class: wide ? "wide" : "" },
    h("div", { class: "panel-head" }, h("h2", {}, title)),
    h("div", { class: "dialog-body" }, body),
    actions ? h("div", { class: "dialog-actions" }, actions) : null);
  document.body.append(dlg);
  dlg.addEventListener("close", () => dlg.remove());
  dlg.showModal();
  return dlg;
}

export function confirmDialog(title, text, okLabel = "Conferma", danger = true) {
  return new Promise(resolve => {
    let result = false;
    const ok = btn(okLabel, { kind: danger ? "danger" : "primary" });
    const cancel = btn("Annulla", { kind: "ghost" });
    const dlg = dialog(title, h("p", { style: { margin: 0 } }, text), [cancel, ok]);
    ok.onclick = () => { result = true; dlg.close(); };
    cancel.onclick = () => dlg.close();
    dlg.addEventListener("close", () => resolve(result));
    cancel.focus();
  });
}

// ------------------------------------------------------------------ log: colore in base al contenuto
/** Classe CSS di una riga di log: prima la gravità, poi il tipo di evento. */
export function logTone(e) {
  if (e.level === "error") return "t-err";
  if (e.level === "warning") return "t-warn";
  return {
    new_items: "t-new", price_drop: "t-drop", sold: "t-sold", scheduler: "t-mon", notify: "t-notify",
    query: e.phase === "start" ? "t-run" : "t-quiet", search: "t-search", config: "t-sys", system: "t-sys",
  }[e.kind] || "t-sys";
}

const LOG_BADGES = {
  "t-new": ["✚", "nuovi"], "t-drop": ["↓", "ribasso"], "t-sold": ["✕", "venduto"], "t-run": ["⟳", "ricerca"],
  "t-quiet": ["✓", "invariato"], "t-mon": ["⏱", "monitor"], "t-notify": ["✉", "notifica"], "t-search": ["★", "ricerche"],
  "t-warn": ["⚠", "avviso"], "t-err": ["✖", "errore"],
};

/** Badge colorato con icona e nome del tipo di evento (es. "✚ NUOVI"). */
export function logBadge(e) {
  const tone = logTone(e);
  const [ico, label] = LOG_BADGES[tone] || ["•", { config: "config", system: "sistema" }[e.kind] || e.kind];
  return h("span", { class: `lb ${tone}` }, h("span", { "aria-hidden": "true" }, ico), label);
}

/** Messaggio del log con evidenziati nomi tra apici, prezzi e numeri. */
export function richMessage(text) {
  const out = [];
  const re = /('[^']{1,80}')|(€\s?\d[\d.]*|\d[\d.]*\s?€)|(\b\d+(?:[.,]\d+)?\b)/g;
  let last = 0;
  for (const m of String(text).matchAll(re)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(h("span", { class: m[1] ? "hl-name" : m[2] ? "hl-eur" : "hl-num" }, m[0]));
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}

// ------------------------------------------------------------------ formattazione
const dtf = new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
const tf = new Intl.DateTimeFormat("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const df = new Intl.DateTimeFormat("it-IT", { day: "2-digit", month: "short" });

export function parseDate(v) {
  if (!v) return null;
  if (v instanceof Date) return isNaN(v) ? null : v;
  const d = new Date(String(v).replace(" ", "T"));
  return isNaN(d) ? null : d;
}
export const fmtDateTime = v => { const d = parseDate(v); return d ? dtf.format(d) : "—"; };
export const fmtTime = v => { const d = parseDate(v); return d ? tf.format(d) : "—"; };
export const fmtDay = v => { const d = parseDate(v); return d ? df.format(d) : "—"; };

export function fmtAgo(v) {
  const d = parseDate(v);
  if (!d) return "mai";
  const s = Math.round((Date.now() - d) / 1000);
  if (s < 0) return fmtIn(v);
  if (s < 45) return "adesso";
  if (s < 3600) return `${Math.round(s / 60)} min fa`;
  if (s < 86400) return `${Math.floor(s / 3600)} h fa`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} g fa`;
  return fmtDateTime(v);
}

export function fmtIn(v) {
  const d = parseDate(v);
  if (!d) return "—";
  const s = Math.max(0, Math.round((d - Date.now()) / 1000));
  if (s < 60) return `tra ${s} s`;
  if (s < 3600) return `tra ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  return `alle ${tf.format(d).slice(0, 5)}`;
}

const nf = new Intl.NumberFormat("it-IT");
export const fmtNum = n => (n === null || n === undefined ? "—" : nf.format(n));
export const fmtPrice = p => (p === null || p === undefined ? "n.d." : `€ ${nf.format(p)}`);
export function fmtInterval(sec) {
  if (!sec) return "—";
  if (sec % 3600 === 0) return `${sec / 3600} h`;
  if (sec % 60 === 0) return `${sec / 60} min`;
  return `${sec} s`;
}

export function debounce(fn, ms = 250) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast("Copiato negli appunti", "success", 2000); }
  catch { toast("Copia non riuscita: seleziona e copia a mano", "warning"); }
}

/** Miniatura subito: cdnBaseUrl + rule (verificato: senza rule il CDN risponde 400). */
export function thumbUrl(base) {
  return base ? `${base}?rule=vertical-mini-card-2x-auto` : null;
}

export function download(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
