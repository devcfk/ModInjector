import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build"          # Dossier temporaire (supprimé en fin de build)
LIVRAISON_DIR = ROOT / "livraison"  # Contient uniquement le livrable final
APP_NAME = "ModInjector"
ZIP_BASE = LIVRAISON_DIR / APP_NAME


def build() -> Path | None:
    """Compile l'exécutable avec PyInstaller. Tout reste dans build/ (rien dans dist/)."""
    print("[1/3] Démarrage de la compilation avec PyInstaller...")
    exe_dir = BUILD_DIR / "exe"
    command = [
        "uv", "run", "python", "-m", "PyInstaller",
        "--noconsole",
        "--onefile",
        "--noconfirm",
        "--name", APP_NAME,
        "--icon", str(ROOT / "assets" / "icon.ico"),
        "--add-data", f"{ROOT / 'assets' / 'icon.ico'};assets",
        "--collect-all", "customtkinter",
        "--distpath", str(exe_dir),
        "--workpath", str(BUILD_DIR / "work"),
        "--specpath", str(BUILD_DIR),
        str(ROOT / "src" / "modinjector" / "main.py"),
    ]

    try:
        subprocess.run(command, check=True, cwd=ROOT)
    except subprocess.CalledProcessError as e:
        print(f"Erreur lors de la compilation : {e}")
        return None

    exe = exe_dir / f"{APP_NAME}.exe"
    if not exe.exists():
        print(f"Erreur : l'exécutable {exe} est introuvable.")
        return None
    print("Compilation terminée avec succès !")
    return exe


def package(exe: Path) -> Path:
    """Assemble le dossier ModInjector/ (exe + Mods/ + data/) et le compresse en .zip."""
    print("\n[2/3] Création de l'archive ZIP...")
    staging_root = BUILD_DIR / "staging"
    staging = staging_root / APP_NAME
    staging.mkdir(parents=True, exist_ok=True)

    shutil.copy2(exe, staging / exe.name)
    (staging / "Mods").mkdir(exist_ok=True)
    (staging / "data").mkdir(exist_ok=True)

    LIVRAISON_DIR.mkdir(exist_ok=True)
    # Nettoie d'anciens livrables (ancien dossier décompressé, ancien zip)
    shutil.rmtree(LIVRAISON_DIR / APP_NAME, ignore_errors=True)
    zip_path = Path(shutil.make_archive(str(ZIP_BASE), "zip", root_dir=staging_root, base_dir=APP_NAME))
    print(f" - Archive ZIP créée : {zip_path}")
    return zip_path


def clean_up():
    """Supprime tous les fichiers temporaires de build."""
    print("\n[3/3] Nettoyage des fichiers temporaires de build...")
    for path in (BUILD_DIR, ROOT / "dist"):
        if path.exists():
            try:
                shutil.rmtree(path)
                print(f" - Dossier '{path.name}/' supprimé.")
            except Exception as e:
                print(f" - Impossible de supprimer '{path.name}/' : {e}")
    for spec_file in ROOT.glob("*.spec"):
        spec_file.unlink(missing_ok=True)
        print(f" - Fichier '{spec_file.name}' supprimé.")


if __name__ == "__main__":
    zip_file = None
    try:
        exe_path = build()
        if exe_path is not None:
            zip_file = package(exe_path)
    finally:
        clean_up()

    if zip_file is None:
        sys.exit(1)
    print(f"\n=> Terminé ! Livrable : {zip_file}")
