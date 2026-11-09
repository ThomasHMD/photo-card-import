#!/usr/bin/env python3
"""Import automatique des cartes photo : un dossier par jour de prise de vue et par appareil
(« 2026-11-09_D750 ») dans le dossier de destination, puis carte vidée (si demandé) et éjectée.
Mode d'emploi : README.md.

  python3 import-cartes.py importer [--simulation] [VOLUME ...]   sans VOLUME : tous les volumes qui ont un DCIM
  python3 import-cartes.py lancer [VOLUME ...]                    même chose, détaché (bouton SwiftBar)
  python3 import-cartes.py menu                                   sortie SwiftBar ; lance l'import d'une carte qui arrive
  python3 import-cartes.py etat                                   résumé lisible

Réglages : appareils.json à côté du script (sinon appareils.exemple.json), ou le fichier désigné par la variable
IMPORT_CARTES_CONFIG. État de la machine : ~/Library/Application Support/import-cartes (ou IMPORT_CARTES_ETAT).

Copie dans un dépôt intermédiaire du même disque, puis range tout d'un coup dans la destination : un service de
synchro ne voit rien avant la fin et ne ralentit pas le transfert. Chaque copie est relue depuis le disque
et comparée à l'octet (empreinte) à ce qui a été lu sur la carte ; un fichier n'est effacé de la carte que si sa copie
identique est dans la destination à ce moment-là. Le journal (journal/importes.tsv) retient ce qui a déjà été
importé : une carte rebranchée ne redonne que le neuf, même si les dossiers ont été vidés ou déplacés depuis.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

ICI = Path(__file__).resolve().parent


def fichier_config() -> Path:
    if os.environ.get("IMPORT_CARTES_CONFIG"):
        return Path(os.path.expanduser(os.environ["IMPORT_CARTES_CONFIG"]))
    perso = ICI / "appareils.json"
    return perso if perso.exists() else ICI / "appareils.exemple.json"


def chemin(valeur: str, base: Path) -> Path:
    """Chemin d'un réglage : absolu, en ~, ou relatif au dossier du fichier de réglages."""
    p = Path(os.path.expanduser(str(valeur)))
    return p if p.is_absolute() else Path(os.path.normpath(base / p))


CONFIG_FICHIER = fichier_config()
CONFIG = json.loads(CONFIG_FICHIER.read_text(encoding="utf-8"))
DEST = chemin(CONFIG["destination"], CONFIG_FICHIER.parent)
JOURNAL = chemin(CONFIG.get("journal", "journal/importes.tsv"), CONFIG_FICHIER.parent)
if os.environ.get("IMPORT_CARTES_ETAT"):  # tests : un état à part, jamais celui de la machine
    LOCAL = Path(os.path.expanduser(os.environ["IMPORT_CARTES_ETAT"]))
    LOGS = LOCAL / "logs"
else:
    LOCAL = Path.home() / "Library" / "Application Support" / "import-cartes"  # état propre à chaque Mac
    LOGS = Path.home() / "Library" / "Logs" / "import-cartes"
JOURNAL_TEXTE = LOGS / "import-cartes.log"
PROGRESSION, DERNIER, VUS, VERROU = (LOCAL / n for n in ("progression.json", "dernier.json", "vus.json", "verrou"))
VIDEOS = {e.lower() for e in CONFIG["extensions_video"]}
EXTS = {e.lower() for e in CONFIG["extensions_photo"]} | VIDEOS
EXIFTOOL = shutil.which("exiftool", path="/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", ""))
COLONNES = ["importe_le", "appareil", "fichier", "taille", "prise_de_vue", "destination", "volume"]
RE_DATE = re.compile(r"^(\d{4})-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
MARGE_DISQUE = 2 * 1024**3
BLOC = 8 * 1024**2
F_NOCACHE = getattr(fcntl, "F_NOCACHE", 48)  # macOS : lire le disque, pas le cache de ce qu'on vient d'écrire


# ---------------------------------------------------------------- utilitaires

def log(msg: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL_TEXTE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def lire(p: Path, defaut):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaut


def ecrire(p: Path, data) -> None:
    LOCAL.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def notifier(texte: str, titre: str = "Import photos") -> None:
    if not CONFIG.get("notifications", True):
        return
    script = f"display notification {json.dumps(texte, ensure_ascii=False)} with title {json.dumps(titre, ensure_ascii=False)}"
    subprocess.run(["osascript", "-e", script], capture_output=True)


def go(octets: float) -> str:
    return f"{octets / 1e9:.1f} Go".replace(".", ",")


def fichiers_txt(n: int) -> str:
    return f"{n} fichier" + ("s" if n > 1 else "")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def vivant(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def sans_cache(f) -> None:
    try:
        fcntl.fcntl(f.fileno(), F_NOCACHE, 1)
    except OSError:
        pass


def empreinte(p: Path) -> str:
    h = hashlib.blake2b()
    with open(p, "rb") as f:
        sans_cache(f)
        while bloc := f.read(BLOC):
            h.update(bloc)
    return h.hexdigest()


def copier_verifie(src: Path, dst: Path) -> None:
    """Copie en calculant l'empreinte de ce qui est lu sur la carte, écrit sur le disque, relit la copie depuis le
    disque et compare : une seule lecture de la carte, et la certitude que la copie est identique."""
    h = hashlib.blake2b()
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        sans_cache(fo)
        while bloc := fi.read(BLOC):
            h.update(bloc)
            fo.write(bloc)
        fo.flush()
        os.fsync(fo.fileno())
    shutil.copystat(src, dst)
    if empreinte(dst) != h.hexdigest():
        raise OSError("copie différente de la carte")


def ejecter(vol: Path) -> bool:
    for _ in range(3):
        if subprocess.run(["diskutil", "eject", str(vol)], capture_output=True).returncode == 0:
            return True
        time.sleep(3)
    return False


# ---------------------------------------------------------------- cartes et fichiers

def volumes_cartes() -> list[Path]:
    """Volumes montés qui ont un DCIM à la racine (carte SD dans le lecteur, appareil monté en USB…)."""
    ignores = set(CONFIG.get("volumes_ignores", []))
    try:
        noms = sorted(os.listdir("/Volumes"))
    except OSError:
        return []
    res = []
    for nom in noms:
        v = Path("/Volumes") / nom
        if nom in ignores or v.is_symlink():
            continue
        try:
            if (v / "DCIM").is_dir():
                res.append(v)
        except OSError:
            pass
    return res


def lister(volume: Path) -> list[Path]:
    fichiers = []
    for racine, dossiers, noms in os.walk(volume / "DCIM"):
        dossiers[:] = sorted(d for d in dossiers if not d.startswith("."))
        for n in sorted(noms):
            if not n.startswith(".") and Path(n).suffix.lower().lstrip(".") in EXTS:
                fichiers.append(Path(racine) / n)
    return fichiers


def lire_exif(fichiers: list[Path]) -> dict[str, dict]:
    if not fichiers:
        return {}
    if not EXIFTOOL:
        raise RuntimeError("exiftool introuvable (brew install exiftool)")
    LOCAL.mkdir(parents=True, exist_ok=True)
    args = LOCAL / "exiftool-args.txt"
    args.write_text("\n".join(str(f) for f in fichiers) + "\n", encoding="utf-8")
    r = subprocess.run([EXIFTOOL, "-j", "-q", "-q", "-fast2", "-charset", "filename=utf8",
                        "-d", "%Y-%m-%d %H:%M:%S", "-Make", "-Model", "-DateTimeOriginal", "-CreateDate",
                        "-FileModifyDate", "-@", str(args)], capture_output=True, text=True)
    try:
        data = json.loads(r.stdout or "[]")
    except ValueError:
        data = []
    return {nfc(d.get("SourceFile", "")): d for d in data}


def date_prise(meta: dict, video: bool) -> str | None:
    """Heure de prise de vue (horloge de l'appareil). Vidéo : la date du fichier passe avant CreateDate (souvent en UTC)."""
    ordre = ("DateTimeOriginal", "FileModifyDate", "CreateDate") if video else ("DateTimeOriginal", "CreateDate", "FileModifyDate")
    for tag in ordre:
        v = str(meta.get(tag, ""))
        m = RE_DATE.match(v)
        if m and 1990 < int(m.group(1)) < 2100:
            return v[:19]
    return None


def nom_appareil(make, model) -> str | None:
    mk, md = str(make or "").upper(), str(model or "").upper()
    if mk or md:
        for a in CONFIG["appareils"]:
            if a.get("marque", "").upper() in mk and a.get("modele", "").upper() in md:
                return a["nom"]
    return re.sub(r"[^A-Za-z0-9]+", "", str(model or "")) or None


def appareil_de_la_carte(meta: dict[str, dict], volume: Path) -> str:
    """Pour un fichier sans EXIF (vidéo muette…) : l'appareil le plus fréquent de la carte, sinon le nom du volume."""
    vus: dict[str, int] = {}
    for m in meta.values():
        n = nom_appareil(m.get("Make"), m.get("Model"))
        if n:
            vus[n] = vus.get(n, 0) + 1
    if vus:
        return max(vus, key=vus.get)
    return re.sub(r"[^A-Za-z0-9]+", "", volume.name) or "Inconnu"


# ---------------------------------------------------------------- journal et destination

def lire_journal() -> dict[str, str]:
    """clé « nom|taille|prise de vue » → destination relative (ou « (…) » si inconnue)."""
    cles: dict[str, str] = {}
    try:
        lignes = JOURNAL.read_text(encoding="utf-8").splitlines()[1:]
    except OSError:
        return cles
    for ligne in lignes:
        c = ligne.split("\t")
        if len(c) >= 6:
            cles[f"{c[2]}|{c[3]}|{c[4]}"] = c[5]
    return cles


def noter(lignes: list[list[str]]) -> None:
    if not lignes:
        return
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    neuf = not JOURNAL.exists()
    with open(JOURNAL, "a", encoding="utf-8") as f:
        if neuf:
            f.write("\t".join(COLONNES) + "\n")
        for l in lignes:
            f.write("\t".join(l) + "\n")


def index_dest() -> dict[str, Path]:
    """« nom|taille » → chemin, pour tout ce qui est déjà dans la destination (posé à la main avant l'outil compris)."""
    idx: dict[str, Path] = {}
    for racine, dossiers, noms in os.walk(DEST):
        dossiers[:] = [d for d in dossiers if not d.startswith(".")]
        for n in noms:
            if n.startswith("."):
                continue
            p = Path(racine) / n
            try:
                idx.setdefault(f"{nfc(n)}|{p.stat().st_size}", p)
            except OSError:
                pass
    return idx


def depot_local() -> Path | None:
    """Dépôt intermédiaire sur le même disque que la destination (rangement final = simple renommage).
    Réglage « depot » : chemin absolu, ou dossier relatif à la racine du disque de la destination
    (défaut .import-cartes-depot) ; destination sur le disque du système : ~/.import-cartes-depot."""
    reglage = os.path.expanduser(str(CONFIG.get("depot", ".import-cartes-depot")))
    if os.path.isabs(reglage):
        cand = Path(reglage)
    else:
        racine = DEST
        while not os.path.ismount(racine) and racine != racine.parent:
            racine = racine.parent
        cand = Path.home() / ".import-cartes-depot" if str(racine) == "/" else racine / reglage
    try:
        cand.mkdir(parents=True, exist_ok=True)
        DEST.mkdir(parents=True, exist_ok=True)
        if os.stat(cand).st_dev == os.stat(DEST).st_dev:
            return cand
    except OSError:
        pass
    return None


def vider_depot(depot: Path) -> None:
    """Restes d'un import interrompu : jamais journalisés, ils seront recopiés depuis la carte."""
    for racine, dossiers, noms in os.walk(depot, topdown=False):
        for n in noms:
            os.remove(os.path.join(racine, n))
        for d in dossiers:
            os.rmdir(os.path.join(racine, d))


def place_libre(cible: Path, taille: int, reserves: set[Path]) -> Path | None:
    """Chemin final ; None si le même fichier (même nom, même taille) y est déjà. Homonyme différent → nom_2.ext."""
    n, c = 1, cible
    while True:
        if c not in reserves:
            if not c.exists():
                reserves.add(c)
                return c
            if c.stat().st_size == taille:
                return None
        n += 1
        c = cible.with_name(f"{cible.stem}_{n}{cible.suffix}")


# ---------------------------------------------------------------- import

def importer(volumes: list[Path], simulation: bool = False) -> int:
    volumes = [v for v in volumes if (v / "DCIM").is_dir()]
    if not volumes:
        print("Aucune carte avec un dossier DCIM.")
        return 0
    vider = bool(CONFIG.get("vider_la_carte"))
    LOCAL.mkdir(parents=True, exist_ok=True)
    verrou = open(VERROU, "w")
    if not simulation:
        fcntl.flock(verrou, fcntl.LOCK_EX)  # un import à la fois : le suivant attend son tour
    noms_vol = ", ".join(v.name for v in volumes)
    debut = time.time()
    etat = {"pid": os.getpid(), "volume": noms_vol, "phase": "lecture", "fait": 0, "total": 0,
            "octets_fait": 0, "octets_total": 0, "debut": datetime.now().isoformat(timespec="seconds")}
    if not simulation:
        ecrire(PROGRESSION, etat)
        log(f"début : {noms_vol}")

    journal, deja_dest = lire_journal(), index_dest()
    plan = []                  # à copier
    a_vider = []               # (fichier sur la carte, clé, taille) : effacé si sa copie identique est dans la destination
    dest_de: dict[str, Path] = {}  # clé → copie dans la destination
    verifies: set[str] = set()     # fichiers de la carte dont la copie a été comparée à l'octet pendant ce passage
    vus_ici: set[str] = set()
    deja = 0
    maintenant = datetime.now().isoformat(timespec="seconds")
    for vol in volumes:
        fichiers = lister(vol)
        meta = lire_exif(fichiers)
        par_defaut = appareil_de_la_carte(meta, vol)
        for f in fichiers:
            try:
                st = f.stat()
            except OSError:
                continue
            m = meta.get(nfc(str(f)), {})
            video = f.suffix.lower().lstrip(".") in VIDEOS
            quand = date_prise(m, video) or datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            cle = f"{f.name}|{st.st_size}|{quand}"
            index = f"{nfc(f.name)}|{st.st_size}"
            if cle in journal or cle in vus_ici:  # déjà importé, ou même photo sur les deux cartes d'un double slot
                deja += 1
                if cle in journal and cle not in dest_de:
                    rel = journal[cle]
                    p = DEST / rel if rel and not rel.startswith("(") else None
                    dest_de[cle] = p if p and p.exists() else deja_dest.get(index)
                a_vider.append((f, cle, st.st_size))
                continue
            vus_ici.add(cle)
            app = nom_appareil(m.get("Make"), m.get("Model")) or par_defaut
            if index in deja_dest:  # déjà posé dans la destination (à la main, avant l'outil)
                deja += 1
                dest_de[cle] = deja_dest[index]
                if not simulation:
                    noter([[maintenant, app, f.name, str(st.st_size), quand, str(deja_dest[index].relative_to(DEST)), vol.name]])
                a_vider.append((f, cle, st.st_size))
                continue
            plan.append((f, st.st_size, quand, app, f"{quand[:10]}_{app}", vol, cle))

    octets_total = sum(p[1] for p in plan)
    if simulation:
        par_dossier: dict[str, list[int]] = {}
        for p in plan:
            par_dossier.setdefault(p[4], [0, 0])
            par_dossier[p[4]][0] += 1
            par_dossier[p[4]][1] += p[1]
        print(f"{noms_vol} → {DEST}")
        for d, (n, o) in sorted(par_dossier.items()):
            print(f"  {d} : {fichiers_txt(n)}, {go(o)}")
        print(f"À copier : {fichiers_txt(len(plan))}, {go(octets_total)} · déjà importés : {deja}")
        if vider:
            abri = sum(1 for _, cle, _ in a_vider if dest_de.get(cle) and dest_de[cle].exists())
            print(f"Effacés de la carte après vérification : {len(plan) + abri} "
                  f"(dont {abri} déjà importés) · laissés (copie introuvable) : {len(a_vider) - abri}")
        return 0

    try:
        DEST.mkdir(exist_ok=True)  # jamais ses parents : un disque débranché ne doit pas renaître sur celui du système
        libre = shutil.disk_usage(DEST).free
        msg = None if octets_total + MARGE_DISQUE <= libre else \
            f"Pas assez de place : {go(octets_total)} à copier, {go(libre)} libres. Rien copié, rien effacé."
    except OSError:
        msg = f"Destination introuvable ({DEST}) : rien copié, rien effacé."
    if msg:
        log(msg)
        notifier(msg, "Import photos ⚠︎")
        ecrire(DERNIER, {"fin": datetime.now().isoformat(timespec="seconds"), "volume": noms_vol, "copies": 0,
                         "deja": deja, "dossiers": {}, "erreurs": [msg], "octets": 0})
        PROGRESSION.unlink(missing_ok=True)
        return 1

    depot = depot_local()
    passage = None
    if depot:
        vider_depot(depot)
        passage = depot / datetime.now().strftime("%Y%m%d-%H%M%S")
    etat.update(phase="copie", total=len(plan), octets_total=octets_total)
    copies, erreurs, reserves, octets, interrompu = [], [], set(), 0, False
    lignes, dossiers = [], {}
    try:
        for i, (f, taille, quand, app, dossier, vol, cle) in enumerate(plan):
            etat.update(fait=i, octets_fait=octets, fichier=f.name)
            ecrire(PROGRESSION, etat)
            cible = place_libre(DEST / dossier / f.name, taille, reserves)
            if cible is None:  # le même fichier est déjà à sa place
                deja += 1
                dest_de[cle] = DEST / dossier / f.name
                noter([[maintenant, app, f.name, str(taille), quand, f"{dossier}/{f.name}", vol.name]])
                a_vider.append((f, cle, taille))
                continue
            tampon = passage / dossier / cible.name if passage else cible
            try:
                tampon.parent.mkdir(parents=True, exist_ok=True)
                copier_verifie(f, tampon)
            except OSError as e:
                erreurs.append(f"{f.name} : {e}")
                log(f"erreur {f} : {e}")
                if tampon.exists():
                    tampon.unlink()
                if not vol.exists():
                    erreurs.append(f"{vol.name} retirée en cours de copie")
                    break
                continue
            copies.append((tampon, cible, f, taille, quand, app, dossier, vol, cle))
            octets += taille
    except BaseException as e:  # interruption : on range quand même ce qui est entièrement copié, on n'efface rien
        interrompu = True
        erreurs.append(f"interrompu : {e!r}")
        log(f"interrompu : {e!r}")
    finally:
        etat.update(phase="rangement", fait=len(copies), octets_fait=octets)
        ecrire(PROGRESSION, etat)
        for tampon, cible, f, taille, quand, app, dossier, vol, cle in copies:
            try:
                if tampon != cible:
                    cible.parent.mkdir(parents=True, exist_ok=True)
                    if cible.exists():  # apparu pendant la copie (rare) : on ne l'écrase jamais
                        cible = place_libre(cible, taille, set()) or cible.with_name(f"{cible.stem}_bis{cible.suffix}")
                    os.rename(tampon, cible)
            except OSError as e:
                erreurs.append(f"{f.name} : rangement impossible ({e})")
                log(f"rangement impossible {tampon} → {cible} : {e}")
                continue
            dossiers[dossier] = dossiers.get(dossier, 0) + 1
            lignes.append([maintenant, app, f.name, str(taille), quand, str(cible.relative_to(DEST)), vol.name])
            dest_de[cle] = cible
            verifies.add(str(f))
            a_vider.append((f, cle, taille))
        noter(lignes)
        if passage and passage.exists():
            try:
                vider_depot(passage)
                passage.rmdir()
            except OSError:
                pass

    # Effacement de la carte : seulement ce dont la copie identique est dans la destination, maintenant.
    vides, restes = 0, 0
    if vider and not interrompu:
        a_relire = [x for x in a_vider if str(x[0]) not in verifies]
        etat.update(phase="verification", fait=0, total=len(a_vider), octets_fait=0,
                    octets_total=sum(x[2] for x in a_relire))
        for i, (f, cle, taille) in enumerate(a_vider):
            etat["fait"] = i
            ecrire(PROGRESSION, etat)
            p = dest_de.get(cle)
            try:
                if not f.exists():
                    continue
                if not p or not p.exists() or p.stat().st_size != taille:
                    restes += 1
                    continue
                if str(f) not in verifies:
                    identique = empreinte(f) == empreinte(p)
                    etat["octets_fait"] += taille
                    if not identique:
                        restes += 1
                        log(f"copie différente, laissé sur la carte : {f} / {p}")
                        continue
                os.remove(f)
                vides += 1
            except OSError as e:
                restes += 1
                erreurs.append(f"{f.name} : pas effacé ({e})")
                log(f"pas effacé {f} : {e}")
        if restes:
            log(f"{fichiers_txt(restes)} laissé(s) sur la carte (copie introuvable ou différente dans {DEST.name})")

    ejectees = []
    if CONFIG.get("ejecter_apres_import") and not interrompu and not erreurs:
        etat.update(phase="ejection")
        ecrire(PROGRESSION, etat)
        for vol in volumes:
            if vol.exists() and ejecter(vol):
                ejectees.append(vol.name)
            elif vol.exists():
                erreurs.append(f"{vol.name} pas éjectée (une appli l'utilise)")

    duree = time.time() - debut
    ecrire(DERNIER, {"fin": datetime.now().isoformat(timespec="seconds"), "volume": noms_vol,
                     "volumes": [str(v) for v in volumes], "copies": len(lignes), "deja": deja,
                     "dossiers": dossiers, "erreurs": erreurs, "octets": octets, "duree_s": round(duree),
                     "vides": vides, "restes": restes, "ejectees": ejectees})
    PROGRESSION.unlink(missing_ok=True)
    log(f"fin : {len(lignes)} copiés ({go(octets)}, {round(duree)} s), {deja} déjà là, {vides} effacés de la carte, "
        f"{restes} laissés, éjectée(s) : {ejectees or 'non'}, {len(erreurs)} erreurs · {dossiers}")

    if lignes:
        texte = f"{fichiers_txt(len(lignes))} ({go(octets)}) → " + ", ".join(f"{d} ({n})" for d, n in sorted(dossiers.items())) + "."
    elif not erreurs:
        texte = f"Rien de neuf ({fichiers_txt(deja)} déjà importé{'s' if deja > 1 else ''})."
    else:
        texte = "Rien copié."
    if restes:
        texte += (f" {fichiers_txt(restes)} laissé{'s' if restes > 1 else ''} sur la carte (copie absente ou différente)"
                  + ("; carte éjectée." if ejectees else "."))
    elif vides:
        texte += " Carte vidée et éjectée." if ejectees else " Carte vidée."
    elif ejectees:
        texte += " Carte éjectée."
    if erreurs:
        texte = f"⚠︎ {len(erreurs)} erreur(s), voir le journal. " + texte
    notifier(texte, f"Import photos · {noms_vol}")
    return 1 if erreurs else 0


def lancer(volumes: list[str]) -> None:
    """Import détaché du processus appelant (SwiftBar n'attend pas)."""
    subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "importer", *volumes],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


# ---------------------------------------------------------------- SwiftBar

def q(s) -> str:
    return "'" + str(s).replace("'", "") + "'"


def menu() -> None:
    plugin = os.environ.get("IMPORT_CARTES_PLUGIN", "")
    vols = volumes_cartes()
    present = {}
    for v in vols:
        try:
            present[str(v)] = os.stat(v).st_dev
        except OSError:
            pass
    vus = lire(VUS, {})
    nouveaux = [v for v, dev in present.items() if vus.get(v) != dev]
    if nouveaux or set(vus) != set(present):
        ecrire(VUS, present)
    if nouveaux:  # carte qui vient d'arriver : import automatique
        log(f"carte détectée : {', '.join(nouveaux)}")
        lancer(nouveaux)

    prog = lire(PROGRESSION, None)
    en_cours = bool(prog) and vivant(prog.get("pid"))
    phase = prog.get("phase") if en_cours else None
    dernier = lire(DERNIER, None)

    if phase == "copie":
        print(f"{prog.get('fait', 0)}/{prog.get('total', 0)} | sfimage=camera.fill")
    elif phase == "verification":
        print(f"vérif {prog.get('fait', 0)}/{prog.get('total', 0)} | sfimage=camera.fill")
    elif en_cours or nouveaux:
        print("… | sfimage=camera.fill")
    elif dernier and dernier.get("erreurs"):
        print("⚠︎ | sfimage=camera")
    else:
        print("| sfimage=camera")
    print("---")

    if en_cours:
        print(f"Import en cours : {prog.get('volume', '')}")
        if phase in ("copie", "verification"):
            dt = max(1, time.time() - datetime.fromisoformat(prog["debut"]).timestamp())
            quoi = "copiés" if phase == "copie" else "vérifiés avant effacement de la carte"
            print(f"{prog.get('fait', 0)}/{prog.get('total', 0)} fichiers {quoi}")
            if prog.get("octets_total"):
                print(f"{go(prog.get('octets_fait', 0))} sur {go(prog.get('octets_total', 0))}"
                      + (f" · {prog.get('octets_fait', 0) / dt / 1e6:.0f} Mo/s" if phase == "copie" else ""))
        else:
            print({"lecture": "Lecture des dates…", "rangement": f"Rangement dans {DEST.name}…",
                   "ejection": "Éjection…"}.get(phase, "…"))
        print("---")

    if vols:
        print("Cartes branchées")
        for v in vols:
            print(f"{v.name}")
            print(f"--Importer maintenant | bash={q(plugin)} param1=importer param2={q(v)} terminal=false refresh=true")
            print(f"--Éjecter | bash={q(plugin)} param1=ejecter param2={q(v)} terminal=false refresh=true")
    else:
        print("Aucune carte branchée")
    print("---")

    if dernier:
        fin = datetime.fromisoformat(dernier["fin"]).strftime("%d/%m %H:%M")
        print(f"Dernier import : {fin} · {dernier.get('volume', '')}")
        print(f"--{fichiers_txt(dernier.get('copies', 0))} copiés ({go(dernier.get('octets', 0))}), {dernier.get('deja', 0)} déjà importés")
        if "vides" in dernier:
            print(f"--Carte : {dernier.get('vides', 0)} effacés, {dernier.get('restes', 0)} laissés"
                  + (", éjectée" if dernier.get("ejectees") else ""))
        for d, n in sorted(dernier.get("dossiers", {}).items()):
            print(f"--{d} ({n}) | bash=/usr/bin/open param1={q(DEST / d)} terminal=false")
        for e in dernier.get("erreurs", [])[:10]:
            print(f"--⚠︎ {e.replace('|', '/')}")
    print(f"Tout importer maintenant | bash={q(plugin)} param1=importer terminal=false refresh=true")
    print(f"Ouvrir {DEST.name} | bash=/usr/bin/open param1={q(DEST)} terminal=false")
    print(f"Journal | bash=/usr/bin/open param1=-a param2=Console param3={q(JOURNAL_TEXTE)} terminal=false")


def etat_lisible() -> None:
    prog, dernier = lire(PROGRESSION, None), lire(DERNIER, None)
    print("Cartes :", ", ".join(v.name for v in volumes_cartes()) or "aucune")
    print("En cours :", json.dumps(prog, ensure_ascii=False) if prog and vivant(prog.get("pid")) else "non")
    print("Dernier :", json.dumps(dernier, ensure_ascii=False, indent=1) if dernier else "aucun")


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "menu"
    reste = argv[2:]
    if cmd == "menu":
        menu()
        return 0
    if cmd == "etat":
        etat_lisible()
        return 0
    if cmd in ("importer", "lancer"):
        simulation = "--simulation" in reste
        cibles = [a for a in reste if not a.startswith("--")]
        if cmd == "lancer":
            lancer(cibles)
            return 0
        vols = [Path(c) for c in cibles] if cibles else volumes_cartes()
        return importer(vols, simulation)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
