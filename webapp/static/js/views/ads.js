// Annunci (deduplicati): filtri, badge NUOVO / RIBASSO / VENDUTO, preferiti, nascosti,
// esportazione CSV, storico prezzi con grafico. A destra le statistiche sugli annunci filtrati:
// prezzi (minimo, mediana, media, massimo, fascia tipica) e frequenza di pubblicazione.

import { api, qs } from "../api.js";
import { barChart, priceChart } from "../charts.js";
import { on, refreshCounts } from "../store.js";
import {
  btn, busy, clear, debounce, dialog, download, empty, field, fmtAgo, fmtDateTime, fmtNum, fmtPrice, h, icon, panel,
  thumbUrl, toast,
} from "../ui.js";

const STATUSES = [["", "tutti"], ["new", "nuovi"], ["drop", "ribassi"], ["sold", "venduti"], ["favorite", "preferiti"], ["hidden", "nascosti"]];
const SORTS = [["published_desc", "Ultimi pubblicati"], ["found_desc", "Trovati di recente"], ["found_asc", "Trovati meno di recente"],
  ["price_asc", "Prezzo crescente"], ["price_desc", "Prezzo decrescente"]];
const PAGE = 50;

export default async function ads(root, params) {
  const searches = await api.get("/api/searches");
  const f = {
    search_id: params.search || "", q: params.q || "", status: params.status || "", sort: params.sort || "published_desc",
    min_price: "", max_price: "", shipping: false, offset: 0,
  };

  // ---------------------------------------------------------------- filtri
  const searchSel = h("select", { class: "select" }, h("option", { value: "" }, "Tutte le ricerche"),
    searches.map(s => h("option", { value: s.id }, s.name)));
  searchSel.value = f.search_id;
  const text = h("input", { class: "input", type: "search", placeholder: "titolo o località…", value: f.q });
  const minP = h("input", { class: "input", type: "number", min: 0, placeholder: "€ min", inputmode: "numeric" });
  const maxP = h("input", { class: "input", type: "number", min: 0, placeholder: "€ max", inputmode: "numeric" });
  const sortSel = h("select", { class: "select" }, SORTS.map(([v, l]) => h("option", { value: v }, l)));
  sortSel.value = f.sort;
  const ship = h("input", { type: "checkbox" });
  const chips = h("div", { class: "chips", role: "group", "aria-label": "Stato" });
  const paintChips = () => {
    clear(chips);
    for (const [v, l] of STATUSES) {
      chips.append(h("button", { type: "button", class: "chip", "aria-pressed": String(f.status === v),
        onclick: () => { f.status = v; f.offset = 0; paintChips(); load(); } }, l));
    }
  };
  paintChips();

  const reloadSoon = debounce(() => { f.offset = 0; load(); }, 250);
  searchSel.addEventListener("change", () => { f.search_id = searchSel.value; reloadSoon(); });
  text.addEventListener("input", () => { f.q = text.value.trim(); reloadSoon(); });
  minP.addEventListener("input", () => { f.min_price = minP.value; reloadSoon(); });
  maxP.addEventListener("input", () => { f.max_price = maxP.value; reloadSoon(); });
  sortSel.addEventListener("change", () => { f.sort = sortSel.value; reloadSoon(); });
  ship.addEventListener("change", () => { f.shipping = ship.checked; reloadSoon(); });

  const filters = h("div", { class: "filters" },
    field("Ricerca", searchSel),
    field("Testo", text, null, "grow"),
    field("Prezzo min", minP), field("Prezzo max", maxP),
    field("Ordina per", sortSel),
    h("label", { class: "check", style: { paddingBottom: "8px" } }, ship, "Con spedizione"),
    h("div", { style: { flexBasis: "100%" } }, chips));

  const statsBody = h("div", { class: "stats-body" });
  const list = h("div", { class: "ads", "aria-live": "polite" });
  const pager = h("div", { class: "pager" });
  const seenBtn = btn("Segna come visti", { icon: "check", sm: true });
  seenBtn.onclick = () => busy(seenBtn, async () => {
    try {
      await api.post(f.search_id ? `/api/searches/${f.search_id}/seen` : "/api/seen");
      toast("Annunci segnati come visti", "success");
      refreshCounts();
      load();
    } catch (e) { toast(e.message, "error"); }
  });
  const csvBtn = btn("CSV", { icon: "download", sm: true, kind: "ghost", title: "Esporta in CSV gli annunci filtrati (tutte le pagine)" });
  csvBtn.onclick = () => busy(csvBtn, async () => {
    try {
      const d = new Date();
      const pad = n => String(n).padStart(2, "0");
      const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
      download(`annunci-subito-${stamp}.csv`, await api.blob(`/api/ads/export.csv${filterQuery({ sort: f.sort })}`));
    } catch (e) { toast(e.message, "error"); }
  });
  // filtri e paginazione restano fermi, scorre solo l'elenco; statistiche nella colonna a destra
  const scope = h("span", { class: "muted small mono" });
  root.append(h("div", { class: "ads-layout" },
    panel("annunci", { flush: true, cls: "ads-panel", actions: [csvBtn, seenBtn], body: [filters, list, pager] }),
    panel("statistiche", { flush: true, cls: "scroll stats-panel", actions: [scope], body: [statsBody] })));
  const toTop = () => { list.scrollTop = 0; root.scrollIntoView({ block: "start" }); };

  function filterQuery(extra = {}) {
    return qs({ search_id: f.search_id, q: f.q, status: f.status, min_price: f.min_price,
      max_price: f.max_price, shipping: f.shipping ? "true" : "", ...extra });
  }

  // ---------------------------------------------------------------- statistiche (colonna a destra)
  let disposeChart = () => {};
  const round = v => (v === null || v === undefined ? null : Math.round(v));
  const fmtRate = v => (v === null ? "—" : v.toLocaleString("it-IT", { maximumFractionDigits: 1 }));
  const spanText = days => (days >= 1 ? `${fmtRate(Math.round(days * 10) / 10)} giorni` : `${Math.max(1, Math.round(days * 24))} ore`);

  function priceTile(cls, label, value, hint) {
    return h("div", { class: `pt ${cls}`, title: hint || "" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value));
  }

  /** Barra min–max con la fascia tipica (metà centrale degli annunci), la mediana e la media. */
  function rangeBar(st) {
    const span = st.max - st.min || 1;
    const pos = v => `${((v - st.min) / span) * 100}%`;
    return h("div", { class: "range" },
      h("div", { class: "range-track" },
        h("div", { class: "range-box", style: { left: pos(st.p25), width: `calc(${pos(st.p75)} - ${pos(st.p25)})` } }),
        h("div", { class: "range-median", style: { left: pos(st.median) }, title: `mediana ${fmtPrice(round(st.median))}` }),
        h("div", { class: "range-mean", style: { left: pos(st.mean) }, title: `media ${fmtPrice(round(st.mean))}` })),
      h("div", { class: "range-labels" }, h("span", {}, fmtPrice(st.min)), h("span", {}, fmtPrice(st.max))),
      h("p", { class: "range-text" }, "Metà degli annunci costa tra ",
        h("strong", {}, fmtPrice(round(st.p25))), " e ", h("strong", {}, fmtPrice(round(st.p75))), "."),
      h("div", { class: "range-legend" },
        h("span", {}, h("i", { class: "lg-box" }), "fascia tipica"),
        h("span", {}, h("i", { class: "lg-median" }), "mediana"),
        h("span", {}, h("i", { class: "lg-mean" }), "media")));
  }

  async function loadStats(my) {
    try {
      const st = await api.get(`/api/ads/stats${filterQuery()}`);
      if (my !== seq) return;
      disposeChart();
      disposeChart = () => {};
      clear(statsBody);
      const searchName = searches.find(s => String(s.id) === String(f.search_id))?.name;
      scope.textContent = searchName || (searches.length > 1 ? "tutte le ricerche" : "");
      if (!st.count && !st.published.last30) {
        statsBody.append(empty("Nessun dato", "Nessun annuncio rispetta i filtri."));
        return;
      }
      const pub = st.published;

      const prices = h("section", { class: "st-block" },
        h("h3", {}, "prezzi", h("span", { class: "muted" }, f.status === "sold" ? " · venduti" : " · disponibili")),
        st.priced ? h("div", { class: "price-tiles" },
          priceTile("t-min", "minimo", fmtPrice(st.min), "L'annuncio più economico"),
          priceTile("t-med", "mediana", fmtPrice(round(st.median)), "Metà degli annunci costa meno di così: risente poco dei prezzi fuori scala"),
          priceTile("t-avg", "media", fmtPrice(round(st.mean)), "Somma dei prezzi divisa per il numero di annunci"),
          priceTile("t-max", "massimo", fmtPrice(st.max), "L'annuncio più caro")) : h("p", { class: "muted small" }, "Nessun annuncio con prezzo."),
        st.priced > 1 ? rangeBar(st) : null);

      const counts = h("section", { class: "st-block" },
        h("h3", {}, "annunci"),
        h("dl", { class: "st-kv" },
          h("dt", {}, f.status === "sold" ? "venduti" : "disponibili"), h("dd", {}, fmtNum(st.count)),
          h("dt", {}, "con prezzo"), h("dd", {}, fmtNum(st.priced)),
          h("dt", {}, "con spedizione"), h("dd", {}, st.count ? `${fmtNum(st.shipping)} (${Math.round(st.shipping / st.count * 100)}%)` : "—")));

      const chartBox = h("div", { class: "st-chart" });
      const publications = h("section", { class: "st-block" },
        h("h3", {}, "pubblicazioni"),
        pub.avg_day === null ? h("p", { class: "muted small" }, "Nessun annuncio pubblicato negli ultimi 7 giorni.") :
          h("div", { class: "rate" },
            h("div", { class: "rate-value" }, `≈ ${fmtRate(pub.avg_day)}`, h("span", {}, " al giorno")),
            h("div", { class: "muted small" }, pub.span_days < 6.5
              ? `stima su ${fmtNum(pub.last7)} annunci pubblicati nelle ultime ${spanText(pub.span_days)}`
              : `${fmtNum(pub.last7)} annunci negli ultimi 7 giorni`)),
        h("dl", { class: "st-kv" },
          h("dt", {}, "oggi"), h("dd", {}, fmtNum(pub.today)),
          h("dt", {}, "ultimi 7 giorni"), h("dd", {}, fmtNum(pub.last7)),
          h("dt", {}, "ultimi 30 giorni"), h("dd", {}, pub.avg_day_30 === null ? fmtNum(pub.last30) : `${fmtNum(pub.last30)} (≈ ${fmtRate(pub.avg_day_30)}/giorno)`)),
        h("div", { class: "st-chart-title muted small" }, "pubblicati per giorno, ultime 2 settimane"),
        chartBox,
        h("p", { class: "muted small", style: { margin: 0 } },
          "Calcolato sulla data di pubblicazione degli annunci raccolti dall'app: più a lungo resta attivo il monitor, più la stima è precisa."));

      statsBody.append(prices, counts, publications);
      disposeChart = barChart(chartBox, pub.per_day, { label: "pubblicati", height: 140 });
    } catch (e) {
      if (my !== seq) return;
      clear(statsBody).append(empty("Statistiche non disponibili", e.message));
    }
  }

  // ---------------------------------------------------------------- elenco
  function adRow(a) {
    const badges = [];
    if (a.is_new) badges.push(h("span", { class: "badge new" }, "nuovo"));
    if (a.is_drop) badges.push(h("span", { class: "badge drop" }, `ribasso −${fmtNum(a.prev_price - a.price)} €`));
    if (a.sold_at) badges.push(h("span", { class: "badge sold" }, "venduto"));
    if (a.shipping) badges.push(h("span", { class: "badge info" }, "spedizione"));
    if (a.company) badges.push(h("span", { class: "badge muted" }, "azienda"));
    if (a.hidden) badges.push(h("span", { class: "badge muted" }, "nascosto"));

    const star = btn("", { icon: "star", sm: true, kind: "ghost", title: a.favorite ? "Togli dai preferiti" : "Aggiungi ai preferiti" });
    if (a.favorite) { star.classList.add("star", "on"); star.querySelector("path").setAttribute("fill", "currentColor"); }
    star.onclick = () => flag(a, { favorite: !a.favorite });
    const hide = btn("", { icon: a.hidden ? "eye" : "eyeoff", sm: true, kind: "ghost",
      title: a.hidden ? "Mostra di nuovo" : "Nascondi (non verrà più notificato)" });
    hide.onclick = () => flag(a, { hidden: !a.hidden });
    const hist = btn("", { icon: "chart", sm: true, kind: "ghost", title: "Storico prezzi e dettagli", onclick: () => detail(a.id) });

    return h("article", { class: `ad${a.is_new ? " is-new" : ""}${a.sold_at ? " sold" : ""}` },
      a.image ? h("img", { class: "thumb", src: thumbUrl(a.image), alt: "", loading: "lazy", referrerpolicy: "no-referrer",
        onerror: e => e.target.replaceWith(h("div", { class: "thumb" }, "—")) }) : h("div", { class: "thumb" }, "—"),
      h("div", { style: { minWidth: 0 } },
        h("a", { class: "ad-title", href: a.link, target: "_blank", rel: "noopener noreferrer" }, a.title),
        h("div", { class: "ad-meta" },
          h("span", {}, a.location || "—"),
          a.published_at ? h("span", { title: fmtDateTime(a.published_at) }, `pubblicato ${fmtAgo(a.published_at)}`) : null,
          // il nome della ricerca serve solo se ce n'è più d'una e non se ne sta già filtrando una
          searches.length > 1 && !f.search_id ? h("span", {}, a.searches.map(s => s.name).join(", ")) : null),
        badges.length ? h("div", { class: "ad-badges" }, badges) : null),
      h("div", { class: "ad-side" },
        h("div", { class: "price" }, a.is_drop ? h("s", {}, fmtPrice(a.prev_price)) : null, fmtPrice(a.price)),
        h("div", { class: "ad-actions" }, star, hide, hist)));
  }

  async function flag(a, change) {
    try {
      const updated = await api.patch(`/api/ads/${a.id}`, change);
      Object.assign(a, updated);
      if ((change.hidden !== undefined && f.status !== "hidden") || (change.favorite === false && f.status === "favorite")) load();
      else load({ keepScroll: true });
      if (change.hidden) toast("Annuncio nascosto: non comparirà più né verrà notificato", "info");
    } catch (e) { toast(e.message, "error"); }
  }

  let seq = 0;
  async function load() {
    const my = ++seq;
    const query = filterQuery({ sort: f.sort, limit: PAGE, offset: f.offset });
    loadStats(my);
    try {
      const r = await api.get(`/api/ads${query}`);
      if (my !== seq) return;
      clear(list);
      if (!r.items.length) {
        list.append(empty(f.status === "new" ? "Nessun annuncio nuovo" : "Nessun annuncio",
          f.status || f.q || f.min_price || f.max_price ? "Prova a cambiare i filtri." : "Le ricerche non hanno ancora trovato annunci."));
      } else {
        r.items.forEach(a => list.append(adRow(a)));
      }
      clear(pager);
      const from = r.total ? f.offset + 1 : 0;
      const to = Math.min(f.offset + PAGE, r.total);
      const prev = btn("‹ precedenti", { sm: true, kind: "ghost", disabled: f.offset === 0,
        onclick: () => { f.offset = Math.max(0, f.offset - PAGE); load(); toTop(); } });
      const next = btn("successivi ›", { sm: true, kind: "ghost", disabled: to >= r.total,
        onclick: () => { f.offset += PAGE; load(); toTop(); } });
      pager.append(`${fmtNum(from)}–${fmtNum(to)} di ${fmtNum(r.total)} annunci`, h("span", { class: "spacer" }), prev, next);
    } catch (e) {
      clear(list).append(empty("Errore", e.message));
    }
  }

  // ---------------------------------------------------------------- dettaglio + storico prezzi
  async function detail(id) {
    try {
      const a = await api.get(`/api/ads/${id}`);
      const rows = [...a.history].reverse().map((p, i, arr) => {
        const before = i < arr.length - 1 ? arr[i + 1].price : null;
        const diff = before !== null && p.price !== null ? p.price - before : null;
        return h("tr", {}, h("td", { class: "mono" }, fmtDateTime(p.seen_at)), h("td", { class: "num" }, fmtPrice(p.price)),
          h("td", { class: "num" }, diff === null || diff === 0 ? "" :
            h("span", { class: `badge ${diff < 0 ? "drop" : "warn"}` }, `${diff > 0 ? "+" : "−"}${fmtNum(Math.abs(diff))} €`)));
      });
      const table = h("div", { class: "table-wrap" }, h("table", { class: "table" },
        h("thead", {}, h("tr", {}, h("th", {}, "rilevato"), h("th", { class: "num" }, "prezzo"), h("th", { class: "num" }, "variazione"))),
        h("tbody", {}, rows)));

      // grafico solo se il prezzo è cambiato almeno una volta; altrimenti basta la tabella
      const priced = a.history.filter(p => p.price !== null);
      const changed = new Set(priced.map(p => p.price)).size > 1;
      const chartBox = h("div", { class: "panel-body" });
      let disposeChart = () => {};
      let showTable = !changed;
      const toggle = btn("", { sm: true, kind: "ghost" });
      const paint = () => {
        disposeChart();
        disposeChart = () => {};
        clear(chartBox);
        if (showTable) chartBox.append(table);
        else disposeChart = priceChart(chartBox, a.history, { until: a.sold_at || a.last_seen_at });
        toggle.textContent = showTable ? "grafico" : "tabella";
        toggle.setAttribute("aria-pressed", String(showTable));
      };
      toggle.onclick = () => { showTable = !showTable; paint(); };
      const first = priced[0]?.price ?? null;
      let summary = "prezzo invariato da quando è stato trovato";
      if (changed && first && a.price !== null) {
        const delta = a.price - first;
        summary = `${fmtPrice(first)} → ${fmtPrice(a.price)} (${delta < 0 ? "−" : "+"}${Math.round(Math.abs(delta) / first * 100)}%)`;
      }

      const dlg = dialog("annuncio", h("div", { class: "stack" },
        h("div", { class: "ad", style: { padding: 0, borderBottom: 0 } },
          a.image ? h("img", { class: "thumb", src: thumbUrl(a.image), alt: "", referrerpolicy: "no-referrer" }) : h("div", { class: "thumb" }, "—"),
          h("div", {}, h("a", { class: "ad-title", href: a.link, target: "_blank", rel: "noopener noreferrer" }, a.title, " ", icon("ext")),
            h("div", { class: "ad-meta" }, h("span", {}, a.location || "—"), h("span", {}, a.searches.map(s => s.name).join(", ")))),
          h("div", { class: "price" }, fmtPrice(a.price))),
        h("dl", { class: "kv" },
          h("dt", {}, "trovato"), h("dd", {}, fmtDateTime(a.first_seen_at)),
          h("dt", {}, "ultima volta visto"), h("dd", {}, fmtDateTime(a.last_seen_at)),
          h("dt", {}, "pubblicato"), h("dd", {}, fmtDateTime(a.published_at)),
          h("dt", {}, "venduto"), h("dd", {}, a.sold_at ? fmtDateTime(a.sold_at) : "no"),
          h("dt", {}, "spedizione"), h("dd", {}, a.shipping === null ? "n.d." : a.shipping ? "sì" : "no")),
        h("div", { class: "panel" },
          h("div", { class: "panel-head" }, h("h2", {}, "storico_prezzi"),
            h("div", { class: "actions" }, h("span", { class: "muted small mono" }, summary), changed ? toggle : null)),
          chartBox)), [btn("Chiudi", { onclick: () => dlg.close() })], { wide: true });
      dlg.addEventListener("close", () => disposeChart());
      paint();
    } catch (e) { toast(e.message, "error"); }
  }

  await load();
  const off = on("event", e => { if (["new_items", "price_drop", "sold"].includes(e.kind) && f.offset === 0) reloadSoon(); });
  return () => { off(); disposeChart(); };
}
