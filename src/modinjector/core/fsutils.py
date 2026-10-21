import json
import os
from pathlib import Path


def write_json_atomic(path: Path, data) -> None:
    """
    Écrit un fichier JSON de façon atomique : le contenu est d'abord écrit dans un fichier
    temporaire puis substitué d'un coup (os.replace). En cas de crash ou de coupure,
    on conserve soit l'ancien fichier, soit le nouveau, jamais un fichier tronqué.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
