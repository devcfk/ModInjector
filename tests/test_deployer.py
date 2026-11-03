import json
import os

import pytest

from core import deployer
from core.deployer import (deploy_mods, get_deployed_mods, is_deploy_interrupted, purge_mods,
                           read_state, state_path)


class Logs(list):
    def __call__(self, message=""):
        self.append(str(message))

    def contient(self, texte: str) -> bool:
        return any(texte in ligne for ligne in self)


def ecrire(chemin, contenu: str):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    """Un jeu avec deux fichiers d'origine et deux mods en conflit sur config/game.ini."""
    jeu, mods = tmp_path / "jeu", tmp_path / "Mods"
    ecrire(jeu / "config" / "game.ini", "original")
    ecrire(jeu / "textures" / "hero.tex", "hero original")
    ecrire(mods / "ModA" / "config" / "game.ini", "A")
    ecrire(mods / "ModA" / "textures" / "new.tex", "nouveau A")
    ecrire(mods / "ModB" / "config" / "game.ini", "B")
    ecrire(mods / "ModB" / "modinfo.json", "{}")
    return jeu, mods


def snapshot(dossier):
    return {str(p.relative_to(dossier)): p.read_text(encoding="utf-8")
            for p in sorted(dossier.rglob("*")) if p.is_file()}


def test_deploiement_puis_purge_restaure_le_jeu(env):
    jeu, mods = env
    avant = snapshot(jeu)

    assert deploy_mods(jeu, mods, ["ModA", "ModB"], Logs())
    assert (jeu / "config" / "game.ini").read_text(encoding="utf-8") == "B"  # le dernier mod gagne
    assert os.path.samefile(jeu / "config" / "game.ini", mods / "ModB" / "config" / "game.ini")
    assert (jeu / "textures" / "new.tex").read_text(encoding="utf-8") == "nouveau A"
    assert not (jeu / "modinfo.json").exists()
    assert get_deployed_mods(jeu) == ["ModA", "ModB"]
    assert not is_deploy_interrupted(jeu)

    assert purge_mods(jeu, Logs())
    assert snapshot(jeu) == avant
    assert not (jeu / ".mod_manager").exists()
    assert (mods / "ModB" / "config" / "game.ini").read_text(encoding="utf-8") == "B"  # les mods sont intacts


def test_redeploiement_idempotent(env):
    jeu, mods = env
    avant = snapshot(jeu)
    assert deploy_mods(jeu, mods, ["ModA"], Logs())
    assert deploy_mods(jeu, mods, ["ModB", "ModA"], Logs())
    assert (jeu / "config" / "game.ini").read_text(encoding="utf-8") == "A"
    assert purge_mods(jeu, Logs())
    assert snapshot(jeu) == avant


def test_purge_sur_jeu_propre_ne_cree_rien(env):
    jeu, _ = env
    assert purge_mods(jeu, Logs())
    assert not (jeu / ".mod_manager").exists()


def test_fichier_org_preexistant_jamais_ecrase(env):
    jeu, mods = env
    ecrire(jeu / "config" / "game.ini.org", "fichier .org livré avec le jeu")
    avant = snapshot(jeu)

    assert deploy_mods(jeu, mods, ["ModB"], Logs())
    assert (jeu / "config" / "game.ini.org").read_text(encoding="utf-8") == "fichier .org livré avec le jeu"
    assert (jeu / "config" / "game.ini.1.org").read_text(encoding="utf-8") == "original"

    assert purge_mods(jeu, Logs())
    assert snapshot(jeu) == avant


def test_fichier_remplace_par_le_jeu_est_conserve(env):
    jeu, mods = env
    assert deploy_mods(jeu, mods, ["ModB"], Logs())
    cible = jeu / "config" / "game.ini"
    cible.unlink()  # Une mise à jour du jeu remplace le fichier
    ecrire(cible, "version patchée du jeu")

    logs = Logs()
    assert purge_mods(jeu, logs)
    assert cible.read_text(encoding="utf-8") == "version patchée du jeu"
    assert (jeu / "config" / "game.ini.org").read_text(encoding="utf-8") == "original"  # ancien original laissé de côté
    assert logs.contient("[CONSERVÉ]")
    assert (mods / "ModB" / "config" / "game.ini").read_text(encoding="utf-8") == "B"


def test_modification_sur_place_signalee(env):
    jeu, mods = env
    assert deploy_mods(jeu, mods, ["ModB"], Logs())
    cible = jeu / "config" / "game.ini"
    with open(cible, "a", encoding="utf-8") as f:  # Écriture à travers le hard link
        f.write(" + modifié par le jeu")
    os.utime(cible, ns=(1, 1))

    logs = Logs()
    assert purge_mods(jeu, logs)
    assert logs.contient("modifié sur place")
    assert cible.read_text(encoding="utf-8") == "original"


def test_purge_partielle_conserve_l_etat(env, monkeypatch):
    jeu, mods = env
    assert deploy_mods(jeu, mods, ["ModA", "ModB"], Logs())

    vrai_unlink = deployer._unlink
    def unlink_verrouille(path):
        if path.name == "game.ini":
            raise PermissionError("fichier utilisé par le jeu")
        vrai_unlink(path)
    monkeypatch.setattr(deployer, "_unlink", unlink_verrouille)

    assert not purge_mods(jeu, Logs())
    etat = read_state(jeu)
    assert list(etat["injected"]) == [os.path.join("config", "game.ini")]
    assert list(etat["backups"]) == [os.path.join("config", "game.ini")]
    assert not deploy_mods(jeu, mods, ["ModA"], Logs())  # Redéploiement refusé tant que la purge échoue

    monkeypatch.setattr(deployer, "_unlink", vrai_unlink)
    assert purge_mods(jeu, Logs())
    assert (jeu / "config" / "game.ini").read_text(encoding="utf-8") == "original"
    assert not (jeu / "textures" / "new.tex").exists()


def test_deploiement_interrompu_reste_purgeable(env, monkeypatch):
    jeu, mods = env
    avant = snapshot(jeu)
    vrai_link, appels = os.link, []
    def link_qui_plante(src, dst):
        if appels:
            raise RuntimeError("crash simulé")
        appels.append(dst)
        vrai_link(src, dst)
    monkeypatch.setattr(deployer.os, "link", link_qui_plante)

    with pytest.raises(RuntimeError):
        deploy_mods(jeu, mods, ["ModA"], Logs())
    assert is_deploy_interrupted(jeu)
    assert len(read_state(jeu)["injected"]) == 1

    monkeypatch.setattr(deployer.os, "link", vrai_link)
    assert purge_mods(jeu, Logs())
    assert snapshot(jeu) == avant


def test_echec_de_copie_restaure_l_original(env, monkeypatch):
    jeu, mods = env
    avant = snapshot(jeu)
    def echec(*_args):
        raise OSError("lien impossible")
    monkeypatch.setattr(deployer.os, "link", echec)
    monkeypatch.setattr(deployer.shutil, "copy2", echec)

    assert not deploy_mods(jeu, mods, ["ModB"], Logs())
    assert purge_mods(jeu, Logs())
    assert snapshot(jeu) == avant


def test_repli_sur_copie(env, monkeypatch):
    jeu, mods = env
    def echec(*_args):
        raise OSError("lien impossible")
    monkeypatch.setattr(deployer.os, "link", echec)

    assert deploy_mods(jeu, mods, ["ModB"], Logs())
    cible = jeu / "config" / "game.ini"
    assert cible.read_text(encoding="utf-8") == "B" and not os.path.samefile(cible, mods / "ModB" / "config" / "game.ini")
    assert purge_mods(jeu, Logs())
    assert cible.read_text(encoding="utf-8") == "original"


def test_etat_illisible_bloque_sans_rien_toucher(env):
    jeu, mods = env
    avant = snapshot(jeu)
    ecrire(state_path(jeu), "{ pas du json")

    assert not purge_mods(jeu, Logs())
    assert not deploy_mods(jeu, mods, ["ModA"], Logs())
    assert is_deploy_interrupted(jeu)
    assert get_deployed_mods(jeu) == []
    apres = snapshot(jeu)
    apres.pop(os.path.join(".mod_manager", "state.json"))
    assert apres == avant


def test_ancien_format_d_etat(env):
    jeu, mods = env
    avant = snapshot(jeu)
    # Simule un déploiement fait par l'ancienne version (sans empreintes)
    (jeu / "config" / "game.ini").rename(jeu / "config" / "game.ini.org")
    os.link(mods / "ModB" / "config" / "game.ini", jeu / "config" / "game.ini")
    ecrire(state_path(jeu), json.dumps({
        "deployed_mods": ["ModB"],
        "injected_files": [os.path.join("config", "game.ini")],
        "org_files": [os.path.join("config", "game.ini")],
    }))

    assert get_deployed_mods(jeu) == ["ModB"]
    assert purge_mods(jeu, Logs())
    assert snapshot(jeu) == avant


def test_chemins_hors_du_jeu_ignores(env, tmp_path):
    jeu, _ = env
    victime = tmp_path / "victime.txt"
    ecrire(victime, "à protéger")
    ecrire(state_path(jeu), json.dumps({"deployed_mods": [], "injected": {"../victime.txt": {}}, "backups": {}}))

    logs = Logs()
    assert purge_mods(jeu, logs)
    assert victime.exists()
    assert logs.contient("hors du dossier du jeu")


def test_dossier_mod_manager_dans_un_mod_ignore(env):
    jeu, mods = env
    ecrire(mods / "ModA" / ".mod_manager" / "state.json", "piège")
    assert deploy_mods(jeu, mods, ["ModA"], Logs())
    assert read_state(jeu)["deployed_mods"] == ["ModA"]


def test_mod_introuvable_ignore(env):
    jeu, mods = env
    logs = Logs()
    assert deploy_mods(jeu, mods, ["Fantome", "ModA"], logs)
    assert logs.contient("introuvable")
    assert get_deployed_mods(jeu) == ["ModA"]


def test_copie_forcee_n_utilise_pas_de_hard_link(env, monkeypatch):
    jeu, mods = env
    avant = snapshot(jeu)
    def interdit(*_args):
        raise AssertionError("os.link ne doit pas être appelé")
    monkeypatch.setattr(deployer.os, "link", interdit)

    logs = Logs()
    assert deploy_mods(jeu, mods, ["ModA", "ModB"], logs, copie_forcee=True)
    cible = jeu / "config" / "game.ini"
    assert cible.read_text(encoding="utf-8") == "B"
    assert not os.path.samefile(cible, mods / "ModB" / "config" / "game.ini")
    assert {info["mode"] for info in read_state(jeu)["injected"].values()} == {"copy"}
    assert not logs.contient("Hard link échoué")

    assert purge_mods(jeu, Logs())
    assert snapshot(jeu) == avant


def test_copie_forcee_autorise_un_autre_disque(env, monkeypatch):
    jeu, mods = env
    monkeypatch.setattr(deployer, "is_same_drive", lambda *_args: False)

    logs = Logs()
    assert not deploy_mods(jeu, mods, ["ModB"], logs)
    assert logs.contient("Forcer la copie réelle")
    assert get_deployed_mods(jeu) == []

    assert deploy_mods(jeu, mods, ["ModB"], Logs(), copie_forcee=True)
    assert (jeu / "config" / "game.ini").read_text(encoding="utf-8") == "B"
