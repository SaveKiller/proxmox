# riporta la situazione generale dei dischi del sistema
#!/usr/bin/env python3

import sys
import utils



if __name__ == "__main__":

    utils.init_logger("get_disks")

    if len(sys.argv) > 1:
        utils.info(f"Uso: get_disks")
        sys.exit(1)

    res = utils.run2("lsblk -o NAME,SIZE,LABEL,TYPE,MOUNTPOINT,FSTYPE,MODEL")
    print(res.stdout)

    
