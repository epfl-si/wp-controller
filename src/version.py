import ast
import os

SETUP_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "setup.py")


def read_version(setup_py: str = SETUP_PY) -> str:
    """The `version=` that setup.py passes to setup(), read without running
    or installing it: the image never `pip install`s this package, so
    importlib.metadata has nothing to offer - setup.py itself (kept out of
    .dockerignore for this) is the single source of truth. "unknown" rather
    than an exception when it can't be read: a missing version must never
    keep the controller from starting."""
    try:
        with open(setup_py) as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return "unknown"

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setup":
            for keyword in node.keywords:
                if keyword.arg == "version" and isinstance(keyword.value, ast.Constant):
                    return str(keyword.value.value)
    return "unknown"
