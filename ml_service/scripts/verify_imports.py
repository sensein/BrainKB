#!/usr/bin/env python3
"""Build-time gate: fail the image build if ml_service's optional AI stacks are
unimportable, instead of shipping and discovering it in production.

Run from Dockerfile.unified after the pip steps for ml_service.

Why this exists
---------------
Both AI stacks are imported behind guards at runtime (core/main.py for
synthscholar, core/shared.py for structsense) so one broken dependency cannot take
the whole service down. That is the right runtime behaviour, but it means a broken
install is INVISIBLE: the container starts, /api/health returns 200, and the
affected routers are simply never mounted. The symptom reaches you hours later as
404s on endpoints that used to exist, or a browser CORS error that is really a
missing route.

The specific failure this was written for:

    openai/_vendor/httpx_aiohttp/transport.py: aiohttp.SocketTimeoutError
    AttributeError: module aiohttp has no attribute SocketTimeoutError

aiohttp gained SocketTimeoutError in 3.10. `pip install --use-deprecated=
legacy-resolver` does not backtrack, so a later requirement silently downgrades an
earlier one — pinning aiohttp in requirements.txt is not sufficient, which is why
the Dockerfile forces it explicitly right before this script runs.

Note it is an AttributeError, not an ImportError. Guards written as
`except ImportError` do not catch it; both are `except Exception` for this reason.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

# Running this as `python scripts/verify_imports.py` puts scripts/ on sys.path, not the
# service root, so `import core.main` would fail with a misleading ModuleNotFoundError
# regardless of what is installed. Add the service root explicitly.
_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

# (module, what breaks if it is unimportable)
#
# structsense is deliberately absent: it is NOT installed by Dockerfile.unified,
# because structsense==0.0.4 holds aiohttp below 3.10 via an old crewai/litellm and
# that breaks openai's import for synthscholar too. Adding it back here without
# restoring the install would fail every build. See the comment on the ml_service
# pip step in Dockerfile.unified.
CHECKS = [
    ("synthscholar", "the whole /api/synth-scholar tree, incl. public reviews"),
]

# Minimum aiohttp that provides SocketTimeoutError, which openai's vendored
# httpx_aiohttp transport references at import time.
AIOHTTP_MIN = (3, 10)


def _fail(*lines: str) -> None:
    # Flush stdout first: it is block-buffered when the build log is a pipe, while
    # stderr is not, so without this the failure block prints BEFORE the progress
    # lines it refers to.
    sys.stdout.flush()
    print("", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    print("BUILD FAILED - ml_service import verification", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    for line in lines:
        print(line, file=sys.stderr)
    print("", file=sys.stderr)
    sys.exit(1)


def check_aiohttp() -> str | None:
    """Return an error string, or None if aiohttp is usable."""
    try:
        import aiohttp
    except Exception as exc:
        return f"aiohttp itself is unimportable: {type(exc).__name__}: {exc}"

    version = getattr(aiohttp, "__version__", "unknown")
    print(f"  aiohttp {version}")

    # Check the attribute rather than parsing the version: the attribute is what
    # openai actually touches, and it is the real contract.
    if not hasattr(aiohttp, "SocketTimeoutError"):
        return (
            f"aiohttp {version} has no SocketTimeoutError (needs "
            f">={'.'.join(map(str, AIOHTTP_MIN))}). Something downgraded it AFTER "
            "the explicit upgrade in Dockerfile.unified - check whether a "
            "requirement added since then pins an older aiohttp."
        )
    return None


def check_app() -> str | None:
    """Import the real ASGI app, the way gunicorn does.

    This is the check that matters most, and it was missing. Verifying only the two
    optional AI stacks let a build ship with a dependency the service's OWN code
    imports directly: bs4 arrived transitively via structsense, dropping structsense
    took it away, and ml_service died on boot with
    `ModuleNotFoundError: No module named 'bs4'` — through core/shared.py, a module
    this script never touched.

    Only ModuleNotFoundError is fatal. Anything else here (missing env vars, no
    database) is expected at build time and says nothing about the image: importing
    core.main builds the app and mounts routers but opens no connections — that
    happens in the lifespan, at runtime.
    """
    try:
        importlib.import_module("core.main")
    except ModuleNotFoundError as exc:
        return (
            f"core.main cannot be imported: {exc}\n"
            "      A package the service imports directly is not installed. Add it to "
            "requirements.txt rather than relying on another package to pull it in."
        )
    except Exception as exc:
        # Not a dependency problem — report and continue.
        print(f"  core.main imported with a non-import error ({type(exc).__name__}: "
              f"{exc}) - expected at build time if it needs env/database")
        return None
    print("  core.main OK (the ASGI app gunicorn loads)")
    return None


def main() -> None:
    print("Verifying ml_service AI stack imports...")

    problems = []

    err = check_aiohttp()
    if err:
        problems.append(err)

    for module, consequence in CHECKS:
        try:
            mod = importlib.import_module(module)
        except Exception as exc:
            # Deliberately broad: this chain (structsense -> crewai -> litellm ->
            # openai, synthscholar -> pydantic-ai -> openai) raises AttributeError
            # and RuntimeError as readily as ImportError.
            problems.append(
                f"{module} is unimportable - would disable {consequence}\n"
                f"      {type(exc).__name__}: {exc}"
            )
        else:
            print(f"  {module} {getattr(mod, '__version__', '?')} OK")

    err = check_app()
    if err:
        problems.append(err)

    if problems:
        _fail(*(f"  * {p}" for p in problems))

    print("All ml_service imports verified.")


if __name__ == "__main__":
    main()
