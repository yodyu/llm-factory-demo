"""Early static checks; Docker remains the execution security boundary."""
import ast
from contracts import ErrorCode, FactoryError

ALLOWED_IMPORTS = frozenset({"math", "statistics", "collections", "json", "datetime", "typing", "bisect", "__future__"})
_DYNAMIC_CALLS = frozenset(
    {
        "__import__",
        "eval",
        "exec",
        "compile",
        "system",
        "popen",
        "Popen",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "posix_spawn",
        "posix_spawnp",
    }
)


def _error(message):
    return FactoryError(ErrorCode.CODE_CONTRACT_ERROR, message)


def _check_source(raw: bytes) -> None:
    try:
        source = raw.decode("utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeError, ValueError, RecursionError) as exc:
        raise _error("invalid Python source") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                raise _error("relative imports are forbidden")
            modules = [node.module]
        else:
            modules = []
        if any(module.split(".")[0] not in ALLOWED_IMPORTS for module in modules):
            raise _error("unapproved dependency import")
        if isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
            )
            if name in _DYNAMIC_CALLS:
                raise _error("dynamic code or imports are forbidden")
