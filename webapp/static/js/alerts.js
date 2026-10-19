// Avvisi nella pagina: notifica del browser e suono.
// Il server decide se e cosa notificare (regole della ricerca, non disturbare, impostazioni) e manda
// un evento con il campo `alert`; qui lo si mostra. Funziona solo con l'app aperta in una scheda.

const MAX_AGE_MS = 2 * 60 * 1000;   // eventi ripetuti dopo una riconnessione: niente avvisi vecchi
const LAST_KEY = "lastAlertId";

let audio = null;

/** Il browser permette l'audio solo dopo un gesto dell'utente: il contesto si prepara al primo clic/tasto. */
function unlockAudio() {
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    if (audio.state === "suspended") audio.resume();
  } catch { audio = null; }
}
for (const type of ["pointerdown", "keydown"]) window.addEventListener(type, unlockAudio, { once: true, capture: true });

/** Due note brevi e morbide (generate, nessun file audio). */
export function playChime() {
  unlockAudio();
  if (!audio) return false;
  const now = audio.currentTime;
  [[880, 0], [1318.5, 0.13]].forEach(([freq, delay]) => {
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, now + delay);
    gain.gain.exponentialRampToValueAtTime(0.18, now + delay + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + delay + 0.35);
    osc.connect(gain).connect(audio.destination);
    osc.start(now + delay);
    osc.stop(now + delay + 0.4);
  });
  return audio.state === "running";
}

export function notificationSupport() {
  if (!("Notification" in window)) return "unsupported";
  if (!window.isSecureContext) return "insecure";          // es. aperta dal telefono via http://192.168…
  return Notification.permission;                          // default | granted | denied
}

export async function requestNotificationPermission() {
  if (notificationSupport() !== "default") return notificationSupport();
  return Notification.requestPermission();
}

export function showNotification(title, body, link) {
  if (notificationSupport() !== "granted") return false;
  const n = new Notification(title, { body, tag: link || title, lang: "it" });
  n.onclick = () => {
    window.focus();
    if (link) window.open(link, "_blank", "noopener");
    else location.hash = "#/annunci?status=new";
    n.close();
  };
  return true;
}

/** Con più schede aperte l'avviso parte una volta sola (la prima che lo riceve). */
function claim(id) {
  try {
    // {id, t}: dopo MAX_AGE_MS il valore non conta più (es. database ripristinato con id più bassi)
    const last = JSON.parse(localStorage.getItem(LAST_KEY) || "null");
    if (last && last.id >= id && Date.now() - last.t < MAX_AGE_MS) return false;
    localStorage.setItem(LAST_KEY, JSON.stringify({ id, t: Date.now() }));
  } catch { /* senza localStorage: ogni scheda avvisa */ }
  return true;
}

export function handleAlertEvent(event) {
  const a = event.alert;
  if (!a) return;
  if (Date.now() - new Date(event.time).getTime() > MAX_AGE_MS) return;
  if (event.id && !claim(event.id)) return;
  if (a.sound) playChime();
  if (a.browser) showNotification(a.title, a.body, a.link);
}
