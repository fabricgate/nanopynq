"""DefaultIP and the bindto driver registry (PYNQ-style)."""

from typing import Any, ClassVar

from nanopynq.transport import Transport

_registry: dict[str, type["DefaultIP"]] = {}


class DefaultIP:
    bindto: ClassVar[list[str]] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for ip_type in cls.bindto:
            _registry[ip_type] = cls

    def __init__(self, description: dict[str, Any], transport: Transport) -> None:
        self.description = description
        self._transport = transport

    def read(self, offset: int = 0) -> int:
        return self._transport.read(self.description["phys_addr"] + offset)

    def write(self, offset: int, value: int) -> None:
        self._transport.write(self.description["phys_addr"] + offset, value)

    @property
    def register_map(self) -> dict[str, int]:
        """Reads the readable registers; wo and read_effect registers are left out (spec 5.3): read them with read()."""
        return {
            name: self.read(reg["offset"])
            for name, reg in self.description["registers"].items()
            if reg["access"] != "wo" and not reg.get("read_effect")
        }


def driver_for(ip_type: str) -> type[DefaultIP]:
    import nanopynq.drivers  # noqa: F401  (registers built-in drivers; lazy to avoid a cycle)

    return _registry.get(ip_type, DefaultIP)
