"""
conftest.py — shared pytest configuration
==========================================

no_network marker
-----------------
Tests decorated with @pytest.mark.no_network run with all outgoing socket
connections blocked.  Any test that accidentally calls lightkurve.search,
astroquery, or any HTTP client will raise RuntimeError before reaching the
network, keeping the CI suite hermetic.

timeout marker
--------------
Requires pytest-timeout.  Tests with @pytest.mark.timeout(N) fail if they
exceed N seconds of wall time.  Used on golden-file regression tests to
enforce the 60-second budget stated in the test module docstrings.
"""

import socket
import pytest


# ---------------------------------------------------------------------------
# no_network fixture — blocks outgoing connections at the socket level
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
    """
    if request.node.get_closest_marker("no_network"):
        monkeypatch.setattr(socket, "socket", _guard_socket)


# ---------------------------------------------------------------------------
# Register custom markers so pytest does not warn about unknown marks
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "no_network: mark test as requiring no network access; "
        "outgoing socket connections are blocked.",
    )
