# riporta lo stato di standby dei dischi di un pool ZFS
#!/usr/bin/env python3

import os
import sys
import subprocess
import re
from pathlib import Path
import utils



if __name__ == "__main__":

    utils.init_logger("get_standby")

    if len(sys.argv) != 2 :
        utils.info(f"Uso: get_standby [<nome_pool_zfs>|<label_disco>]")
        sys.exit(1)

    labelpart = sys.argv[1]

    # items: lista di dischi trovati: dict con key label e value lista_dischi)
    labdisks = utils.get_disks_of_label(labelpart)
    if len(labdisks) == 0 :
        utils.error(f"no disks for label containing '{labelpart}'")
        exit(1)
    for label, disks in labdisks.items():
        disksStr = "  ".join([disk for disk in disks])
        utils.info(f"label found : {label} => [ {disksStr} ]")
        for name,status in utils.get_standby_status(disks):
            #model = utils.get_model_of_disk(name)
            #utils.info(f"{name} ({model}) => {status}")
            utils.info(f"{name} () => {status}")
        utils.info("")
    exit(0)

