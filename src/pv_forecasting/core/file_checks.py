from pathlib import Path


def is_lfs_pointer(path: str | Path) -> bool:
    path = Path(path)
    if not path.exists() or not path.is_file():
        return False
    if path.stat().st_size > 1024:
        return False
    try:
        head = path.read_bytes()[:128]
    except OSError:
        return False
    return head.startswith(b"version https://git-lfs.github.com/spec/v1")


def describe_file_state(path: str | Path) -> str:
    path = Path(path)
    if not path.exists():
        return "missing"
    if is_lfs_pointer(path):
        return "lfs_pointer"
    if path.is_file() and path.stat().st_size == 0:
        return "empty"
    return "ok"
