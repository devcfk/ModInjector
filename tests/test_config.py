import json

from core.config import ConfigManager


def test_sauvegarde_et_rechargement(tmp_path):
    jeu = tmp_path / "jeu"
    jeu.mkdir()
    cfg = ConfigManager(tmp_path / "data" / "config.json", tmp_path / "Mods")
    assert cfg.ajouter_jeu("Mon Jeu", str(jeu)) is None
    cfg.set_load_order("Mon Jeu", ["ModA", "ModB"])

    relu = ConfigManager(tmp_path / "data" / "config.json", tmp_path / "Mods")
    assert relu.erreur_chargement is None
    assert relu.get_jeu("Mon Jeu")["load_order"] == ["ModA", "ModB"]
    assert relu.jeu_actif_nom == "Mon Jeu"
    assert not (tmp_path / "data" / "config.json.tmp").exists()


def test_config_illisible_mise_de_cote(tmp_path):
    fichier = tmp_path / "data" / "config.json"
    fichier.parent.mkdir()
    fichier.write_text("{ cassé", encoding="utf-8")

    cfg = ConfigManager(fichier, tmp_path / "Mods")
    assert cfg.jeux == []
    assert cfg.erreur_chargement
    copies = list(fichier.parent.glob("config.corrompu-*.json"))
    assert len(copies) == 1 and copies[0].read_text(encoding="utf-8") == "{ cassé"

    cfg.save()  # La sauvegarde suivante n'écrase pas la copie
    assert copies[0].exists()


def test_config_de_type_inattendu(tmp_path):
    fichier = tmp_path / "config.json"
    fichier.write_text(json.dumps(["pas", "un", "objet"]), encoding="utf-8")
    cfg = ConfigManager(fichier, tmp_path / "Mods")
    assert cfg.jeux == [] and cfg.erreur_chargement
