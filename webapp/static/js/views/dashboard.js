// Dashboard: contatori compatti, ultimi annunci (in primo piano, con indicatore di aggiornamento),
// a lato stato del monitor e log in tempo reale (riempie l'altezza disponibile, righe nuove in basso).

import { api, qs } from "../api.js";
import { on, store } from "../store.js";
import {
  btn, busy, clear, debounce, empty, fmtAgo, fmtDateTime, fmtIn, fmtNum, fmtPrice, fmtTime, h, led, logBadge, logTone, panel, richMessage, thumbUrl, toast,
} from "../ui.js";

const STATE = {
  running: ["ok", "Attivo"], checking: ["ok pulse", "Controllo in corso"], paused: ["warn", "In pausa (fascia oraria)"],
  cooldown: ["warn pulse", "In pausa: subito.it sta bloccando"], stopped: ["", "Fermo"],
};
const LATEST = 40;   // il pannello scorre: se ne mostrano di più
const LOG_LINES = 200;   // il pannello scorre: si tengono le ultime 200 righe

export default async function dashboard(root) {
  const data = await api.get("/api/dashboard?days=30");
  const disposers = [];

  // --------------------------------------------------------------- avvisi
  const alerts = h("div", { class: "stack" });
  const renderAlerts = list => {
    clear(alerts);
    alerts.classList.toggle("hidden", !list.length);
    for (const a of list) alerts.append(h("div", { class: "alert err", role: "alert" }, h("strong", {}, "!"), h("span", {}, a)));
  };
  renderAlerts(data.alerts);

  // --------------------------------------------------------------- contatori (una riga compatta)
  const stat = (label, value, href, title) => h(href ? "a" : "span", { class: "ms", href, title },
    h("span", {}, label), h("b", {}, value));
  const stats = h("div", { class: "mini-stats" },
    stat("ricerche attive", `${data.searches_active}/${data.searches_total}`, "#/ricerche"),
    stat("annunci", fmtNum(data.ads_active), "#/annunci", `${fmtNum(data.ads_total)} compresi i venduti`),
    stat("nuovi oggi", fmtNum(data.new_today), null, "Trovati dalle 00:00"),
    stat("venduti", fmtNum(data.sold_total), "#/annunci?status=sold"),
    stat("preferiti", fmtNum(data.favorites), "#/annunci?status=favorite"));

  // --------------------------------------------------------------- ultimi annunci
  const list = h("div", { class: "ads compact", "aria-live": "polite" });
  const activity = h("span", { class: "activity-inline", role: "status" });
  const runAll = btn("Aggiorna ora", { icon: "refresh", sm: true, title: "Esegui subito tutte le ricerche attive" });
  runAll.onclick = () => busy(runAll, async () => {
    try {
      const r = await api.post("/api/run-all");
      if (!r.started) toast(r.detail || "Esecuzione già in corso", "info");
    } catch (e) { toast(e.message, "error"); }
  });
  const latestPanel = panel("ultimi_annunci", {
    flush: true, cls: "scroll",
    actions: [activity, runAll, h("a", { class: "btn sm ghost", href: "#/annunci" }, "tutti")],
    body: [list],
  });

  let known = null;           // id già mostrati: i nuovi lampeggiano
  let lastUpdate = null;
  let justUpdated = false;     // evidenzia "aggiornato hh:mm:ss" dopo un controllo

  const adRow = (a, fresh) => {
    const badges = [];
    if (a.is_new) badges.push(h("span", { class: "badge new" }, "nuovo"));
    if (a.is_drop) badges.push(h("span", { class: "badge drop" }, `ribasso −${fmtNum(a.prev_price - a.price)} €`));
    if (a.sold_at) badges.push(h("span", { class: "badge sold" }, "venduto"));
    return h("article", { class: `ad${a.is_new ? " is-new" : ""}${a.sold_at ? " sold" : ""}${fresh ? " flash" : ""}` },
      a.image ? h("img", { class: "thumb", src: thumbUrl(a.image), alt: "", loading: "lazy", referrerpolicy: "no-referrer",
        onerror: e => e.target.replaceWith(h("div", { class: "thumb" }, "—")) }) : h("div", { class: "thumb" }, "—"),
      h("div", { style: { minWidth: 0 } },
        h("a", { class: "ad-title", href: a.link, target: "_blank", rel: "noopener noreferrer" }, a.title),
        h("div", { class: "ad-meta" },
          h("span", {}, a.location || "—"),
          a.published_at ? h("span", { title: `pubblicato ${fmtDateTime(a.published_at)}` }, `pubblicato ${fmtAgo(a.published_at)}`) : null,
          data.searches_total > 1 ? h("span", {}, a.searches.map(s => s.name).join(", ")) : null),
        badges.length ? h("div", { class: "ad-badges" }, badges) : null),
      h("div", { class: "ad-side" },
        h("div", { class: "price" }, a.is_drop ? h("s", {}, fmtPrice(a.prev_price)) : null, fmtPrice(a.price))));
  };

  function renderActivity() {
    const names = [...store.running.values()].map(r => r.name);
    latestPanel.classList.toggle("refreshing", names.length > 0);
    clear(activity);
    if (names.length) activity.append(h("span", { class: "spinner", "aria-hidden": "true" }), `controllo ${names.map(n => `'${n}'`).join(", ")}…`);
    else if (lastUpdate) activity.append(h("span", { class: `muted${justUpdated ? " updated" : ""}` }, `aggiornato ${fmtTime(lastUpdate)}`));
  }

  async function loadLatest() {
    try {
      const r = await api.get(`/api/ads${qs({ sort: "published_desc", limit: LATEST })}`);
      clear(list);
      if (!r.items.length) {
        list.append(empty("Nessun annuncio ancora", data.searches_total
          ? "Le ricerche non hanno ancora trovato annunci: premi «Aggiorna ora» o avvia il monitor."
          : "Crea la prima ricerca: l'URL di subito.it si compone da solo.",
        data.searches_total ? null : h("a", { class: "btn primary", href: "#/ricerche/nuova" }, "+ Nuova ricerca")));
      }
      for (const a of r.items) list.append(adRow(a, known !== null && !known.has(a.id)));
      known = new Set(r.items.map(a => a.id));
      lastUpdate = new Date();
      renderActivity();
      justUpdated = false;
    } catch (e) {
      clear(list).append(empty("Errore", e.message));
    }
  }
  const reloadLatest = debounce(loadLatest, 400);

  // --------------------------------------------------------------- monitor
  const stateEl = h("div", { class: "big-state" });
  const kv = h("dl", { class: "kv" });
  const toggle = btn("", { kind: "primary" });
  const monitorPanel = panel("monitor", { actions: [h("a", { class: "btn sm ghost", href: "#/monitor" }, "dettagli")],
    body: [h("div", { class: "stack" }, stateEl, kv, h("div", { class: "row" }, toggle))] });

  function renderMonitor(s) {
    if (!s) return;
    const [cls, text] = STATE[s.state] || ["", s.state];
    clear(stateEl).append(led(cls), text);
    clear(kv).append(
      h("dt", {}, "ultimo controllo"), h("dd", {}, s.last_check ? `${fmtTime(s.last_check)} (${fmtAgo(s.last_check)})` : "—"),
      h("dt", {}, "prossimo"), h("dd", {}, s.running && s.next_check ? `${fmtTime(s.next_check)} (${fmtIn(s.next_check)})` : "—"),
      h("dt", {}, "intervallo"), h("dd", {}, `${s.settings.interval_sec} s (predefinito)`),
      h("dt", {}, "fascia"), h("dd", {}, s.settings.active_from === s.settings.active_to ? "sempre attivo" :
        `${s.settings.active_from} → ${s.settings.active_to}`));
    clear(toggle).append(s.running ? "■ Ferma monitor" : "▶ Avvia monitor");
    toggle.className = `btn ${s.running ? "danger" : "primary"}`;
    monitorPanel.classList.toggle("active-glow", s.running);
    toggle.onclick = () => busy(toggle, async () => {
      try { renderMonitor(store.monitor = await api.post(`/api/monitor/${s.running ? "stop" : "start"}`)); }
      catch (e) { toast(e.message, "error"); }
    });
  }
  renderMonitor(data.monitor);
  disposers.push(on("status", renderMonitor));
  const tick = setInterval(() => renderMonitor(store.monitor || data.monitor), 1000);

  // --------------------------------------------------------------- specchietto del log
  const logBox = h("ol", { class: "minilog", role: "log", "aria-label": "Ultimi eventi" });
  const logLine = (e, fresh) => h("li", { class: `ml ${logTone(e)}${fresh ? " fresh" : ""}` },
    h("time", { title: fmtDateTime(e.time) }, fmtTime(e.time)),
    logBadge(e),
    h("span", { class: "msg" }, richMessage(e.message)));
  const liveLed = led(store.live === "on" ? "ok pulse" : "");
  disposers.push(on("live", state => { liveLed.className = `led ${state === "on" ? "ok pulse" : state === "off" ? "err" : "warn"}`; }));
  const logPanel = panel("log", { flush: true, cls: "fill",
    actions: [h("span", { class: "row small muted", style: { gap: "6px" } }, liveLed, "live"),
      h("a", { class: "btn sm ghost", href: "#/log" }, "completo")],
    body: [logBox] });
  const logScroll = () => logPanel.querySelector(".panel-body");
  // segue le righe nuove solo se si è già in fondo (chi sta leggendo più in alto non viene spostato)
  const atBottom = () => { const b = logScroll(); return b.scrollHeight - b.scrollTop - b.clientHeight < 40; };
  const toBottom = () => { const b = logScroll(); b.scrollTop = b.scrollHeight; };
  try {
    const recent = await api.get(`/api/events?limit=${LOG_LINES}`);
    for (const e of recent) logBox.append(logLine(e, false));   // ordine cronologico: il più recente in basso
  } catch { /* il log si riempie con gli eventi live */ }
  if (!logBox.children.length) logBox.append(h("li", { class: "ml empty muted" }, "in attesa di eventi…"));
  disposers.push(on("event", e => {
    const follow = atBottom();
    logBox.querySelector(".empty")?.remove();
    logBox.append(logLine(e, true));
    while (logBox.children.length > LOG_LINES) logBox.firstElementChild.remove();
    if (follow) toBottom();
  }));

  // annunci a sinistra (priorità), monitor e log in una colonna laterale alta quanto lo schermo
  root.append(alerts, stats, h("div", { class: "dash-grid" }, latestPanel,
    h("div", { class: "dash-side" }, monitorPanel, logPanel)));
  toBottom();
  renderActivity();
  await loadLatest();

  // aggiornamenti: indicatore durante i controlli, elenco ricaricato quando finiscono o cambia qualcosa
  disposers.push(on("activity", renderActivity));
  disposers.push(on("event", e => {
    if (e.phase === "end") justUpdated = true;
    if (e.phase === "end" || ["new_items", "price_drop", "sold"].includes(e.kind)) reloadLatest();
  }));
  const relTimes = setInterval(loadLatest, 60000);   // "pubblicato x min fa"
  const refreshAlerts = setInterval(async () => {
    try { renderAlerts((await api.get("/api/health")).alerts); } catch { /* ignorato */ }
  }, 30000);

  return () => {
    disposers.forEach(d => d());
    clearInterval(tick);
    clearInterval(relTimes);
    clearInterval(refreshAlerts);
  };
}
