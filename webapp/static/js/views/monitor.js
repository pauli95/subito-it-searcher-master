// Monitor: avvio/arresto, stato, impostazioni dello scheduler, salute delle ricerche.

import { api } from "../api.js";
import { on, store } from "../store.js";
import {
  btn, busy, clear, empty, field, fmtAgo, fmtIn, fmtTime, h, led, panel, switchEl, toast,
} from "../ui.js";

const STATE = {
  running: ["ok", "Attivo", "In attesa del prossimo controllo"],
  checking: ["ok pulse", "Controllo in corso", "Sto interrogando subito.it"],
  paused: ["warn", "In pausa", "Fuori dalla fascia oraria impostata"],
  cooldown: ["warn pulse", "Pausa di sicurezza", "subito.it ha bloccato le richieste: riprendo più tardi"],
  stopped: ["", "Fermo", "Avvialo per controllare le ricerche in automatico"],
};

export default async function monitor(root) {
  let health = await api.get("/api/health");
  let status = store.monitor || await api.get("/api/monitor");
  const disposers = [];

  // ---------------------------------------------------------------- stato
  const stateBox = h("div", { class: "stack" });
  const toggle = btn("", {});
  const statePanel = panel("stato", { body: [stateBox] });

  function renderState() {
    const s = status;
    const [cls, label, hint] = STATE[s.state] || ["", s.state, ""];
    const current = s.current ? health.searches.find(x => x.id === s.current)?.name : null;
    clear(toggle).append(s.running ? "■ Ferma monitor" : "▶ Avvia monitor");
    toggle.className = `btn ${s.running ? "danger" : "primary"}`;
    statePanel.classList.toggle("active-glow", s.running);
    clear(stateBox).append(
      h("div", { class: "big-state" }, led(cls), label),
      h("div", { class: "muted" }, current ? `Sto controllando '${current}'` : hint),
      h("dl", { class: "kv" },
        h("dt", {}, "avviato"), h("dd", {}, s.started_at && s.running ? `${fmtTime(s.started_at)} (${fmtAgo(s.started_at)})` : "—"),
        h("dt", {}, "ultimo controllo"), h("dd", {}, s.last_check ? `${fmtTime(s.last_check)} (${fmtAgo(s.last_check)})` : "—"),
        h("dt", {}, "prossimo controllo"), h("dd", {}, s.running && s.next_check ? `${fmtTime(s.next_check)} (${fmtIn(s.next_check)})` : "—"),
        s.cooldown_until ? h("dt", {}, "pausa fino alle") : null, s.cooldown_until ? h("dd", {}, fmtTime(s.cooldown_until)) : null,
        h("dt", {}, "controlli eseguiti"), h("dd", {}, String(s.cycles)),
        h("dt", {}, "fascia attiva ora"), h("dd", {}, s.in_window ? "sì" : "no")),
      h("div", { class: "row" }, toggle));
  }
  toggle.onclick = () => busy(toggle, async () => {
    try { status = store.monitor = await api.post(`/api/monitor/${status.running ? "stop" : "start"}`); renderState(); }
    catch (e) { toast(e.message, "error"); }
  });

  // ---------------------------------------------------------------- impostazioni scheduler
  const settings = (await api.get("/api/settings")).monitor;
  const interval = h("input", { class: "input", type: "number", min: 60, step: 30, value: settings.interval_sec });
  const from = h("input", { class: "input", type: "time", value: settings.active_from });
  const to = h("input", { class: "input", type: "time", value: settings.active_to });
  const jitter = h("input", { class: "input", type: "number", min: 0, max: 120, value: settings.jitter_sec });
  const gap = h("input", { class: "input", type: "number", min: 0, max: 60, value: settings.min_gap_sec });
  const autostart = switchEl(settings.autostart, null, "Avvia il monitor all'apertura dell'app");
  const silent = switchEl(settings.first_run_silent, null, "Primo controllo dopo l'avvio senza notifiche");
  const sync = switchEl(settings.sync !== false, null, "Controlla tutte le ricerche insieme (un unico conto alla rovescia)");
  const save = btn("Salva", { kind: "primary", type: "submit", icon: "check" });
  const form = h("form", { class: "form-grid", novalidate: true },
    h("div", { class: "span-12" }, field("Intervallo predefinito (secondi)", interval, "Per le ricerche senza un intervallo proprio. Minimo 60.")),
    h("div", { class: "span-6" }, field("Attivo dalle", from)),
    h("div", { class: "span-6" }, field("In pausa dalle", to, "Orari uguali = sempre attivo; può passare la mezzanotte")),
    h("div", { class: "span-6" }, field("Jitter massimo (s)", jitter, "Pausa casuale aggiunta tra le richieste")),
    h("div", { class: "span-6" }, field("Pausa minima (s)", gap, "Tra due richieste consecutive")),
    h("div", { class: "span-12" }, autostart.el),
    h("div", { class: "span-12" }, silent.el),
    h("div", { class: "span-12" }, sync.el,
      h("div", { class: "muted small" }, "Le ricerche con un intervallo proprio più lungo, o in pausa per errori, saltano i giri finché non è il loro momento.")),
    h("div", { class: "span-12" }, save));
  form.addEventListener("submit", e => {
    e.preventDefault();
    busy(save, async () => {
      try {
        await api.put("/api/settings/monitor", {
          interval_sec: Number(interval.value), active_from: from.value || "00:00", active_to: to.value || "00:00",
          jitter_sec: Number(jitter.value), min_gap_sec: Number(gap.value),
          autostart: autostart.input.checked, first_run_silent: silent.input.checked, sync: sync.input.checked,
        });
        toast("Impostazioni del monitor salvate", "success");
        status = store.monitor = await api.get("/api/monitor");
        renderState();
      } catch (err) { toast(err.message, "error", 7000); }
    });
  });

  // ---------------------------------------------------------------- salute
  const alertsBox = h("div", { class: "stack" });
  const searchesBody = h("tbody");
  const recentBody = h("tbody");
  function renderHealth() {
    clear(alertsBox);
    alertsBox.classList.toggle("hidden", !health.alerts.length);
    health.alerts.forEach(a => alertsBox.append(h("div", { class: "alert err", role: "alert" }, h("strong", {}, "!"), h("span", {}, a))));
    clear(searchesBody);
    if (!health.searches.length) searchesBody.append(h("tr", {}, h("td", { colspan: 5 }, empty("Nessuna ricerca", ""))));
    for (const s of health.searches) {
      const cls = !s.enabled ? "" : s.consecutive_errors > 2 ? "err" : s.consecutive_errors ? "warn" : s.last_ok_at ? "ok" : "";
      searchesBody.append(h("tr", { class: s.enabled ? "" : "off" },
        h("td", {}, led(cls)),
        h("td", {}, h("a", { href: `#/ricerche/${s.id}` }, s.name),
          s.last_error ? h("div", { class: "error-line" }, s.last_error) : null),
        h("td", { class: "num" }, s.consecutive_errors ? h("span", { class: "badge sold" }, String(s.consecutive_errors)) : "0"),
        h("td", { class: "mono hide-mobile" }, fmtAgo(s.last_ok_at)),
        h("td", { class: "mono" }, s.enabled ? (s.next_due ? fmtIn(s.next_due) : "—") : "disattivata")));
    }
    clear(recentBody);
    if (!health.recent.length) recentBody.append(h("tr", {}, h("td", { colspan: 6, class: "muted" }, "Nessuna risposta registrata da quando il server è partito.")));
    for (const r of health.recent.slice(0, 25)) {
      recentBody.append(h("tr", {},
        h("td", { class: "mono" }, fmtTime(r.time)),
        h("td", {}, r.name),
        h("td", {}, r.ok ? h("span", { class: "badge new" }, "ok") : h("span", { class: "badge sold", title: r.error }, r.error_kind || "errore")),
        h("td", { class: "num" }, r.ok ? String(r.found) : "—"),
        h("td", { class: "num" }, r.ok ? String(r.new) : "—"),
        h("td", { class: "num hide-mobile" }, `${r.duration.toFixed(2)} s`)));
    }
  }

  const table = (head, body) => h("div", { class: "table-wrap" }, h("table", { class: "table" }, h("thead", {}, h("tr", {}, head)), body));
  root.append(alertsBox,
    h("div", { class: "grid grid-2" }, statePanel, panel("scheduler", { body: [form] })),
    panel("salute_ricerche", { flush: true, body: [table([h("th", {}, ""), h("th", {}, "ricerca"), h("th", { class: "num" }, "errori di fila"),
      h("th", { class: "hide-mobile" }, "ultimo ok"), h("th", {}, "prossimo")], searchesBody)] }),
    panel("ultime_risposte", { flush: true, body: [table([h("th", {}, "ora"), h("th", {}, "ricerca"), h("th", {}, "esito"),
      h("th", { class: "num" }, "letti"), h("th", { class: "num" }, "nuovi"), h("th", { class: "num hide-mobile" }, "durata")], recentBody)] }),
    h("p", { class: "muted small" }, "Backoff: dopo un errore il controllo di quella ricerca viene rimandato (2×, 4×… fino a 2 ore). " +
      "Se subito.it risponde 403/429 il monitor si ferma del tutto per 15 minuti, poi 30, 60 e 120."));
  renderState();
  renderHealth();

  disposers.push(on("status", s => { status = s; renderState(); }));
  const refresh = async () => { try { health = await api.get("/api/health"); renderHealth(); renderState(); } catch { /* offline */ } };
  disposers.push(on("event", e => { if (["query", "new_items", "error", "scheduler"].includes(e.kind)) refresh(); }));
  const tick = setInterval(() => { renderState(); }, 1000);
  const slow = setInterval(refresh, 15000);
  return () => { disposers.forEach(d => d()); clearInterval(tick); clearInterval(slow); };
}
