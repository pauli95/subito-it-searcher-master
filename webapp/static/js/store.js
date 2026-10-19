// Stato condiviso tra le viste + connessione in tempo reale (Server-Sent Events).

import { api } from "./api.js";

const listeners = new Map();

export const store = {
  meta: null,            // catalogo categorie, tipi, ordinamenti, valori predefiniti
  monitor: null,         // stato del monitor (aggiornato da SSE ogni 5 s)
  live: "connecting",    // connecting | on | off
  lastEventId: 0,
  unreadErrors: 0,
  newAds: 0,
  running: new Map(),    // ricerche in controllo adesso: id -> {name, since}
};

/** Bus eventi: "event" (ogni evento del log), "status" (monitor), "live", "counts",
 *  "activity" (ricerche in controllo: store.running cambiato). */
export function on(name, fn) {
  if (!listeners.has(name)) listeners.set(name, new Set());
  listeners.get(name).add(fn);
  return () => listeners.get(name).delete(fn);
}

export function emit(name, payload) {
  for (const fn of listeners.get(name) || []) {
    try { fn(payload); } catch (e) { console.error(e); }
  }
}

export async function loadMeta() {
  if (!store.meta) store.meta = await api.get("/api/meta");
  return store.meta;
}

export function category(slug) {
  return store.meta?.catalog.categories.find(c => c.slug === slug) || null;
}

let source = null;

export function connectLive() {
  if (source) source.close();
  source = new EventSource(`/api/events/stream?after=${store.lastEventId}`);
  store.live = "connecting";
  emit("live", store.live);
  source.onopen = () => { store.live = "on"; emit("live", "on"); };
  source.onerror = () => { store.live = "off"; emit("live", "off"); };   // EventSource riprova da solo
  source.onmessage = msg => {
    const event = JSON.parse(msg.data);
    if (event.id) store.lastEventId = Math.max(store.lastEventId, event.id);
    trackActivity(event);
    emit("event", event);
  };
  source.addEventListener("status", msg => {
    store.monitor = JSON.parse(msg.data);
    emit("status", store.monitor);
  });
}

export async function refreshMonitor() {
  store.monitor = await api.get("/api/monitor");
  emit("status", store.monitor);
  return store.monitor;
}

export async function refreshCounts() {
  const [ads, health] = await Promise.all([
    api.get("/api/ads?status=new&limit=1"),
    api.get("/api/health"),
  ]);
  store.newAds = ads.total;
  store.health = health;
  emit("counts", { newAds: ads.total, health });
}

// ------------------------------------------------------------------ controlli in corso
const STALE_MS = 90 * 1000;   // un controllo non dura mai così tanto: evita indicatori bloccati

function trackActivity(e) {
  if (!e.phase || !e.search_id) return;
  if (e.phase === "start") {
    if (Date.now() - new Date(e.time).getTime() > STALE_MS) return;   // evento vecchio dopo riconnessione
    store.running.set(e.search_id, { name: e.name || `#${e.search_id}`, since: Date.now() });
  } else if (!store.running.delete(e.search_id)) {
    return;
  }
  emit("activity", store.running);
}

setInterval(() => {
  let changed = false;
  for (const [id, r] of store.running) if (Date.now() - r.since > STALE_MS) { store.running.delete(id); changed = true; }
  if (changed) emit("activity", store.running);
}, 10000);
