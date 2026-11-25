class TransportTimeout(Exception):
    """The device returned fewer bytes than the protocol requires."""

    def __init__(self, expected: int, received: int):
        super().__init__(f"timeout: expected {expected} bytes, received {received}")
        self.expected = expected
        self.received = received


class BuildError(Exception):
    """A step of the gateware build (synth / pnr / pack) failed."""

    def __init__(self, step: str, returncode: int, log: str):
        super().__init__(f"build step '{step}' failed (exit {returncode})")
        self.step = step
        self.returncode = returncode
        self.log = log


class ProgrammerNotFound(Exception):
    """openFPGALoader could not be located (PATH / NANOPYNQ_OPENFPGALOADER); only needed when it is the programmer."""


class ProgramError(Exception):
    """Loading the bitstream into SRAM failed. With openFPGALoader, `stderr` holds its raw stderr; with nanopynq's
    own sequence, the FPGA's IDCODE or status register."""

    def __init__(self, message: str, stderr: str):
        super().__init__(message)
        self.stderr = stderr


class ManifestError(Exception):
    """The design's metadata (.npq or manifest.yaml) is missing, malformed, does not fit the board, or its bitstream
    sha256 does not match."""


class NpqError(ManifestError):
    """A .npq broke rule `rule` (V1..V12, spec 5.9) at `where` (e.g. ips.leds.registers.data.width; "" is the file)."""

    def __init__(self, rule: str, where: str, detail: str):
        super().__init__(f"{rule} at {where or '(file)'}: {detail}")
        self.rule = rule
        self.where = where


class PortNotFound(Exception):
    """No (or no unambiguous) serial port matches the board; pass `port=` explicitly."""


class PortOpenError(Exception):
    """The serial port exists but could not be opened (busy, or no permission)."""


class BoardNotResponding(Exception):
    """The sysinfo ID register did not read back the expected value."""


class DesignMismatch(Exception):
    """The board answers, but the design on it is not the one the .npq describes (sys.version or sys.design_id)."""


class BridgeError(Exception):
    """A JTAG scan came back, but not as a bridge response (`response` holds the 64 bits read)."""

    def __init__(self, response: int):
        super().__init__(
            f"JTAG bridge returned 0x{response:016X} instead of a response: the board is not running a "
            "nanopynq base design, or the TAP lost user instruction 0x42"
        )
        self.response = response


class I2CError(Exception):
    """An I2C device did not acknowledge (`addr` is its 7-bit address) or answered unexpectedly."""

    def __init__(self, addr: int, detail: str = "no ACK"):
        super().__init__(f"I2C device 0x{addr:02X}: {detail}")
        self.addr = addr


class CaptureOverflow(Exception):
    """The captured frame was larger than the capture buffer; the data is incomplete."""
