# Report ispezione Proxmox

**Data:** 15 giugno 2026  
**Host:** `proxmox` — `10.1.1.70`  
**Metodo:** SSH root (password), sola lettura — nessuna modifica applicata

---

## 1. Accesso SSH

| Verifica | Esito |
|----------|-------|
| Connessione `root@10.1.1.70` | OK |
| `PermitRootLogin` | `yes` (`/etc/ssh/sshd_config`) |
| Autenticazione chiave | Non configurata per root (solo password) |
| Utente Proxmox API | Solo `root@pam` |

L'accesso root via SSH con password funziona. L'host è raggiungibile dalla rete locale tramite l'alias SSH `proxmox-root` (configurato in `~/.ssh/config`).

---

## 2. Hardware e sistema host

| Componente | Dettaglio |
|------------|-----------|
| OS | Debian 12 (bookworm) |
| Proxmox VE | 8.4.0 / manager 8.4.1 |
| Kernel | 6.8.12-10-pve |
| CPU | 20 thread visibili (i9-13900HK) |
| RAM | 32 GiB totali, ~3.5 GiB usati |
| Swap | **0 B — non configurato** |
| Uptime al check | ~59 min (reboot oggi 15/06 alle 12:18) |

### Dischi fisici

| Device | Modello | Ruolo | Note |
|--------|---------|-------|------|
| `sda` 256 GB | ORICO-256 | `rpool` (OS Proxmox) | SSD interno/USB boot |
| `nvme0n1` 1 TB | Kingston OM8PGP41024N | `apps-pool` | VM Windows, storage veloce |
| `sdb` 3.6 TB | WD40EFZX (Red) | `main-pool` RAIDZ1 | USB via ASM1156 |
| `sdc` 3.6 TB | WD40EFZX (Red) | `main-pool` RAIDZ1 | USB via ASM1156 |
| `sdd` 3.6 TB | WD40EFRX (Red) | `main-pool` RAIDZ1 | USB via ASM1156 |

I tre WD Red del NAS transitano da bridge **ASMedia ASM1156** su bus USB 3.0 (`lsusb`).

---

## 3. Storage ZFS

### Pool

| Pool | Tipo | Stato | Capacità usata | Ultimo scrub |
|------|------|-------|----------------|--------------|
| `rpool` | single (SSD ORICO) | ONLINE | ~52 GB / 228 GB | 14/06/2026, 0 errori |
| `apps-pool` | single (NVMe Kingston) | ONLINE | ~433 GB / 952 GB (45%) | 14/06/2026, 0 errori |
| `main-pool` | **RAIDZ1** (3×4 TB USB) | ONLINE | ~4.3 TB / ~7.1 TB (60%) | 14/06/2026, 0 errori |

### Dataset NAS (`main-pool`)

| Dataset | Mount | Spazio usato | Uso |
|---------|-------|--------------|-----|
| `main-pool/data` | `/mnt/main-pool/data` | 650 GB | Dati generali (+ file `data2.hc` per backup incrementale) |
| `main-pool/cloud` | `/mnt/main-pool/cloud` | 1.52 TB | Cloud storage |
| `main-pool/media` | `/mnt/main-pool/media` | 161 GB | Media |
| `main-pool/you` | `/mnt/main-pool/you` | 1.99 TB | Archivio personale |

Proprietà utili: `compression=lz4`, `atime=off`, `recordsize=128K`.

### Storage Proxmox (`/etc/pve/storage.cfg`)

- `local` — ISO/template/backup su `/var/lib/vz`
- `local-zfs` — CT root su `rpool/data`
- `apps-pool` — VM disk su NVMe (`sparse 0`)

### Backup esterno (`onebackup`)

- Filesystem **ext4** su disco esterno, montato via **autofs** su `/mnt/onebackup`
- Destinazione dei job schedulati da `mirror_scheduler`
- Share Samba `[onebackup]` configurata ma dipende dal mount

---

## 4. NAS — Samba e condivisioni

**Samba:** attivo (`smbd`, `nmbd` running). **NFS:** non attivo.

| Share | Path | Utente | Note |
|-------|------|--------|------|
| `data` | `/mnt/main-pool/data` | admin | non browseable |
| `cloud` | `/mnt/main-pool/cloud` | admin | |
| `you` | `/mnt/main-pool/you` | admin | non browseable |
| `media` | `/mnt/main-pool/media` | admin | |
| `onebackup` | `/mnt/onebackup` | admin | veto su `lost+found` |

Configurazione Samba: min protocol SMB3, ma presenti anche `lanman auth = Yes` e `ntlm auth = ntlmv1-permitted` (protocolli legacy abilitati).

Al momento del check **nessun client connesso** (`smbstatus` vuoto).

---

## 5. Container LXC (Debian 12)

| VMID | Nome | IP | Stato | RAM | CPU | Note |
|------|------|-----|-------|-----|-----|------|
| 102 | `dualbot` | 10.1.1.72 | **stopped** | 22 GB | 20 core | Mount `/simlogs` 100 GB; unprivileged |
| 103 | `ticksaver` | 10.1.1.73 | running | 2 GB | 6 core | |
| 104 | `lobsaver` | 10.1.1.77 | running | 2 GB | 2 core | `onboot: 1` |

Tutti su `vmbr0`, gateway `10.1.1.1`, firewall LXC abilitato.

---

## 6. Macchine virtuali Windows

| VMID | Nome | Stato | RAM | Disco | Note |
|------|------|-------|-----|-------|------|
| 100 | `Win11` | **stopped** | 8 GB | 200 GB (`apps-pool`) | OVMF, TPM 2.0, virtio-scsi, ISO Win11 montata |
| 101 | `Play1` | **stopped** | 12 GB | 200 GB (`apps-pool`) | 12 core, e1000 (non virtio net) |

VM 100 ha un disco aggiuntivo **non collegato**: `unused0: apps-pool:vm-100-disk-3` (122 GB usati su ZFS).

---

## 7. Rete

```
vmbr0: 10.1.1.70/24, gateway 10.1.1.1
bridge-ports: enp87s0 (Ethernet attiva)
wlp86s0: Wi-Fi presente ma DOWN
```

Firewall Proxmox: **disabilitato** (`pve-firewall status: disabled/running`).

---

## 8. Servizi custom e automazioni

### Servizi systemd Python (utente `admin`)

| Servizio | Script | Funzione |
|----------|--------|----------|
| `mirror_scheduler` | `mirror_scheduler.py` | Backup schedulato verso `/mnt/onebackup` |
| `pool_standby` | `pool_standby.py main-pool 20` | Standby dischi NAS dopo 20 min di idle |

Entrambi **attivi** al momento del check.

Altri servizi rilevanti: `memcached`, `glances`, `smartmontools`, `chrony`, `usermin`.

### Schedule backup (`/home/admin/bin/services/mirror_setup.json`)

| Tipo | Giorno | Ora | Sorgente | Destinazione |
|------|--------|-----|----------|--------------|
| mirror | domenica | 05:00 | `/mnt/main-pool/media` | `/mnt/onebackup/media` |
| mirror | domenica | 07:00 | `/mnt/main-pool/cloud` | `/mnt/onebackup/cloud` |
| mirror | lunedì | 06:00 | `/home/admin` | `/mnt/onebackup/home` |
| split | lun/mer/ven | 07:00 | `data2.hc` | `/mnt/onebackup/data` |
| mirror | mar/gio/sab | 07:00 | `/mnt/main-pool/you` | `/mnt/onebackup/you` |

### Script Python (`/home/admin/pyscripts/`)

Scaricati in locale in `src/`:

| File | Scopo |
|------|-------|
| `utils.py` | Libreria comune: logging, Telegram, SMART, hdparm, memcached |
| `pool_standby.py` | Monitor idle ZFS → standby dischi |
| `set_standby.py` / `get_standby.py` | CLI standby manuale |
| `smart_check.py` | Check SMART pool con alert Telegram |
| `mirror.py` | Mirror cartelle (sync bidirezionale cancellazioni) |
| `mirror_scheduler.py` | Scheduler backup da JSON |
| `bigsplitter.py` | Backup incrementale file grandi a chunk |
| `get_disks.py` | Elenco dischi per pool/label |
| `get_log.py` | Lettura log servizi |
| `update_service.py` | Deploy unit systemd da `~/bin/services/` |

---

## 9. Backup Proxmox nativo

`/etc/pve/vzdump.cron` è **vuoto** (solo header auto-generato): **nessun backup automatico vzdump** configurato per CT/VM.

---

## 10. SMART dischi NAS

| Disco | Health | Power-on hours | Start/Stop count |
|-------|--------|----------------|------------------|
| sdb | PASSED | ~30 755 h | 23 428 |
| sdc | PASSED | ~40 613 h | 20 557 |
| sdd | PASSED | **~60 933 h** | 21 998 |

Tutti senza settori riallocati al momento del check. `sdd` è il più vecchio (~7 anni di runtime).

---

## 11. Criticità e raccomandazioni

### Alta priorità

1. **Backup mirror fallito oggi (15/06 ore 06:00)**  
   Il job `/home/admin → /mnt/onebackup/home` è fallito con:  
   `source folder ... and dest folder ... MUST exists`.  
   Probabile causa: `/mnt/onebackup` non montato o cartella `home` assente al momento dell'esecuzione (disco USB esterno + autofs).

2. **NAS su USB con RAIDZ1 a 3 dischi**  
   Un solo guasto disco compromette il pool fino a sostituzione. USB aggiunge latenza e rischio disconnessioni rispetto a SATA diretto. Monitorare SMART e avere piano di sostituzione.

3. **Nessuno swap**  
   Con CT da 22 GB (`dualbot`) e VM da 12 GB, un avvio simultaneo può esaurire la RAM (32 GB). Valutare zvol swap su `rpool` o limitare RAM allocata.

4. **Root SSH con password abilitato**  
   `PermitRootLogin yes` + autenticazione password espone l'host. Raccomandato: chiave SSH, disabilitare password per root, o almeno `PermitRootLogin prohibit-password`.

5. **Nessun vzdump schedulato**  
   CT e VM non hanno backup Proxmox nativi. L'unica protezione dati è il mirror verso `onebackup` (parziale, dipende dal mount).

### Media priorità

6. **Start/Stop count elevato sui WD Red** (~20k–23k)  
   Coerente con `pool_standby` che spegne i dischi dopo 20 min. Usura meccanica accelerata; valutare timeout più lungo o dischi sempre accesi in orari di backup.

7. **Disco `sdd` con ~61k ore**  
   SMART OK ma età significativa; candidato prioritario per sostituzione preventiva nel RAIDZ1.

8. **`zfs-volume-wait.service` fallito al boot**  
   Errore in journal alle 12:28. Potrebbe impattare zvol (es. se usati in futuro). Verificare se ci sono zvol attivi.

9. **VM 100 — disco `vm-100-disk-3` unused**  
   122 GB allocati su `apps-pool` senza essere montati nella VM. Spreco spazio o disco dimenticato.

10. **Samba — protocolli legacy**  
    `lanman auth` e `ntlmv1-permitted` riducono la sicurezza pur con `server min protocol = SMB3`.

11. **`dualbot` (CT 102) fermo**  
    Container con risorse importanti (22 GB RAM, 20 core) spento. Verificare se intenzionale.

12. **Entrambe le VM Windows ferme**  
    Win11 e Play1 stopped; ISO Win11 ancora montata su entrambe.

### Bassa priorità / informativo

13. **Aggiornamenti apt pendenti** — diversi pacchetti base (bash, curl, corosync, ecc.) non aggiornati.

14. **Errori ACPI/Bluetooth al boot** — tipici del mini PC GEEKOM, non bloccanti.

15. **efivarfs al 71%** — monitorare se cresce (molte entry EFI).

16. **Firewall Proxmox disabilitato** — accettabile in LAN fidata, da rivedere se esposto.

17. **Reboot frequente** — ultimo oggi; precedenti il 27/05 e 15/11/2025. Investigare cause se non pianificati.

---

## 12. Riepilogo architettura

```
┌─────────────────────────────────────────────────────────────┐
│  GEEKOM IT13 — proxmox 10.1.1.70 (Proxmox VE 8.4)         │
├─────────────────────────────────────────────────────────────┤
│  rpool (ORICO 256GB)     → OS, CT root (local-zfs)          │
│  apps-pool (NVMe 1TB)    → VM Win11, Play1                │
│  main-pool (RAIDZ1 USB)  → NAS: data/cloud/media/you       │
│  onebackup (ext4 USB)    → backup mirror (autofs)          │
├─────────────────────────────────────────────────────────────┤
│  CT 103 ticksaver  10.1.1.73  [running]                     │
│  CT 104 lobsaver   10.1.1.77  [running, onboot]           │
│  CT 102 dualbot    10.1.1.72  [stopped]                     │
│  VM 100 Win11      [stopped, 8GB]                           │
│  VM 101 Play1      [stopped, 12GB]                          │
├─────────────────────────────────────────────────────────────┤
│  Samba → LAN  |  pool_standby → spin-down WD Red           │
│  mirror_scheduler → backup settimanale su onebackup        │
└─────────────────────────────────────────────────────────────┘
```

---

## 13. File scaricati in locale

Gli script operativi sono stati copiati da `/home/admin/pyscripts/` in:

```
src/
├── bigsplitter.py
├── get_disks.py
├── get_log.py
├── get_standby.py
├── mirror.py
├── mirror_scheduler.py
├── pool_standby.py
├── set_standby.py
├── smart_check.py
├── update_service.py
└── utils.py
```

Per allineare modifiche future: editare in `src/` e ridistribuire su Proxmox in `/home/admin/pyscripts/`.

---

*Report generato automaticamente. Nessuna modifica è stata applicata al sistema remoto.*
