// Notifiche: interruttori dei canali, non disturbare, raggruppamento, configurazione Telegram e ntfy,
// notifiche del browser e suono, test.

import { notificationSupport, playChime, requestNotificationPermission } from "../alerts.js";
import { api } from "../api.js";
import { store } from "../store.js";
import { btn, busy, clear, field, h, led, panel, switchEl, toast } from "../ui.js";

export default async function notifications(root) {
  let s = await api.get("/api/settings");

  async function save(section, values, msg) {
    try {
      s = await api.put(`/api/settings/${section}`, values);
      if (msg) toast(msg, "success");
      return true;
    } catch (e) { toast(e.message, "error", 7000); return false; }
  }

  const testBtn = channel => {
    const b = btn("Invia test", { sm: true, icon: "play" });
    b.onclick = () => busy(b, async () => {
      try { await api.post(`/api/notifications/test/${channel}`); toast(`Messaggio di prova ${channel} inviato`, "success"); }
      catch (e) { toast(e.message, "error", 8000); }
    });
    return b;
  };

  const channelSwitch = (key, label) => {
    const sw = switchEl(s.notifications[key], async (checked, input) => {
      if (!await save("notifications", { [key]: checked }, `${label} ${checked ? "attivate" : "disattivate"}`)) input.checked = !checked;
    });
    sw.input.setAttribute("aria-label", `${label}: attive`);
    return sw.el;
  };

  // ---------------------------------------------------------------- generale
  const dnd = switchEl(s.notifications.dnd, async (checked, input) => {
    if (!await save("notifications", { dnd: checked }, checked ? "Non disturbare attivo: nessuna notifica" : "Notifiche riattivate")) input.checked = !checked;
  }, "Non disturbare (sospende tutte le notifiche)");
  const group = h("input", { class: "input", type: "number", min: 1, max: 100, value: s.notifications.group_threshold });
  group.addEventListener("change", () => save("notifications", { group_threshold: Number(group.value) }, "Raggruppamento salvato"));

  const general = panel("generale", { body: [h("div", { class: "stack" }, dnd.el,
    field("Raggruppa oltre", group, "Se una ricerca trova almeno questo numero di annunci insieme, arriva un solo messaggio riassuntivo"),
    h("p", { class: "muted small", style: { margin: 0 } }, "Le regole per singola ricerca (solo nuovi, anche ribassi, soglia di prezzo) si impostano nel form della ricerca."))] });

  // ---------------------------------------------------------------- Windows
  const win = s.channels.windows;
  const windows = panel("windows", { actions: [channelSwitch("windows", "Notifiche Windows"), testBtn("windows")],
    body: [h("p", { class: "muted", style: { margin: 0 } }, win.available
      ? `Avviso di sistema con il numero di annunci trovati (libreria ${win.backend}).`
      : "Non disponibile su questo sistema: installa il pacchetto win11toast.")] });

  // ---------------------------------------------------------------- Telegram
  const token = h("input", { class: "input", type: "password", autocomplete: "new-password", spellcheck: "false",
    placeholder: s.telegram.token_set ? `token salvato (${s.telegram.token_hint}): lascia vuoto per non cambiarlo` : "123456789:ABC-DEF…" });
  const showTok = btn("mostra", { sm: true, onclick: () => {
    token.type = token.type === "password" ? "text" : "password";
    showTok.textContent = token.type === "password" ? "mostra" : "nascondi";
  } });
  const chat = h("input", { class: "input", spellcheck: "false", placeholder: "@nome_canale oppure 123456789", value: s.telegram.chatid });
  const tgSave = btn("Salva", { kind: "primary", type: "submit" });
  const tgClear = btn("Rimuovi token", { kind: "danger", sm: true, onclick: async () => {
    if (await save("telegram", { clear_token: true }, "Token rimosso")) { token.value = ""; token.placeholder = "123456789:ABC-DEF…"; }
  } });
  const tgForm = h("form", { class: "stack", autocomplete: "off" },
    field("Token del bot", h("div", { class: "input-group" }, token, showTok), "Lo trovi nel messaggio di @BotFather. Non viene mai mostrato per intero."),
    field("Chat ID", chat, "Nome del canale con la @ (il bot deve esserne amministratore) oppure id numerico"),
    h("details", { class: "small muted" }, h("summary", {}, "Come si configura?"),
      h("ol", {}, h("li", {}, "Scrivi a @BotFather su Telegram e crea un bot: ti dà il token."),
        h("li", {}, "Crea un canale e aggiungi il bot come amministratore."),
        h("li", {}, "Usa come Chat ID il nome del canale, es. @miei_annunci."))),
    h("div", { class: "row" }, tgSave, s.telegram.token_set ? tgClear : null));
  tgForm.addEventListener("submit", e => {
    e.preventDefault();
    busy(tgSave, async () => {
      if (await save("telegram", { token: token.value.trim(), chatid: chat.value.trim() }, "Telegram salvato")) {
        token.value = "";
        token.placeholder = `token salvato (${s.telegram.token_hint}): lascia vuoto per non cambiarlo`;
      }
    });
  });
  const telegram = panel("telegram", { actions: [channelSwitch("telegram", "Notifiche Telegram"), testBtn("telegram")], body: [tgForm] });

  // ---------------------------------------------------------------- ntfy
  const server = h("input", { class: "input", type: "url", placeholder: "https://ntfy.sh", value: s.ntfy.server });
  const topic = h("input", { class: "input", spellcheck: "false", placeholder: "miei-annunci-x7f3", value: s.ntfy.topic });
  const ntSave = btn("Salva", { kind: "primary", type: "submit" });
  const ntForm = h("form", { class: "stack" },
    field("Server", server),
    field("Topic", topic, "Chiunque conosca il topic può leggere le notifiche: usane uno difficile da indovinare"),
    h("div", { class: "row" }, ntSave));
  ntForm.addEventListener("submit", e => {
    e.preventDefault();
    busy(ntSave, () => save("ntfy", { server: server.value.trim(), topic: topic.value.trim() }, "ntfy salvato"));
  });
  const ntfy = panel("ntfy", { actions: [channelSwitch("ntfy", "Notifiche ntfy"), testBtn("ntfy")], body: [ntForm] });

  // ---------------------------------------------------------------- browser e suono
  const permText = h("span", {});
  const permBtn = btn("Consenti notifiche", { sm: true, kind: "primary" });
  const paintPerm = () => {
    const state = notificationSupport();
    const [cls, text] = {
      granted: ["ok", "permesso concesso"],
      default: ["warn", "il browser non ha ancora dato il permesso"],
      denied: ["err", "bloccate dal browser: riattivale dalle impostazioni del sito (icona a sinistra dell'indirizzo)"],
      insecure: ["warn", "non disponibili da un altro dispositivo (serve https): sul telefono usa Telegram o ntfy"],
      unsupported: ["err", "questo browser non supporta le notifiche"],
    }[state];
    clear(permText).append(led(cls), " ", text);
    permBtn.classList.toggle("hidden", state !== "default");
  };
  permBtn.onclick = async () => { await requestNotificationPermission(); paintPerm(); };
  paintPerm();

  const browserSwitch = switchEl(s.notifications.browser, async (checked, input) => {
    if (checked && notificationSupport() === "default") await requestNotificationPermission();
    paintPerm();
    if (!await save("notifications", { browser: checked }, `Notifiche del browser ${checked ? "attivate" : "disattivate"}`)) input.checked = !checked;
  });
  browserSwitch.input.setAttribute("aria-label", "Notifiche del browser: attive");
  const soundSwitch = switchEl(s.notifications.sound, async (checked, input) => {
    if (checked) playChime();   // il clic sblocca l'audio e fa sentire il suono scelto
    if (!await save("notifications", { sound: checked }, `Suono ${checked ? "attivato" : "disattivato"}`)) input.checked = !checked;
  });
  soundSwitch.input.setAttribute("aria-label", "Suono: attivo");

  // la prova passa dal server (evento -> connessione live -> questa pagina), come un avviso vero
  const serverTest = async channel => {
    if (store.live !== "on") return toast("Connessione live assente: l'avviso non arriverebbe. Ricarica la pagina.", "warning", 7000);
    try { await api.post(`/api/notifications/test/${channel}`); } catch (e) { toast(e.message, "error"); }
  };
  const testBrowser = btn("Prova", { sm: true, icon: "play", onclick: async () => {
    if (notificationSupport() === "default") await requestNotificationPermission();
    paintPerm();
    if (notificationSupport() !== "granted") return toast("Notifica non mostrata: manca il permesso del browser", "warning");
    serverTest("browser");
  } });
  const testSound = btn("Prova", { sm: true, icon: "play", onclick: () => serverTest("sound") });

  const line = (sw, title, hint, test) => h("div", { class: "row", style: { justifyContent: "space-between", flexWrap: "nowrap" } },
    h("div", {}, h("div", {}, title), h("div", { class: "muted small" }, hint)), h("div", { class: "row", style: { flexWrap: "nowrap" } }, sw.el, test));
  const browser = panel("browser_e_suono", { body: [h("div", { class: "stack" },
    line(browserSwitch, "Notifica del browser", "Compare anche se la scheda è in secondo piano; clic = apre l'annuncio", testBrowser),
    h("div", { class: "small" }, permText, " ", permBtn),
    line(soundSwitch, "Suono", "Due note brevi quando arriva un annuncio da notificare", testSound),
    h("p", { class: "muted small", style: { margin: 0 } },
      "Funzionano solo con l'app aperta in una scheda del browser (anche ridotta a icona). Seguono le stesse regole degli altri canali: non disturbare e regole della ricerca."))] });

  root.append(h("div", { class: "grid grid-2" }, general, browser), h("div", { class: "grid grid-2" }, telegram, ntfy), windows);
}
