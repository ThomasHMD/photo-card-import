#!/usr/bin/env python3
"""Tests de import-cartes.py sur de fausses cartes (de simples dossiers avec un DCIM).

Ils ne touchent jamais un vrai volume, la vraie destination ni l'état de la machine : chaque test a ses réglages
(IMPORT_CARTES_CONFIG), son état (IMPORT_CARTES_ETAT) et passe ses cartes en argument. La commande « menu », qui
regarde les vrais volumes de /Volumes, n'est jamais lancée ici. Il faut exiftool (brew install exiftool).

  python3 tests/test_import.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "import-cartes.py"
EXIFTOOL = shutil.which("exiftool", path="/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", ""))
# Un JPEG valide de 1 × 1 pixel : exiftool y écrit ensuite la marque, le modèle et la date de prise de vue.
JPEG = bytes.fromhex(
    "FFD8FFE000104A46494600010100000100010000FFDB004300030202020203020202030303030406040404040408060605060908"
    "0A0A090809090A0C0F0C0A0B0E0B09090D110D0E0F101011100A0C12131210130F101010FFC9000B080001000101011100FFCC00"
    "0600101005FFDA0008010100003F00D2CF20FFD9")


@unittest.skipUnless(EXIFTOOL, "exiftool introuvable (brew install exiftool)")
class ImportCartes(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="import-cartes-test-"))
        self.dest = self.t / "dest"
        conf = self.t / "conf"
        conf.mkdir()
        self.config = conf / "appareils.json"
        # Destination relative au fichier de réglages, journal par défaut (conf/journal/importes.tsv).
        self.regler(vider_la_carte=True)
        self.journal = conf / "journal" / "importes.tsv"

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def regler(self, **reglages):
        base = {"destination": "../dest", "depot": str(self.t / "depot"), "notifications": False,
                "vider_la_carte": True, "ejecter_apres_import": False, "volumes_ignores": [],
                "appareils": [{"marque": "NIKON", "modele": "D750", "nom": "D750"}],
                "extensions_photo": ["jpg", "nef"], "extensions_video": ["mov"]}
        base.update(reglages)
        self.config.write_text(json.dumps(base), encoding="utf-8")

    def photo(self, carte: str, nom: str, modele="NIKON D750", date="2026:11:09 10:00:00", note="") -> Path:
        f = self.t / carte / "DCIM" / "100TEST" / nom
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(JPEG)
        marque = modele.split()[0]
        subprocess.run([EXIFTOOL, "-q", "-overwrite_original", f"-Make={marque}", f"-Model={modele}",
                        f"-DateTimeOriginal={date}", f"-Comment={note or nom}", str(f)], check=True)
        return f

    def importer(self, *cartes: str, simulation=False) -> subprocess.CompletedProcess:
        env = dict(os.environ, IMPORT_CARTES_CONFIG=str(self.config), IMPORT_CARTES_ETAT=str(self.t / "etat"))
        args = [sys.executable, "-I", str(SCRIPT), "importer"] + (["--simulation"] if simulation else [])
        return subprocess.run(args + [str(self.t / c) for c in cartes], env=env, capture_output=True, text=True)

    def sur_la_carte(self, carte: str) -> list[str]:
        return sorted(p.name for p in (self.t / carte / "DCIM").rglob("*") if p.is_file())

    def dans(self, dossier: str) -> list[str]:
        d = self.dest / dossier
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []

    # ------------------------------------------------------------------------------------------------

    def test_copie_par_jour_et_appareil_puis_carte_videe(self):
        a = self.photo("CARTE", "DSC_0001.JPG")
        b = self.photo("CARTE", "DSC_0002.JPG", date="2026:11:08 18:30:00")
        c = self.photo("CARTE", "IMG_0003.JPG", modele="FUJIFILM X-Pro9")
        octets = {f.name: f.read_bytes() for f in (a, b, c)}
        r = self.importer("CARTE")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.dans("2026-11-09_D750"), ["DSC_0001.JPG"])
        self.assertEqual(self.dans("2026-11-08_D750"), ["DSC_0002.JPG"])
        self.assertEqual(self.dans("2026-11-09_FUJIFILMXPro9"), ["IMG_0003.JPG"])  # appareil inconnu : modèle EXIF
        for dossier in ("2026-11-09_D750", "2026-11-08_D750", "2026-11-09_FUJIFILMXPro9"):
            for n in self.dans(dossier):
                self.assertEqual((self.dest / dossier / n).read_bytes(), octets[n])
        self.assertEqual(self.sur_la_carte("CARTE"), [])
        self.assertEqual(len(self.journal.read_text(encoding="utf-8").splitlines()), 4)  # en-tête + 3
        self.assertEqual(list((self.t / "depot").iterdir()), [])  # dépôt intermédiaire vidé

    def test_jamais_deux_fois(self):
        f = self.photo("CARTE", "DSC_0001.JPG")
        garde = f.read_bytes()
        self.importer("CARTE")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(garde)  # la même photo revient (carte rebranchée sans avoir été vidée)
        r = self.importer("CARTE")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.dans("2026-11-09_D750"), ["DSC_0001.JPG"])
        self.assertEqual(self.sur_la_carte("CARTE"), [])  # sa copie identique est là : effacée

    def test_copie_disparue_reste_sur_la_carte(self):
        self.regler(vider_la_carte=False)
        f = self.photo("CARTE", "DSC_0001.JPG")
        self.importer("CARTE")
        shutil.rmtree(self.dest / "2026-11-09_D750")  # dossier vidé depuis l'import
        self.regler(vider_la_carte=True)
        r = self.importer("CARTE")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(f.exists())  # copie introuvable : jamais effacée
        self.assertFalse((self.dest / "2026-11-09_D750").exists())  # déjà importée : pas recopiée

    def test_homonyme_different_jamais_ecrase(self):
        self.photo("CARTE", "DSC_0001.JPG", note="premiere")
        self.importer("CARTE")
        self.photo("CARTE", "DSC_0001.JPG", note="autre photo, compteur repassé par zéro")
        r = self.importer("CARTE")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.dans("2026-11-09_D750"), ["DSC_0001.JPG", "DSC_0001_2.JPG"])

    def test_double_slot_copie_une_fois(self):
        f = self.photo("SLOT1", "DSC_0001.JPG")
        (self.t / "SLOT2" / "DCIM" / "100TEST").mkdir(parents=True)
        shutil.copy2(f, self.t / "SLOT2" / "DCIM" / "100TEST" / f.name)
        r = self.importer("SLOT1", "SLOT2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.dans("2026-11-09_D750"), ["DSC_0001.JPG"])
        self.assertEqual(self.sur_la_carte("SLOT1") + self.sur_la_carte("SLOT2"), [])

    def test_carte_gardee_si_vider_desactive(self):
        self.regler(vider_la_carte=False)
        self.photo("CARTE", "DSC_0001.JPG")
        self.importer("CARTE")
        self.assertEqual(self.dans("2026-11-09_D750"), ["DSC_0001.JPG"])
        self.assertEqual(self.sur_la_carte("CARTE"), ["DSC_0001.JPG"])

    def test_simulation_ne_touche_a_rien(self):
        self.photo("CARTE", "DSC_0001.JPG")
        r = self.importer("CARTE", simulation=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("À copier : 1 fichier", r.stdout)
        self.assertEqual(self.sur_la_carte("CARTE"), ["DSC_0001.JPG"])
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.dans("2026-11-09_D750"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
