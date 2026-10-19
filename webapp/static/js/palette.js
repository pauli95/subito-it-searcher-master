// Barra comandi (Ctrl+K): filtro "fuzzy", frecce, Invio, Esc.

import { clear, h } from "./ui.js";

function score(label, query) {
  // tutte le lettere della query in ordine; bonus per inizio parola e lettere consecutive
  const l = label.toLowerCase();
  const q = query.toLowerCase().trim();
  if (!q) return 1;
  let pos = 0, s = 0, prev = -2;
  for (const ch of q) {
    if (ch === " ") continue;
    const i = l.indexOf(ch, pos);
    if (i < 0) return 0;
    s += 1 + (i === prev + 1 ? 2 : 0) + (i === 0 || l[i - 1] === " " || l[i - 1] === ":" ? 3 : 0);
    prev = i;
    pos = i + 1;
  }
  return s;
}

export async function openPalette(loadCommands) {
  const root = document.getElementById("palette-root");
  if (root.firstChild) return;
  const previous = document.activeElement;
  const input = h("input", { type: "text", placeholder: "Cosa vuoi fare? (es. nuova, esegui, monitor)", "aria-label": "Comando",
    role: "combobox", "aria-expanded": "true", "aria-controls": "palette-list", autocomplete: "off", spellcheck: "false" });
  const list = h("ul", { class: "palette-list", id: "palette-list", role: "listbox" });
  const box = h("div", { class: "palette-box", role: "dialog", "aria-modal": "true", "aria-label": "Barra comandi" },
    h("div", { class: "palette-input" }, h("span", { class: "gt" }, ">"), input),
    list,
    h("div", { class: "palette-foot" }, h("span", {}, "↑↓ scegli"), h("span", {}, "↵ esegui"), h("span", {}, "esc chiudi")));
  const overlay = h("div", { class: "palette" }, box);
  root.append(overlay);
  input.focus();

  let commands = [];
  let shown = [];
  let active = 0;

  function close() {
    clear(root);
    if (previous && previous.focus) previous.focus();
  }

  function render() {
    shown = commands.map(c => ({ c, s: score(c.label, input.value) })).filter(x => x.s > 0)
      .sort((a, b) => b.s - a.s).slice(0, 40).map(x => x.c);
    active = Math.min(active, Math.max(0, shown.length - 1));
    clear(list);
    if (!shown.length) list.append(h("li", { class: "muted" }, "Nessun comando"));
    shown.forEach((c, i) => {
      const li = h("li", { role: "option", id: `pal-${i}`, "aria-selected": String(i === active),
        onclick: () => exec(c), onmousemove: () => { if (active !== i) { active = i; render(); } } },
        c.label, h("span", { class: "grp" }, c.hint ? `${c.group} · ${c.hint}` : c.group));
      list.append(li);
    });
    input.setAttribute("aria-activedescendant", shown.length ? `pal-${active}` : "");
    list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }

  function exec(c) {
    close();
    c.run();
  }

  input.addEventListener("input", () => { active = 0; render(); });
  input.addEventListener("keydown", e => {
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, shown.length - 1); render(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); render(); }
    else if (e.key === "Enter") { e.preventDefault(); if (shown[active]) exec(shown[active]); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
  });
  overlay.addEventListener("mousedown", e => { if (e.target === overlay) close(); });

  list.append(h("li", { class: "muted" }, "Caricamento…"));
  commands = await loadCommands();
  render();
}
