"""Block real network access so an offline run cannot silently call NVIDIA or DuckDuckGo.

Any attempt to resolve or connect to a non-loopback address raises ConnectionError (so a leak
shows as an error in the run) and is recorded in `attempts` (so the result can state it).
"""

from __future__ import annotations

import contextlib
import ipaddress
import socket
from collections.abc import Callable, Iterator
from typing import Any

LOCAL_NAMES = {"localhost", "127.0.0.1", "::1", ""}


def _is_local(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    host = str(host or "")
    if host in LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@contextlib.contextmanager
def block_network(attempts: list[str]) -> Iterator[None]:
    """Patch socket resolution and connection; non-loopback targets are refused and recorded."""

    def refuse(target: object) -> None:
        attempts.append(str(target))
        raise ConnectionError(f"network blocked in offline mode: {target}")

    def host_guard(real: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(host: Any, *a: Any, **k: Any) -> Any:
            if not _is_local(host):
                refuse(host)
            return real(host, *a, **k)

        return wrapper

    def addr_guard(real: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(self: Any, address: Any, *a: Any, **k: Any) -> Any:
            if isinstance(address, tuple) and not _is_local(address[0]):
                refuse(address[0])
            return real(self, address, *a, **k)

        return wrapper

    # (owner, attribute, guard): resolvers take a host first; connect/getnameinfo take an address.
    targets = [
        (socket, "getaddrinfo", host_guard),
        (socket, "gethostbyname", host_guard),
        (socket, "gethostbyname_ex", host_guard),
        (socket.socket, "connect", addr_guard),
        (socket.socket, "connect_ex", addr_guard),
    ]
    saved = [(owner, name, getattr(owner, name)) for owner, name, _ in targets]
    real_gni = socket.getnameinfo

    def getnameinfo(sockaddr: Any, flags: int) -> Any:
        if isinstance(sockaddr, tuple) and not _is_local(sockaddr[0]):
            refuse(sockaddr[0])
        return real_gni(sockaddr, flags)

    try:
        for owner, name, guard in targets:
            setattr(owner, name, guard(getattr(owner, name)))
        socket.getnameinfo = getnameinfo
        yield
    finally:
        for owner, name, real in saved:
            setattr(owner, name, real)
        socket.getnameinfo = real_gni
