import json
import re
import shutil
import sys
import time
from pathlib import Path

from core.fsutils import write_json_atomic

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent
else:
    # core/ -> modinjector/ -> src/ -> racine du projet
    APP_DIR = Path(__file__).resolve().parents[3]

DATA_DIR = APP_DIR / "data"
CONFIG_FILE = DATA_DIR / "config.json"
MODS_DIR = APP_DIR / "Mods"

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


def nom_dossier_valide(nom: str) -> str:
    """Transforme un nom de jeu en nom de dossier utilisable sous Windows."""
    return _INVALID_CHARS.sub("_", nom).strip().strip(".")


class ConfigManager:
    """
    Gère la configuration multi-jeux.

    Format de config.json :
    {
        "jeux": [{"nom": "...", "dossier": "...", "load_order": ["ModA", ...], "copie_forcee": false}],
        "jeu_actif": "..."
    }
    Les mods de chaque jeu sont rangés dans Mods/<nom du jeu>/<mod>.
    """

    def __init__(self, config_file: Path = CONFIG_FILE, mods_root: Path = MODS_DIR):
        self.config_file = config_file
        self.mods_root = mods_root
        self.jeux: list[dict] = []
        self.jeu_actif_nom: str = ""
        self.erreur_chargement: str | None = None  # renseigné si config.json était illisible
        self.load()

    # --- Persistance ---
    def load(self) -> None:
        self.jeux = []
        self.jeu_actif_nom = ""
        self.erreur_chargement = None
        if not self.config_file.exists():
            return
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("format inattendu")
            if "jeux" in data:
                self.jeux = [
                    {
                        "nom": str(j.get("nom", "")),
                        "dossier": str(j.get("dossier", "")),
                        "load_order": [str(m) for m in j.get("load_order", [])],
                        "copie_forcee": bool(j.get("copie_forcee", False)),
                    }
                    for j in data["jeux"]
                    if isinstance(j, dict) and j.get("nom")
                ]
                self.jeu_actif_nom = str(data.get("jeu_actif", ""))
            elif data.get("dossier_jeu"):
                self._migrer_ancien_format(data)
        except (OSError, ValueError, TypeError, AttributeError) as e:
            self._mettre_de_cote_config_illisible(e)
            return

        if self.jeux and not self.get_jeu(self.jeu_actif_nom):
            self.jeu_actif_nom = self.jeux[0]["nom"]

    def _mettre_de_cote_config_illisible(self, erreur: Exception) -> None:
        """Conserve une copie du fichier illisible pour qu'il ne soit pas écrasé à la prochaine sauvegarde."""
        self.jeux, self.jeu_actif_nom = [], ""
        copie = self.config_file.with_name(f"{self.config_file.stem}.corrompu-{time.strftime('%Y%m%d-%H%M%S')}.json")
        try:
            self.config_file.replace(copie)
            self.erreur_chargement = (f"La configuration était illisible ({erreur}).\n"
                                      f"Elle a été mise de côté dans :\n{copie}")
        except OSError:
            self.erreur_chargement = f"La configuration est illisible ({erreur})."
        print(self.erreur_chargement)

    def save(self) -> None:
        data = {"jeux": self.jeux, "jeu_actif": self.jeu_actif_nom}
        try:
            write_json_atomic(self.config_file, data)
        except OSError as e:
            print(f"Erreur lors de la sauvegarde: {e}")

    def _migrer_ancien_format(self, data: dict) -> None:
        """Ancien format : un seul jeu (dossier_jeu) et des mods directement dans Mods/."""
        dossier = data["dossier_jeu"]
        nom = Path(dossier).name or "Jeu"
        self.jeux = [{"nom": nom, "dossier": dossier, "load_order": list(data.get("load_order", [])),
                      "copie_forcee": False}]
        self.jeu_actif_nom = nom

        # Déplace les mods existants (Mods/<mod>) vers Mods/<jeu>/<mod>
        cible = self.mods_dir(nom)
        cible.mkdir(parents=True, exist_ok=True)
        if self.mods_root.exists():
            for item in list(self.mods_root.iterdir()):
                if item.is_dir() and item != cible:
                    try:
                        shutil.move(str(item), str(cible / item.name))
                    except Exception as e:
                        print(f"Migration impossible pour {item.name}: {e}")
        self.save()

    # --- Accès aux jeux ---
    def noms_jeux(self) -> list[str]:
        return [j["nom"] for j in self.jeux]

    def get_jeu(self, nom: str) -> dict | None:
        for j in self.jeux:
            if j["nom"] == nom:
                return j
        return None

    def jeu_actif(self) -> dict | None:
        return self.get_jeu(self.jeu_actif_nom)

    def set_jeu_actif(self, nom: str) -> None:
        if self.get_jeu(nom):
            self.jeu_actif_nom = nom
            self.save()

    def mods_dir(self, nom: str) -> Path:
        return self.mods_root / nom_dossier_valide(nom)

    # --- Modification des jeux ---
    def ajouter_jeu(self, nom: str, dossier: str) -> str | None:
        """Retourne un message d'erreur, ou None si OK."""
        nom = nom.strip()
        if not nom or not nom_dossier_valide(nom):
            return "Le nom du jeu est invalide."
        if any(nom_dossier_valide(n).lower() == nom_dossier_valide(nom).lower() for n in self.noms_jeux()):
            return "Un jeu portant ce nom existe déjà."
        if not dossier or not Path(dossier).is_dir():
            return "Le dossier du jeu n'existe pas."
        self.jeux.append({"nom": nom, "dossier": dossier, "load_order": [], "copie_forcee": False})
        self.mods_dir(nom).mkdir(parents=True, exist_ok=True)
        if not self.jeu_actif_nom:
            self.jeu_actif_nom = nom
        self.save()
        return None

    def modifier_jeu(self, ancien_nom: str, nom: str, dossier: str) -> str | None:
        jeu = self.get_jeu(ancien_nom)
        if jeu is None:
            return "Jeu introuvable."
        nom = nom.strip()
        if not nom or not nom_dossier_valide(nom):
            return "Le nom du jeu est invalide."
        if not dossier or not Path(dossier).is_dir():
            return "Le dossier du jeu n'existe pas."

        if nom != ancien_nom:
            if any(
                n != ancien_nom and nom_dossier_valide(n).lower() == nom_dossier_valide(nom).lower()
                for n in self.noms_jeux()
            ):
                return "Un jeu portant ce nom existe déjà."
            ancien_dir, nouveau_dir = self.mods_dir(ancien_nom), self.mods_dir(nom)
            if ancien_dir.exists() and ancien_dir != nouveau_dir:
                try:
                    ancien_dir.rename(nouveau_dir)
                except OSError as e:
                    return f"Impossible de renommer le dossier des mods : {e}"
            if self.jeu_actif_nom == ancien_nom:
                self.jeu_actif_nom = nom

        jeu["nom"] = nom
        jeu["dossier"] = dossier
        self.save()
        return None

    def supprimer_jeu(self, nom: str) -> None:
        """Retire le jeu de la config. Ses mods (Mods/<jeu>) sont conservés sur le disque."""
        self.jeux = [j for j in self.jeux if j["nom"] != nom]
        if self.jeu_actif_nom == nom:
            self.jeu_actif_nom = self.jeux[0]["nom"] if self.jeux else ""
        self.save()

    def set_load_order(self, nom: str, load_order: list[str]) -> None:
        jeu = self.get_jeu(nom)
        if jeu is not None:
            jeu["load_order"] = list(load_order)
            self.save()

    def set_copie_forcee(self, nom: str, active: bool) -> None:
        """Copie réelle des fichiers au lieu de hard links lors des déploiements de ce jeu."""
        jeu = self.get_jeu(nom)
        if jeu is not None:
            jeu["copie_forcee"] = bool(active)
            self.save()
