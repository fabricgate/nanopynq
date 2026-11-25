import pytest

from nanopynq.drivers.i2c import I2C
from nanopynq.sensors.ov2640 import OV2640, OV2640_SETTINGS_CIF
from tests.fakes import FakeCameraBus

DESC = {"phys_addr": 0x3000, "registers": {}, "parameters": {}}


def make():
    bus = FakeCameraBus()
    return OV2640(I2C(DESC, bus)), bus


def test_init_table_starts_with_dsp_output_enable():  # P0: these two enable the DVP outputs
    assert OV2640_SETTINGS_CIF[:3] == ((0xFF, 0x00), (0x2C, 0xFF), (0x2E, 0xDF))
    assert len(OV2640_SETTINGS_CIF) == 157


def test_init_soft_resets_then_writes_the_table(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    cam, bus = make()
    cam.init()
    assert bus.writes[0] == (1, 0x12, 0x80)
    assert len(bus.writes) == 1 + sum(1 for r, _ in OV2640_SETTINGS_CIF if r != 0xFF)


def test_chip_id():
    assert make()[0].chip_id() == 0x2642


def test_set_size_qqvga_writes_window_and_zoom(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    cam, bus = make()
    cam.set_size(160, 120)
    dsp = {r: v for b, r, v in bus.writes if b == 0}
    assert (dsp[0x51], dsp[0x52], dsp[0x5A], dsp[0x5B], dsp[0x5C]) == (100, 74, 40, 30, 0)  # HSIZE VSIZE ZMOW ZMOH ZMHH
    assert bus.writes[-1] == (0, 0x05, 0x00)  # DSP re-enabled last
    assert (1, 0x11, 0x03) in bus.writes and (0, 0xD3, 0x88) in bus.writes  # CLKRC, R_DVP_SP


@pytest.mark.parametrize("w,h", [(800, 600), (161, 120), (160, 100)])
def test_unsupported_sizes_rejected(w, h):
    with pytest.raises(ValueError):
        make()[0].set_size(w, h)


def test_only_yuv422(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    cam, bus = make()
    cam.set_format("yuv422")
    assert (0, 0xDA, 0x00) in bus.writes
    with pytest.raises(ValueError):
        cam.set_format("jpeg")
