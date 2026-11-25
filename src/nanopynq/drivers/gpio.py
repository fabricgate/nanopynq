from typing import cast

from nanopynq.ip import DefaultIP


class Pin:
    def __init__(self, ip: "_GPIO", index: int):
        self._ip = ip
        self._mask = 1 << index

    def read(self) -> int:
        return 1 if self._ip.read() & self._mask else 0

    def on(self) -> None:
        self._ip.write(0, self._ip.read() | self._mask)

    def off(self) -> None:
        self._ip.write(0, self._ip.read() & ~self._mask)

    def toggle(self) -> None:
        self._ip.write(0, self._ip.read() ^ self._mask)


class _GPIO(DefaultIP):
    def __len__(self) -> int:
        return cast(int, self.description["parameters"]["width"])

    def __getitem__(self, i: int) -> Pin:
        if not 0 <= i < len(self):
            raise IndexError(f"pin {i} out of range (width {len(self)})")
        return Pin(self, i)


class GPIOOut(_GPIO):
    bindto = ["nanopynq:gpio_out:1.0"]

    def write_all(self, value: int) -> None:
        self.write(0, value)


class GPIOIn(_GPIO):
    bindto = ["nanopynq:gpio_in:1.0"]

    def read_all(self) -> int:
        return self.read(0)
