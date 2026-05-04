import os
import stat
import shutil
from pathlib import Path
from typing import Union


def _on_rm_error(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)
    except Exception:
        pass


def safe_rmtree(path: Union[str, Path]) -> None:
    path = Path(path)

    if not path.exists():
        return

    shutil.rmtree(path, onerror=_on_rm_error)
