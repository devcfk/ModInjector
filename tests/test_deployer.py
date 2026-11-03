import json
import os

import pytest
from core import deployer
from core.deployer import deploy_mods, get_deployed_mods, is_deploy_interrupted, purge_mods, read_state, state_path


class Logs(list):
    def __call__(self, message=""):
        self.append(str(message))

    def contains(self, text: str) -> bool:
        return any(text in line for line in self)


def write(path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    """Un game avec deux fichiers d'origine et deux mods en conflit sur config/game.ini."""
    game, mods = tmp_path / "game", tmp_path / "Mods"
    write(game / "config" / "game.ini", "original")
    write(game / "textures" / "hero.tex", "hero original")
    write(mods / "ModA" / "config" / "game.ini", "A")
    write(mods / "ModA" / "textures" / "new.tex", "new A")
    write(mods / "ModB" / "config" / "game.ini", "B")
    write(mods / "ModB" / "modinfo.json", "{}")
    return game, mods


def snapshot(folder):
    return {str(p.relative_to(folder)): p.read_text(encoding="utf-8") for p in sorted(folder.rglob("*")) if p.is_file()}


def test_deploy_then_purge_restores_game(env):
    game, mods = env
    before = snapshot(game)

    assert deploy_mods(game, mods, ["ModA", "ModB"], Logs())
    assert (game / "config" / "game.ini").read_text(encoding="utf-8") == "B"  # the last mod wins
    assert os.path.samefile(game / "config" / "game.ini", mods / "ModB" / "config" / "game.ini")
    assert (game / "textures" / "new.tex").read_text(encoding="utf-8") == "new A"
    assert not (game / "modinfo.json").exists()
    assert get_deployed_mods(game) == ["ModA", "ModB"]
    assert not is_deploy_interrupted(game)

    assert purge_mods(game, Logs())
    assert snapshot(game) == before
    assert not (game / ".mod_manager").exists()
    assert (mods / "ModB" / "config" / "game.ini").read_text(encoding="utf-8") == "B"  # mods are untouched


def test_redeploy_is_idempotent(env):
    game, mods = env
    before = snapshot(game)
    assert deploy_mods(game, mods, ["ModA"], Logs())
    assert deploy_mods(game, mods, ["ModB", "ModA"], Logs())
    assert (game / "config" / "game.ini").read_text(encoding="utf-8") == "A"
    assert purge_mods(game, Logs())
    assert snapshot(game) == before


def test_purge_on_clean_game_creates_nothing(env):
    game, _ = env
    assert purge_mods(game, Logs())
    assert not (game / ".mod_manager").exists()


def test_existing_org_file_is_never_overwritten(env):
    game, mods = env
    write(game / "config" / "game.ini.org", ".org file shipped with the game")
    before = snapshot(game)

    assert deploy_mods(game, mods, ["ModB"], Logs())
    assert (game / "config" / "game.ini.org").read_text(encoding="utf-8") == ".org file shipped with the game"
    assert (game / "config" / "game.ini.1.org").read_text(encoding="utf-8") == "original"

    assert purge_mods(game, Logs())
    assert snapshot(game) == before


def test_file_replaced_by_game_is_kept(env):
    game, mods = env
    assert deploy_mods(game, mods, ["ModB"], Logs())
    target = game / "config" / "game.ini"
    target.unlink()  # A game update replaces the file
    write(target, "patched game version")

    logs = Logs()
    assert purge_mods(game, logs)
    assert target.read_text(encoding="utf-8") == "patched game version"
    assert (game / "config" / "game.ini.org").read_text(encoding="utf-8") == "original"  # old original left aside
    assert logs.contains("[CONSERVÉ]")
    assert (mods / "ModB" / "config" / "game.ini").read_text(encoding="utf-8") == "B"


def test_in_place_change_is_reported(env):
    game, mods = env
    assert deploy_mods(game, mods, ["ModB"], Logs())
    target = game / "config" / "game.ini"
    with open(target, "a", encoding="utf-8") as f:  # Write through the hard link
        f.write(" + modified by the game")
    os.utime(target, ns=(1, 1))

    logs = Logs()
    assert purge_mods(game, logs)
    assert logs.contains("modifié sur place")
    assert target.read_text(encoding="utf-8") == "original"


def test_partial_purge_keeps_state(env, monkeypatch):
    game, mods = env
    assert deploy_mods(game, mods, ["ModA", "ModB"], Logs())

    real_unlink = deployer._unlink

    def locked_unlink(path):
        if path.name == "game.ini":
            raise PermissionError("file used by the game")
        real_unlink(path)

    monkeypatch.setattr(deployer, "_unlink", locked_unlink)

    assert not purge_mods(game, Logs())
    state = read_state(game)
    assert list(state["injected"]) == [os.path.join("config", "game.ini")]
    assert list(state["backups"]) == [os.path.join("config", "game.ini")]
    assert not deploy_mods(game, mods, ["ModA"], Logs())  # Redeploy refused while the purge fails

    monkeypatch.setattr(deployer, "_unlink", real_unlink)
    assert purge_mods(game, Logs())
    assert (game / "config" / "game.ini").read_text(encoding="utf-8") == "original"
    assert not (game / "textures" / "new.tex").exists()


def test_interrupted_deployment_can_be_purged(env, monkeypatch):
    game, mods = env
    before = snapshot(game)
    real_link, calls = os.link, []

    def crashing_link(src, dst):
        if calls:
            raise RuntimeError("simulated crash")
        calls.append(dst)
        real_link(src, dst)

    monkeypatch.setattr(deployer.os, "link", crashing_link)

    with pytest.raises(RuntimeError):
        deploy_mods(game, mods, ["ModA"], Logs())
    assert is_deploy_interrupted(game)
    assert len(read_state(game)["injected"]) == 1

    monkeypatch.setattr(deployer.os, "link", real_link)
    assert purge_mods(game, Logs())
    assert snapshot(game) == before


def test_copy_failure_restores_original(env, monkeypatch):
    game, mods = env
    before = snapshot(game)

    def fail(*_args):
        raise OSError("link not possible")

    monkeypatch.setattr(deployer.os, "link", fail)
    monkeypatch.setattr(deployer.shutil, "copy2", fail)

    assert not deploy_mods(game, mods, ["ModB"], Logs())
    assert purge_mods(game, Logs())
    assert snapshot(game) == before


def test_falls_back_to_copy(env, monkeypatch):
    game, mods = env

    def fail(*_args):
        raise OSError("link not possible")

    monkeypatch.setattr(deployer.os, "link", fail)

    assert deploy_mods(game, mods, ["ModB"], Logs())
    target = game / "config" / "game.ini"
    assert target.read_text(encoding="utf-8") == "B" and not os.path.samefile(
        target, mods / "ModB" / "config" / "game.ini"
    )
    assert purge_mods(game, Logs())
    assert target.read_text(encoding="utf-8") == "original"


def test_unreadable_state_blocks_without_touching_anything(env):
    game, mods = env
    before = snapshot(game)
    write(state_path(game), "{ not json")

    assert not purge_mods(game, Logs())
    assert not deploy_mods(game, mods, ["ModA"], Logs())
    assert is_deploy_interrupted(game)
    assert get_deployed_mods(game) == []
    after = snapshot(game)
    after.pop(os.path.join(".mod_manager", "state.json"))
    assert after == before


def test_old_state_format(env):
    game, mods = env
    before = snapshot(game)
    # Simulate a deployment made by the old version (no fingerprints)
    (game / "config" / "game.ini").rename(game / "config" / "game.ini.org")
    os.link(mods / "ModB" / "config" / "game.ini", game / "config" / "game.ini")
    write(
        state_path(game),
        json.dumps(
            {
                "deployed_mods": ["ModB"],
                "injected_files": [os.path.join("config", "game.ini")],
                "org_files": [os.path.join("config", "game.ini")],
            }
        ),
    )

    assert get_deployed_mods(game) == ["ModB"]
    assert purge_mods(game, Logs())
    assert snapshot(game) == before


def test_paths_outside_game_are_ignored(env, tmp_path):
    game, _ = env
    victim = tmp_path / "victim.txt"
    write(victim, "must stay")
    write(state_path(game), json.dumps({"deployed_mods": [], "injected": {"../victim.txt": {}}, "backups": {}}))

    logs = Logs()
    assert purge_mods(game, logs)
    assert victim.exists()
    assert logs.contains("hors du dossier du jeu")


def test_mod_manager_folder_inside_mod_is_ignored(env):
    game, mods = env
    write(mods / "ModA" / ".mod_manager" / "state.json", "trap")
    assert deploy_mods(game, mods, ["ModA"], Logs())
    assert read_state(game)["deployed_mods"] == ["ModA"]


def test_missing_mod_is_skipped(env):
    game, mods = env
    logs = Logs()
    assert deploy_mods(game, mods, ["Ghost", "ModA"], logs)
    assert logs.contains("introuvable")
    assert get_deployed_mods(game) == ["ModA"]


def test_force_copy_uses_no_hard_link(env, monkeypatch):
    game, mods = env
    before = snapshot(game)

    def forbidden(*_args):
        raise AssertionError("os.link must not be called")

    monkeypatch.setattr(deployer.os, "link", forbidden)

    logs = Logs()
    assert deploy_mods(game, mods, ["ModA", "ModB"], logs, force_copy=True)
    target = game / "config" / "game.ini"
    assert target.read_text(encoding="utf-8") == "B"
    assert not os.path.samefile(target, mods / "ModB" / "config" / "game.ini")
    assert {info["mode"] for info in read_state(game)["injected"].values()} == {"copy"}
    assert not logs.contains("Hard link échoué")

    assert purge_mods(game, Logs())
    assert snapshot(game) == before


def test_force_copy_allows_another_drive(env, monkeypatch):
    game, mods = env
    monkeypatch.setattr(deployer, "is_same_drive", lambda *_args: False)

    logs = Logs()
    assert not deploy_mods(game, mods, ["ModB"], logs)
    assert logs.contains("Forcer la copie réelle")
    assert get_deployed_mods(game) == []

    assert deploy_mods(game, mods, ["ModB"], Logs(), force_copy=True)
    assert (game / "config" / "game.ini").read_text(encoding="utf-8") == "B"
