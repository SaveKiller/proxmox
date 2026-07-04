# stampa il log del servizio specificato
#!/usr/bin/env python3

import sys
import utils

if __name__ == "__main__":

    utils.init_logger("get_log")

    if len(sys.argv) < 2:
        utils.info(f"Uso: get_log <nome_service>")
        sys.exit(1)

    service_name = sys.argv[1]
    # stampa i log del servizio
    res = utils.run2(f"journalctl -n 40 -t {service_name} --no-pager ")
    print(res.stdout)

    
