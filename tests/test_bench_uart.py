import importlib.util
from pathlib import Path

from nanopynq.transport.uartbone import UARTBone
from tests.fakes import FakeUARTBoneDevice

spec = importlib.util.spec_from_file_location(
    "bench_uart", Path(__file__).resolve().parents[1] / "tools" / "p0" / "bench_uart.py"
)
bench_uart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench_uart)


class StepClock:
    """Advances 1 s per call. measure(d=3): start=0, checks 1,2 (read), 3 (stop), end=4 -> 2 reads, 4 s."""

    def __init__(self):
        self.t = -1.0

    def __call__(self):
        self.t += 1.0
        return self.t


def test_measure_issues_one_read_per_loop_and_right_word_count():
    for words in (1, 255):
        dev = FakeUARTBoneDevice({0: 0x4E505131})
        n, elapsed = bench_uart.measure(UARTBone(dev, 115200), words, 3.0, StepClock())
        assert n == dev.frames == 2 and elapsed == 4.0
        assert dev.received[1] == words  # length byte of the last request frame


def test_bench_table_row_shape_and_values():
    dev = FakeUARTBoneDevice({0: 0x4E505131})
    (row,) = bench_uart.bench(UARTBone(dev, 115200), 115200, 3.0, StepClock())
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[0] == "115200" and len(cells) == 3
    assert cells[1] == f"{2 / 4:.0f}" and float(cells[2]) == round(2 * 255 * 4 / 1000 / 4, 1)
    assert dev.frames == 4  # 2 one-word + 2 burst reads


def test_bench_reports_no_response_on_silent_device():
    dev = FakeUARTBoneDevice(truncate_after=0)
    (row,) = bench_uart.bench(UARTBone(dev, 3000000), 3000000, 2.0, StepClock())
    assert row == "| 3000000 | no response | no response |"
