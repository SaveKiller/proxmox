#!/usr/bin/env python3
# health check generale + ultimo backup per job, invio Telegram

import json
import re
import utils
from datetime import datetime, timedelta
from pathlib import Path

SCHEDULE_FILE = Path.home() / "bin" / "services" / "mirror_setup.json"
DISPLAY_ORDER = ["media", "home", "cloud", "vzdump-ct", "data", "you"]


def fmt_duration(sec):
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    if h: return f"{h}h{m:02d}m"
    if m: return f"{m}m{s:02d}s"
    return f"{s}s"


def fmt_bytes(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB": return f"{n:.1f}{u}" if u != "B" else f"{int(n)}B"
        n /= 1024


def parse_log_ts(line):
    m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if not m: return None
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")


def parse_journal_ts(line):
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
    if m: return datetime.fromisoformat(m.group(1))
    return None


def job_label(text):
    labels = {"/mnt/main-pool/media": "media", "/home/admin": "home", "/mnt/main-pool/cloud": "cloud", "vzdump-ct": "vzdump-ct"}
    for k, v in labels.items():
        if k in text: return v
    if "data2.hc" in text: return "data"
    if "/mnt/main-pool/you" in text: return "you"
    return text[:40]


def entry_label(entry):
    if entry["type"] == "vzdump": return "vzdump-ct"
    return job_label(entry["source"])


def journal_last_runs(journal_text):
    last, current = {}, None
    for line in journal_text.splitlines():
        if "Command failed" in line:
            if current: current["failed"] = True
            continue
        ts = parse_journal_ts(line)
        m = re.search(r"\[info\] start (mirror|split|vzdump) : (.+)$", line)
        if m and ts:
            current = {"label": job_label(m.group(2)), "start": ts, "failed": False}
            continue
        m = re.search(r"\[info\] end (mirror|split|vzdump) : (.+)$", line)
        if m and ts and current:
            last[current["label"]] = {
                "end": ts, "duration": (ts - current["start"]).total_seconds(), "failed": current["failed"]
            }
            current = None
    return last


def last_mirror_run(dest):
    log = Path(dest) / "mirror.log"
    if not log.exists(): return None
    lines = log.read_text(errors="replace").splitlines()
    start_ts, end_line = None, None
    for line in lines:
        if "Start Mirror" in line: start_ts = parse_log_ts(line)
        if "End Mirror" in line: end_line = line
    if not end_line: return None
    end_ts = parse_log_ts(end_line)
    m = re.search(r"SIZE:([\d.]+\s*\w+)", end_line)
    dur = (end_ts - start_ts).total_seconds() if start_ts and end_ts else None
    return {"end": end_ts, "duration": dur, "size": m.group(1).strip() if m else "?"}


def last_split_run(dest):
    log = Path(dest) / "logs" / "backup.log"
    if not log.exists(): return None
    end_line = None
    for line in log.read_text(errors="replace").splitlines():
        if "completed split" in line: end_line = line
    if not end_line: return None
    end_ts = parse_log_ts(end_line)
    m = re.search(r"(\d+) chunks updated", end_line)
    total = utils.run2(f"du -sh {dest} 2>/dev/null | cut -f1").stdout.strip()
    chunks = m.group(1) if m else "?"
    size = f"{chunks} chunks upd, {total} tot" if total else f"{chunks} chunks upd"
    return {"end": end_ts, "size": size}


def last_vzdump_run(storage, journal_run):
    dump_dir = Path(f"/mnt/{storage}/dump") if not storage.startswith("/") else Path(storage) / "dump"
    if not dump_dir.exists():
        dump_dir = Path("/mnt/onebackup/vzdump/dump")
    files = sorted(dump_dir.glob("vzdump-*"), key=lambda p: p.stat().st_mtime, reverse=True) if dump_dir.exists() else []
    if files:
        latest = files[0].name
        m = re.search(r"(\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2})", latest)
        batch = [f for f in files if m and m.group(1) in f.name] if m else [files[0]]
        end_ts = datetime.fromtimestamp(files[0].stat().st_mtime)
        size = fmt_bytes(sum(f.stat().st_size for f in batch))
        dur = journal_run["duration"] if journal_run else None
        return {"end": end_ts, "duration": dur, "size": size, "failed": journal_run["failed"] if journal_run else False}
    if journal_run:
        return {"end": journal_run["end"], "duration": journal_run["duration"], "size": "?", "failed": journal_run["failed"]}
    return None


def journal_matches_run(jrun, run_end, tolerance_sec=120):
    if not jrun or not run_end: return False
    return abs((jrun["end"] - run_end).total_seconds()) < tolerance_sec


def run_info(entry, journal_runs):
    lbl = entry_label(entry)
    jrun = journal_runs.get(lbl)
    if entry["type"] == "mirror":
        run = last_mirror_run(entry["destination"])
        if run and jrun and journal_matches_run(jrun, run["end"]):
            run["failed"] = jrun["failed"]
        elif run:
            run["failed"] = False
    elif entry["type"] == "split":
        run = last_split_run(entry["destination"])
        if run and jrun and journal_matches_run(jrun, run["end"]):
            run["duration"] = jrun["duration"]
            run["failed"] = jrun["failed"]
        elif run:
            run["failed"] = False
    elif entry["type"] == "vzdump":
        run = last_vzdump_run(entry["storage"], jrun)
    else:
        return None
    if run and jrun and "failed" not in run:
        run["failed"] = jrun["failed"]
    if run and "failed" not in run:
        run["failed"] = False
    return run


def backups_section():
    schedule = json.load(open(SCHEDULE_FILE))
    journal = utils.run2("journalctl -u mirror_scheduler --since '90 days ago' --no-pager -o short-iso").stdout
    journal_runs = journal_last_runs(journal)
    entries = [e for e in schedule if e.get("enabled", True) and e["type"] != "healthcheck"]
    entries.sort(key=lambda e: DISPLAY_ORDER.index(entry_label(e)) if entry_label(e) in DISPLAY_ORDER else 99)
    lines, errors = [], 0
    for e in entries:
        lbl, run = entry_label(e), run_info(e, journal_runs)
        if not run or not run.get("end"):
            lines.append(f"-- {lbl}: mai eseguito")
            continue
        status = "ERR" if run.get("failed") else "OK"
        if run.get("failed"): errors += 1
        day = run["end"].strftime("%Y-%m-%d %H:%M")
        dur = fmt_duration(run["duration"]) if run.get("duration") is not None else "?"
        lines.append(f"{status} {lbl}: {day}  {dur}  {run.get('size', '?')}")
    lines.insert(0, f"Jobs: {len(entries)}  Errors: {errors}")
    return "\n".join(lines)


def machine_section():
    lines = [utils.run2("uptime -p").stdout.strip(), utils.run2("uptime").stdout.strip().split("load average:")[-1].strip()]
    mem = utils.run2("free -h | awk '/Mem:/{print $3\"/\"$2}'").stdout.strip()
    lines.append(f"RAM used: {mem}")
    if utils.run2("mountpoint -q /mnt/onebackup").returncode == 0:
        lines.append(f"onebackup: {utils.run2('df -h /mnt/onebackup | tail -1').stdout.strip()}")
    else:
        lines.append("onebackup: NOT MOUNTED")
    zfs = utils.run2("sudo zfs list -H -o name,avail,used main-pool rpool").stdout.strip()
    if zfs: lines.append("ZFS:\n  " + zfs.replace("\n", "\n  "))
    pools = utils.run2("sudo zpool list -H -o name,health,free main-pool rpool").stdout.strip()
    if pools: lines.append("Pools:\n  " + pools.replace("\n", "\n  "))
    disks = utils.get_disks_of_pool("main-pool")
    smart = []
    for diskname, model in disks:
        r = utils.smart_check_for_disk(diskname)
        if r is None: smart.append(f"  {model}: N/A")
        else:
            err, result, _ = r
            smart.append(f"  {model}: {'FAIL' if err else 'OK'}")
    if smart: lines.append("SMART main-pool:\n" + "\n".join(smart))
    namedisks = utils.get_disks_of_label("main-pool")
    if "main-pool" in namedisks:
        st = "  ".join(f"{n.split('/')[-1]}:{s}" for n, s in utils.get_standby_status(namedisks["main-pool"]))
        lines.append(f"NAS disks: {st}")
    lines.append("CT:\n" + utils.run2("sudo pct list").stdout.strip())
    return "\n".join(lines)


def main():
    utils.init_logger("health_check")
    msg = f"PROXMOX HEALTH CHECK\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    msg += "=== HOST ===\n" + machine_section() + "\n\n"
    msg += "=== ULTIMO BACKUP ===\n" + backups_section()
    utils.send_to_telegram(msg)
    utils.info("health check sent to telegram")


if __name__ == "__main__":
    main()
