# Subito Searcher

Controlla le tue ricerche su [subito.it](https://www.subito.it) e ti avvisa quando compaiono annunci nuovi
o quando un prezzo scende. Gira sul tuo PC, con un'interfaccia web in stile terminale; puoi ricevere gli avvisi
come notifiche di Windows, notifiche del browser, suono, Telegram o ntfy.

**Funzioni principali**

- Componi le ricerche con un form (parole chiave, località, categoria, prezzo, spedizione…): l'URL di
  subito.it si costruisce da solo. Se incolli un URL, il form si compila.
- *Anteprima risultati* prima di salvare una ricerca.
- Monitor automatico, con un intervallo e una fascia oraria per ogni ricerca, pause casuali tra le
  richieste e rallentamento automatico se il sito blocca.
- Annunci senza doppioni, con badge **NUOVO / RIBASSO / VENDUTO**, storico prezzi con grafico, preferiti e
  annunci nascosti.
- Statistiche di prezzo (minimo, mediana, media, massimo) ed esportazione CSV.
- Notifiche con regole per ricerca, *non disturbare* e raggruppamento.
- Backup e ripristino, avvio con Windows, accesso facoltativo dal telefono protetto da PIN.

## Requisiti

- Windows 10/11. Funziona anche su Linux e macOS, ma senza le notifiche di sistema e l'avvio automatico.
- Python 3.10 o superiore (testato con 3.13), scaricabile da <https://www.python.org>. Durante l'installazione
  spunta "Add python.exe to PATH".

## Installazione e avvio

Doppio clic su **`avvia.bat`**. Cosa succede:

1. al primo avvio crea un ambiente virtuale in `.venv`;
2. installa le dipendenze (in seguito le reinstalla solo se `requirements.txt` cambia);
3. avvia il server e apre il browser su <http://127.0.0.1:8000>.

Lascia aperta la finestra nera: se la chiudi, l'app si ferma.

Da terminale:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python server.py --open
```

Con `--port 8080` usa un'altra porta. La documentazione interattiva delle API è su <http://127.0.0.1:8000/docs>.

**Tenerla sempre accesa.** In *Impostazioni → avvio* attiva entrambe le opzioni:

- *Avvia Subito Searcher all'accesso a Windows*: il server parte in background, senza finestra;
- *Avvia il monitor quando parte l'app*.

L'interfaccia resta raggiungibile su <http://127.0.0.1:8000> (conviene salvarla nei preferiti). Per fermarla
usa il pulsante *Chiudi l'app* nello stesso pannello.

L'avvio automatico crea il file `Subito Searcher.vbs` nella cartella *Esecuzione automatica* dell'utente. Non
tocca il registro e non chiede privilegi di amministratore: per disattivarlo basta togliere l'opzione o
cancellare il file.

## Primo utilizzo

1. Apri **Ricerche → Nuova ricerca** (tasto `n`).
2. Prepara la ricerca in uno dei due modi:
   - incolla nel campo *Hai già un URL?* l'indirizzo di una ricerca fatta su subito.it;
   - oppure compila i campi: per esempio parole chiave `iphone 13`, località `Padova`, categoria
     *Telefonia*, prezzo massimo `400`.
3. Premi **Anteprima risultati** per vedere cosa troverebbe, con le miniature.
4. Facoltativo: aggiungi le parole da escludere (es. `rotto, ricambi, cover`) e regola l'intervallo e le
   notifiche della ricerca.
5. Premi **Salva**. Il primo controllo parte subito e non manda notifiche: gli annunci già online diventano
   la base di partenza.
6. Avvia il monitor dalla **Dashboard** o con **Ctrl+K → Avvia monitor**.
7. Configura almeno un canale in **Notifiche** e premi *Invia test* (o *Prova*).

## Interfaccia

Nella barra in alto, in ogni sezione, c'è sempre l'indicatore del monitor: conto alla rovescia al prossimo controllo, spinner durante il controllo e "✓ aggiornato 14:46 · 2 nuovi" per qualche secondo quando finisce.

Tema scuro "terminale" con accento verde; il tema chiaro si attiva dal pulsante in alto a destra. Tutti i colori
sono variabili CSS in `webapp/static/css/theme.css`. Il layout funziona anche su schermi piccoli.

| Sezione | Cosa fa |
|---|---|
| **Dashboard** | a schermo intero (scorrono solo i pannelli): contatori in una riga, gli ultimi 40 annunci per data di pubblicazione (si aggiornano da soli; durante un controllo compare lo spinner); a lato stato del monitor e log in tempo reale alto quanto lo schermo (righe più recenti in basso, colori secondo il contenuto) |
| **Ricerche** | elenco con stato, errori e numero di annunci; esegui ora, attiva/disattiva, duplica, elimina; esporta/importa JSON |
| **Nuova/modifica ricerca** | i campi di ricerca, l'URL generato in tempo reale (*Copia*, *Apri su subito.it*), l'anteprima, intervallo e fascia oraria della ricerca, regole di notifica |
| **Annunci** | filtri e statistiche fissi in alto, scorre solo l'elenco; annunci senza doppioni, filtri, ordinamento, statistiche di prezzo, preferiti ⭐, nascosti, export CSV, dettaglio con storico prezzi |
| **Monitor** | avvio e arresto, prossimo controllo, impostazioni dello scheduler, salute di ogni ricerca, ultime risposte di subito.it |
| **Notifiche** | Windows, browser, suono, Telegram, ntfy: interruttori e pulsanti di prova; non disturbare; raggruppamento |
| **Log** | console in tempo reale con livelli colorati, filtri, ricerca nel testo, pausa |
| **Impostazioni** | avvio con Windows, chiusura dell'app, pulizia degli annunci vecchi, backup e ripristino, export/import delle ricerche, accesso dalla rete locale |

**Scorciatoie**

- **Ctrl+K** apre la barra dei comandi. Da lì puoi creare una ricerca, eseguirle tutte, avviare o
  fermare il monitor, esportare in CSV, fare un backup, andare a una sezione, oppure eseguire, modificare
  o aprire gli annunci di una ricerca.
- Da tastiera: `n` nuova ricerca, `d` dashboard, `r` ricerche, `a` annunci, `m` monitor, `l` log.

### Screenshot descritti

**Dashboard**
- A sinistra la barra laterale scura con il logo `>_ subito-searcher` e le sette sezioni (quella attiva è
  evidenziata in verde). In basso tre LED con un testo accanto: *monitor* (attivo/fermo), *subito.it* (ok o
  errori), *live* (connessione in tempo reale).
- In alto il prompt `> dashboard` con il cursore che lampeggia e, accanto, l'indicatore del monitor
  (`⏱ prossimo controllo tra 4:37`, lo spinner durante i controlli, `✓ aggiornato` quando finiscono); a destra
  il pulsante *comandi Ctrl K* e il cambio tema.
- Sotto, una riga compatta di contatori: ricerche attive, annunci, nuovi oggi, venduti, preferiti.
- A sinistra, la colonna principale `~/ultimi_annunci`: miniatura, titolo, località, "pubblicato 10 min fa",
  badge e prezzo; gli annunci appena arrivati lampeggiano in verde. In alto il pulsante *Aggiorna ora*.
- A destra, una colonna alta quanto lo schermo che resta ferma mentre scorri: lo stato del monitor e sotto
  il `~/log` in tempo reale, con le righe più recenti in basso. Ogni riga ha un colore secondo il contenuto
  (verde nuovi annunci, ciano ribassi e ricerche in corso, viola venduti e notifiche, ambra avvisi, rosso
  errori, grigio controlli senza novità) e le righe nuove entrano dal basso con un lampo verde e un cursore.

**Nuova ricerca**
- In cima il campo *Hai già un URL?*.
- Sotto, il form su griglia:
  - nome;
  - parole chiave con l'interruttore *solo nel titolo*;
  - località con un menu a tendina che propone comuni, province e regioni mentre scrivi ("Padova (PD)",
    "Padova (provincia)", "Veneto");
  - categoria con ricerca;
  - tipo di annuncio, prezzo min/max, *solo con spedizione*, ordinamento, parole da escludere.
- Un riquadro in stile riga di comando mostra l'URL generato, con i pulsanti *Copia* e *Apri su subito.it*.
  Eventuali avvisi compaiono in ambra, per esempio "il prezzo su Tutte le categorie lo applica l'app".
- In basso *Anteprima risultati* apre una finestra con il numero di annunci letti e validi e una lista con
  miniature e prezzi.

**Annunci**
- Una barra di filtri (ricerca, testo, prezzo, ordinamento, spedizione) e una fila di "chip": tutti, nuovi,
  ribassi, venduti, preferiti, nascosti.
- Sotto, una striscia di statistiche in carattere monospazio: `ANNUNCI 5 · MINIMO € 210 · MEDIANA € 340 ·
  MEDIA € 335 · MASSIMO € 450`.
- Ogni annuncio è una riga con:
  - la miniatura;
  - il titolo cliccabile, la località e "trovato 2 h fa";
  - i badge colorati: verde *NUOVO*, ciano *RIBASSO −40 €*, rosso *VENDUTO*, viola *SPEDIZIONE*;
  - a destra il prezzo grande (quello vecchio barrato in caso di ribasso) e le icone stella, occhio e grafico.

**Storico prezzi**
- Il pulsante con l'icona del grafico apre una finestra con i dati dell'annuncio e il pannello `~/storico_prezzi`.
- Il riepilogo dice per esempio "€ 520 → € 450 (−13%)".
- Il grafico è a gradini verdi, con un punto per ogni rilevazione. Passando il mouse compaiono una linea
  tratteggiata e l'etichetta "€ 490 (−30 €) · 07/10/26, 14:21".
- Il pulsante *tabella* mostra gli stessi dati in righe.

**Monitor**
- A sinistra un LED grande con lo stato ("Attivo", "Controllo in corso", "In pausa", "Pausa di sicurezza");
  a destra il form dello scheduler.
- Sotto, la tabella *salute_ricerche*, con un LED, gli errori di fila e il prossimo controllo per ogni
  ricerca, e la tabella delle ultime risposte di subito.it con l'esito e la durata.

**Notifiche**
- Pannelli affiancati: *generale* (non disturbare, raggruppamento), *browser_e_suono* (con lo stato del
  permesso del browser), *telegram* (token nascosto con "mostra"), *ntfy* e *windows*.
- Ogni canale ha un interruttore e un pulsante *Invia test* o *Prova*.

**Log**
- Una console a tutta larghezza con righe del tipo `14:21:05 [nuovi] 'iPhone Padova': 2 nuovi annunci`.
- Il colore dipende dal livello: grigio per le informazioni, verde per i successi, ambra per gli avvisi,
  rosso per gli errori.
- In alto ci sono i filtri e i pulsanti *pausa*, *segui* e *pulisci*.

**Telefono**
- La barra laterale diventa un menu a scomparsa, i pannelli si dispongono su una colonna e le tabelle
  nascondono le colonne secondarie.

## Notifiche

| Canale | Come funziona | Note |
|---|---|---|
| **Windows** | avviso di sistema con il numero di annunci | libreria `win11toast`; se manca, nessun errore. Se non vedi nulla, controlla *Non disturbare* / *Assistente notifiche* di Windows |
| **Browser** | notifica del browser; un clic apre l'annuncio | serve l'app aperta in una scheda (anche ridotta a icona) e il permesso del browser. Non disponibile dal telefono via `http://192.168…` (i browser la consentono solo in https o su 127.0.0.1) |
| **Suono** | due note brevi generate dalla pagina | serve l'app aperta; il browser abilita l'audio dopo il primo clic sulla pagina |
| **Telegram** | un messaggio per annuncio, con titolo, prezzo, località e link | serve un bot (@BotFather) e un canale in cui il bot è amministratore |
| **ntfy** | notifica push su telefono tramite <https://ntfy.sh> o un server proprio | usa un topic difficile da indovinare: chi lo conosce legge le notifiche |

**Regole**
- **Per ricerca** (nel form): notifica i nuovi annunci, notifica anche i ribassi, soglia di prezzo
  (es. "solo se costa al massimo 300 €").
- **Globali**:
  - *non disturbare* sospende tutto;
  - il *raggruppamento* manda un solo messaggio riassuntivo quando una ricerca trova molti annunci
    insieme (5 per impostazione predefinita).
- Gli annunci nascosti non vengono più notificati, nemmeno se il prezzo scende.

## Annunci, statistiche ed esportazione

- **Deduplicazione**: lo stesso annuncio trovato da più ricerche è uno solo e viene notificato una volta.
- **Badge**:
  - **NUOVO**: trovato dopo l'ultima volta che hai premuto *Segna come visti*;
  - **RIBASSO**: il prezzo è sceso rispetto alla rilevazione precedente;
  - **VENDUTO**: segnalato come venduto da subito.it.
- **Statistiche**: calcolate sugli annunci che rispettano i filtri attivi, quindi cambiano con la ricerca,
  il testo e il prezzo selezionati.
  - I venduti sono esclusi, perché non sono più offerte disponibili; filtrando su *venduti* le statistiche
    riguardano solo quelli.
  - Sono esclusi anche gli annunci senza prezzo o a 0 €.
  - La *mediana* è il prezzo che sta a metà: risente poco degli annunci fuori scala ed è il riferimento più
    utile per capire "quanto costa di solito".
- **CSV**: il pulsante *CSV* esporta tutti gli annunci filtrati, non solo la pagina visibile.
  - Il file usa separatore `;` e UTF-8 con BOM, quindi Excel in italiano lo apre direttamente.
  - I titoli che iniziano con `=`, `+`, `-` o `@` vengono preceduti da un apostrofo, perché Excel non li
    esegua come formule.

## Monitoraggio

Il monitor gira dentro il server.

- **Giro unico (predefinito)**: allo scadere del conto alla rovescia tutte le ricerche vengono controllate
  insieme, una dopo l'altra, e il conto riparte per tutte. "Esegui ora" su una singola ricerca non la
  sfasa dalle altre, mentre "Aggiorna ora" vale come un giro completo. Si può tornare a calendari
  indipendenti per ricerca dall'impostazione *Controlla tutte le ricerche insieme* nel Monitor.
- **Intervalli e fasce orarie**:
  - ogni ricerca può avere un intervallo proprio (minimo 60 s); nel giro unico, se è più lungo di
    quello predefinito, la ricerca salta i giri finché non è il suo momento;
  - ogni ricerca può avere una propria fascia oraria;
  - fuori dalla fascia globale il monitor resta **in pausa**.
- **Pause tra le richieste**: le ricerche vengono eseguite una alla volta, con una pausa minima e un
  ritardo casuale (jitter).
- **Rallentamento dopo gli errori**:
  - se una ricerca fallisce, il controllo successivo viene rimandato del doppio, poi del quadruplo e
    così via (massimo 2 ore);
  - se subito.it blocca le richieste (403/429) si ferma tutto per 15 minuti, poi 30, 60, fino a 120.
- **Stato di salute**: ultime risposte con la loro durata, errori consecutivi per ricerca e un avviso se la
  struttura della pagina di subito.it sembra cambiata (dati della pagina illeggibili, oppure tutte le
  ultime ricerche trovano 0 annunci).
- **Errori**: un errore su una ricerca non ferma le altre, e lo scheduler non si interrompe per eccezioni
  impreviste.
- **Silenzio all'avvio**: il primo controllo dopo l'avvio non invia notifiche (impostazione
  `first_run_silent`), così un riavvio non rimanda tutto.
- **Manutenzione giornaliera**: pulizia degli annunci non più visti da N giorni (se impostata) e del log.
  I preferiti non vengono mai cancellati.

## Backup e sicurezza

- **Backup**: si creano dalle Impostazioni (in `data/backups/`) e si possono scaricare. Prima di ogni
  ripristino l'app salva una copia dello stato attuale, quindi si può sempre tornare indietro.
- **Ascolto e difese**: il server ascolta solo su `127.0.0.1`. Rifiuta le richieste con un Host diverso
  (difesa dal "DNS rebinding") e le modifiche che arrivano da altri siti aperti nel browser (CSRF).
- **Accesso dal telefono** (facoltativo):
  - in *Impostazioni → accesso_rete_locale* attivalo, scegli un PIN di 4–12 cifre e riavvia;
  - ogni dispositivo diverso dal PC deve inserire il PIN, con al massimo 5 tentativi ogni 5 minuti;
  - al primo avvio Windows chiede il permesso del firewall: consenti solo le reti private.
- **Dati personali**: il token Telegram e i dati personali stanno in `data/`, esclusa da git insieme ai file
  della versione precedente (`.gitignore`). Nell'interfaccia il token non viene mai mostrato per intero.

## Dati e migrazione dalla versione precedente

Tutto sta nel database SQLite `data/subito.db`: ricerche, annunci, storico prezzi, log e impostazioni.

Al **primo avvio** vengono importati automaticamente, una sola volta:

| File precedente | Cosa viene importato |
|---|---|
| `searches.tracked` | ricerche, prezzi min/max e annunci già trovati |
| `telegram_api_credentials` | token e chat id Telegram |
| `ntfy_config` | server e topic ntfy |
| `settings.json`, `app_state.json` | impostazioni della versione web precedente, se presenti |

I file originali **non vengono modificati né cancellati** e restano come backup. Dopo l'import non vengono
più aggiornati. Le ricerche importate diventano ricerche "per parametri" (modificabili dal form) quando l'URL
è riconosciuto; le altre restano valide come "solo URL".

## Riga di comando

Le opzioni sono le stesse della versione originale e lavorano sullo stesso database dell'interfaccia web:

```bat
python subito-searcher.py --add Auto --url "https://www.subito.it/annunci-italia/vendita/usato/?q=auto" --minPrice 50 --maxPrice 100
python subito-searcher.py --add iPhone --url "https://www.subito.it/annunci-italia/vendita/telefonia/?q=iphone" --exclude "rotto, ricambi, cover"
python subito-searcher.py --short_list
python subito-searcher.py --list
python subito-searcher.py --refresh
python subito-searcher.py --daemon --delay 120 --activeHour 8 --pauseHour 23
python subito-searcher.py --delete Auto
python subito-searcher.py --addtoken "TOKEN" --addchatid "@canale"
python subito-searcher.py --ntfy_server https://ntfy.sh --ntfy_topic mio-topic
```

- `--exclude` (nuova): parole da escludere dai titoli, separate da virgola.
  - Il confronto ignora maiuscole e accenti.
  - Lavora dall'inizio delle parole: `rott` esclude "rotto" e "rotta", ma `cover` non esclude "discovery".
- `--tgoff`, `--notifyoff`, `--ntfyoff` disattivano un canale solo per quell'esecuzione.
- `--add` con un nome già esistente sostituisce la ricerca, come nella versione originale.
- Non avviare `--daemon` mentre il monitor della web app è attivo: le stesse ricerche verrebbero
  controllate due volte.

Strumento di prova per gli URL:

```bat
python tools/urltool.py luoghi Pad
python tools/urltool.py costruisci --parole "iphone 13" --luogo "Padova (PD)" --categoria telefonia --max 400 --spedizione
python tools/urltool.py analizza "https://www.subito.it/annunci-veneto/vendita/elettronica/?q=tv"
python tools/urltool.py anteprima "https://www.subito.it/annunci-veneto/vendita/telefonia/?q=iphone" --escludi "rotto, cover"
```

## URL di subito.it: cosa è verificato e cosa no

Il formato è documentato nel codice (`core/urlbuilder.py`). Tutto quello che segue è stato verificato sul
sito reale, anche con test automatici (`python -m pytest -m live`).

- **Percorso**: `/annunci-{regione|italia}/{vendita|cerco|affitto|regalo|affitto-vacanze}/{categoria|usato}/{provincia}/{comune}/`.
  Uno slug inesistente restituisce 404.
- **Parametri**:
  - `q` parole chiave;
  - `qso=true` cerca solo nel titolo;
  - `shp=true` solo annunci con spedizione;
  - `ps`/`pe` prezzo minimo e massimo in euro;
  - `order` ordinamento: `datedesc`, `relevance`, `priceasc`, `pricedesc`, più anno e chilometri per auto e moto.
- **Il filtro prezzo del sito funziona solo con una categoria specifica**: su "Tutte le categorie" viene
  ignorato. Per questo il prezzo viene sempre filtrato anche dall'app sui risultati.
- **Ordinamento**: in molte categorie quello predefinito del sito è "rilevanza". Le nuove ricerche usano
  "più recenti", così gli annunci nuovi compaiono in prima pagina.

**Non verificabile, quindi non gestito dal form**
- I filtri specifici di alcune categorie (marca/modello/anno delle auto, metri quadri degli immobili, taglie…)
  hanno parametri diversi per categoria e non documentati. Restano utilizzabili incollando l'URL completo:
  la ricerca viene salvata come "solo URL" e funziona normalmente.
- subito.it può cambiare questi formati senza preavviso. Se succede, il Monitor mostra l'avviso "struttura
  cambiata". I dati di località e categorie si rigenerano con:

```bat
python tools/build_geo.py          :: 20 regioni, 110 province, 7.911 comuni (core/resources/geo.json)
python tools/build_categories.py   :: 45 categorie con tipi e ordinamenti (core/resources/categories.json)
```

La fonte sono le API pubbliche usate dal sito (`hades.subito.it`), perché gli URL usano province e nomi di
subito, che non coincidono sempre con ISTAT. Per esempio subito ha le nuove province sarde, mantiene alcuni
comuni già fusi e distingue gli omonimi con la sigla ("Calliano TN"). L'elenco ISTAT serve come controllo
incrociato e per i nomi con gli accenti corretti.

## Risoluzione dei problemi

| Problema | Soluzione |
|---|---|
| "La porta 8000 è già in uso" | l'app è già avviata (magari in background): apri <http://127.0.0.1:8000>. Oppure usa `server.py --port 8080` |
| Pausa di sicurezza / errori 403 o 429 | subito.it sta limitando le richieste: il monitor riprende da solo. Allunga gli intervalli o riduci il numero di ricerche |
| Avviso "struttura cambiata" | il sito ha cambiato le pagine: controlla se esiste una versione aggiornata del programma |
| Le notifiche di Windows non compaiono | disattiva *Non disturbare* di Windows e prova *Invia test*; controlla che in Notifiche il canale sia attivo |
| La notifica del browser non arriva | il permesso dev'essere "concesso" (pannello *browser_e_suono*) e l'app aperta in una scheda; dal telefono usa Telegram o ntfy |
| Telegram: "chat not found" | il bot deve essere amministratore del canale; il chat id va scritto con la `@` |
| Nessun annuncio trovato | prova l'URL con *Apri su subito.it* e controlla le parole escluse e il prezzo |

## Sviluppo e test

```bat
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest              :: test offline (parser con pagina reale salvata, filtri, URL builder, API...)
.venv\Scripts\python -m pytest -m live      :: verifica gli URL generati su subito.it reale (richiede internet)
```

## Cosa cambia rispetto alla versione originale

- **Compatibilità con il sito attuale**: subito.it ha cambiato la struttura dei dati (`items.originalList`) e
  lo script originale trovava sempre 0 annunci senza segnalarlo. Ora vengono letti sia il formato nuovo sia
  quello vecchio.
- **Deduplicazione, storico prezzi, ribassi e venduti**.
- **Pausa con jitter** tra le richieste consecutive, per non sovraccaricare il sito.
- **Errori** (rete, blocco 403/429, struttura cambiata) registrati nel log, senza interrompere le altre ricerche.
- **Bug corretti**:
  - annunci senza spedizione saltati in silenzio;
  - "spedizione: No" letta come disponibile;
  - `TypeError` sulla spedizione mancante e nel gestore degli errori;
  - `import` duplicato e shebang `python3.7`;
  - header HTTP con virgolette dentro i valori;
  - Telegram: l'URL era costruito a mano e il Markdown si rompeva con i caratteri speciali (ora si usano
    `params=` e HTML con escape);
  - `win10toast` sostituito da `win11toast`, con fallback silenzioso.

## Struttura del progetto

```
core/          logica senza interfaccia: db (SQLite e migrazioni), repo (query), scraper, filtri,
               notifiche, engine, monitor (scheduler), import, eventi, urlbuilder, geo, categorie,
               service, exporting (CSV), autostart
core/resources dati di località e categorie
tools/         rigenerazione dei dati e urltool.py
webapp/        FastAPI: main.py (API REST e SSE), security.py (Host, CSRF, PIN)
webapp/static  frontend senza build: css/theme.css (tutti i colori), css/app.css, js/ (moduli ES)
tests/         test pytest (tests/fixtures: pagina reale di subito.it ridotta)
server.py      avvio del server web
avvia.bat      avvio con doppio clic (virtualenv + dipendenze + browser)
subito-searcher.py   riga di comando
```
