import json

from core.config import ConfigManager


def test_save_and_reload(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    cfg = ConfigManager(tmp_path / "data" / "config.json", tmp_path / "Mods")
    assert cfg.add_game("My Game", str(game)) is None
    cfg.set_load_order("My Game", ["ModA", "ModB"])

    reloaded = ConfigManager(tmp_path / "data" / "config.json", tmp_path / "Mods")
    assert reloaded.load_error is None
    assert reloaded.get_game("My Game")["load_order"] == ["ModA", "ModB"]
    assert reloaded.active_game_name == "My Game"
    assert not (tmp_path / "data" / "config.json.tmp").exists()


def test_unreadable_config_is_quarantined(tmp_path):
    config = tmp_path / "data" / "config.json"
    config.parent.mkdir()
    config.write_text("{ broken", encoding="utf-8")

    cfg = ConfigManager(config, tmp_path / "Mods")
    assert cfg.games == []
    assert cfg.load_error
    copies = list(config.parent.glob("config.corrupted-*.json"))
    assert len(copies) == 1 and copies[0].read_text(encoding="utf-8") == "{ broken"

    cfg.save()  # The next save does not overwrite the copy
    assert copies[0].exists()


def test_config_of_unexpected_type(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    cfg = ConfigManager(config, tmp_path / "Mods")
    assert cfg.games == [] and cfg.load_error


def test_force_copy_per_game(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    cfg = ConfigManager(tmp_path / "data" / "config.json", tmp_path / "Mods")
    assert cfg.add_game("My Game", str(game)) is None
    assert cfg.get_game("My Game")["force_copy"] is False
    cfg.set_force_copy("My Game", True)
    assert cfg.update_game("My Game", "Renamed Game", str(game)) is None

    reloaded = ConfigManager(tmp_path / "data" / "config.json", tmp_path / "Mods")
    assert reloaded.get_game("Renamed Game")["force_copy"] is True


def test_french_keys_config_is_migrated(tmp_path):
    """config.json written by v1.0 / v1.1 (French keys) is converted and saved in the new format."""
    config = tmp_path / "data" / "config.json"
    config.parent.mkdir()
    old = {
        "jeux": [
            {"nom": "Old", "dossier": "C:/Games/Old", "load_order": ["ModA"], "copie_forcee": True},
            {"nom": "Other", "dossier": "D:/Other", "load_order": []},  # v1.0: no copie_forcee
        ],
        "jeu_actif": "Other",
    }
    config.write_text(json.dumps(old), encoding="utf-8")

    cfg = ConfigManager(config, tmp_path / "Mods")
    assert cfg.load_error is None
    assert cfg.games == [
        {"name": "Old", "game_dir": "C:/Games/Old", "load_order": ["ModA"], "force_copy": True},
        {"name": "Other", "game_dir": "D:/Other", "load_order": [], "force_copy": False},
    ]
    assert cfg.active_game_name == "Other"

    saved = json.loads(config.read_text(encoding="utf-8"))
    assert saved == {"games": cfg.games, "active_game": "Other"}


def test_single_game_format_is_migrated(tmp_path):
    """Oldest format: one game, mods directly in Mods/."""
    config, mods = tmp_path / "data" / "config.json", tmp_path / "Mods"
    config.parent.mkdir()
    (mods / "ModA").mkdir(parents=True)
    config.write_text(json.dumps({"dossier_jeu": "C:/Games/MyGame", "load_order": ["ModA"]}), encoding="utf-8")

    cfg = ConfigManager(config, mods)
    assert cfg.get_game("MyGame") == {
        "name": "MyGame",
        "game_dir": "C:/Games/MyGame",
        "load_order": ["ModA"],
        "force_copy": False,
    }
    assert (mods / "MyGame" / "ModA").is_dir()
