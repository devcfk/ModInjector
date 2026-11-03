import json
import os
import shutil
import stat
from pathlib import Path

from core.fsutils import write_json_atomic
from i18n import t

STATE_DIR = ".mod_manager"
STATE_FILE = "state.json"
STATE_VERSION = 2
BACKUP_SUFFIX = ".org"
SAVE_EVERY = 25  # Intermediate state save every N injected files

# state.json format (version 2):
# {
#     "version": 2,
#     "deployed_mods": ["ModA", "ModB"],
#     "in_progress": false,            # true if a deployment was interrupted
#     "injected": {"relative/path": {"source": "...", "mode": "link"|"copy", "size": 0, "mtime_ns": 0}},
#     "backups": {"relative/path": "relative/path.org"}
# }
# The old format (injected_files / org_files) is converted on read.


class StateError(Exception):
    """The deployment state (state.json) cannot be read."""


def is_same_drive(path1: Path, path2: Path) -> bool:
    """Check whether two paths are on the same drive."""
    # On Windows, resolve() gives "C:\...", so we compare the drive letters
    return path1.resolve().drive.upper() == path2.resolve().drive.upper()


def load_dir(mod_dir: Path) -> list[Path]:
    """
    Return the relative paths of all the files of a mod.
    Skips modinfo.json and anything inside a .mod_manager folder (reserved for ModInjector).
    """
    files = []
    if mod_dir.exists():
        for child in mod_dir.rglob("*"):
            if child.is_dir() or child.name == "modinfo.json":
                continue
            rel = child.relative_to(mod_dir)
            if rel.parts[0].lower() == STATE_DIR:
                continue
            files.append(rel)
    return files


def state_path(game_dir: Path) -> Path:
    return game_dir / STATE_DIR / STATE_FILE


def _normalize_state(data) -> dict:
    """Validate the state read from disk and convert the old format if needed."""
    if not isinstance(data, dict):
        raise StateError(t("state.unexpected_format"))
    injected = data.get("injected")
    if injected is None:  # Old format: plain list of files, without fingerprints
        injected = {p: {} for p in data.get("injected_files", [])}
    backups = data.get("backups")
    if backups is None:  # Old format: the original is always <file>.org
        backups = {p: p + BACKUP_SUFFIX for p in data.get("org_files", [])}
    if not isinstance(injected, dict) or not isinstance(backups, dict):
        raise StateError(t("state.unexpected_format"))
    return {
        "version": STATE_VERSION,
        "deployed_mods": list(data.get("deployed_mods", [])),
        "in_progress": bool(data.get("in_progress", False)),
        "injected": dict(injected),
        "backups": dict(backups),
    }


def read_state(game_dir: Path) -> dict | None:
    """Return the deployment state, or None if no mod is deployed. Raise StateError if unreadable."""
    state_file = state_path(game_dir)
    if not state_file.exists():
        return None
    try:
        with open(state_file, encoding="utf-8") as f:
            return _normalize_state(json.load(f))
    except (OSError, ValueError) as e:
        raise StateError(str(e)) from e


def _save_state(game_dir: Path, state: dict) -> None:
    write_json_atomic(state_path(game_dir), state)


def get_deployed_mods(game_dir: Path) -> list[str]:
    """Return the (ordered) list of mods currently deployed in the game (read-only)."""
    try:
        state = read_state(game_dir)
    except StateError:
        return []
    return state["deployed_mods"] if state else []


def is_deploy_interrupted(game_dir: Path) -> bool:
    """True if a deployment was interrupted (crash, forced close...): a purge is recommended."""
    try:
        state = read_state(game_dir)
    except StateError:
        return True
    return bool(state and state["in_progress"])


# ------------------------------------------------------------------------ File helpers
def _in_game(game_dir: Path, rel: str) -> Path | None:
    """Absolute path of rel inside the game, or None if it escapes the game folder (tampered state)."""
    path = game_dir / rel
    if not path.resolve().is_relative_to(game_dir.resolve()):
        return None
    return path


def _fingerprint(path: Path) -> dict:
    st = path.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def _unlink(path: Path) -> None:
    """Delete a file, clearing the read-only attribute if needed."""
    try:
        path.unlink()
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)
        path.unlink()


def _free_backup_path(target: Path) -> Path:
    """Free backup name: <file>.org, otherwise <file>.1.org, <file>.2.org..."""
    candidate = target.with_name(target.name + BACKUP_SUFFIX)
    i = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = target.with_name(f"{target.name}.{i}{BACKUP_SUFFIX}")
        i += 1
    return candidate


def _remove_empty_parents(path: Path, root: Path) -> None:
    current_dir = path.parent
    while current_dir != root and current_dir.exists():
        try:
            current_dir.rmdir()
            current_dir = current_dir.parent
        except OSError:
            break  # The folder is not empty, stop going up


def _check_injected(target: Path, info: dict) -> tuple[bool, bool]:
    """
    Tell whether the file in the game is still the one injected by ModInjector.
    Return (still_ours, modified_in_place).
    """
    expected = {"size": info["size"], "mtime_ns": info["mtime_ns"]} if "size" in info else None
    source = info.get("source")
    if source:
        try:
            if os.path.samefile(target, source):
                # Hard link intact: any change also affected the mod's file
                return True, expected is not None and _fingerprint(target) != expected
        except OSError:
            pass
    if expected is None:
        return True, False  # Old format: no check possible
    return _fingerprint(target) == expected, False


# ------------------------------------------------------------------------------- Purge
def purge_mods(game_dir: Path, logger=print) -> bool:
    """
    Restore the game to its original state by:
    1. Deleting the files injected by ModInjector (except those replaced by the game since).
    2. Renaming the backups (.org) back to their original name.
    Return True if the game is fully restored. On partial failure (locked file, game running...),
    the remaining items are kept in the state for another purge.
    """
    try:
        state = read_state(game_dir)
    except StateError as e:
        logger(t("purge.state_unreadable", path=state_path(game_dir), error=e))
        logger(t("purge.nothing_touched"))
        return False
    if state is None:
        logger(t("purge.already_clean"))
        return True

    errors = 0
    remaining_injected: dict[str, dict] = {}
    kept: set[str] = set()  # files replaced by the game since the injection

    # 1. Delete the injected files (hard links or copies)
    for rel, info in state["injected"].items():
        target = _in_game(game_dir, rel)
        if target is None:
            logger(t("purge.path_outside_game", path=rel))
            continue
        if not (target.exists() or target.is_symlink()):
            continue  # Already gone
        try:
            still_ours, modified = _check_injected(target, info)
        except OSError as e:
            logger(t("purge.cannot_inspect", name=target.name, error=e))
            remaining_injected[rel] = info
            errors += 1
            continue

        if not still_ours:
            kept.add(rel)
            logger(t("purge.kept_replaced", path=rel))
            continue
        if modified:
            logger(t("purge.modified_in_place", path=rel, source=info.get("source")))
        try:
            _unlink(target)
            logger(t("purge.removed", name=target.name))
        except OSError as e:
            logger(t("purge.cannot_delete", name=target.name, error=e))
            remaining_injected[rel] = info
            errors += 1
            continue
        _remove_empty_parents(target, game_dir)

    # 2. Restore the original files (.org -> normal)
    remaining_backups: dict[str, str] = {}
    for rel, backup_rel in state["backups"].items():
        if rel in remaining_injected:
            remaining_backups[rel] = backup_rel  # The injected file is still there: retry later
            continue
        target, backup = _in_game(game_dir, rel), _in_game(game_dir, backup_rel)
        if target is None or backup is None:
            logger(t("purge.path_outside_game", path=rel))
            continue
        if not backup.exists():
            logger(t("purge.backup_missing", path=backup_rel))
            continue
        if rel in kept or target.exists():
            # Never overwrite a file that the game recreated or updated
            logger(t("purge.target_exists", path=rel, backup=backup.name))
            continue
        try:
            backup.rename(target)
            logger(t("purge.restored", name=target.name))
        except OSError as e:
            logger(t("purge.cannot_restore", name=backup.name, error=e))
            remaining_backups[rel] = backup_rel
            errors += 1

    # 3. Final cleanup (or keep what is left to do)
    if errors:
        state["injected"], state["backups"] = remaining_injected, remaining_backups
        _save_state(game_dir, state)
        logger(t("purge.partial", count=errors))
        return False

    state_path(game_dir).unlink(missing_ok=True)
    try:
        (game_dir / STATE_DIR).rmdir()
    except OSError:
        pass
    logger(t("purge.success"))
    return True


# -------------------------------------------------------------------------- Deployment
def _inject_file(game_dir: Path, rel: Path, source: Path, state: dict, logger, force_copy: bool = False) -> bool:
    """
    Inject a file into the game (backup of the original, then hard link or copy). Updates the state.
    force_copy: really copy the file instead of creating a hard link.
    """
    target = game_dir / rel

    # 1. Back up the original under a free name (never overwrite an existing backup)
    if target.is_dir():
        logger(t("inject.target_is_dir", path=rel))
        return False
    if target.exists() or target.is_symlink():
        backup = _free_backup_path(target)
        try:
            target.rename(backup)
        except OSError as e:
            logger(t("inject.cannot_backup", name=target.name, error=e))
            return False
        state["backups"][str(rel)] = str(backup.relative_to(game_dir))
        logger(t("inject.backed_up", name=backup.name))

    # 2. Create the parent folders if needed
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger(t("inject.cannot_create_dir", path=rel, error=e))
        return False

    # 3. Inject the file
    mode = "copy"
    if not force_copy:
        try:
            # os.link creates a hard link to the source: instant injection, 0 extra bytes.
            os.link(source, target)
            mode = "link"
        except OSError as e:
            # Fallback: regular copy
            logger(t("inject.link_failed", name=target.name, error=e))
    if mode == "copy":
        try:
            shutil.copy2(source, target)
        except OSError as ex:
            logger(t("inject.cannot_inject", name=target.name, error=ex))
            try:
                _unlink(target)  # Remove a possible partial copy so the original can be restored
            except OSError:
                pass
            return False

    state["injected"][str(rel)] = {"source": str(source), "mode": mode, **_fingerprint(target)}
    logger(t("inject.linked" if mode == "link" else "inject.copied", name=target.name, mod=source.parent.name))
    return True


def deploy_mods(game_dir: Path, mods_root: Path, load_order: list[str], logger=print, force_copy: bool = False) -> bool:
    """
    Deploy the mods following the priority order (load_order).
    load_order = ["Mod1", "Mod2"] -> Mod2 has priority and overrides Mod1 on conflict.
    force_copy: really copy the files instead of using hard links (the game can then be on another drive).
    The state is saved along the way: even if interrupted, the deployment can still be purged.
    """
    if not force_copy and not is_same_drive(game_dir, mods_root):
        logger(t("deploy.not_same_drive", game_drive=game_dir.resolve().drive, app_drive=mods_root.resolve().drive))
        return False

    # Always purge before redeploying
    logger(t("deploy.step_purge"))
    if not purge_mods(game_dir, logger):
        logger(t("deploy.purge_failed"))
        return False

    logger(t("deploy.step_conflicts"))
    # Build the final file map: final_files_map[relative_path] = absolute_source_path
    final_files_map: dict[Path, Path] = {}
    found_mods = []

    for mod_name in load_order:
        mod_dir = mods_root / mod_name
        if not mod_dir.is_dir():
            logger(t("deploy.mod_missing", mod=mod_name))
            continue
        found_mods.append(mod_name)
        for rel_path in load_dir(mod_dir):
            # If a previous mod defined this file, it is overridden here (the last one wins)
            final_files_map[rel_path] = mod_dir / rel_path

    if not final_files_map:
        logger(t("deploy.nothing_to_deploy"))
        return True

    logger(t("deploy.step_copies" if force_copy else "deploy.step_links"))
    state = {
        "version": STATE_VERSION,
        "deployed_mods": found_mods,
        "in_progress": True,
        "injected": {},
        "backups": {},
    }
    try:
        _save_state(game_dir, state)  # Before touching the game at all
    except OSError as e:
        logger(t("deploy.cannot_write_state", error=e))
        return False

    errors = 0
    try:
        for i, (rel_path, source_path) in enumerate(final_files_map.items(), start=1):
            if not _inject_file(game_dir, rel_path, source_path, state, logger, force_copy):
                errors += 1
            if i % SAVE_EVERY == 0:
                _save_state(game_dir, state)
        state["in_progress"] = False
    finally:
        # Always record what has been done, even if an exception occurred
        _save_state(game_dir, state)

    logger(t("deploy.done", count=errors))
    return errors == 0
