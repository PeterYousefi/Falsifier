"""
Verify that batman and the falsifier distutils-compat shim load cleanly inside
a *spawn* worker process.

Why a file (not a heredoc):
    multiprocessing's "spawn" start method re-imports __main__ in the child
    interpreter.  When __main__ was read from stdin (``python - <<'EOF'``) the
    child cannot resolve the path and raises FileNotFoundError: ... '<stdin>'.
    Executing this as a real file gives the child a resolvable __main__.

Why "spawn" explicitly:
    The CI runner is Ubuntu, where the default start method is "fork".  Using
    "fork" would never exercise the code path this check exists to protect
    (spawn workers on macOS).  We force "spawn" so the guard is meaningful
    regardless of the OS default.
"""

import multiprocessing
import sys


def _worker() -> None:
    import falsifier._distutils_compat  # noqa: F401  (side-effect: distutils shim)
    import batman  # noqa: F401
    print("batman loaded OK in spawn worker", flush=True)


if __name__ == "__main__":
    ctx = multiprocessing.get_context("spawn")
    p = ctx.Process(target=_worker)
    p.start()
    p.join()
    if p.exitcode != 0:
        sys.exit(f"Spawn worker exited with code {p.exitcode}")
    print("batman spawn-worker verification passed")
