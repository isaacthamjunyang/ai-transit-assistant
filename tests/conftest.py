"""Every test runs with no OpenAI key and no way to reach the real OpenAI.

explain.py imports ENV_PATH by name, so a test that patches lta_static.ENV_PATH does not stop it reading the real .env.
A test that needs a key or a model reply sets it itself (explain.read_openai_api_key, explain._openai_complete).
With no key explain falls back to the fixed clause before any network call, in Demo Mode too.
"""

import pytest

import config
import explain


@pytest.fixture(autouse=True)
def _no_real_openai(monkeypatch, tmp_path):
    monkeypatch.setattr(explain, "ENV_PATH", tmp_path / "no-openai.env")  # a file that does not exist
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AI_EXPLANATION_ENABLED", raising=False)  # the model path is off unless a test turns it on


@pytest.fixture(autouse=True, scope="module")
def _no_bus_traffic_factor(request):
    """The bus traffic factor (config.BUS_PEAK_FACTOR) depends on the time a bus leg starts, and many fixtures here are
    stamped with the machine clock. So that no older test depends on the time of day, they run with the factor at 1.0
    (the behaviour they were written for). It is module scoped on purpose: a module-scoped browser fixture builds its
    page before any function-scoped fixture runs, and would otherwise see the real factor in the weekday peak hours. A
    module that tests the factor sets USES_BUS_TRAFFIC = True and pins its own clock."""
    if getattr(request.module, "USES_BUS_TRAFFIC", False):
        yield
        return
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config, "BUS_PEAK_FACTOR", 1.0)
        yield


@pytest.fixture(autouse=True, scope="module")
def _no_reroute_planner(request):
    """/api/reroute-options asks the OneMap planner for routes after a miss. A real .env can hold credentials, so no
    test reaches it unless the module sets USES_REROUTE_PLANNER = True and stubs the OneMap transport itself."""
    if getattr(request.module, "USES_REROUTE_PLANNER", False):
        yield
        return
    import main

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(main, "_reroute_planner_starts", lambda *args, **kwargs: [])
        yield


# ---- no real network from any test ----------------------------------------------------------------------------------
# A test that reaches LTA DataMall, OneMap, data.gov.sg or any other outside host fails, even when the code under test
# swallows the error. Only loopback is allowed (the in-process servers the browser tests start). The browser itself is
# a separate process; its page only talks to those loopback servers.
import ipaddress
import socket

NETWORK_LEAKS: list[str] = []
_LOCAL_NAMES = {"", "localhost", "testserver", "0.0.0.0", "::", "::1"}


def _is_local(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    if host is None or str(host).lower() in _LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True, scope="session")
def _block_real_network():
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_getaddrinfo(host, *args, **kwargs):
        if not _is_local(host):
            NETWORK_LEAKS.append(f"DNS lookup {host}")
            raise OSError(f"tests may not reach the network: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    def _address_host(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
            return address[0]
        return None

    def guarded_connect(self, address):
        host = _address_host(self, address)
        if host is not None and not _is_local(host):
            NETWORK_LEAKS.append(f"connect {host}")
            raise OSError(f"tests may not reach the network: {host}")
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        host = _address_host(self, address)
        if host is not None and not _is_local(host):
            NETWORK_LEAKS.append(f"connect {host}")
            return 10061
        return real_connect_ex(self, address)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
        patch.setattr(socket.socket, "connect", guarded_connect)
        patch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
        yield


@pytest.fixture(autouse=True)
def _fail_on_network_leak(request, _block_real_network):
    before = len(NETWORK_LEAKS)
    yield
    found = NETWORK_LEAKS[before:]
    if found:
        pytest.fail("real network attempt in this test: " + "; ".join(sorted(set(found))), pytrace=False)


def pytest_sessionfinish(session, exitstatus):
    if NETWORK_LEAKS and session.exitstatus == 0:
        session.exitstatus = 1  # a leak in a module-scoped fixture, outside any single test body
