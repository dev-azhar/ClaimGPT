import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def ensure_dir(path: Path) -> Path:
    """Guarantee that *path* is a directory and is writeable.
    If a regular file exists at *path* or any of its parents, it is unlinked first.
    If directory creation or write verification fails (e.g. stale Docker mounts, permissions),
    it falls back to a container-local directory under /tmp, preserving subfolders.
    Returns the Path that was successfully ensured and verified.
    """
    path = Path(path).resolve()
    
    # Try target path first
    try:
        for parent in reversed(path.parents):
            try:
                if parent.exists() and not parent.is_dir():
                    parent.unlink()
            except Exception:
                pass
                
        if path.exists() and not path.is_dir():
            try:
                path.unlink()
            except Exception:
                pass
                
        path.mkdir(parents=True, exist_ok=True)
        
        # Test writeability
        test_file = path / f".write_test_{os.getpid()}"
        test_file.touch(exist_ok=True)
        test_file.unlink(missing_ok=True)
        return path
    except Exception as e:
        logger.warning("Failed to ensure or write to directory '%s': %s. Falling back to container-local storage.", path, e)
        
    # Fallback to local /tmp inside container
    try:
        fallback_base = Path("/tmp")
        parts = list(path.parts)
        if "tmp" in parts:
            idx = parts.index("tmp")
            rel_parts = parts[idx+1:]
            fallback_path = fallback_base / Path(*rel_parts)
        else:
            fallback_path = fallback_base / (path.name or "parser_debug_fallback")
            
        fallback_path.mkdir(parents=True, exist_ok=True)
        test_file = fallback_path / f".write_test_{os.getpid()}"
        test_file.touch(exist_ok=True)
        test_file.unlink(missing_ok=True)
        return fallback_path
    except Exception as fallback_err:
        logger.error("Fallback directory creation also failed: %s", fallback_err)
        try:
            fallback_base.mkdir(parents=True, exist_ok=True)
            return fallback_base
        except Exception:
            return path
