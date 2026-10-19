// Creazione / modifica di una ricerca. L'URL di subito.it si compone in tempo reale dai campi;
// incollando un URL esistente i campi si compilano da soli.

import { api } from "../api.js";
import { navigate } from "../app.js";
import { category, loadMeta, refreshCounts } from "../store.js";
import {
  btn, busy, clear, confirmDialog, copyText, debounce, dialog, field, fmtPrice, h, icon, panel, switchEl, thumbUrl, toast,
} from "../ui.js";

const INTERVALS = [[null, "Predefinito (impostazioni)"], [60, "1 minuto"], [120, "2 minuti"], [300, "5 minuti"],
  [600, "10 minuti"], [900, "15 minuti"], [1800, "30 minuti"], [3600, "1 ora"], [10800, "3 ore"]];

// ------------------------------------------------------------------ combobox accessibile
function combobox({ input, fetchOptions, onPick, emptyText = "Nessun risultato" }) {
  const list = h("ul", { class: "combo-list hidden", role: "listbox" });
  const id = `cb-${Math.random().toString(36).slice(2, 8)}`;
  list.id = id;
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", id);
  input.setAttribute("aria-expanded", "false");
  input.autocomplete = "off";
  let options = [];
  let active = -1;
  let seq = 0;
  let pending = false;      // risultati in arrivo: le opzioni mostrate sono vecchie
  let pickOnLoad = false;   // Invio premuto mentre si caricava: scegli il primo appena arriva

  const close = () => { list.classList.add("hidden"); input.setAttribute("aria-expanded", "false"); active = -1; };
  const paint = () => {
    clear(list);
    if (!options.length) list.append(h("li", { class: "group" }, emptyText));
    let idx = 0;
    for (const o of options) {
      if (o.group) { list.append(h("li", { class: "group", role: "presentation" }, o.group)); continue; }
      const i = idx++;
      o._i = i;
      list.append(h("li", { role: "option", id: `${id}-${i}`, class: o.indent ? "indent" : "", "aria-selected": String(i === active),
        onmousedown: e => { e.preventDefault(); if (!pending) pick(o); } },
        h("span", { class: "opt-main" }, o.label), o.sub ? h("span", { class: "opt-sub" }, o.sub) : null));
    }
    input.setAttribute("aria-activedescendant", active >= 0 ? `${id}-${active}` : "");
    list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  };
  const selectable = () => options.filter(o => !o.group);
  const pick = o => { pickOnLoad = false; close(); onPick(o); };
  const refresh = async () => {
    const my = ++seq;
    const result = await fetchOptions(input.value);
    if (my !== seq) return;
    pending = false;
    options = result;
    active = selectable().length ? 0 : -1;
    list.classList.remove("hidden");
    input.setAttribute("aria-expanded", "true");
    paint();
    if (pickOnLoad) {
      pickOnLoad = false;
      if (selectable()[0]) pick(selectable()[0]);
    }
  };
  const debounced = debounce(refresh, 120);
  input.addEventListener("input", () => {
    pending = true;
    list.querySelectorAll('[role="option"]').forEach(li => li.setAttribute("aria-disabled", "true"));
    debounced();
  });
  input.addEventListener("focus", () => { input.select(); refresh(); });
  input.addEventListener("blur", () => setTimeout(close, 120));
  input.addEventListener("keydown", e => {
    const sel = selectable();
    if (e.key === "ArrowDown") { e.preventDefault(); if (list.classList.contains("hidden")) refresh(); active = Math.min(active + 1, sel.length - 1); paint(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); paint(); }
    else if (e.key === "Enter" && pending) { e.preventDefault(); pickOnLoad = true; }
    else if (e.key === "Enter" && !list.classList.contains("hidden")) { e.preventDefault(); if (sel[active]) pick(sel[active]); }
    else if (e.key === "Escape") { close(); }
  });
  return h("div", { class: "combo" }, input, list);
}

// ------------------------------------------------------------------ vista
export default async function searchForm(root, { id }) {
  const meta = await loadMeta();
  const catalog = meta.catalog;
  const editing = id ? await api.get(`/api/searches/${id}`) : null;

  const state = {
    mode: editing && !editing.params ? "url" : "params",
    params: { ...meta.defaults, ...(editing?.params || {}) },
    url: editing?.url || "",
    locationLabel: editing?.summary?.location || "Tutta Italia",
  };

  // ---------------------------------------------------------------- campi
  const name = h("input", { class: "input", required: true, maxlength: 100, placeholder: "es. iPhone 13 Padova", value: editing?.name || "" });
  const keywords = h("input", { class: "input", placeholder: "es. iphone 13 pro", value: state.params.keywords || "" });
  const titleOnly = h("input", { type: "checkbox" }); titleOnly.checked = !!state.params.title_only;
  const location = h("input", { class: "input", placeholder: "Comune, provincia o regione…", value: state.locationLabel });
  const categoryInput = h("input", { class: "input", placeholder: "Cerca una categoria…" });
  const adType = h("select", { class: "select" });
  const minPrice = h("input", { class: "input", type: "number", min: 0, step: 1, inputmode: "numeric", placeholder: "nessuno" });
  const maxPrice = h("input", { class: "input", type: "number", min: 0, step: 1, inputmode: "numeric", placeholder: "nessuno" });
  const shipping = h("input", { type: "checkbox" }); shipping.checked = !!state.params.shipping_only;
  const order = h("select", { class: "select" });
  const exclude = h("input", { class: "input", placeholder: "rotto, ricambi, cover", value: (editing?.exclude_words || []).join(", ") });
  const rawUrl = h("input", { class: "input", type: "url", placeholder: "https://www.subito.it/annunci-…", value: state.mode === "url" ? state.url : "" });
  const paste = h("input", { class: "input", type: "url", placeholder: "Incolla qui un URL di ricerca di subito.it per compilare i campi" });

  const setPrice = () => {
    const lo = state.mode === "url" ? editing?.min_price : state.params.min_price;
    const hi = state.mode === "url" ? editing?.max_price : state.params.max_price;
    minPrice.value = lo ?? "";
    maxPrice.value = hi ?? "";
  };
  setPrice();

  const enabled = switchEl(editing ? editing.enabled : true, null, "Ricerca attiva");
  const interval = h("select", { class: "select" }, INTERVALS.map(([v, l]) => h("option", { value: v ?? "" }, l)));
  interval.value = editing?.interval_sec ?? "";
  if (editing?.interval_sec && ![...interval.options].some(o => o.value === String(editing.interval_sec))) {
    interval.append(h("option", { value: editing.interval_sec }, `${editing.interval_sec} s`));
    interval.value = editing.interval_sec;
  }
  const activeFrom = h("input", { class: "input", type: "time", value: editing?.active_from || "" });
  const activeTo = h("input", { class: "input", type: "time", value: editing?.active_to || "" });
  const notifyNew = h("input", { type: "checkbox" }); notifyNew.checked = editing ? editing.notify_new : true;
  const notifyDrop = h("input", { type: "checkbox" }); notifyDrop.checked = editing ? editing.notify_price_drop : false;
  const notifyMax = h("input", { class: "input", type: "number", min: 0, placeholder: "nessuna", value: editing?.notify_max_price ?? "" });

  // ---------------------------------------------------------------- località (autocompletamento server)
  const locationBox = combobox({
    input: location,
    emptyText: "Nessuna località trovata",
    fetchOptions: async q => {
      if (!q.trim() || q === state.locationLabel) {
        return [{ label: "Tutta Italia", sub: "", value: { region: null, province: null, town: null } }];
      }
      const res = await api.get(`/api/geo?q=${encodeURIComponent(q)}&limit=12`);
      return res.map(l => ({ label: l.label, sub: l.detail, value: l }));
    },
    onPick: o => {
      Object.assign(state.params, { region: o.value.region, province: o.value.province, town: o.value.town });
      state.locationLabel = o.label;
      location.value = o.label;
      update();
    },
  });

  // ---------------------------------------------------------------- categoria (filtro locale)
  const catLabel = slug => catalog.categories.find(c => c.slug === slug)?.label || slug;
  categoryInput.value = catLabel(state.params.category);
  const categoryBox = combobox({
    input: categoryInput,
    fetchOptions: async q => {
      const needle = q.trim().toLowerCase();
      const showAll = !needle || needle === catLabel(state.params.category).toLowerCase();
      const out = [];
      for (const g of catalog.tree) {
        const children = g.children.filter(c => showAll || c.label.toLowerCase().includes(needle));
        const groupMatch = showAll || g.label.toLowerCase().includes(needle);
        if (!groupMatch && !children.length) continue;
        out.push({ label: g.label, value: g.slug, sub: g.slug === "usato" ? "" : "tutta la macrocategoria" });
        children.forEach(c => out.push({ label: c.label, value: c.slug, indent: true }));
      }
      return out;
    },
    onPick: o => {
      state.params.category = o.value;
      categoryInput.value = o.label;
      fillAdTypes();
      fillOrders();
      update();
    },
  });

  function fillAdTypes() {
    const cat = category(state.params.category);
    clear(adType);
    for (const t of catalog.ad_types) {
      if (cat && !cat.ad_types.includes(t.key)) continue;
      adType.append(h("option", { value: t.key }, t.label));
    }
    if (![...adType.options].some(o => o.value === state.params.ad_type)) state.params.ad_type = adType.options[0]?.value || "s";
    adType.value = state.params.ad_type;
  }
  function fillOrders() {
    const cat = category(state.params.category);
    const orders = cat?.orders || Object.keys(catalog.orders);
    clear(order);
    const siteDefault = orders[0] ? catalog.orders[orders[0]] || orders[0] : "";
    order.append(h("option", { value: "" }, `Predefinito del sito (${siteDefault.toLowerCase()})`));
    for (const o of orders) order.append(h("option", { value: o }, catalog.orders[o] || o));
    if (state.params.order && !orders.includes(state.params.order)) state.params.order = "datedesc";
    order.value = state.params.order || "";
  }
  fillAdTypes();
  fillOrders();

  // ---------------------------------------------------------------- URL in tempo reale
  const urlCode = h("code", {}, "…");
  const warnings = h("div", { class: "stack", style: { gap: "6px" } });
  const openLink = h("a", { class: "btn sm", target: "_blank", rel: "noopener noreferrer", href: "#" }, icon("ext"), "Apri su subito.it");
  const copyBtn = btn("Copia", { icon: "copy", sm: true, onclick: () => copyText(urlCode.textContent) });
  const previewBtn = btn("Anteprima risultati", { icon: "eye", sm: true, kind: "primary" });
  let currentUrl = "";
  let buildError = null;

  const readParams = () => {
    const p = state.params;
    p.keywords = keywords.value;
    p.title_only = titleOnly.checked;
    p.ad_type = adType.value;
    p.min_price = minPrice.value === "" ? null : Number(minPrice.value);
    p.max_price = maxPrice.value === "" ? null : Number(maxPrice.value);
    p.shipping_only = shipping.checked;
    p.order = order.value || null;
    return p;
  };

  async function refreshUrl() {
    clear(warnings);
    if (state.mode === "url") {
      currentUrl = rawUrl.value.trim();
      urlCode.textContent = currentUrl || "—";
      openLink.href = currentUrl || "#";
      buildError = null;
      return;
    }
    try {
      const r = await api.post("/api/url/build", readParams());
      buildError = null;
      currentUrl = r.url;
      urlCode.textContent = r.url;
      openLink.href = r.url;
      if (document.activeElement !== location) { state.locationLabel = r.location.label; location.value = r.location.label; }
      r.warnings.forEach(w => warnings.append(h("div", { class: "alert" }, h("strong", {}, "i"), h("span", {}, w))));
    } catch (e) {
      buildError = e.message;
      urlCode.textContent = "—";
      openLink.href = "#";
      warnings.append(h("div", { class: "alert err" }, h("strong", {}, "!"), h("span", {}, e.message)));
    }
  }
  const update = debounce(refreshUrl, 180);

  [keywords, minPrice, maxPrice, rawUrl].forEach(el => el.addEventListener("input", update));
  [titleOnly, adType, shipping, order].forEach(el => el.addEventListener("change", update));

  // ---------------------------------------------------------------- incolla URL -> campi
  async function applyPastedUrl() {
    const value = paste.value.trim();
    if (!value) return;
    try {
      const r = await api.post("/api/url/parse", { url: value });
      state.mode = "params";
      state.params = { ...meta.defaults, ...r.params };
      keywords.value = r.params.keywords || "";
      titleOnly.checked = r.params.title_only;
      shipping.checked = r.params.shipping_only;
      minPrice.value = r.params.min_price ?? "";
      maxPrice.value = r.params.max_price ?? "";
      categoryInput.value = catLabel(r.params.category);
      fillAdTypes();
      fillOrders();
      location.value = "…";
      paste.value = "";
      setMode("params");
      update();
      toast("Campi compilati dall'URL" + (r.warnings.length ? ` (${r.warnings.join("; ")})` : ""), r.warnings.length ? "warning" : "success", 6000);
      if (!name.value.trim() && r.params.keywords) name.value = r.params.keywords;
    } catch (e) {
      const keep = await confirmDialog("URL non scomponibile",
        `${e.message}. Puoi comunque salvare la ricerca "solo come URL": funziona, ma i parametri non saranno modificabili dal form.`,
        "Usa come solo URL", false);
      if (keep) { rawUrl.value = value; paste.value = ""; setMode("url"); update(); }
    }
  }
  paste.addEventListener("paste", () => setTimeout(applyPastedUrl, 0));
  paste.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); applyPastedUrl(); } });

  // ---------------------------------------------------------------- anteprima
  previewBtn.onclick = () => busy(previewBtn, async () => {
    if (buildError) return toast(buildError, "error");
    const body = state.mode === "url"
      ? { mode: "url", url: rawUrl.value.trim(), min_price: minPrice.value || null, max_price: maxPrice.value || null, exclude_words: exclude.value }
      : { mode: "params", params: readParams(), exclude_words: exclude.value };
    try {
      const r = await api.post("/api/preview", body);
      const rows = r.items.slice(0, 15).map(a => h("div", { class: "ad" },
        a.image ? h("img", { class: "thumb", src: thumbUrl(a.image), alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : h("div", { class: "thumb" }, "—"),
        h("div", {}, h("a", { class: "ad-title", href: a.link, target: "_blank", rel: "noopener noreferrer" }, a.title),
          h("div", { class: "ad-meta" }, h("span", {}, a.location), a.shipping ? h("span", {}, "spedizione") : null)),
        h("div", { class: "ad-side" }, h("div", { class: "price" }, fmtPrice(a.price)))));
      const dlg = dialog("anteprima", h("div", { class: "stack" },
        h("div", { class: "stats" },
          h("div", { class: "stat" }, h("div", { class: "label" }, "letti"), h("div", { class: "value" }, r.found), h("div", { class: "hint" }, "prima pagina del sito")),
          h("div", { class: "stat" }, h("div", { class: "label" }, "validi"), h("div", { class: "value" }, r.matched), h("div", { class: "hint" }, `${r.excluded} esclusi dai filtri`)),
          h("div", { class: "stat" }, h("div", { class: "label" }, "prezzi"), h("div", { class: "value", style: { fontSize: "18px" } },
            r.price_min !== null ? `${fmtPrice(r.price_min)} – ${fmtPrice(r.price_max)}` : "—"))),
        r.found === 0 ? h("div", { class: "alert" }, "Nessun annuncio: prova ad allargare località o parole chiave.") : null,
        h("div", { class: "panel" }, h("div", { class: "ads" }, rows))), [btn("Chiudi", { onclick: () => dlg.close() })], { wide: true });
    } catch (e) { toast(e.message, "error", 7000); }
  });

  // ---------------------------------------------------------------- layout
  const span = (n, el) => { el.classList.add(`span-${n}`); return el; };
  const paramsFields = h("div", { class: "form-grid" },
    span(8, field("Parole chiave", keywords, "Lascia vuoto per tutti gli annunci della categoria e località")),
    span(4, h("div", { class: "field", style: { justifyContent: "flex-end" } },
      h("label", { class: "check" }, titleOnly, "Cerca solo nel titolo"))),
    span(6, field("Località", locationBox, "Regione, provincia o comune; vuoto = tutta Italia")),
    span(6, field("Categoria", categoryBox)),
    span(4, field("Tipo di annuncio", adType)),
    span(4, field("Ordinamento", order, "\"Più recenti\" fa comparire subito gli annunci nuovi")),
    span(4, h("div", { class: "field", style: { justifyContent: "flex-end" } },
      h("label", { class: "check" }, shipping, "Solo con spedizione"))));
  const urlFields = h("div", { class: "form-grid" },
    span(12, field("URL di ricerca", rawUrl, "Ricerca salvata come solo URL: i parametri non sono modificabili singolarmente")));

  const priceFields = h("div", { class: "form-grid" },
    span(3, field("Prezzo min €", minPrice)),
    span(3, field("Prezzo max €", maxPrice)),
    span(6, field("Parole da escludere", exclude, "Separate da virgola; si applicano ai titoli (\"cover\" non esclude \"discovery\")")));

  const modeNote = h("div", {});
  function setMode(mode) {
    state.mode = mode;
    paramsFields.classList.toggle("hidden", mode !== "params");
    urlFields.classList.toggle("hidden", mode !== "url");
    clear(modeNote);
    if (mode === "url") {
      modeNote.append(h("div", { class: "alert" }, h("span", {}, "Modalità solo URL. "),
        btn("Prova a convertire in campi", { sm: true, onclick: () => { paste.value = rawUrl.value; applyPastedUrl(); } })));
    }
  }
  setMode(state.mode);

  const form = h("form", { class: "stack", novalidate: true });
  const saveBtn = btn(editing ? "Salva modifiche" : "Salva e cerca", { kind: "primary", type: "submit", icon: "check" });

  form.append(
    panel(editing ? `ricerche/${editing.id}` : "ricerche/nuova", {
      actions: [h("a", { class: "btn sm ghost", href: "#/ricerche" }, "annulla")],
      body: [h("div", { class: "stack" },
        h("div", { class: "form-grid" }, span(12, field("Nome della ricerca", name))),
        field("Hai già un URL?", paste, "Incollalo: i campi si compilano da soli"),
        modeNote,
        h("fieldset", {}, h("legend", {}, "query"), paramsFields, urlFields),
        h("fieldset", {}, h("legend", {}, "filtri"), priceFields),
        h("div", { class: "field" }, h("span", { class: "label-text" }, "URL generato"),
          h("div", { class: "urlbox" }, h("span", { class: "muted" }, "$"), urlCode),
          h("div", { class: "row" }, copyBtn, openLink, h("span", { class: "spacer" }), previewBtn)),
        warnings)],
    }),
    h("div", { class: "grid grid-2" },
      panel("monitoraggio", { body: [h("div", { class: "form-grid" },
        span(12, enabled.el),
        span(12, field("Intervallo di controllo", interval, "Minimo 1 minuto; il monitor aggiunge una pausa casuale tra le richieste")),
        span(6, field("Attiva dalle", activeFrom)),
        span(6, field("Fino alle", activeTo, "Vuoto = segue la fascia globale")))] }),
      panel("notifiche", { body: [h("div", { class: "form-grid" },
        span(12, h("label", { class: "check" }, notifyNew, "Notifica i nuovi annunci")),
        span(12, h("label", { class: "check" }, notifyDrop, "Notifica anche i ribassi di prezzo")),
        span(12, field("Notifica solo sotto (€)", notifyMax, "Gli annunci più cari vengono salvati ma non notificati")))] })),
    h("div", { class: "row" }, saveBtn, h("a", { class: "btn ghost", href: "#/ricerche" }, "Annulla"), h("span", { class: "spacer" }),
      editing ? btn("Elimina ricerca", { kind: "danger", icon: "trash", onclick: async () => {
        if (!await confirmDialog(`Eliminare '${editing.name}'?`, "La ricerca e i suoi annunci verranno eliminati.", "Elimina")) return;
        try { await api.del(`/api/searches/${editing.id}`); toast("Ricerca eliminata"); navigate("#/ricerche"); }
        catch (e) { toast(e.message, "error"); }
      } }) : null));

  form.addEventListener("submit", async e => {
    e.preventDefault();
    if (!name.value.trim()) { name.setAttribute("aria-invalid", "true"); name.focus(); return toast("Dai un nome alla ricerca", "error"); }
    name.removeAttribute("aria-invalid");
    if ((activeFrom.value === "") !== (activeTo.value === "")) return toast("Fascia oraria: indica sia l'inizio sia la fine, oppure nessuno dei due", "error");
    const payload = {
      name: name.value.trim(),
      mode: state.mode,
      params: state.mode === "params" ? readParams() : null,
      url: state.mode === "url" ? rawUrl.value.trim() : null,
      min_price: state.mode === "url" && minPrice.value !== "" ? Number(minPrice.value) : null,
      max_price: state.mode === "url" && maxPrice.value !== "" ? Number(maxPrice.value) : null,
      exclude_words: exclude.value,
      enabled: enabled.input.checked,
      interval_sec: interval.value ? Number(interval.value) : null,
      active_from: activeFrom.value || null,
      active_to: activeTo.value || null,
      notify_new: notifyNew.checked,
      notify_price_drop: notifyDrop.checked,
      notify_max_price: notifyMax.value === "" ? null : Number(notifyMax.value),
    };
    await busy(saveBtn, async () => {
      try {
        const r = editing ? await api.put(`/api/searches/${editing.id}`, payload) : await api.post("/api/searches", payload);
        const run = r.run ? (r.run.ok ? ` — ${r.run.found} annunci letti` : ` — errore: ${r.run.error}`) : "";
        toast(`Ricerca '${r.search.name}' ${editing ? "salvata" : "creata"}${run}`, r.run && !r.run.ok ? "warning" : "success", 6000);
        refreshCounts();
        navigate("#/ricerche");
      } catch (err) { toast(err.message, "error", 8000); }
    });
  });

  root.append(form);
  await refreshUrl();
  if (!editing) name.focus();
}
