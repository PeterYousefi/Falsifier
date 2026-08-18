"""
conftest.py — shared pytest configuration
==========================================

Python 3.12 / batman / distutils shim
---------------------------------------
``batman`` (a ``transitleastsquares`` dependency) imports
``distutils.ccompiler`` at module level.  ``distutils`` was removed from the
Python 3.12 stdlib.  The fix lives in ``falsifier._distutils_compat`` — a
committed source file that is imported here before any test collection can
trigger a batman/TLS import.  See that module for the full explanation and
rationale.  ``setuptools>=68`` is declared in ``pyproject.toml`` dev deps and
must be present for the ``_distutils_hack`` path to work; the stub fallback in
``falsifier._distutils_compat`` covers environments where it is absent.

no_network marker
-----------------
Tests decorated with @pytest.mark.no_network run with all outgoing socket
connections blocked.  Any test that accidentally calls lightkurve.search,
astroquery, or any HTTP client will raise RuntimeError before reaching the
network, keeping the CI suite hermetic.

session-wide socket guard
--------------------------
A session-scoped autouse fixture replaces socket.socket with a guard that
raises an immediately-informative error naming the test and the remote host
whenever ANY outbound connection is attempted.  This catches network calls
in tests that are *not* marked no_network — the most common cause of hangs
when a TLS or lightkurve fallback silently tries to phone home.

timeout
-------
A project-wide default of 30 s is set in pyproject.toml [tool.pytest.ini_options].
Tests that legitimately need more time opt in with @pytest.mark.timeout(N).
"""

# ---------------------------------------------------------------------------
# Python 3.12 distutils shim — must run before any batman/TLS import
# ---------------------------------------------------------------------------
# The shim logic lives in falsifier._distutils_compat (a committed source
# file) so it is active whenever falsifier is imported — in the API server,
# scripts, and here in the test process.  conftest.py imports it explicitly
# as an early-import guarantee before any test collection can trigger a
# batman/TLS import.
import falsifier._distutils_compat  # noqa: F401  (side-effect import)

import socket
import pytest


# ---------------------------------------------------------------------------
# Session-wide socket guard — catches ALL outbound network calls
# ---------------------------------------------------------------------------

_ORIGINAL_SOCKET = socket.socket


class _BlockedSocket:
    """Drop-in replacement for socket.socket that fails fast on connect()."""

    def __init__(self, *args, **kwargs):
        # Store args so the object looks like a real socket (some libraries
        # inspect the family/type before calling connect).
        self._family = args[0] if args else socket.AF_INET
        self._type = args[1] if len(args) > 1 else socket.SOCK_STREAM
        # Create an actual socket so bind/getsockname still work for
        # localhost-only use cases (e.g. ephemeral port allocation in tests).
        self._sock = _ORIGINAL_SOCKET(*args, **kwargs)

    def connect(self, address):
        host = address[0] if isinstance(address, (tuple, list)) else str(address)
        raise RuntimeError(
            f"\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  BLOCKED NETWORK CALL in test suite\n"
            f"  Host attempted : {host}\n"
            f"  Fix            : mock the external call or use cached data.\n"
            f"  Real network access belongs only in scripts/fetch_golden.py,\n"
            f"  which is run manually, never from pytest.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    # Delegate every other method to the real socket so localhost/unix-socket
    # I/O (used by some test helpers) continues to work.
    def __getattr__(self, name):
        return getattr(self._sock, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._sock.close()


@pytest.fixture(autouse=True, scope="session")
def _block_all_outbound_sockets(request):
    """
    Session-scoped autouse fixture: replace socket.socket with _BlockedSocket
    for the entire test session.

    Any test that tries to open an outbound TCP connection will receive a
    clear RuntimeError naming the remote host.  Tests that need a real
    network connection (scripts/fetch_golden.py) must never run under pytest.

    The no_network marker-based fixture below provides a secondary, per-test
    layer of protection for legacy tests that predate this session guard.
    """
    socket.socket = _BlockedSocket
    yield
    socket.socket = _ORIGINAL_SOCKET


# ---------------------------------------------------------------------------
# Per-test no_network fixture (legacy — kept for backward compatibility)
# ---------------------------------------------------------------------------

class _NetworkBlockedError(RuntimeError):
    """Raised when a test marked no_network attempts a network connection."""


def _guard_socket(*args, **kwargs):
    raise _NetworkBlockedError(
        "Network access is not permitted in tests marked @pytest.mark.no_network.\n"
        "If this test legitimately needs network access, remove the marker.\n"
        "If it should not need network access, the code under test is making an\n"
        "unexpected outgoing connection — this is a bug."
    )


@pytest.fixture(autouse=True)
def _block_network_if_marked(request, monkeypatch):
    """
    Autouse fixture: if the test is marked no_network, replace
    socket.socket with a guard that raises on any connection attempt.
    Superseded by the session-wide guard above, but retained so that
    existing tests relying on the _NetworkBlockedError type still work.
    """
    if request.node.get_closest_marker("no_network"):
        monkeypatch.setattr(socket, "socket", _guard_socket)
