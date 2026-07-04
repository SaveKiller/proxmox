# libreria di utilità per monitoraggio dei dischi, invio a telegram e logging
import os
import subprocess
import re
import inspect
import logging

from pathlib import Path
from systemd.journal import JournalHandler
from pymemcache.client import base

global logger

memc = base.Client(('localhost', 11211))



# === Configurazione logging ===
def init_logger(app_name):
    global logger
    logger = logging.getLogger(app_name)
    logger.addHandler(logging.StreamHandler())
    logger.addHandler(JournalHandler())
    logger.setLevel(logging.INFO)
    logger.propagate = False
    

def info(msg):
    logger.info(f"[info] {msg}")

def err(msg):
    logger.error(f"❌ [error] {msg}")

def error(msg):
    logger.error(f"❌ [error] {msg}")


def send_to_telegram(msg):
    """Invia un messaggio a Telegram (richiede telegram_notify.sh, eseguibile in ~/bin/)"""
    # risale di 1 frame per ottenere chi ha chiamato questa funzione
    msg = f"SERVICE [{os.path.basename(inspect.stack()[1].filename).replace('.py', '')}]\n{msg}"
    # fa gli escape dei caratteri speciali non visibili in Telegram
    msg = msg.replace("[", "[[").replace("]", "]]")
    # esegue il comando per inviare il messaggio a Telegram
    run(os.path.expanduser("~/bin/telegram_notify.sh"), [msg])


# Funzione per eseguire un comando bash con argomenti
# e restituire il risultato
# Se args è None, il comando viene eseguito senza argomenti
def run(command, args=None, check=True, shell=False, printErrors=True):
    """
    Esegue comando shell:
        command (str or list): Comando da eseguire. Se `shell=True`, deve essere una stringa.
        args (list): Lista di argomenti da passare al comando (usata solo se command è una stringa singola e shell=False).
        check (bool): Se True, solleva eccezione se il comando fallisce.
        shell (bool): Se True, esegue il comando tramite la shell (`bash`, `sh`, ecc.).
    """
    # compone il comando completo
    full_command = [command] + args if args is not None and not shell else command
    
    # esegue il comando
    try :
        res = subprocess.run(full_command, capture_output=True, text=True, check=check, shell=shell)
        return res
    except subprocess.CalledProcessError as e:
        if printErrors :
            print(f"Command failed: {e.cmd}")
            print(f"Return code: {e.returncode}")
            print(f"Output:\n{e.output}")
            print(f"Error:\n{e.stderr}")
        return e


def run2(command, printErrors=True):
    """Esegue un comando di shell e ne restituisce il risultato"""
    try : return subprocess.run(command, capture_output=True, text=True, check=True, shell=True)
    except subprocess.CalledProcessError as e:
        if printErrors :
            print(f"Command failed: {e.cmd}")
            print(f"Return code: {e.returncode}")
            print(f"Output:\n{e.output}")
            print(f"Error:\n{e.stderr}")
        return e

def get_standby_status(disks):
    """In ingresso accetta una lista di nomedisco e 
    restituisce una lista di coppie (nomedisco, 'standby|running')"""
    result = []
    for disk in disks:
        result.append((disk, 'standby' if is_standby_status(disk) else 'running'))
        # disksStr = f"disks[{' '.join([disk[0].replace('/dev/', '') for disk in disks])}]"
        # verb = "are" if len(disks) > 1 else "is"
        # result += f"{disksStr} {verb} {'in standby' if isStandby else 'running'}\n"
    return result


def is_standby_status(diskname):
    """Esegue il comando hdparm -C per verificare se il disco è in standby, restituisce True o False"""
    res = run2(f"sudo /sbin/hdparm -C {diskname}", printErrors=False)
    if res.returncode != 0 : return False
    hdparm = res.stdout.strip()
    return bool(re.search(r"not ready|standby", hdparm, re.IGNORECASE))


def set_standby_disks(disks):
    """Mette i dischi specificati in standby"""
    for diskname in disks:
        res = run2(f"sudo /sbin/hdparm -y {diskname}")


def get_attr_from_smart_line(line):
    """Restituisce una stringa con il nome dell'attributo e il suo valore
    considerando le linee restituite da smartctl"""
    errorValues = 0
    linearr = line.split()
    tot = len(linearr)
    if tot < 2 : return "", errorValues
    attributes=['Reallocated_Sector_Ct', 'Current_Pending_Sector']
    if linearr[1] in attributes:
        errorValues += int(linearr[tot- 1])
        return f"{linearr[1]}:{linearr[tot-1]}", errorValues
    return "", errorValues


# Funzione che restituisce il risultato di un check SMART 
# sul disco passato come argomento
# e restituisce:
# - foundErrors: True se ci sono errori, False altrimenti
# - smartline: stringa con il risultato del check
def smart_check_for_disk(diskname):
    
    # esegue il comando smartctl
    comSmartctl = run("sudo", ["/usr/sbin/smartctl", "-H", "-A", diskname])
    smartctl = comSmartctl.stdout.strip()

    if re.search(r"SMART support is: Unavailable|Unknown USB bridge|No such device", smartctl, re.IGNORECASE):
        print(f"SMART not available: {diskname}")
        return

    health_match = re.search(r"SMART.*(overall-health|Health Status|overall-health self-assessment).*", smartctl, re.IGNORECASE)
    health_line = "SMART PASSED" if health_match else "State not available"

    if re.search(r"PASSED|OK", health_line, re.IGNORECASE):
        result = f"{health_line}"
    else:
        result = f"Error: {health_line}"

    attribStr = ""
    attrValues = 0
    foundErrors = False

    for line in smartctl.splitlines():
        resline, errorValues = get_attr_from_smart_line(line)
        attrValues += errorValues
        if resline == "" : continue
        attribStr += f"{resline}" + "\n"

    # smartline = f"PROXMOX {diskname} | {model} : {result}"
    # smartMsg += f"{smartline}"+"\n"+ attribStr + "\n"
    if "PASSED" not in result : foundErrors = True
    if attrValues > 0 : foundErrors = True

    return foundErrors, result, attribStr


def get_model_of_disk(diskname):
    udevadm = run2(f"udevadm info --query=all --name={diskname}", printErrors=False).stdout.strip()
    model = re.search(r"ID_MODEL=(\S+)", udevadm).group(1).replace("_", " ").replace("-", " ")
    return model


def get_disks_of_pool(pool_name):
    """ Restituisce i dischi (nome, model) del pool ZFS spcificato, lista vuota se fallisce """
    res = run2(f'sudo blkid | grep \"{pool_name}\"', printErrors=False)
    if res.returncode > 0 : return []
    disk_names = re.findall(r"(/dev/\S+)\d:", res.stdout.strip())
    if len(disk_names) == 0 : return []
    disks = []
    for diskname in disk_names:
        udevadm = run2(f"udevadm info --query=all --name={diskname}", printErrors=False).stdout.strip()
        model = re.search(r"ID_MODEL=(\S+)", udevadm).group(1).replace("_", " ").replace("-", " ")
        disks.append((diskname, model))
    return disks


def get_disks_of_label(label):
    # controlla prima su memcached, se c'è lo prende da li
    blkid = memc.get(b'blkid')
    # se non c'è esegue il comando e l'output lo mette in memcached
    if blkid is None : 
        resblkid = run2(f'sudo blkid', printErrors=False)
        if resblkid.returncode > 0 : return ""
        blkid = resblkid.stdout.strip()
        memc.set(b'blkid', blkid)
    disks = {}
    for m in re.finditer(fr'(.*):.*\sLABEL="([^"]*{label}[^"]*)"', str(blkid), re.IGNORECASE):
        label = m.group(2)
        name = m.group(1)
        if label not in disks : disks[label] = []
        disks[label].append(name)
    return disks

    