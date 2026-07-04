# verifica lo stato SMART dei dischi di un pool ZFS
#!/usr/bin/env python3

import os
import sys
import subprocess
import re
from pathlib import Path
import utils


utils.init_logger("smart_check")

if len(sys.argv) < 2:
    utils.info(f"Uso: smart_check <nome_pool_zfs>")
    sys.exit(1)

pool_name = sys.argv[1]

# disks: lista di dischi trovati: coppie (nome, model)
disks = utils.get_disks_of_pool(pool_name)
if len(disks) == 0 :
    errorStr = f"nessun disco trovato per il pool '{pool_name}' oppure pool non esistente."
    utils.error(errorStr)
    sys.exit(1)

# esegue il check smart per ogni disco
# e crea la stringa di output
smartMsg = ""
foundErrors = False
for disk in disks:
    diskname, model = disk
    isErrors, result, attribStr = utils.smart_check_for_disk(diskname)
    foundErrors = foundErrors or isErrors
    smartMsg += f"\nPROXMOX {diskname} | {model} : {result}" + "\n" + attribStr + "\n"

# stampa il risultato e lo invia a telegram se ci sono errori
utils.info(smartMsg)
if foundErrors:
    smartMsg = f"SMART ERRORS FOUND FOR {pool_name}:\n" + smartMsg
    utils.send_to_telegram(smartMsg)
