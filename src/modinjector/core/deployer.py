import json
import os
import shutil
import stat
from pathlib import Path

from core.fsutils import write_json_atomic

STATE_DIR = ".mod_manager"
STATE_FILE = "state.json"
STATE_VERSION = 2
BACKUP_SUFFIX = ".org"
SAVE_EVERY = 25  # Sauvegarde intermédiaire de l'état tous les N fichiers injectés

# Format de state.json (version 2) :
# {
#     "version": 2,
#     "deployed_mods": ["ModA", "ModB"],
#     "in_progress": false,            # true si un déploiement a été interrompu
#     "injected": {"chemin/relatif": {"source": "...", "mode": "link"|"copy", "size": 0, "mtime_ns": 0}},
#     "backups": {"chemin/relatif": "chemin/relatif.org"}
# }
# L'ancien format (injected_files / org_files) est converti à la lecture.


class StateError(Exception):
    """L'état du déploiement (state.json) est illisible."""


def is_same_drive(path1: Path, path2: Path) -> bool:
    """Vérifie si deux chemins sont sur le même lecteur (disque)."""
    # Sur Windows, resolve() ou absolute() donne "C:\...", donc on compare la lettre du lecteur
    return path1.resolve().drive.upper() == path2.resolve().drive.upper()


def load_dir(dossier: Path) -> list[Path]:
    """
    Retourne la liste des chemins relatifs de tous les fichiers d'un mod.
    Ignore modinfo.json et tout ce qui se trouve dans un dossier .mod_manager (réservé à ModInjector).
    """
    liste_elements = []
    if dossier.exists():
        for child in dossier.rglob("*"):
            if child.is_dir() or child.name == "modinfo.json":
                continue
            rel = child.relative_to(dossier)
            if rel.parts[0].lower() == STATE_DIR:
                continue
            liste_elements.append(rel)
    return liste_elements


def state_path(dossier_jeu: Path) -> Path:
    return dossier_jeu / STATE_DIR / STATE_FILE


def _normalize_state(data) -> dict:
    """Valide l'état lu sur le disque et convertit l'ancien format si besoin."""
    if not isinstance(data, dict):
        raise StateError("format inattendu")
    injected = data.get("injected")
    if injected is None:  # Ancien format : simple liste de fichiers, sans empreinte
        injected = {p: {} for p in data.get("injected_files", [])}
    backups = data.get("backups")
    if backups is None:  # Ancien format : l'original est toujours <fichier>.org
        backups = {p: p + BACKUP_SUFFIX for p in data.get("org_files", [])}
    if not isinstance(injected, dict) or not isinstance(backups, dict):
        raise StateError("format inattendu")
    return {
        "version": STATE_VERSION,
        "deployed_mods": list(data.get("deployed_mods", [])),
        "in_progress": bool(data.get("in_progress", False)),
        "injected": dict(injected),
        "backups": dict(backups),
    }


def read_state(dossier_jeu: Path) -> dict | None:
    """Retourne l'état du déploiement, None si aucun mod n'est déployé. Lève StateError si illisible."""
    fichier_state = state_path(dossier_jeu)
    if not fichier_state.exists():
        return None
    try:
        with open(fichier_state, encoding="utf-8") as f:
            return _normalize_state(json.load(f))
    except (OSError, ValueError) as e:
        raise StateError(str(e)) from e


def _save_state(dossier_jeu: Path, etat: dict) -> None:
    write_json_atomic(state_path(dossier_jeu), etat)


def get_deployed_mods(dossier_jeu: Path) -> list[str]:
    """Retourne la liste (ordonnée) des mods actuellement déployés dans le jeu (lecture seule)."""
    try:
        etat = read_state(dossier_jeu)
    except StateError:
        return []
    return etat["deployed_mods"] if etat else []


def is_deploy_interrupted(dossier_jeu: Path) -> bool:
    """Vrai si un déploiement a été interrompu (crash, fermeture forcée...) : une purge est conseillée."""
    try:
        etat = read_state(dossier_jeu)
    except StateError:
        return True
    return bool(etat and etat["in_progress"])


# ------------------------------------------------------------------ Utilitaires fichiers
def _in_game(dossier_jeu: Path, rel: str) -> Path | None:
    """Chemin absolu de rel dans le jeu, ou None s'il sort du dossier du jeu (état altéré)."""
    chemin = dossier_jeu / rel
    if not chemin.resolve().is_relative_to(dossier_jeu.resolve()):
        return None
    return chemin


def _fingerprint(path: Path) -> dict:
    st = path.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def _unlink(path: Path) -> None:
    """Supprime un fichier, en retirant au besoin l'attribut lecture seule."""
    try:
        path.unlink()
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)
        path.unlink()


def _free_backup_path(cible: Path) -> Path:
    """Nom de sauvegarde libre : <fichier>.org, sinon <fichier>.1.org, <fichier>.2.org..."""
    candidat = cible.with_name(cible.name + BACKUP_SUFFIX)
    i = 1
    while candidat.exists() or candidat.is_symlink():
        candidat = cible.with_name(f"{cible.name}.{i}{BACKUP_SUFFIX}")
        i += 1
    return candidat


def _remove_empty_parents(chemin: Path, racine: Path) -> None:
    current_dir = chemin.parent
    while current_dir != racine and current_dir.exists():
        try:
            current_dir.rmdir()
            current_dir = current_dir.parent
        except OSError:
            break  # Le dossier n'est pas vide, on arrête de remonter


def _check_injected(cible: Path, info: dict) -> tuple[bool, bool]:
    """
    Indique si le fichier présent dans le jeu est toujours celui injecté par ModInjector.
    Retourne (toujours_le_notre, modifie_sur_place).
    """
    attendu = {"size": info["size"], "mtime_ns": info["mtime_ns"]} if "size" in info else None
    source = info.get("source")
    if source:
        try:
            if os.path.samefile(cible, source):
                # Hard link intact : toute modification a aussi touché le fichier du mod
                return True, attendu is not None and _fingerprint(cible) != attendu
        except OSError:
            pass
    if attendu is None:
        return True, False  # Ancien format : aucune vérification possible
    return _fingerprint(cible) == attendu, False


# ------------------------------------------------------------------------------- Purge
def purge_mods(dossier_jeu: Path, logger=print) -> bool:
    """
    Restaure le jeu à son état d'origine en :
    1. Supprimant les fichiers injectés par ModInjector (sauf ceux remplacés depuis par le jeu).
    2. Renommant les sauvegardes (.org) à leur nom initial.
    Retourne True si le jeu est entièrement restauré. En cas d'échec partiel (fichier verrouillé,
    jeu en cours d'exécution...), les éléments non traités restent dans l'état pour une nouvelle purge.
    """
    try:
        etat = read_state(dossier_jeu)
    except StateError as e:
        logger(f"[ERREUR] Le fichier d'état {state_path(dossier_jeu)} est illisible : {e}")
        logger("  -> Aucun fichier n'a été modifié. Vérifiez ou supprimez ce fichier manuellement.")
        return False
    if etat is None:
        logger("[INFO] Aucun mod n'est actuellement déployé. Le jeu est déjà propre.")
        return True

    erreurs = 0
    restants_injectes: dict[str, dict] = {}
    conserves: set[str] = set()  # fichiers remplacés par le jeu depuis l'injection

    # 1. Suppression des fichiers injectés (Hard Links ou copies)
    for rel, info in etat["injected"].items():
        cible = _in_game(dossier_jeu, rel)
        if cible is None:
            logger(f"[ATTENTION] Chemin hors du dossier du jeu ignoré : {rel}")
            continue
        if not (cible.exists() or cible.is_symlink()):
            continue  # Déjà absent
        try:
            notre_fichier, modifie = _check_injected(cible, info)
        except OSError as e:
            logger(f"[ERREUR] Impossible d'examiner {cible.name} : {e}")
            restants_injectes[rel] = info
            erreurs += 1
            continue

        if not notre_fichier:
            conserves.add(rel)
            logger(f"[CONSERVÉ] {rel} a été remplacé par le jeu (mise à jour ?) depuis l'injection : il est conservé.")
            continue
        if modifie:
            logger(
                f"[ATTENTION] {rel} a été modifié sur place depuis l'injection : le fichier source du mod "
                f"({info.get('source')}) l'a été aussi. Réinstallez ce mod si besoin."
            )
        try:
            _unlink(cible)
            logger(f"[SUPPRIMÉ] Fichier injecté retiré : {cible.name}")
        except OSError as e:
            logger(f"[ERREUR] Impossible de supprimer {cible.name} : {e}")
            restants_injectes[rel] = info
            erreurs += 1
            continue
        _remove_empty_parents(cible, dossier_jeu)

    # 2. Restauration des fichiers originaux (.org -> normal)
    restants_backups: dict[str, str] = {}
    for rel, backup_rel in etat["backups"].items():
        if rel in restants_injectes:
            restants_backups[rel] = backup_rel  # Le fichier injecté est toujours là : on réessaiera
            continue
        cible, sauvegarde = _in_game(dossier_jeu, rel), _in_game(dossier_jeu, backup_rel)
        if cible is None or sauvegarde is None:
            logger(f"[ATTENTION] Chemin hors du dossier du jeu ignoré : {rel}")
            continue
        if not sauvegarde.exists():
            logger(f"[ATTENTION] Sauvegarde introuvable, rien à restaurer : {backup_rel}")
            continue
        if rel in conserves or cible.exists():
            # Ne jamais écraser un fichier que le jeu a recréé ou mis à jour
            logger(
                f"[ATTENTION] {rel} existe déjà (version du jeu plus récente ?) : "
                f"l'ancien original est laissé dans {sauvegarde.name}."
            )
            continue
        try:
            sauvegarde.rename(cible)
            logger(f"[RESTAURÉ] Fichier original rétabli : {cible.name}")
        except OSError as e:
            logger(f"[ERREUR] Impossible de restaurer {sauvegarde.name} : {e}")
            restants_backups[rel] = backup_rel
            erreurs += 1

    # 3. Nettoyage final (ou conservation de ce qui reste à faire)
    if erreurs:
        etat["injected"], etat["backups"] = restants_injectes, restants_backups
        _save_state(dossier_jeu, etat)
        logger(
            f"[ÉCHEC PARTIEL] {erreurs} élément(s) n'ont pas pu être traités (le jeu est-il lancé ?). "
            "Fermez le jeu puis relancez la purge."
        )
        return False

    state_path(dossier_jeu).unlink(missing_ok=True)
    try:
        (dossier_jeu / STATE_DIR).rmdir()
    except OSError:
        pass
    logger("[SUCCÈS] Le jeu a été entièrement purgé et restauré à son état d'origine.")
    return True


# -------------------------------------------------------------------------- Déploiement
def _inject_file(dossier_jeu: Path, rel: Path, source: Path, etat: dict, logger, copie_forcee: bool = False) -> bool:
    """
    Injecte un fichier dans le jeu (sauvegarde de l'original, hard link ou copie). Met à jour l'état.
    copie_forcee : copie réelle du fichier au lieu d'un hard link.
    """
    cible = dossier_jeu / rel

    # 1. Sauvegarde de l'original sous un nom libre (jamais d'écrasement d'une sauvegarde existante)
    if cible.is_dir():
        logger(f"[ERREUR] {rel} est un dossier dans le jeu : fichier du mod ignoré.")
        return False
    if cible.exists() or cible.is_symlink():
        sauvegarde = _free_backup_path(cible)
        try:
            cible.rename(sauvegarde)
        except OSError as e:
            logger(f"[ERREUR] Impossible de mettre {cible.name} en sécurité : {e}")
            return False
        etat["backups"][str(rel)] = str(sauvegarde.relative_to(dossier_jeu))
        logger(f"[BACKUP] Original mis en sécurité : {sauvegarde.name}")

    # 2. Création des dossiers parents si nécessaire
    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger(f"[ERREUR] Impossible de créer le dossier de {rel} : {e}")
        return False

    # 3. Injection du fichier
    mode = "copy"
    if not copie_forcee:
        try:
            # os.link crée le Hard Link vers la source. L'injection est instantanée et prend 0 octet.
            os.link(source, cible)
            mode = "link"
        except OSError as e:
            # Fallback de secours (Copie classique)
            logger(f"[ATTENTION] Hard link échoué pour {cible.name}, copie standard activée... ({e})")
    if mode == "copy":
        try:
            shutil.copy2(source, cible)
        except OSError as ex:
            logger(f"[ERREUR CRITIQUE] Impossible d'injecter {cible.name} : {ex}")
            try:
                _unlink(cible)  # Retire une éventuelle copie partielle pour pouvoir restaurer l'original
            except OSError:
                pass
            return False

    etat["injected"][str(rel)] = {"source": str(source), "mode": mode, **_fingerprint(cible)}
    logger(f"[{'INJECTÉ' if mode == 'link' else 'COPIÉ'}] {cible.name} (Source: {source.parent.name})")
    return True


def deploy_mods(
    dossier_jeu: Path, dossier_mods_racine: Path, load_order: list[str], logger=print, copie_forcee: bool = False
) -> bool:
    """
    Déploie les mods en respectant l'ordre de priorité (load_order).
    load_order = ["Mod1", "Mod2"] -> Mod2 est prioritaire et écrase Mod1 si conflit.
    copie_forcee : copie réelle des fichiers au lieu de hard links (le jeu peut alors être sur un autre disque).
    L'état est enregistré au fil de l'eau : même interrompu, le déploiement reste purgeable.
    """
    if not copie_forcee and not is_same_drive(dossier_jeu, dossier_mods_racine):
        logger("[ERREUR CRITIQUE] Le jeu et ModInjector NE SONT PAS sur le même disque !")
        logger(f"  -> Disque du Jeu : {dossier_jeu.resolve().drive}")
        logger(f"  -> Disque de ModInjector : {dossier_mods_racine.resolve().drive}")
        logger("Veuillez déplacer le dossier entier de ModInjector sur le MÊME disque que votre jeu,")
        logger("ou activez l'option « Forcer la copie réelle des fichiers ».")
        return False

    # Toujours purger avant de redéployer
    logger("--- ÉTAPE 1 : Purge du jeu (Nettoyage préalable) ---")
    if not purge_mods(dossier_jeu, logger):
        logger("[ERREUR] La purge préalable a échoué : déploiement annulé pour ne pas mélanger les états.")
        return False

    logger("\n--- ÉTAPE 2 : Calcul des conflits (Load Order) ---")
    # Construire la map finale des fichiers
    # final_files_map[chemin_relatif] = chemin_source_absolu
    final_files_map: dict[Path, Path] = {}
    mods_trouves = []

    for nom_mod in load_order:
        dossier_mod = dossier_mods_racine / nom_mod
        if not dossier_mod.is_dir():
            logger(f"[ATTENTION] Le mod '{nom_mod}' est introuvable. Ignoré.")
            continue
        mods_trouves.append(nom_mod)
        for rel_path in load_dir(dossier_mod):
            # Si le fichier était défini par un mod précédent, il est écrasé ici (le dernier gagne)
            final_files_map[rel_path] = dossier_mod / rel_path

    if not final_files_map:
        logger("[INFO] Aucun fichier de mod à déployer.")
        return True

    logger(
        "\n--- ÉTAPE 3 : Déploiement "
        + ("des copies (copie réelle forcée) ---" if copie_forcee else "des Hard Links ---")
    )
    etat = {
        "version": STATE_VERSION,
        "deployed_mods": mods_trouves,
        "in_progress": True,
        "injected": {},
        "backups": {},
    }
    try:
        _save_state(dossier_jeu, etat)  # Avant toute modification du jeu
    except OSError as e:
        logger(f"[ERREUR CRITIQUE] Impossible d'écrire l'état du déploiement : {e}")
        return False

    erreurs = 0
    try:
        for i, (rel_path, source_path) in enumerate(final_files_map.items(), start=1):
            if not _inject_file(dossier_jeu, rel_path, source_path, etat, logger, copie_forcee):
                erreurs += 1
            if i % SAVE_EVERY == 0:
                _save_state(dossier_jeu, etat)
        etat["in_progress"] = False
    finally:
        # Toujours enregistrer ce qui a été fait, même en cas d'exception
        _save_state(dossier_jeu, etat)

    logger(f"\n--- FIN DU DÉPLOIEMENT ({erreurs} erreurs) ---")
    return erreurs == 0
