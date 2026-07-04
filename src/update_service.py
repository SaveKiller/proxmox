# aggiorna e ricarica il servizio systemd specificato
#!/usr/bin/env python3

import sys
import subprocess
from pathlib import Path
import utils


def run(cmd, check=True):
    utils.info(f"> {' '.join(cmd)}")
    subprocess.run(cmd, check=check)

def main():

    if len(sys.argv) != 2:
        utils.info("Update and reload a systemd service")
        utils.info("Uso: update_service <service_name>")
        sys.exit(1)

    service_name = sys.argv[1]
    service_name_service = f"{service_name}.service"
    src = Path("/home/admin/bin/services") / service_name_service
    dst = Path("/etc/systemd/system") / service_name_service

    utils.info(f"🔄 updating service '{service_name}'"
          f"\n  source:\t{src}\n  destination:\t{dst}")

    if not src.exists():
        utils.error(f"❌ error: source file {src} not found.")
        sys.exit(1)

    try:
        run(["sudo", "cp", str(src), str(dst)])
        run(["sudo", "systemd-analyze", "verify", str(dst)])
        run(["sudo", "systemctl", "daemon-reexec"])
        run(["sudo", "systemctl", "daemon-reload"])
        run(["sudo", "systemctl", "enable", service_name])
        run(["sudo", "systemctl", "restart", service_name])
        utils.info(f"✅ service '{service_name}' updated, verified and restarted.")
    except subprocess.CalledProcessError:
        utils.error("❌ error during service management.")
        sys.exit(1)


if __name__ == "__main__":
    utils.init_logger("update_service")
    main()
