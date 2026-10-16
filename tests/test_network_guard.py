"""The conftest guard: a request to LTA, OneMap or DataMall is refused and recorded, loopback is allowed."""

import socket

import pytest

import conftest


def test_the_guard_refuses_and_records_a_lookup_of_an_outside_host():
    before = len(conftest.NETWORK_LEAKS)
    for host in ("datamall2.mytransport.sg", "www.onemap.gov.sg", "api.data.gov.sg"):
        with pytest.raises(OSError):
            socket.getaddrinfo(host, 443)
    assert len(conftest.NETWORK_LEAKS) - before == 3
    del conftest.NETWORK_LEAKS[before:]  # this test proves the guard, so its own records are not leaks


def test_the_guard_refuses_a_connect_to_an_outside_address():
    before = len(conftest.NETWORK_LEAKS)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError):
            sock.connect(("203.0.113.9", 443))
    finally:
        sock.close()
    assert len(conftest.NETWORK_LEAKS) == before + 1
    del conftest.NETWORK_LEAKS[before:]


def test_loopback_is_allowed():
    assert conftest._is_local("127.0.0.1") and conftest._is_local("localhost")
    assert not conftest._is_local("datamall2.mytransport.sg")
