import json
import os
import shutil
from pathlib import Path

def is_same_drive(path1: Path, path2: Path) -> bool:
    """Vérifie si deux chemins sont sur le même lecteur (disque)."""
    # Sur Windows, resolve() ou absolute() donne "C:\...", donc on compare la lettre du lecteur
    return path1.resolve().drive.upper() == path2.resolve().drive.upper()

def load_dir(dossier: Path) -> list[Path]:
    """Retourne la liste des chemins relatifs de tous les fichiers d'un dossier (ignore les .modinfo.json)."""
    liste_elements = []
    if dossier.exists():
        for child in dossier.rglob("*"):
            if not child.is_dir() and child.name != "modinfo.json":
                liste_elements.append(child.relative_to(dossier))
    return liste_elements

def get_state_file(dossier_jeu: Path) -> Path:
    manager_dir = dossier_jeu / ".mod_manager"
    manager_dir.mkdir(parents=True, exist_ok=True)
    return manager_dir / "state.json"

def get_deployed_mods(dossier_jeu: Path) -> list[str]:
    """Retourne la liste (ordonnée) des mods actuellement déployés dans le jeu (lecture seule)."""
    fichier_state = dossier_jeu / ".mod_manager" / "state.json"
    if not fichier_state.exists():
        return []
    try:
        with open(fichier_state, "r", encoding="utf-8") as f:
            return list(json.load(f).get("deployed_mods", []))
    except Exception:
        return []

def purge_mods(dossier_jeu: Path, logger=print) -> None:
    """
    Restaure le jeu à son état d'origine en :
    1. Supprimant tous les fichiers injectés par ModInjector.
    2. Renommant les fichiers originaux (.org) à leur nom initial.
    """
    fichier_state = get_state_file(dossier_jeu)
    if not fichier_state.exists():
        logger("[INFO] Aucun mod n'est actuellement déployé. Le jeu est déjà propre.")
        return

    try:
        with open(fichier_state, "r", encoding="utf-8") as f:
            etat = json.load(f)
    except Exception as e:
        logger(f"[ERREUR] Impossible de lire l'état actuel : {e}")
        return

    # 1. Suppression des fichiers injectés (Hard Links ou copies)
    fichiers_injectes = etat.get("injected_files", [])
    for rel_path_str in fichiers_injectes:
        chemin_cible = dossier_jeu / rel_path_str
        if chemin_cible.exists() or chemin_cible.is_symlink():
            try:
                chemin_cible.unlink()
                logger(f"[SUPPRIMÉ] Fichier injecté retiré : {chemin_cible.name}")
            except Exception as e:
                logger(f"[ERREUR] Impossible de supprimer {chemin_cible.name} : {e}")
        
        # Nettoyage du dossier parent s'il est devenu vide
        current_dir = chemin_cible.parent
        while current_dir != dossier_jeu and current_dir.exists():
            try:
                current_dir.rmdir()
                current_dir = current_dir.parent
            except OSError:
                break # Le dossier n'est pas vide, on arrête de remonter

    # 2. Restauration des fichiers originaux (.org -> normal)
    fichiers_org = etat.get("org_files", [])
    for rel_path_str in fichiers_org:
        chemin_original = dossier_jeu / rel_path_str
        chemin_org = chemin_original.with_name(chemin_original.name + ".org")
        
        if chemin_org.exists():
            # Par sécurité, si l'original existe encore, on l'écrase
            if chemin_original.exists():
                chemin_original.unlink()
            try:
                chemin_org.rename(chemin_original)
                logger(f"[RESTAURÉ] Fichier original rétabli : {chemin_original.name}")
            except Exception as e:
                logger(f"[ERREUR] Impossible de restaurer {chemin_org.name} : {e}")

    # 3. Nettoyage final
    fichier_state.unlink()
    logger("[SUCCÈS] Le jeu a été entièrement purgé et restauré à son état d'origine.")


def deploy_mods(dossier_jeu: Path, dossier_mods_racine: Path, load_order: list[str], logger=print) -> bool:
    """
    Déploie les mods en respectant l'ordre de priorité (load_order).
    load_order = ["Mod1", "Mod2"] -> Mod2 est prioritaire et écrase Mod1 si conflit.
    """
    if not is_same_drive(dossier_jeu, dossier_mods_racine):
        logger(f"[ERREUR CRITIQUE] Le jeu et ModInjector NE SONT PAS sur le même disque !")
        logger(f"  -> Disque du Jeu : {dossier_jeu.resolve().drive}")
        logger(f"  -> Disque de ModInjector : {dossier_mods_racine.resolve().drive}")
        logger("Veuillez déplacer le dossier entier de ModInjector sur le MÊME disque que votre jeu.")
        return False

    # Toujours purger avant de redéployer
    logger("--- ÉTAPE 1 : Purge du jeu (Nettoyage préalable) ---")
    purge_mods(dossier_jeu, logger)
    
    logger("\n--- ÉTAPE 2 : Calcul des conflits (Load Order) ---")
    # Construire la map finale des fichiers
    # final_files_map[chemin_relatif] = chemin_source_absolu
    final_files_map: dict[Path, Path] = {}
    
    for nom_mod in load_order:
        dossier_mod = dossier_mods_racine / nom_mod
        if not dossier_mod.exists():
            logger(f"[ATTENTION] Le mod '{nom_mod}' est introuvable. Ignoré.")
            continue
            
        fichiers_mod = load_dir(dossier_mod)
        for rel_path in fichiers_mod:
            # Si le fichier était défini par un mod précédent, il est écrasé silencieusement ici
            final_files_map[rel_path] = dossier_mod / rel_path

    if not final_files_map:
        logger("[INFO] Aucun fichier de mod à déployer.")
        return True

    logger("\n--- ÉTAPE 3 : Déploiement des Hard Links ---")
    etat = {
        "deployed_mods": list(load_order),
        "injected_files": [],
        "org_files": []
    }
    
    erreurs = 0
    for rel_path, source_path in final_files_map.items():
        chemin_cible = dossier_jeu / rel_path
        chemin_org = chemin_cible.with_name(chemin_cible.name + ".org")
        
        # 1. Sauvegarde .org si le fichier existe et n'a pas encore été sauvegardé
        if chemin_cible.exists() and not chemin_cible.is_symlink():
            if not chemin_org.exists():
                try:
                    chemin_cible.rename(chemin_org)
                    logger(f"[BACKUP] Original mis en sécurité : {chemin_cible.name}.org")
                    etat["org_files"].append(str(rel_path))
                except Exception as e:
                    logger(f"[ERREUR] Impossible de renommer {chemin_cible.name} en .org : {e}")
                    erreurs += 1
                    continue
            else:
                # Si le .org existe déjà, le fichier cible actuel est un résidu ou une erreur
                chemin_cible.unlink()

        # 2. Création des dossiers parents si nécessaire
        chemin_cible.parent.mkdir(parents=True, exist_ok=True)
        
        # 3. Injection du fichier
        try:
            # os.link crée le Hard Link vers la source. L'injection est instantanée et prend 0 octet.
            os.link(source_path, chemin_cible)
            etat["injected_files"].append(str(rel_path))
            logger(f"[INJECTÉ] {chemin_cible.name} (Source: {source_path.parent.name})")
        except OSError as e:
            # Fallback de secours (Copie classique)
            logger(f"[ATTENTION] Hard link échoué pour {chemin_cible.name}, copie standard activée... ({e})")
            try:
                shutil.copy2(source_path, chemin_cible)
                etat["injected_files"].append(str(rel_path))
                logger(f"[COPIÉ] {chemin_cible.name} (Source: {source_path.parent.name})")
            except Exception as ex:
                logger(f"[ERREUR CRITIQUE] Impossible d'injecter {chemin_cible.name} : {ex}")
                erreurs += 1

    # 4. Sauvegarde de l'état
    fichier_state = get_state_file(dossier_jeu)
    with open(fichier_state, "w", encoding="utf-8") as f:
        json.dump(etat, f, indent=4, ensure_ascii=False)
        
    logger(f"\n--- FIN DU DÉPLOIEMENT ({erreurs} erreurs) ---")
    return erreurs == 0