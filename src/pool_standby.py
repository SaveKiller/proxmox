# servizio per mettere in standby i dischi di un pool ZFS dopo x minuti di inattività
#!/usr/bin/env python3

import os
import sys
import subprocess
import re

from datetime import datetime
from pathlib import Path
from itertools import islice

import utils


global MIN_MINUTES
global IOSTAT_INTERVAL_SEC


MIN_MINUTES = 10
IOSTAT_INTERVAL_SEC = 5

# fascia senza standby: backup mattutini (dom 05:00/07:00, altri giorni 07:00) + margine
NO_STANDBY_WINDOWS = [(4, 30, 9, 0)]


def in_no_standby_window(now=None):
    now = now or datetime.now()
    now_min = now.hour * 60 + now.minute
    for h0, m0, h1, m1 in NO_STANDBY_WINDOWS:
        if h0 * 60 + m0 <= now_min < h1 * 60 + m1: return True
    return False


# generatore per il comando iostat
# restituisce True se il pool è inattivo (a livello di letture/scritture), 
# False altrimenti. il ciclo non termina mai
def iostat_idle(poolName):
    cmd = ["zpool", "iostat", "-H", poolName, str(IOSTAT_INTERVAL_SEC)]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1) as proc:
        for line in islice(proc.stdout, 1, None):
            yield " ".join([l.strip() for l in line.strip().split()][3:5]) == "0 0"


def get_standby_status_msg(poolName, disks):
    diskstr = "  ".join([f"{name}:{status}" for name,status in utils.get_standby_status(disks)])
    return f"{poolName} [{diskstr}]"


# cicla sul generatore iostat per capire se il pool è attivo/inattivo
# e regolare lo stato di standby dei dischi corrispondenti
def monitor_iostat(poolName, disks, minutes):
    idle_count = 0
    in_standby = utils.is_standby_status(disks[0])
    max_idle_cycles = int(minutes) * (60 // IOSTAT_INTERVAL_SEC)
    last_activity_time = ""
    for in_idle in iostat_idle(poolName):

        # è inattivo e in standby? non fa nulla
        if in_standby and in_idle: continue

        # è attivo e non in standby? resetta il contatore idle e 
        # salva il time di quest'ultima attività
        if not in_standby and not in_idle:
            idle_count = 0
            last_activity_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            continue

        # è in stand-by e tornerà attivo? lo notifica e cambia stato
        if in_standby and not in_idle:
            in_standby = False
            idle_count = 0
            msg = f"{poolName} is active, canceling standby.\n"
            msg += get_standby_status_msg(poolName, disks)
            utils.info(msg)
            continue
        
        # è inattivo e non in standby? valuta se entrare in standby
        if not in_standby and in_idle:
            if in_no_standby_window():
                idle_count = 0
                continue
            idle_count += 1
            
            # se il pool è inattivo da più di 24 cicli (2 min), logga il time dell'ultima attività
            if idle_count == 24 and len(last_activity_time) > 0:
                utils.info(f"{poolName} last activity at {last_activity_time}")
                    
            # se il pool è inattivo da più di max_idle_cycles, entra in standby    
            if idle_count >= max_idle_cycles:
                
                # se non è già in standby => entra in standby e cambia stato
                if not utils.is_standby_status(disks[0]):
                    msgExistingStatus = "entering standby\n"
                    utils.set_standby_disks(disks)
                else :
                    msgExistingStatus = "already in standby\n"
                
                # logga lo stato di standby in console, log e telegram
                msg = f"{poolName} in idle for {minutes} minutes, {msgExistingStatus}"
                msg += get_standby_status_msg(poolName, disks)
                utils.info(msg)

                # resetta il contatore idle e lo stato
                in_standby = True
                idle_count = 0


def main():

    # Verifica che il numero di argomenti sia corretto
    if len(sys.argv) < 3:
        utils.err(f"Usage: pool_standby <poolname_zfs> <timeout_minutes>")
        sys.exit(1)

    # primo argomento dev'essere il nome del pool
    poolName = sys.argv[1]

    # namedisks: dict di dischi associati alla label passata
    namedisks = utils.get_disks_of_label(poolName)
    if len(namedisks) == 0 :
        utils.err(f"nessun disco trovato per il pool '{poolName}' oppure pool non esistente.")
        sys.exit(1)

    # Verifica che il secondo argomento (i minuti) sia un numero maggiore di MIN_MINUTES
    minutes = sys.argv[2] if sys.argv[2].isdigit() and int(sys.argv[2]) > MIN_MINUTES else MIN_MINUTES
    msg = f"Service starting for {poolName} (timeout {minutes} min, no-standby 04:30-09:00)\n"
    disks = namedisks[poolName]
    msg += get_standby_status_msg(poolName, disks)
    utils.info(msg)

    try:
        # esegue il comando iostat in un processo separato
        # e lo monitora per l'attività di lettura/scrittura
        monitor_iostat(poolName, namedisks[poolName], minutes)
        
    except KeyboardInterrupt:
        msg = f"Keyboard interrupt received, exiting gracefully\n"
        msg += str(utils.get_standby_status(disks))
        utils.info(msg)
        sys.exit(0)
    except Exception as e:
        # In caso di errore, esci con codice 1
        errmsg = f"An unexpected error occurred, exiting : {e}\n"
        utils.err(errmsg)
        sys.exit(1)


if __name__ == "__main__":
    utils.init_logger("pool_standby")
    main()
