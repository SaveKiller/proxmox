#!/usr/bin/env python3

import json
import os
import time
import subprocess
import utils
from datetime import datetime, timedelta
from pathlib import Path

SCHEDULE_FILE = Path.home() / "bin" / "services" / "mirror_setup.json"
CHECK_INTERVAL = 10  # secondi
last_mtime = None


# def log(msg):
#     print(f"[{datetime.now().isoformat()}] {msg}", flush=True)


def load_schedule():
    with open(SCHEDULE_FILE) as f : content = json.load(f)
    for entry in content:
        # Se day è una lista, converte tutti i giorni in minuscolo
        if isinstance(entry["day"], list):
            entry["day"] = [d.lower() for d in entry["day"]]
        else:
            entry["day"] = [entry["day"].lower()]
    return content


def next_execution_time(schedule):
    now = datetime.now()
    next_jobs = []
    
    # crea i jobs relativi alle schedulazioni del json
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for entry in schedule:
        if not entry.get("enabled", True) or entry.get("run_after"):
            continue
        hour = entry.get("hour", 0)
        minute = entry.get("minute", 0)
        for target_day in entry["day"]:
            # calcola la prossima data di esecuzione (next_run)
            delta_days = (days.index(target_day) - now.weekday()) % 7
            next_run = (now + timedelta(days=delta_days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            # se next_run è nel passato, aggiunge una settimana
            if delta_days == 0 and next_run < now:
                next_run += timedelta(days=7)
            # salva il job come coppia (data di esecuzione, contenuto del job)
            next_jobs.append((next_run, entry))

    # ordina i jobs per data di esecuzione crescente
    next_jobs.sort(key=lambda x: x[0])

    # restituisce il primo job con data di esecuzione maggiore o uguale a oggi
    return next_jobs[0]


def execute(entry):
    job_type = entry.get("type", "mirror")
    if job_type == "split":
        source, dest = entry["source"], entry["destination"]
        utils.info(f"start split : {source} => {dest}")
        utils.run2(f"/usr/bin/python3 /home/admin/pyscripts/bigsplitter.py split {source} {dest}")
        utils.info(f"end split : {source} => {dest}")
    elif job_type == "vzdump":
        vmids = " ".join(str(v) for v in entry["vmids"])
        storage, keep_last = entry["storage"], entry["keep_last"]
        utils.info(f"start vzdump : {vmids} => {storage} keep-last={keep_last}")
        utils.run2(f"sudo vzdump {vmids} --storage {storage} --mode snapshot --compress zstd --prune-backups keep-last={keep_last}")
        utils.info(f"end vzdump : {vmids} => {storage}")
    elif job_type == "healthcheck":
        utils.info("start healthcheck")
        utils.run2("/usr/bin/python3 /home/admin/pyscripts/health_check.py")
        utils.info("end healthcheck")
    else:
        source, dest = entry["source"], entry["destination"]
        utils.info(f"start mirror : {source} => {dest}")
        utils.run2(f"/usr/bin/python3 /home/admin/pyscripts/mirror.py {source} {dest}")
        utils.info(f"end mirror : {source} => {dest}")


def run_followups(completed, schedule):
    for entry in schedule:
        if not entry.get("enabled", True) or entry.get("run_after") != completed["source"]: continue
        utils.info(f"run_after : {completed['source']} => {entry['source']}")
        execute(entry)
        run_followups(entry, schedule)


def reload_schedule():
    global last_mtime
    last_mtime = None
    schedule = load_schedule()
    last_mtime = SCHEDULE_FILE.stat().st_mtime
    next, job = next_execution_time(schedule)
    target = job.get("destination") or job.get("storage") or job.get("type")
    utils.info(f"next mirror @ {next} : {job['source']} => {target}")
    return next, job


def main():
    global last_mtime
    utils.info("start service mirror_scheduler")

    if not SCHEDULE_FILE.exists():
        utils.error("non trovato il file json delle schedulazioni: /home/user/bin/services/mirror.json")
        return

    # prima lettura del contenuto del file di schedulazioni
    next_run_time, job = reload_schedule()    

    while True:
        
        # rileva modifiche al file e, nel caso, lo ricarica
        if SCHEDULE_FILE.stat().st_mtime != last_mtime:
            utils.info("schedule json changed, reloading")
            next_run_time, job = reload_schedule()

        # esegue il job di mirror se è arrivata l'ora
        if datetime.now() >= next_run_time:
            target = job.get("destination") or job.get("storage") or job.get("type")
            utils.info(f"execute job : {job['source']} => {target}")
            schedule = load_schedule()
            execute(job)
            run_followups(job, schedule)
            next_run_time, job = reload_schedule()

        # sleep per l'intervallo di minimo di attesa
        time.sleep(CHECK_INTERVAL)



if __name__ == "__main__":
    utils.init_logger("mirror_scheduler")
    main()
