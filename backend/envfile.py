"""Load KEY=VALUE pairs from a local .env file without extra dependencies."""

import os
from pathlib import Path


def load_env(path: str | Path = ".env") -> list[str]:
    """Add variables from path to os.environ; real environment values win.

    Returns the names that were set. A missing file is not an error.
    """
    path = Path(path)
    if not path.is_file():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and value and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded
