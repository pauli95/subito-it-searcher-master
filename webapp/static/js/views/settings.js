// Impostazioni: avvio con Windows, manutenzione, backup/ripristino, export/import ricerche, accesso dalla rete locale, info.

import { api } from "../api.js";
import { loadMeta, refreshCounts } from "../store.js";
import {
  btn, busy, clear, confirmDialog, download, empty, field, fmtDateTime, fmtNum, h, panel, switchEl, toast,
} from "../ui.js";

const kb = bytes => (bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`);

export default async function settings(root) {
  let s = await api.get("/api/settings");
  const meta = await loadMeta();

  // ---------------------------------------------------------------- avvio
  const auto = await api.get("/api/system/autostart");
  const winStart = switchEl(auto.enabled, async (checked, input) => {
    try {
      const r = await api.put("/api/system/autostart", { enabled: checked });
      toast(r.enabled ? "L'app partirà in background all'accesso a Windows" : "Avvio con Windows disattivato", "success");
    } catch (e) { input.checked = !checked; toast(e.message, "error", 8000); }
  }, "Avvia Subito Searcher all'accesso a Windows");
  if (!auto.supported) winStart.input.disabled = true;
  const monitorStart = switchEl(s.monitor.autostart, async (checked, input) => {
    try { s = await api.put("/api/settings/monitor", { autostart: checked }); toast(`Avvio automatico del monitor ${checked ? "attivato" : "disattivato"}`, "success"); }
    catch (e) { input.checked = !checked; toast(e.message, "error"); }
  }, "Avvia il monitor quando parte l'app");
  const quit = btn("Chiudi l'app", { icon: "power", sm: true, kind: "danger" });
  quit.onclick = async () => {
    if (!await confirmDialog("Chiudere Subito Searcher?", "Il server si arresta e il monitor smette di controllare le ricerche. Per riaprirlo usa avvia.bat (o riaccedi a Windows se l'avvio automatico è attivo).", "Chiudi")) return;
    busy(quit, async () => {
      try {
        await api.post("/api/system/shutdown");
        clear(root).append(empty("App chiusa", "Il server è stato arrestato. Puoi chiudere questa scheda; per riaprire l'app usa avvia.bat."));
      } catch (e) { toast(e.message, "error", 8000); }
    });
  };
  const startup = panel("avvio", { actions: [quit], body: [h("div", { class: "stack" },
    winStart.el,
    h("p", { class: "muted small", style: { margin: 0 } }, auto.supported
      ? "Il server parte in background, senza finestra: apri l'interfaccia da http://127.0.0.1:8000 (salvala nei preferiti) e chiudilo con «Chiudi l'app»."
      : "Disponibile solo su Windows."),
    monitorStart.el,
    h("p", { class: "muted small", style: { margin: 0 } }, "Attivali entrambi per avere il controllo degli annunci sempre acceso, anche senza aprire il browser."))] });

  // ---------------------------------------------------------------- manutenzione
  const days = h("input", { class: "input", type: "number", min: 0, max: 3650, value: s.maintenance.cleanup_days });
  const saveDays = btn("Salva", { kind: "primary", sm: true });
  saveDays.onclick = () => busy(saveDays, async () => {
    try { s = await api.put("/api/settings/maintenance", { cleanup_days: Number(days.value) }); toast("Pulizia automatica salvata", "success"); }
    catch (e) { toast(e.message, "error"); }
  });
  const nowDays = h("input", { class: "input", type: "number", min: 1, max: 3650, value: 60 });
  const cleanNow = btn("Pulisci ora", { kind: "danger", sm: true });
  cleanNow.onclick = async () => {
    const n = Number(nowDays.value);
    if (!n || n < 1) return toast("Indica un numero di giorni", "error");
    if (!await confirmDialog("Pulire gli annunci vecchi?", `Verranno eliminati gli annunci non più visti da più di ${n} giorni (i preferiti restano). Conviene fare prima un backup.`, "Pulisci")) return;
    busy(cleanNow, async () => {
      try { const r = await api.post(`/api/maintenance/cleanup?days=${n}`); toast(`Eliminati ${fmtNum(r.removed)} annunci`, "success"); refreshCounts(); }
      catch (e) { toast(e.message, "error"); }
    });
  };
  const maintenance = panel("manutenzione", { body: [h("div", { class: "stack" },
    field("Pulizia automatica (giorni)", h("div", { class: "input-group" }, days, saveDays),
      "Ogni giorno elimina gli annunci non più visti da N giorni. 0 = mai."),
    field("Pulizia manuale (giorni)", h("div", { class: "input-group" }, nowDays, cleanNow)))] });

  // ---------------------------------------------------------------- backup
  const backupsBody = h("tbody");
  async function loadBackups() {
    const list = await api.get("/api/backups");
    clear(backupsBody);
    if (!list.length) backupsBody.append(h("tr", {}, h("td", { colspan: 3, class: "muted" }, "Nessun backup.")));
    for (const b of list) {
      const restore = btn("ripristina", { sm: true, kind: "ghost" });
      restore.onclick = async () => {
        if (!await confirmDialog("Ripristinare questo backup?", `Il database verrà sostituito con ${b.name}. Lo stato attuale viene prima salvato in un nuovo backup, quindi puoi tornare indietro.`, "Ripristina")) return;
        busy(restore, async () => {
          try { await api.post(`/api/backups/${encodeURIComponent(b.name)}/restore`); toast("Database ripristinato", "success"); refreshCounts(); loadBackups(); }
          catch (e) { toast(e.message, "error", 8000); }
        });
      };
      backupsBody.append(h("tr", {},
        h("td", { class: "mono" }, b.name, h("div", { class: "muted small" }, fmtDateTime(b.created_at))),
        h("td", { class: "num" }, kb(b.size)),
        h("td", { class: "nowrap" },
          btn("", { icon: "download", sm: true, kind: "ghost", title: "Scarica", onclick: async () => {
            try { download(b.name, await api.blob(`/api/backups/${encodeURIComponent(b.name)}`)); } catch (e) { toast(e.message, "error"); }
          } }),
          restore,
          btn("", { icon: "trash", sm: true, kind: "ghost", title: "Elimina", onclick: async () => {
            if (!await confirmDialog("Eliminare il backup?", b.name, "Elimina")) return;
            try { await api.del(`/api/backups/${encodeURIComponent(b.name)}`); loadBackups(); } catch (e) { toast(e.message, "error"); }
          } }))));
    }
  }
  const createBackup = btn("Crea backup", { icon: "plus", sm: true, kind: "primary" });
  createBackup.onclick = () => busy(createBackup, async () => {
    try { const r = await api.post("/api/backups"); toast(`Backup creato: ${r.name}`, "success"); loadBackups(); }
    catch (e) { toast(e.message, "error"); }
  });
  const upload = h("input", { type: "file", accept: ".db,application/octet-stream", class: "hidden" });
  upload.addEventListener("change", async () => {
    const file = upload.files[0];
    upload.value = "";
    if (!file) return;
    if (!await confirmDialog("Ripristinare da file?", `Il database verrà sostituito con ${file.name}. Lo stato attuale viene prima salvato in un backup.`, "Ripristina")) return;
    try { await api.upload("/api/backups/upload/restore", file); toast("Database ripristinato dal file", "success"); refreshCounts(); loadBackups(); }
    catch (e) { toast(e.message, "error", 8000); }
  });
  const backups = panel("backup", { flush: true,
    actions: [btn("Ripristina da file…", { icon: "upload", sm: true, kind: "ghost", onclick: () => upload.click() }), createBackup],
    body: [h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", {}, "file"), h("th", { class: "num" }, "dimensione"), h("th", {}, ""))), backupsBody)), upload] });

  // ---------------------------------------------------------------- export/import ricerche
  const importInput = h("input", { type: "file", accept: "application/json,.json", class: "hidden" });
  importInput.addEventListener("change", async () => {
    const file = importInput.files[0];
    importInput.value = "";
    if (!file) return;
    try {
      const out = await api.post("/api/searches/import", JSON.parse(await file.text()));
      toast(`Importate ${out.created.length} ricerche` + (out.errors.length ? `; scartate: ${out.errors.join("; ")}` : ""), out.errors.length ? "warning" : "success", 8000);
    } catch (e) { toast(e instanceof SyntaxError ? "File JSON non valido" : e.message, "error"); }
  });
  const transfer = panel("ricerche_json", { body: [h("div", { class: "stack" },
    h("p", { class: "muted", style: { margin: 0 } }, "Esporta le ricerche (parametri, filtri, regole) in un file JSON da conservare o importare su un altro PC. Gli annunci non sono inclusi: per quelli usa il backup."),
    h("div", { class: "row" },
      btn("Esporta JSON", { icon: "download", onclick: async () => { try { download("ricerche-subito.json", await api.blob("/api/searches/export")); } catch (e) { toast(e.message, "error"); } } }),
      btn("Importa JSON", { icon: "upload", onclick: () => importInput.click() })), importInput)] });

  // ---------------------------------------------------------------- rete locale
  const lan = switchEl(s.server.lan, null, "Consenti l'accesso dagli altri dispositivi della rete (es. telefono)");
  const pin = h("input", { class: "input", type: "password", inputmode: "numeric", autocomplete: "new-password", maxlength: 12,
    placeholder: s.server.pin_set ? "PIN impostato: lascia vuoto per non cambiarlo" : "da 4 a 12 cifre" });
  const saveLan = btn("Salva", { kind: "primary", sm: true });
  saveLan.onclick = () => busy(saveLan, async () => {
    const body = { lan: lan.input.checked };
    if (pin.value) body.pin = pin.value;
    try {
      s = await api.put("/api/settings/server", body);
      pin.value = "";
      toast("Salvato: riavvia l'app (chiudi la finestra e riapri avvia.bat) per applicare", "warning", 9000);
    } catch (e) { toast(e.message, "error", 7000); }
  });
  const network = panel("accesso_rete_locale", { body: [h("div", { class: "stack" },
    lan.el,
    field("PIN di accesso", pin, "Richiesto a ogni dispositivo diverso da questo PC (5 tentativi ogni 5 minuti)"),
    h("div", { class: "alert" }, h("strong", {}, "i"), h("span", {},
      "Serve un riavvio. Al primo avvio Windows chiederà il permesso del firewall: consenti solo le reti private. Gli indirizzi da usare sul telefono compaiono nella finestra del server.")),
    h("div", { class: "row" }, saveLan))] });

  // ---------------------------------------------------------------- info
  const info = panel("info", { body: [h("dl", { class: "kv" },
    h("dt", {}, "versione"), h("dd", {}, meta.version),
    h("dt", {}, "dati località"), h("dd", {}, meta.geo_generated || "—"),
    h("dt", {}, "dati categorie"), h("dd", {}, meta.catalog.generated || "—"),
    h("dt", {}, "API"), h("dd", {}, h("a", { href: "/docs", target: "_blank" }, "/docs")),
    h("dt", {}, "scorciatoie"), h("dd", {}, "Ctrl+K comandi · n nuova ricerca · d dashboard · r ricerche · a annunci · m monitor · l log"))] });

  root.append(h("div", { class: "grid grid-2" }, startup, maintenance), backups, h("div", { class: "grid grid-2" }, transfer, network), info);
  await loadBackups();
}
