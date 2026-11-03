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
    # core/ -> modinjector/ -> src/ -> project root
    APP_DIR = Path(__file__).resolve().parents[3]

DATA_DIR = APP_DIR / "data"
CONFIG_FILE = DATA_DIR / "config.json"
MODS_DIR = APP_DIR / "Mods"

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


def safe_folder_name(name: str) -> str:
    """Turn a game name into a folder name that is valid on Windows."""
    return _INVALID_CHARS.sub("_", name).strip().strip(".")


class ConfigManager:
    """
    Manages the multi-game configuration.

    config.json format:
    {
        "games": [{"name": "...", "game_dir": "...", "load_order": ["ModA", ...], "force_copy": false}],
        "active_game": "..."
    }
    Each game's mods are stored in Mods/<game name>/<mod>.
    Older formats (French keys from v1.0/v1.1, single-game format) are converted on load.
    """

    def __init__(self, config_file: Path = CONFIG_FILE, mods_root: Path = MODS_DIR):
        self.config_file = config_file
        self.mods_root = mods_root
        self.games: list[dict] = []
        self.active_game_name: str = ""
        self.load_error: str | None = None  # set if config.json could not be read
        self.load()

    # --- Persistence ---
    def load(self) -> None:
        self.games = []
        self.active_game_name = ""
        self.load_error = None
        if not self.config_file.exists():
            return
        try:
            with open(self.config_file, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("format inattendu")
            if "games" in data:
                self._load_games(data["games"], "name", "game_dir", "force_copy")
                self.active_game_name = str(data.get("active_game", ""))
            elif "jeux" in data:
                # v1.0 / v1.1 format, with French keys: converted and saved in the new format
                self._load_games(data["jeux"], "nom", "dossier", "copie_forcee")
                self.active_game_name = str(data.get("jeu_actif", ""))
                self.save()
            elif data.get("dossier_jeu"):
                self._migrate_single_game_format(data)
        except (OSError, ValueError, TypeError, AttributeError) as e:
            self._quarantine_unreadable_config(e)
            return

        if self.games and not self.get_game(self.active_game_name):
            self.active_game_name = self.games[0]["name"]

    def _load_games(self, games: list, name_key: str, dir_key: str, force_copy_key: str) -> None:
        self.games = [
            {
                "name": str(g.get(name_key, "")),
                "game_dir": str(g.get(dir_key, "")),
                "load_order": [str(m) for m in g.get("load_order", [])],
                "force_copy": bool(g.get(force_copy_key, False)),
            }
            for g in games
            if isinstance(g, dict) and g.get(name_key)
        ]

    def _quarantine_unreadable_config(self, error: Exception) -> None:
        """Keep a copy of the unreadable file so that the next save does not overwrite it."""
        self.games, self.active_game_name = [], ""
        copy = self.config_file.with_name(f"{self.config_file.stem}.corrupted-{time.strftime('%Y%m%d-%H%M%S')}.json")
        try:
            self.config_file.replace(copy)
            self.load_error = f"La configuration était illisible ({error}).\nElle a été mise de côté dans :\n{copy}"
        except OSError:
            self.load_error = f"La configuration est illisible ({error})."
        print(self.load_error)

    def save(self) -> None:
        data = {"games": self.games, "active_game": self.active_game_name}
        try:
            write_json_atomic(self.config_file, data)
        except OSError as e:
            print(f"Error while saving the configuration: {e}")

    def _migrate_single_game_format(self, data: dict) -> None:
        """Oldest format: a single game (dossier_jeu) with mods directly in Mods/."""
        game_dir = data["dossier_jeu"]
        name = Path(game_dir).name or "Jeu"
        self.games = [
            {"name": name, "game_dir": game_dir, "load_order": list(data.get("load_order", [])), "force_copy": False}
        ]
        self.active_game_name = name

        # Move existing mods (Mods/<mod>) to Mods/<game>/<mod>
        target = self.mods_dir(name)
        target.mkdir(parents=True, exist_ok=True)
        if self.mods_root.exists():
            for item in list(self.mods_root.iterdir()):
                if item.is_dir() and item != target:
                    try:
                        shutil.move(str(item), str(target / item.name))
                    except Exception as e:
                        print(f"Could not migrate {item.name}: {e}")
        self.save()

    # --- Game lookup ---
    def game_names(self) -> list[str]:
        return [g["name"] for g in self.games]

    def get_game(self, name: str) -> dict | None:
        for g in self.games:
            if g["name"] == name:
                return g
        return None

    def active_game(self) -> dict | None:
        return self.get_game(self.active_game_name)

    def set_active_game(self, name: str) -> None:
        if self.get_game(name):
            self.active_game_name = name
            self.save()

    def mods_dir(self, name: str) -> Path:
        return self.mods_root / safe_folder_name(name)

    # --- Game changes ---
    def add_game(self, name: str, game_dir: str) -> str | None:
        """Return an error message, or None on success."""
        name = name.strip()
        if not name or not safe_folder_name(name):
            return "Le nom du jeu est invalide."
        if any(safe_folder_name(n).lower() == safe_folder_name(name).lower() for n in self.game_names()):
            return "Un jeu portant ce nom existe déjà."
        if not game_dir or not Path(game_dir).is_dir():
            return "Le dossier du jeu n'existe pas."
        self.games.append({"name": name, "game_dir": game_dir, "load_order": [], "force_copy": False})
        self.mods_dir(name).mkdir(parents=True, exist_ok=True)
        if not self.active_game_name:
            self.active_game_name = name
        self.save()
        return None

    def update_game(self, old_name: str, name: str, game_dir: str) -> str | None:
        """Rename a game and/or change its folder. Return an error message, or None on success."""
        game = self.get_game(old_name)
        if game is None:
            return "Jeu introuvable."
        name = name.strip()
        if not name or not safe_folder_name(name):
            return "Le nom du jeu est invalide."
        if not game_dir or not Path(game_dir).is_dir():
            return "Le dossier du jeu n'existe pas."

        if name != old_name:
            if any(
                n != old_name and safe_folder_name(n).lower() == safe_folder_name(name).lower()
                for n in self.game_names()
            ):
                return "Un jeu portant ce nom existe déjà."
            old_dir, new_dir = self.mods_dir(old_name), self.mods_dir(name)
            if old_dir.exists() and old_dir != new_dir:
                try:
                    old_dir.rename(new_dir)
                except OSError as e:
                    return f"Impossible de renommer le dossier des mods : {e}"
            if self.active_game_name == old_name:
                self.active_game_name = name

        game["name"] = name
        game["game_dir"] = game_dir
        self.save()
        return None

    def remove_game(self, name: str) -> None:
        """Remove the game from the config. Its mods (Mods/<game>) are kept on disk."""
        self.games = [g for g in self.games if g["name"] != name]
        if self.active_game_name == name:
            self.active_game_name = self.games[0]["name"] if self.games else ""
        self.save()

    def set_load_order(self, name: str, load_order: list[str]) -> None:
        game = self.get_game(name)
        if game is not None:
            game["load_order"] = list(load_order)
            self.save()

    def set_force_copy(self, name: str, enabled: bool) -> None:
        """Really copy files instead of using hard links when deploying this game."""
        game = self.get_game(name)
        if game is not None:
            game["force_copy"] = bool(enabled)
            self.save()
