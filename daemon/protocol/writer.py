import os
import tempfile
import yaml
from pathlib import Path

def atomic_write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, suffix=".tmp"
    ) as tmp:
        yaml.safe_dump(data, tmp, sort_keys=False)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    tmp_path.rename(path)
