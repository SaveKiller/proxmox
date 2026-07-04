# mette in standby i dischi del pool ZFS specificato
#!/usr/bin/env python3

import os
import sys
import subprocess
import re
from pathlib import Path
import utils
from time import sleep


if len(sys.argv) < 2:
    print(f"Uso: set_standby <nome_pool_zfs>")
    sys.exit(1)

utils.init_logger("set_standby")

pool_name = sys.argv[1]

# restituisce i dischi del pool
# errorStr: stringa di errore (e uscita) in caso di fallimento, vuota altrimenti
# disks: lista di dischi trovati: coppie (nome, model)
labdisks = utils.get_disks_of_label(pool_name)
if len(labdisks) == 0:
    errorStr = f"nessun disco trovato per il pool '{pool_name}' oppure pool non esistente."
    utils.error(errorStr)
    sys.exit(1)

# per ogni label recupera i dischi es esegue set_standby
# per la lista di dischi associati, può essere un pool zfs
# (quindi piú dischi), oppure singolo disco
for label, disks in labdisks.items():
    disksStr = "  ".join([disk for disk in disks])
    utils.info(f"label found : {label} => [ {disksStr} ]")
    utils.set_standby_disks(disks)
    sleep(2)
    for name,status in utils.get_standby_status(disks):
        model = utils.get_model_of_disk(name)
        utils.info(f"{name} ({model}) => {status}")
    utils.info("")

    
        


