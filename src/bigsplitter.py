#!/usr/bin/env python3
# -*- coding: utf-8 -*-


# NESSUNA DIPENDENZA ESTERNA O DA ALTRI .py
# [VERSIONE PER COMPATIBILE CON LINUX]

# BACKUP DI BIG FILE
# backup/restore del big file data2.hc
# Il backup prevede lo split del big file in chunks e
# quando il big file cambia all'aggiornamento del backup stesso
# si aggiorneranno solo i singoli chunks cambiati invece che tutto
# il big file


import os
import sys
import hashlib
import logging
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler

padN = lambda n, digits: f'{n:0{digits}}'

def setLogger(destFolder: Path):
    logfolder = destFolder / "logs"
    logfolder.mkdir(parents=True, exist_ok=True)
    logname = logfolder / "backup.log"
    handler = TimedRotatingFileHandler(str(logname), when="midnight", interval=1, encoding="utf-8", backupCount=14)
    handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
    handler.suffix = "%Y%m%d"
    logger = logging.getLogger('backup')
    logger.setLevel(logging.INFO)
    # evita duplicati se richiamato due volte
    if not any(isinstance(h, TimedRotatingFileHandler) for h in logger.handlers):
        logger.addHandler(handler)
    return logger

def writeBinaryFile(filename: Path, content: bytes):
    with open(filename, "wb") as f:
        f.write(content)

def readBinaryFile(filename: Path) -> bytes:
    with open(filename, "rb") as f:
        return f.read()

def readFileBinInChunks(filename: Path, chunkSize: int):
    iChunk = 0
    with open(filename, "rb") as fr:
        while True:
            chunk = fr.read(chunkSize)
            if chunk:
                yield chunk, hashlib.sha1(chunk).hexdigest(), iChunk
            else:
                break
            iChunk += 1

def mapFileChunksInDictOLD(destFolder: Path):
    existing = {}
    chunkSize = None
    for file in destFolder.iterdir():
        if not file.is_file() or not file.name.endswith(".chunk"):
            continue
        # formato: <originFile>.<index>.<hash>.<sizemb>.chunk
        # usa rsplit per tollerare punti nel nome originFile
        parts = file.name.rsplit(".", 5)
        if len(parts) != 6:
            continue  # ignora file non conformi
        origin, iChunk, sha, cSize, ext = parts[0], parts[1], parts[2], parts[3], parts[5]
        if ext != "chunk":
            continue
        if chunkSize is None:
            chunkSize = cSize
        elif str(chunkSize) != str(cSize):
            logger.error(f"error, chunkSize is different in files ({chunkSize} and {cSize}), exit")
            return {}, -1
        existing[iChunk] = (sha, file)  # chiave stringa con padding
    return existing, (str(chunkSize) if chunkSize is not None else None)


def mapFileChunksInDict(destFolder) :
    existing = {}
    # legge i nomi di tutti i chunk nella destinazione del backup
    fileList = os.listdir(destFolder)
    chunkSize = -1
    for file in fileList:
        if file[-6:] != ".chunk": continue
        [fname, fext, iChunk, sha, cSize, ext] = file.split(".")
        # verifica che il chunksize sia uguale per tutti i chunk
        if chunkSize == -1 : chunkSize = cSize
        elif chunkSize != cSize :
            logger.error(f"error, chunkSize is different in files ({chunkSize} and {cSize}), exit")
            return {} , -1
        chunkFilename = os.path.join(destFolder, file)
        # crea una  dict[index]=(sha, chunkFilename) con tutti i nomi file esistenti
        existing[iChunk] = (sha, chunkFilename)
    return existing , chunkSize


def splitFileToBackup(dataFile: Path, chunkSizeMB: int, destFolder: Path, ichunksDigits: int = 6):
    fsize = dataFile.stat().st_size
    fsizeMb = fsize / (1024 * 1024)
    chunkSizeB = chunkSizeMB * 1024 * 1024
    nChunks = (fsize + chunkSizeB - 1) // chunkSizeB
    updChunks = 0

    dataFileOnlyName = dataFile.name
    logger.info(f"{dataFile} : size is {int(fsizeMb)} mb => spitting in {nChunks} chunks of {chunkSizeMB} mb")

    existing, sizeFound = mapFileChunksInDict(destFolder)
    if sizeFound not in (None, str(chunkSizeMB), "-1", -1):
        logger.error(f"error, mismatch chunk size, existing: {sizeFound} mb, wanted: {chunkSizeMB} mb, exit!")
        return

    for (chunk, sha, i) in readFileBinInChunks(dataFile, chunkSizeB):
        iStr = padN(i, ichunksDigits)
        chunkfname = f"{dataFileOnlyName}.{iStr}.{sha}.{chunkSizeMB}.chunk"
        target = destFolder / chunkfname
        # log ogni 1000 chunks
        if (i+1) % 100 == 0 : logger.info(f"{i+1} chunks processed, continue...")

        if iStr not in existing:
            logger.info(f"{iStr} not found , writing {chunkfname}")
            writeBinaryFile(target, chunk)
            continue

        (exSha, exPath) = existing[iStr]
        if exSha == sha : continue

        logger.info(f"{iStr} new hash , deleting existing chunk and writing {chunkfname}")
        try:
            os.remove(exPath)
        except FileNotFoundError:
            pass
        writeBinaryFile(target, chunk)
        updChunks += 1


    logger.info(f"completed split and backup of {dataFile}, {updChunks} chunks updated.")

def mergeFileFromBackup(dataFile: Path, destFolder: Path, ichunksDigits: int = 6):
    if dataFile.exists():
        logger.error(f"file {dataFile} already exists, exit!")
        return
    existing, _ = mapFileChunksInDict(destFolder)
    i = 0
    fileLen = 0
    with open(dataFile, "wb") as wf:
        while True:
            iStr = padN(i, ichunksDigits)
            if iStr not in existing:
                break
            (exHash, exPath) = existing[iStr]
            chunkContent = readBinaryFile(exPath)
            fileLen += len(chunkContent)
            wf.write(chunkContent)
            logger.info(f"chunk {i} : written in final file")
            i += 1
    logger.info(f"completed {fileLen/(1024*1024):.0f} mb final file ({i} chunks) : {dataFile}.")

if __name__ == "__main__":
    try:
        if len(sys.argv) != 4:
            print("--------------------------------------------------------------------------------------------")
            print("bigsplitter.py <split|merge> <originFile> <destFolder>")
            print("'destFolder' is backup destination fullpath")
            print("--------------------------------------------------------------------------------------------")
            print("bigsplitter.py split <originFile> <destFolder> : split/backup originFile TO destFolder")
            print("bigsplitter.py merge <originFile> <destFolder> : restore originFile FROM destFolder")
            print("'originFile' is single specific data file in origin position")
            print("file chunk format is <originFile>.<index>.<hash>.<sizemb>.chunk")
            sys.exit(1)

        origin = Path(sys.argv[2]).resolve()
        dest = Path(sys.argv[3]).resolve()
        global logger
        logger = setLogger(dest)

        if not dest.is_dir():
            logger.error(f"folder {dest} not found, exit.")
            sys.exit(1)

        cmd = sys.argv[1].lower()
        if cmd == "split":
            if not origin.is_file():
                logger.error(f"file {origin} not found, exit.")
                sys.exit(1)
            splitFileToBackup(origin, 100, dest, 6)
        elif cmd == "merge":
            if origin.exists():
                logger.error(f"file {origin} found, remove it and retry, exit.")
                sys.exit(1)
            mergeFileFromBackup(origin, dest, 6)
        else:
            logger.error(f"unknown option {sys.argv[1]}, exit.")
            sys.exit(1)

    except Exception as ex:
        print(f"Exception: {ex}", file=sys.stderr)
        sys.exit(1)
