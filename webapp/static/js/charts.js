// Grafici SVG senza librerie, una sola serie ciascuno: colore --chart-1 (validato), niente legenda
// (il titolo del pannello nomina la serie), griglia discreta, tooltip al passaggio, vista tabella.
//  - barChart: annunci trovati per giorno. Barre arrotondate in alto, ancorate alla base, 2 px di spazio.
//  - priceChart: storico prezzi di un annuncio. Linea a gradini da 2 px (il prezzo resta valido fino
//    alla variazione successiva), marcatori da 8 px con anello del colore di fondo, mirino verticale.

import { clear, fmtDateTime, fmtDay, fmtNum, fmtPrice, h, parseDate } from "./ui.js";

const NS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
};

/** Massimo dell'asse = 4 tacche intere e "tonde" (1, 2, 5 × 10^n ciascuna). */
function niceMax(v) {
  if (v <= 4) return 4;
  const raw = v / 4;
  const pow = 10 ** Math.floor(Math.log10(raw));
  for (const m of [1, 2, 2.5, 5, 10]) {
    const step = m * pow;
    if (step >= raw && Number.isInteger(step)) return step * 4;
  }
  return 40 * pow;
}

/** Riempie i giorni mancanti con 0 per avere un asse temporale continuo. */
export function fillDays(series, days) {
  const map = new Map(series.map(d => [d.day, d.count]));
  const out = [];
  const today = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    out.push({ day: key, count: map.get(key) || 0 });
  }
  return out;
}

export function barChart(container, data, { label = "annunci", height: chartHeight = 220 } = {}) {
  const wrap = h("div", { class: "chart" });
  const tip = h("div", { class: "tooltip hidden", role: "status" });
  container.append(wrap);

  function draw() {
    clear(wrap);
    const width = Math.max(240, wrap.clientWidth || 600);
    const height = chartHeight;
    const m = { top: 12, right: 8, bottom: 26, left: 34 };
    const iw = width - m.left - m.right;
    const ih = height - m.top - m.bottom;
    const max = niceMax(Math.max(0, ...data.map(d => d.count)));
    const step = iw / data.length;
    const gap = 2;
    const bw = Math.max(2, step - gap);
    const y = v => m.top + ih - (v / max) * ih;

    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", style: `height:${height}px`,
      "aria-label": `${label} per giorno, ultimi ${data.length} giorni; massimo ${max}` });

    for (let i = 0; i <= 4; i++) {
      const v = (max / 4) * i;
      const yy = Math.round(y(v)) + 0.5;
      svg.append(svgEl("line", { class: "grid-line", x1: m.left, x2: width - m.right, y1: yy, y2: yy }));
      const t = svgEl("text", { class: "axis-text", x: m.left - 6, y: yy + 4, "text-anchor": "end" });
      t.textContent = fmtNum(Math.round(v));
      svg.append(t);
    }

    const labelEvery = Math.ceil(data.length / Math.max(2, Math.floor(iw / 64)));
    data.forEach((d, i) => {
      const x = m.left + i * step + gap / 2;
      const top = y(d.count);
      const hgt = m.top + ih - top;
      const r = Math.min(4, bw / 2, hgt);
      const base = m.top + ih;
      // area di hover alta quanto il grafico (più grande della barra)
      const hit = svgEl("rect", { class: "bar-hit", x: m.left + i * step, y: m.top, width: step, height: ih, tabindex: "-1" });
      const bar = svgEl("path", {
        class: "bar",
        d: hgt <= 0 ? `M${x},${base}h${bw}` :
          `M${x},${base}V${top + r}Q${x},${top} ${x + r},${top}H${x + bw - r}Q${x + bw},${top} ${x + bw},${top + r}V${base}Z`,
      });
      const show = () => {
        bar.classList.add("hover");
        tip.textContent = "";
        tip.append(h("strong", {}, fmtNum(d.count)), ` ${label} · ${fmtDay(d.day)}`);
        tip.style.left = `${((x + bw / 2) / width) * 100}%`;
        tip.style.top = `${Math.min(top, base - 4)}px`;
        tip.classList.remove("hidden");
      };
      const hide = () => { bar.classList.remove("hover"); tip.classList.add("hidden"); };
      hit.addEventListener("mouseenter", show);
      hit.addEventListener("mouseleave", hide);
      svg.append(hit, bar);
      const last = data.length - 1;
      // l'ultima data ha sempre l'etichetta; quella regolare troppo vicina viene saltata
      if (i === last || (i % labelEvery === 0 && last - i >= labelEvery * 0.75)) {
        const t = svgEl("text", { class: "axis-text", x: x + bw / 2, y: height - 8, "text-anchor": "middle" });
        t.textContent = fmtDay(d.day);
        svg.append(t);
      }
    });
    wrap.append(svg, tip);
  }

  draw();
  const ro = new ResizeObserver(() => draw());
  ro.observe(wrap);
  return () => ro.disconnect();
}

export function dataTable(data, label = "annunci") {
  return h("div", { class: "table-wrap" }, h("table", { class: "table" },
    h("thead", {}, h("tr", {}, h("th", {}, "Giorno"), h("th", { class: "num" }, label))),
    h("tbody", {}, [...data].reverse().map(d => h("tr", {}, h("td", { class: "mono" }, fmtDay(d.day)),
      h("td", { class: "num" }, fmtNum(d.count)))))));
}

/** points: [{price, seen_at}] in ordine cronologico; `until` estende l'ultimo prezzo fino a quella data. */
export function priceChart(container, points, { until = null } = {}) {
  const data = points.filter(p => p.price !== null && parseDate(p.seen_at))
    .map(p => ({ price: p.price, t: parseDate(p.seen_at).getTime(), at: p.seen_at }));
  const wrap = h("div", { class: "chart" });
  const tip = h("div", { class: "tooltip hidden", role: "status" });
  container.append(wrap);
  if (!data.length) return () => {};
  const last = data[data.length - 1];
  const untilT = parseDate(until)?.getTime() || 0;
  const end = Math.max(last.t, untilT);
  const endAt = untilT > last.t ? until : last.at;

  function draw() {
    clear(wrap);
    const width = Math.max(280, wrap.clientWidth || 560);
    const height = 220;
    const m = { top: 14, right: 14, bottom: 26, left: 58 };
    const iw = width - m.left - m.right;
    const ih = height - m.top - m.bottom;
    const prices = data.map(d => d.price);
    let lo = Math.min(...prices);
    let hi = Math.max(...prices);
    const pad = Math.max(1, (hi - lo) * 0.15 || hi * 0.1);
    lo = Math.max(0, Math.floor((lo - pad) / 5) * 5);
    hi = Math.ceil((hi + pad) / 5) * 5;
    const t0 = data[0].t;
    const span = Math.max(1, end - t0);
    const x = t => m.left + ((t - t0) / span) * iw;
    const y = v => m.top + ih - ((v - lo) / (hi - lo)) * ih;

    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
      "aria-label": `Storico prezzi: ${data.length} rilevazioni, da ${fmtPrice(data[0].price)} a ${fmtPrice(data[data.length - 1].price)}` });
    for (let i = 0; i <= 4; i++) {
      const v = lo + ((hi - lo) / 4) * i;
      const yy = Math.round(y(v)) + 0.5;
      svg.append(svgEl("line", { class: "grid-line", x1: m.left, x2: width - m.right, y1: yy, y2: yy }));
      const t = svgEl("text", { class: "axis-text", x: m.left - 6, y: yy + 4, "text-anchor": "end" });
      t.textContent = fmtPrice(Math.round(v));
      svg.append(t);
    }
    for (const [tt, at, anchor] of [[t0, data[0].at, "start"], [end, endAt, "end"]]) {
      if (anchor === "end" && fmtDay(at) === fmtDay(data[0].at)) continue;
      const t = svgEl("text", { class: "axis-text", x: x(tt), y: height - 8, "text-anchor": anchor });
      t.textContent = fmtDay(at);
      svg.append(t);
    }

    let d = `M${x(data[0].t)},${y(data[0].price)}`;
    for (let i = 1; i < data.length; i++) d += `H${x(data[i].t)}V${y(data[i].price)}`;
    d += `H${x(end)}`;
    svg.append(svgEl("path", { class: "line", d }));

    const cross = svgEl("line", { class: "crosshair hidden", y1: m.top, y2: m.top + ih });
    svg.append(cross);
    const dots = data.map(p => {
      const c = svgEl("circle", { class: "dot", cx: x(p.t), cy: y(p.price), r: 4 });
      svg.append(c);
      return c;
    });

    // area di hover = tutto il grafico; si aggancia al punto più vicino in orizzontale
    const hit = svgEl("rect", { class: "bar-hit", x: m.left, y: m.top, width: iw, height: ih });
    svg.append(hit);
    const show = ev => {
      const box = svg.getBoundingClientRect();
      const px = ((ev.clientX - box.left) / box.width) * width;
      let best = 0;
      data.forEach((p, i) => { if (Math.abs(x(p.t) - px) < Math.abs(x(data[best].t) - px)) best = i; });
      const p = data[best];
      dots.forEach((c, i) => c.classList.toggle("hover", i === best));
      cross.setAttribute("x1", x(p.t));
      cross.setAttribute("x2", x(p.t));
      cross.classList.remove("hidden");
      const prev = best > 0 ? data[best - 1].price : null;
      tip.textContent = "";
      tip.append(h("strong", {}, fmtPrice(p.price)),
        prev !== null && prev !== p.price ? ` (${p.price < prev ? "−" : "+"}${fmtNum(Math.abs(p.price - prev))} €)` : "",
        ` · ${fmtDateTime(p.at)}`);
      tip.style.left = `${(x(p.t) / width) * 100}%`;
      tip.style.top = `${y(p.price)}px`;
      tip.classList.remove("hidden");
    };
    const hide = () => { cross.classList.add("hidden"); tip.classList.add("hidden"); dots.forEach(c => c.classList.remove("hover")); };
    hit.addEventListener("mousemove", show);
    hit.addEventListener("mouseleave", hide);
    wrap.append(svg, tip);
  }

  draw();
  const ro = new ResizeObserver(() => draw());
  ro.observe(wrap);
  return () => ro.disconnect();
}
