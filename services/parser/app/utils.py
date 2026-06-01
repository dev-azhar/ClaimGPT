import os
from pathlib import Path

def ensure_dir(path: Path) -> None:
    """Guarantee that *path* is a directory.
    If a regular file exists at *path* or any of its parents, it is removed first to avoid FileExistsError.
    """
    path = Path(path).resolve()
    # Check all parent directories up to root to ensure none are regular files blocking creation
    for parent in reversed(path.parents):
        try:
            if parent.exists() and not parent.is_dir():
                parent.unlink()
        except Exception:
            pass
            
    try:
        if path.exists() and not path.is_dir():
            path.unlink()
    except Exception:
        pass
        
    try:
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        try:
            # If still raising FileExistsError, some blocking node exists; remove it
            if path.exists():
                if not path.is_dir():
                    path.unlink()
                else:
                    import shutil
                    shutil.rmtree(path)
        except Exception:
            pass
        # Final attempt
        path.mkdir(parents=True, exist_ok=True)
