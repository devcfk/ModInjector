import json
import os
from pathlib import Path


def write_json_atomic(path: Path, data) -> None:
    """
    Write a JSON file atomically: the content is first written to a temporary file,
    which then replaces the target in one step (os.replace). After a crash or power loss,
    we keep either the old file or the new one, never a truncated file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
