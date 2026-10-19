// Elenco ricerche: stato, riepilogo, conteggi, azioni rapide, export/import.

import { api } from "../api.js";
import { navigate } from "../app.js";
import { on, refreshCounts, store } from "../store.js";
import {
  btn, busy, clear, confirmDialog, debounce, download, empty, fmtAgo, fmtIn, fmtInterval, fmtNum, h, icon, led, panel,
  switchEl, toast,
} from "../ui.js";

export default async function searches(root) {
  let list = [];
  let filter = "";
  const tbody = h("tbody");
  const body = h("div", {});
  const search = h("input", { class: "input", type: "search", placeholder: "filtra per nome…", "aria-label": "Filtra ricerche",
    oninput: debounce(e => { filter = e.target.value.toLowerCase(); render(); }, 150) });

  const fileInput = h("input", { type: "file", accept: "application/json,.json", class: "hidden" });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    fileInput.value = "";
    if (!file) return;
    try {
      const out = await api.post("/api/searches/import", JSON.parse(await file.text()));
      toast(`Importate ${out.created.length} ricerche` + (out.errors.length ? `, ${out.errors.length} scartate: ${out.errors.join("; ")}` : ""),
        out.errors.length ? "warning" : "success", 8000);
      await load();
    } catch (e) { toast(e instanceof SyntaxError ? "File JSON non valido" : e.message, "error"); }
  });

  const runAll = btn("Esegui tutte", { icon: "refresh" });
  runAll.onclick = () => busy(runAll, async () => {
    try { await api.post("/api/run-all"); toast("Esecuzione avviata: segui l'esito nel log", "info"); }
    catch (e) { toast(e.message, "error"); }
  });

  const actions = [
    search,
    btn("Esporta", { icon: "download", sm: true, kind: "ghost", onclick: async () => {
      try { download("ricerche-subito.json", await api.blob("/api/searches/export")); } catch (e) { toast(e.message, "error"); }
    } }),
    btn("Importa", { icon: "upload", sm: true, kind: "ghost", onclick: () => fileInput.click() }),
    runAll,
    h("a", { class: "btn primary", href: "#/ricerche/nuova" }, icon("plus"), "Nuova ricerca"),
  ];
  root.append(panel("ricerche", { flush: true, actions, body: [body, fileInput] }));

  function statusLed(s) {
    if (!s.enabled) return led("");
    if (s.consecutive_errors) return led(s.consecutive_errors > 2 ? "err" : "warn");
    return led(s.last_ok_at ? "ok" : "");
  }

  function row(s) {
    const sw = switchEl(s.enabled, async (checked, input) => {
      try { Object.assign(s, await api.post(`/api/searches/${s.id}/enabled`, { enabled: checked })); render(); }
      catch (e) { input.checked = !checked; toast(e.message, "error"); }
    });
    sw.input.setAttribute("aria-label", `Attiva ${s.name}`);

    const run = btn("", { icon: "play", sm: true, kind: "ghost", title: "Esegui ora" });
    run.onclick = () => busy(run, async () => {
      try {
        const r = await api.post(`/api/searches/${s.id}/run`);
        toast(r.ok ? `'${s.name}': ${r.found} letti, ${r.new} nuovi` : `'${s.name}': ${r.error}`, r.ok ? (r.new ? "success" : "info") : "error");
        await load();
        refreshCounts();
      } catch (e) { toast(e.message, "error"); }
    });

    const summary = s.summary.mode === "params"
      ? [s.summary.keywords ? `"${s.summary.keywords}"` : "senza parole chiave", s.summary.location, s.summary.category]
      : ["solo URL"];
    const filters = [];
    if (s.min_price !== null || s.max_price !== null) filters.push(`€ ${s.min_price ?? 0}–${s.max_price ?? "∞"}`);
    if (s.exclude_words.length) filters.push(`escludi: ${s.exclude_words.join(", ")}`);
    if (s.active_from) filters.push(`${s.active_from}→${s.active_to}`);

    return h("tr", { class: s.enabled ? "" : "off" },
      h("td", { style: { width: "28px" } }, statusLed(s)),
      h("td", {},
        h("a", { class: "search-name", href: `#/ricerche/${s.id}` }, s.name),
        h("div", { class: "search-sub" }, summary.filter(Boolean).map(t => h("span", {}, t)), filters.map(t => h("span", { class: "mono" }, t))),
        s.last_error ? h("div", { class: "error-line" }, `⚠ ${s.last_error}` + (s.consecutive_errors > 1 ? ` (${s.consecutive_errors} di fila)` : "")) : null),
      h("td", { class: "num hide-mobile" }, s.interval_sec ? fmtInterval(s.interval_sec) : `${fmtInterval(store.monitor?.settings?.interval_sec)} *`),
      h("td", { class: "mono hide-mobile nowrap" }, fmtAgo(s.last_run_at),
        h("div", { class: "muted small" }, s.next_due ? `prossimo ${fmtIn(s.next_due)}` : "")),
      h("td", { class: "num" },
        h("a", { href: `#/annunci?search=${s.id}` }, fmtNum(s.stats.active)),
        s.stats.new ? h("div", {}, h("a", { class: "badge new", href: `#/annunci?search=${s.id}&status=new` }, `${s.stats.new} nuovi`)) : null),
      h("td", { class: "nowrap" }, h("div", { class: "row", style: { flexWrap: "nowrap", gap: "2px" } },
        sw.el, run,
        btn("", { icon: "edit", sm: true, kind: "ghost", title: "Modifica", onclick: () => navigate(`#/ricerche/${s.id}`) }),
        btn("", { icon: "copy", sm: true, kind: "ghost", title: "Duplica", onclick: async () => {
          try { const d = await api.post(`/api/searches/${s.id}/duplicate`); toast(`Creata '${d.name}' (disattivata)`, "success"); await load(); }
          catch (e) { toast(e.message, "error"); }
        } }),
        btn("", { icon: "trash", sm: true, kind: "ghost", title: "Elimina", onclick: async () => {
          const ok = await confirmDialog(`Eliminare '${s.name}'?`,
            `La ricerca e i suoi ${s.stats.total} annunci verranno eliminati (i preferiti e gli annunci trovati anche da altre ricerche restano). L'operazione non si può annullare.`,
            "Elimina");
          if (!ok) return;
          try { await api.del(`/api/searches/${s.id}`); toast(`'${s.name}' eliminata`); await load(); refreshCounts(); }
          catch (e) { toast(e.message, "error"); }
        } }))));
  }

  function render() {
    clear(body);
    if (!list.length) {
      body.append(empty("Nessuna ricerca", "Una ricerca controlla periodicamente subito.it e ti avvisa dei nuovi annunci.",
        h("a", { class: "btn primary", href: "#/ricerche/nuova" }, "+ Crea la prima ricerca")));
      return;
    }
    const shown = list.filter(s => !filter || s.name.toLowerCase().includes(filter));
    clear(tbody).append(...shown.map(row));
    body.append(h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", {}, h("span", { class: "sr-only" }, "stato")), h("th", {}, "ricerca"),
        h("th", { class: "num hide-mobile" }, "intervallo"), h("th", { class: "hide-mobile" }, "ultimo controllo"),
        h("th", { class: "num" }, "annunci"), h("th", {}, "azioni"))),
      tbody)),
    h("div", { class: "pager" }, `${shown.length} di ${list.length} ricerche · * intervallo predefinito delle impostazioni`));
  }

  async function load() {
    list = await api.get("/api/searches");
    render();
  }
  await load();

  const reload = debounce(() => load().catch(() => {}), 800);
  const off = on("event", e => { if (["query", "new_items", "error", "search"].includes(e.kind)) reload(); });
  const timer = setInterval(render, 15000); // aggiorna "x min fa" / "tra x"
  return () => { off(); clearInterval(timer); };
}
