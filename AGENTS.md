## Regole di Comunicazione e Stile

- Parla e pensa sempre in **ITALIANO**.
- Nomi variabili/funzioni/classi: **INGLESE**.
- Commenti e Docstring: **ITALIANO**.
- Log strings: **INGLESE**.


## Proxmox

In questo progetto l'agente aiuta l'utente a gestire al meglio
la piattaforma proxmox installata in rete locale e attiva 24h.
Ha 2 funzioni principali:
1) Ospita vari ctx e vm, sia linux che windows.
2) Gestisce una condivisione di vari hard disk magnetici 
wd red da 4Tb (formattati zfs) come farebbe un NAS.
Gli hd sono connessi tramite usb4 tramite case esterni.
L'hardware su cui gira proxmox è un minipc:
GEEKOM Mini PC IT13 2025 Edizione,
Intel i9-13900HK Processore(14 Core, 20 Thread,fino a 5.4 GHz),
32 GB RAM DDR4 + 1TB SSD, 
8K Iris Xe Grafica|USB 4.0

## Backups

Uno dei principali task di questa macchina proxmox è fare backup settimanali
da dataset NAS (`main-pool`) verso il disco esterno `/mnt/onebackup`.
Se l'utente chiede di verificare i backup, controlla lo stato dei job
schedulati con destinazione `onebackup` (non confondere con vzdump VM/CT).
Fino al 15 giugno 2026 c'erano fallimenti perché `onebackup` non era montato;
è stato risolto, non menzionarlo salvo richiesta esplicita.

### Architettura

| Componente | Ruolo |
|------------|-------|
| `mirror_scheduler` | Servizio systemd che legge lo schedule e lancia i job |
| `mirror.py` | Mirror incrementale cartella → cartella |
| `bigsplitter.py` | Backup a chunk del file `data2.hc` (solo chunk modificati) |
| `pool_standby` | Mette in standby i dischi NAS dopo 20 min di idle |

I job con `run_after` nel JSON partono in sequenza subito dopo il job padre,
senza attendere un orario: serve a tenere il disco `onebackup` attivo e
evitare il parking tra backup della stessa domenica.

### File (repo locale → server)

| Locale | Server |
|--------|--------|
| `services/mirror_setup.json` | `/home/admin/bin/services/mirror_setup.json` |
| `src/mirror_scheduler.py` | `/home/admin/pyscripts/mirror_scheduler.py` |
| `src/mirror.py` | `/home/admin/pyscripts/mirror.py` |
| `src/bigsplitter.py` | `/home/admin/pyscripts/bigsplitter.py` |
| `src/health_check.py` | `/home/admin/pyscripts/health_check.py` |
| `services/mirror_scheduler.service` | `/home/admin/bin/services/mirror_scheduler.service` |
| `services/onebackup-vzdump.storage` | append in `/etc/pve/storage.cfg` |

Dopo modifiche a schedule o script: `scp` su server + `systemctl restart mirror_scheduler`.
Per il file `.service` usare `update_service.py` sul server.

### Schedule attuale (`mirror_setup.json`)

```
         DOM                    LUN/MER/VEN       MAR/GIO/SAB
       ─────                    ───────────       ───────────
05:00  media ──▶ home ──▶ cloud ──▶ vzdump-ct ──▶ healthcheck   07:00 data      07:00 you
       (catena run_after)                      (split)         (mirror)
```

| Job | Tipo | Trigger | Sorgente | Destinazione | Dim. ~ |
|-----|------|---------|----------|--------------|--------|
| media | mirror | dom 05:00 | `/mnt/main-pool/media` | `/mnt/onebackup/media` | 163G |
| home | mirror | `run_after` media | `/home/admin` | `/mnt/onebackup/home` | 300M |
| cloud | mirror | `run_after` home | `/mnt/main-pool/cloud` | `/mnt/onebackup/cloud` | 1.6T |
| vzdump-ct | vzdump | `run_after` cloud | CT 102,103,104 | `/mnt/onebackup/vzdump` | ~35G |
| healthcheck | healthcheck | `run_after` vzdump-ct | — | Telegram | — |
| data | split | lun/mer/ven 07:00 | `/mnt/main-pool/data/data2.hc` | `/mnt/onebackup/data` | 650G |
| you | mirror | mar/gio/sab 07:00 | `/mnt/main-pool/you` | `/mnt/onebackup/you` | 2.0T |

Campi JSON job: `type` (`mirror`|`split`|`vzdump`|`healthcheck`), `enabled`, `day`, `hour`, `minute`,
`source`, `destination`. Opzionale: `run_after` = `source` del job padre
(esclude il job dallo schedule orario).
Per `vzdump`: `storage`, `vmids` (lista VMID), `keep_last` (retention).

**vzdump CT** (102 dualbot, 103 ticksaver, 104 lobsaver): domenica in catena dopo cloud,
storage `onebackup-vzdump` → `/mnt/onebackup/vzdump`, `keep-last=2`.
VM Windows (100, 101) escluse. Log in journal + file in `/mnt/onebackup/vzdump/dump/`.

**healthcheck**: domenica dopo vzdump, esegue `health_check.py` → Telegram con stato host
e **ultimo backup** di ogni job (data/ora, durata, dimensione, OK/ERR).
**pool_standby** non invia più Telegram (solo log). SMART errori ancora via `smart_check.py`.

### Destinazione onebackup

- Disco ext4 su USB, montato via **autofs** su `/mnt/onebackup`
- Se non montato i job falliscono con: `source folder ... and dest folder ... MUST exists`
- Verifica: `mountpoint /mnt/onebackup` e `df -h /mnt/onebackup`

### Log e come leggere il successo

| Job | Log | Riga di successo |
|-----|-----|------------------|
| mirror | `<dest>/mirror.log` | `End Mirror  <src> => <dst>, SIZE:... COPIED:... DELETED:...` |
| split | `<dest>/logs/backup.log` | `completed split and backup of ... N chunks updated.` |
| vzdump | journal + `/mnt/onebackup/vzdump/dump/` | `end vzdump : 102 103 104 => onebackup-vzdump` |

Journal systemd (sempre utile):
```bash
journalctl -u mirror_scheduler --since "14 days ago" --no-pager | grep -E "Command failed|start mirror|start split|start vzdump|end mirror|end split|end vzdump|run_after"
```
- **OK**: `end mirror` / `end split` / `end vzdump` senza `Command failed` prima
- **KO**: `Command failed` + messaggio (tipico: destinazione non montata)

### Procedura rapida di controllo

Connetti via SSH host `proxmox-root` (10.1.1.70, user root, chiave `~/.ssh/proxmox`).

```bash
# 1. Servizio e prossimo job
systemctl is-active mirror_scheduler
journalctl -u mirror_scheduler -n 5 --no-pager

# 2. Mount destinazione
mountpoint /mnt/onebackup && df -h /mnt/onebackup

# 3. Schedule sul server
cat /home/admin/bin/services/mirror_setup.json

# 4. Ultimo successo per job (tail log)
tail -2 /mnt/onebackup/media/mirror.log
tail -2 /mnt/onebackup/home/mirror.log
tail -2 /mnt/onebackup/cloud/mirror.log
tail -2 /mnt/onebackup/you/mirror.log
tail -2 /mnt/onebackup/data/logs/backup.log
ls -lt /mnt/onebackup/vzdump/dump/ | head -5

# 5. Errori recenti
journalctl -u mirror_scheduler --since "14 days ago" --no-pager | grep "Command failed"
```

Evita `du -sh` su cartelle grandi (cloud/you): impiega molti minuti.
Per confronto dimensioni usa i log `SIZE:` o `du` solo se esplicitamente richiesto.

### Cosa riportare all'utente

Per ogni job: ultimo run riuscito (data/ora dal log), eventuali errori nel journal,
stato mount `onebackup`, prossimo job schedulato (ultima riga `next mirror @` nel journal).
Segnala se un job mirror ha `COPIED:0` a lungo (probabilmente già allineato, non errore).
Segnala se dst è molto più grande di src su cloud (possibili file eliminati non ripuliti).

## Rete LAN

Mappa IP e dispositivi: fonte unica `L:\Logon\network.txt`, esposta nel progetto come symlink `docs/network.txt` (non versionare, non copiare nel repo).

## SSH

La connessione dell'agente la macchina proxmox può essere fatta
tramite ssh, usando le credenziali del sistema o del file .env

## Fai Domande

Prima di implementare cambiamenti chiarisci i requisiti.
Se nel task l'utente non ha specificato qualcosa e devi prendere una 
decisione, non farlo, fai invece la domanda all'utente. 
Per ogni domanda, proponi anche la risposta raccomandata. 
Usa vscode_askQuestions se disponibile, o il tool dell'ambiente 
per gestire le domande all'utente. 
Se dalle sue risposte nascono altre domande fai anche quelle, 
senza nessun limite.
Più domande fai migliore sarà il risultato.


## Direttive di sviluppo codice

Quando sviluppi delle parti di codice operativo, tieni molto presente che 
questo progetto è **gestito da 1 solo dev** , quindi non servono linee guida
rigide, non servono controlli dei parametri o altre verifiche prudenziali
su validità di dati o percorsi di esecuzione perchè sono gestiti da un solo
utente che non metterà dati non validi nelle chiamate.

Usa sempre le seguenti direttive: 

D1) **IMPORTANTE: CODICE SINTETICO** 
Quando devi scrivere nuovo codice devi farlo in modo asciutto, cioè:
- devi usare pochi metodi di media lunghezza, quindi non tanti metodi piccoli
- non devi gestire tutti i corner case dei parametri 
- controllo parametri minimale o assente
- il codice nuovo deve essere SEMPRE minimale perchè deve essere considerato
da chi ancora non l'ha visto, l'utente vuole vedere il core del funzionamento,
in poche righe da cui si capice il meccanismo di base, come nel caso di un POC.
Se ogni 3 righe ci sono controlli di validità di variabili, dati, esistenza di 
funzioni o altra roba che spesso si trova nel codice di produzione, si crea un
overhead di sviluppo che nasconde spesso dei meccanismi belli e semplici.

D2) **IMPORTANTE: NO VALORI DI DEFAULT**
Ovunque ci sia la possibilità di inserire valori di default 
o fallback o if else che evitano un'eccezione, NON LO FARE. 
E' importante che se, per qualche motivo,
non c'è il dato, la variabile o il valore corretto, l'app vada in eccezione
spiegando bene l'errore. Quindi
- non mettere valori di default nei metodi se non strettamente necessari
- non mettere if else che nascondono errori o mancanze di dati
- non creare percorsi di fallback logici se non strettamente necessari
- qualsiasi problema non previsto deve scatenare un eccezione ben loggata e un uscita.

D3) Quando ti chiedo una qualche modifica che inficia parametri
delle funzioni già esistenti **NON garantire retrocompatibilità** 
per chiamate della funzione prima della modifica.
E' un app in sviluppo, è normale che le firme delle funzioni cambino
e che non funzionino più se chiamate con la firma vecchia, se tieni 
sempre tutto il codice vecchio si complica e allunga
la codebase in modo notevole e va evitato.

D4) Gestione delle eccezioni: quando possibile gestisce le eccezioni
in modo generico in metodi superiori della pipeline di esecuzioni,
non mettere messaggi di eccezione personalizzati dentro ogni controllo
di ogni metodo.


## Policy di stile di codice

Quando scrivi codice devi rispettare alcune regole di stile e formattazione:
- devi preferire sempre le chiamate di funzione e metodi con i parametri in una linea, 
senza andare a capo ad ogni parametro. Se proprio la linea è troppo lunga,
vai capo con blocchi di parametri, non un parametro per riga. 
Esempio :
results = function(
    parametro_a:type_a, parametro_b:type_b, parametro_c;type_c,
    parametro_d:type_d, parametro_e:type_e, parametro_e;type_e)

- non mettere la parentesi chiusa di fine chiamata della funzione a capo, deve essere inline,
a meno che non ci sia un lungo type hint di ritorno della funzione per cui serve un'altra riga.
Esempio:
results = function1(
    parametro_a:type_a, parametro_b:type_b, parametro_c;type_c)

results = function2(
    parametro_a:type_a, parametro_b:type_b, parametro_c;type_c
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:

- tra un metodo e l'altro lascia 2 righe vuote, non solo 1.

- in try except preferisce sempre stile inline quando righe non troppo lunghe.
Esempio:
try: parsed["SLR"] = float(raw)
except ValueError: continue

- negli if preferisce sempre stile inline quando righe o blocchi non lughi.
Esempio:
if tf <= 0 : raise Exception(f"invalid TF in combo key: {tf}")

- nei return di oggetti con molti campi preferisci sempre la versione inline,
creando righe di medio-lunghe ma cmq leggibili.
Esempio:
return { "tf": tf, "per": per, "slr": slr, "agl": agl, "agh": agh,
        "so": so, "trt": trt, "trh": trh, "trm": trm, 
        "has_trailing": has_trailing, "combo_string": combo_string }

- delle definizioni di funzioni con molti parametri preferisce 
sempre i parametri inline dove possibile con lunghezza medio-lunga della riga.
Esempio:
def kernel(ask: np.ndarray, bid: np.ndarray, spread: np.ndarray, atr: np.ndarray,
        smatr: np.ndarray, hh: np.ndarray, ll: np.ndarray, open_signal: np.ndarray,
        slr: float, so: int, candle_id: np.ndarray, point_value: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:


## Formattazione JSON
Quando devi creare json devono sempre essere formattati usando 
come indentazione 4 spazi.


## Policy del piano di lavoro

Attiva questa procedura solo se il prompt dell’utente contiene esplicitamente la keyword `#plan-<nome>`. 
Es. di prompt: 
"fai il piano #plan-rework  ... e la spiegazione del piano"
allora devi creare un piano chiamato 'rework'.

Se la keyword `#plan-<nome>` non è presente rispondi normalmente alla richiesta dell’utente.

Se la keyword `#plan-<nome>` è presente, segui queste regole:

- La cartella in cui va creato il piano è `./docs/plans/`. Se non esiste devi crearla.
- Il nome completo del file del piano sarà : `./docs/plans/plan-<nome>.md`,
nell'es. quindi `./docs/plans/plan-rework.md`
- Se il file del plan fornito non esiste, crealo, se esiste aggiornalo.
- Usa il file del plan fornito come riferimento principale per il piano del task corrente.
- Scrivi il piano direttamente nel file, non lasciarlo solo nella chat.
- Non iniziare l’implementazione finché il file di piano non è stato approvato esplicitamente dall'utente.
- Quando inizia l’implementazione, mantieni il file del plan allineato con l’avanzamento e marca i passi completati.
- Se il task cambia significativamente, aggiorna il piano prima di procedere con nuove modifiche.
- **IMPORTANTE** Mentre fai il piano cerca tutti i punti dubbi in cui poter fare 
domande all'utente e **fai le domande**, non importa se sono molte, 
più domande fai più aderente sarà il piano al volere dell'utente e 
meno tempo si perderà dopo per correggerlo.
- **IMPORTANTE** Usa sempre il tool fornito dall'ambiente per fare domande 
all'utente con risposta multipla (es. vscode_askQuestions).

Struttura preferita per il file del plan :

1. Obiettivo
2. Contesto
3. Vincoli
4. Assunzioni
5. File coinvolti
6. Piano
7. Rischi
8. Validazione
9. Avanzamento