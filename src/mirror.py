# fa il mirror di una sorgente in una destinazione (es. un backup)
import os
import logging
import stat
import sys
import shutil
from logging.handlers import RotatingFileHandler

# è una variabile globale e
# serve nell'uso di rmtree quando ci sono errori di eliminazione
# di files o cartelle, viene segnalato in mirror.log
removeError = False

def setLogger(destFolder) :
    logname = f"{destFolder}{os.path.sep}mirror.log"
    handler = RotatingFileHandler(logname, mode='a', maxBytes=104857600, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
    handler.suffix = "%Y%m%d"
    logger = logging.getLogger('backup')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger


def getIgnoreLines(sourcePath) :
    """
    Restituisce le linee del file mirror.ignore in una lista
    """
    ignores = []
    ignoreFile = rf"{sourcePath}{os.path.sep}mirror.ignore"
    if not os.path.isfile(ignoreFile) : return ignores
    with open(ignoreFile, "r") as f :
        for line in f : ignores.append(line.strip())
    return ignores


# lista tutti i file/cartelle a partire da path
# ESCLUSI
# - file di sistema
# - i files/folders dentro mirror.ignore
# restituisce la tupla (nomefile, modTimestamp, fullname)
def listFiles(path, onlyfiles=False, onlydirs=False, ignores=None) :
    if not os.path.exists(path) or (onlyfiles and onlydirs) : return []
    result = []
    if ignores is None : ignores = []
    for entry in os.scandir(path) :

        # ignora alcuni files:
        # 1) se è un file e si vuole solo cartelle
        # 2) se è un cartella e si vuole solo file
        # 3) se è un file di sistema che porterebbe ad un errore
        if onlydirs and entry.is_file() : continue
        if onlyfiles and entry.is_dir() : continue
        # ignora i file di sistema(disabilitato per ora, da trovare come farlo in linux)
        #if os.stat(entry.path).st_file_attributes & stat.FILE_ATTRIBUTE_SYSTEM > 0 : continue

        # ignora i files/folders che contengono nel loro path completo
        # linee contenute in mirror.ignore.
        # ES: una linea del file mirror.ignore contiene
        # la stringa "\venv\":  verranno ignorati
        # tutti i file che hanno nel loro path completo la stringa "\venv\",
        # quindi in un backup di un progetto python contentente un virtual env,
        # verranno copiati tutti i file esclusi quelli dentro la cartella \venv\
        if len([1 for i in ignores if i in entry.path]) > 0 : continue

        # data di modifica del file
        modified = os.path.getmtime(entry.path) if onlyfiles else 0

        # restituisce la tupla corrispondente al file
        result.append((entry.name, modified, entry.path))
    return result



# copia tutti i file da origFolder in destFolder in modo mirror
# quindi se un file viene cancellato dalla orig, viene cancellato
# anche nella dest
def mirrorFolderTree(origFolder, destFolder, sourceIgnores=None) :
    copied = 0
    deleted = 0
    size = 0

    def handleFileError(func, path, exc_info):
        logger.error(f"Error on {path}: {exc_info}")
        global removeError
        removeError = True


    try:

        # se non esiste la cartella di dest , la crea
        if not os.path.isdir(destFolder) : os.makedirs(destFolder)

        # nella dest esclude solo il file mirror.log, se non lo facesse
        # verrebbe cancellato ogni volta che viene eseguito il backup perchè
        # non presente nella origFolder
        dictDestFiles = {i[0]:[i[1],i[2]] for i in listFiles(destFolder, onlyfiles=True, ignores=["mirror.log"])}

        # queste vengono raccolte per poterle cancellare se non incluse nel mirror
        # non riguarda la ricorsione del mirror sulle sottocartelle
        dictDestFolders = {i[0]: [i[1], i[2]] for i in listFiles(destFolder, onlydirs=True)}

        # nella source esclude solo il contenuto di mirror.ignore
        listaOrig = listFiles(origFolder, onlyfiles=True, ignores=sourceIgnores)

        # copia dei singoli files
        n = len(listaOrig)
        #print(f"    processing {n} files in {origFolder}")
        for name,mod,fname in listaOrig :

            # skip se non è nella dest o hanno date di modifica diverse
            if name in dictDestFiles and mod == dictDestFiles[name][0] :
                # print(f"skipping {fname} , exists in {destFolder}")
                # elimina il nome dalla dict di destinazione perchè processato
                del dictDestFiles[name]
                continue

            try :
                # print(f"copying {fname} => {destFolder}")
                fsize = os.stat(fname).st_size
                fsizemb = round(fsize / (1024 * 1024), 2)
                size += fsize
                shutil.copy2(fname, destFolder)
                copied += 1
                # elimina il nome dalla dict di destinazione perchè processato
                if name in dictDestFiles : del dictDestFiles[name]
                try : logger.info(f"[{fsizemb} mb] copied {fname}")
                except Exception as ex : print(f"logger error for {fname} : {ex}")

            except Exception as ex:
                print(f"error in copy file {fname} to {destFolder}")
                logger.error(f"error in copy file {fname} to {destFolder}")
                logger.error(f"error: {ex}")
                logger.error("continue to next file")

        # a questo punto sono rimasti nella dictDestFiles
        # solo i file che erano presenti in dest ma che non erano
        # nella cartella originaria, quindi sono i cancellati in orig
        # e vanno cancellati anche in dest
        for k,v in dictDestFiles.items() :
            os.remove(v[1])
            deleted += 1
            print(f"deleted {v[1]}")
            try: logger.info(f"deleted {v[1]}")
            except Exception as ex: print(f"logger error for {v[1]} : {ex}")


        # ricorsione nelle directory contenute
        listaOrigFolders = listFiles(origFolder, onlydirs=True, ignores=sourceIgnores)

        # verifica che non si debbano cancellare delle cartelle nella dest,
        # perchè non sono più presenti nella orig (per es "node_modules")
        for k,v in dictDestFolders.items() :
            if k not in [i[0] for i in listaOrigFolders] :
                global removeError
                removeError = False
                shutil.rmtree(v[1], ignore_errors=False, onerror=handleFileError)
                if not removeError :
                    deleted += 1
                    print(f"deleted {v[1]}")
                    try: logger.info(f"deleted {v[1]}")
                    except Exception as ex: print(f"logger error for {v[1]} : {ex}")



        for subfolder,mod,fsubfolder in listaOrigFolders :
            c,d,s = mirrorFolderTree(fsubfolder, f"{destFolder}{os.path.sep}{subfolder}", sourceIgnores=sourceIgnores)
            copied += c
            deleted += d
            size += s

    except Exception as ex: print(f"General Exception: {ex}")
    return copied, deleted, size




if __name__ == "__main__":

    try:

        nParams = len(sys.argv)
        if nParams != 3 :
            print("--------------------------------------------------------------------------------------------")
            print(f"mirror.py <folderSource> <folderDest>")
            print("'folderSource' is mirror origin fullpath")
            print("'folderDest' is mirror destination fullpath")
            print("--------------------------------------------------------------------------------------------")
            exit(1)

        # la sorgente e la destinazione devono esistere
        if not os.path.isdir(sys.argv[1]) or not os.path.isdir(sys.argv[2]) :
            print(f"source folder {sys.argv[1]} and dest folder {sys.argv[2]} MUST exists, exit.")
            exit(1)

        sourcePath, destPath = sys.argv[1], sys.argv[2]

        # set log sulla destinazione
        logger = setLogger(destPath)

        logger.info(f"------------------------------------------------------------------------------------------------")
        logger.info(f"Start Mirror  {sourcePath} => {destPath}")
        size = 0
        try:
            ignores = getIgnoreLines(sourcePath)
            copied, deleted, size = mirrorFolderTree(sourcePath, destPath, sourceIgnores=ignores)
            size = f"{round(size / (1024 * 1024 * 1024), 2)} gb"
        except Exception as ex:
            logger.error(f"General Exception: {ex}")

        logger.info(f"End Mirror  {sys.argv[1]} => {sys.argv[2]}, SIZE:{size}  COPIED:{copied}  DELETED:{deleted}")
        logger.info(f"------------------------------------------------------------------------------------------------")

    except Exception as ex:
        print(f"Exception: {ex}")
        input("Press any key")
