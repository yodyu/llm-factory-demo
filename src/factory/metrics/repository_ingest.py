"""Bounded source discovery only; importing or executing repository code is forbidden."""
from pathlib import Path

SKIP = {'.git', '.venv', 'venv', '__pycache__', 'tests', 'test', 'build', 'dist', 'node_modules', '.pytest_cache'}


def repository_sources(root):
    root = Path(root).resolve()
    paths = []
    for path in sorted(root.rglob('*.py')):
        relative = path.relative_to(root)
        if path.stat().st_size == 0 or SKIP.intersection(relative.parts) or path.name.startswith('test_') or any(p.is_symlink() for p in (path, *path.parents) if p != root):
            continue
        paths.append(relative.as_posix())
    if not paths or len(paths) > 128:
        raise ValueError('repository must provide 1..128 bounded Python source files')
    return paths
