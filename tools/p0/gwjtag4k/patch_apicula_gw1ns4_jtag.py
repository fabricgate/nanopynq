"""Local patch: add GW_JTAG for GW1NS-4 (cell (0,0)) to an Apicula 0.35 copy. Upstream since YosysHQ/apicula#578."""
import os, re, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from apycula.chipdb import load_chipdb, save_chipdb

JTAG = {'jtag': {
    'inputs': {
        'tck_pad_i': 'DUMMY_JTAG_TCK_PAD', 'tms_pad_i': 'DUMMY_JTAG_TMS_PAD',
        'tdi_pad_i': 'DUMMY_JTAG_TDI_PAD', 'tdo_er1_i': 'C1', 'tdo_er2_i': 'C2'},
    'outputs': {
        'tdo_pad_o': 'DUMMY_JTAG_TDO_PAD', 'pause_dr_o': 'DUMMY_JTAG_PAUSE',
        'tck_o': 'Q6', 'tdi_o': 'Q5', 'test_logic_reset_o': 'Q3',
        'run_test_idle_er1_o': 'Q4', 'run_test_idle_er2_o': 'F0',
        'shift_dr_capture_dr_o': 'Q7', 'update_dr_o': 'Q2',
        'enable_er1_o': 'Q0', 'enable_er2_o': 'Q1'}}}

db_path = os.path.join(here, 'apycula', 'GW1NS-4.msgpack.xz')
db = load_chipdb(db_path)
db.extra_func.setdefault((0, 0), {}).update(JTAG)
save_chipdb(db, db_path)
print('chipdb patched:', db.extra_func[(0, 0)].keys())

gp = os.path.join(here, 'apycula', 'gowin_pack.py')
src = open(gp, encoding='utf-8').read()
marker = '    """ GW1NSR-4C chip. Tangnano4k board """\n    def __init__(self, cli_args: CliArgs, pnr: Netlist):\n        super().__init__(cli_args, pnr)\n'
method = '''
    def get_GW_JTAG_fuses(self, bel: BelDesc) -> list[CellFuseBits]:
        av = set()
        self.chipdb.get_cfg_attr_val(AttrVal('JTAG_ER1', 'USED'), av)
        self.chipdb.get_cfg_attr_val(AttrVal('JTAG_ER2', 'USED'), av)
        bits = self.chipdb.get_cfg_fuses(bel.x, bel.y, av)
        return [CellFuseBits(bel.x, bel.y, bits)] if bits else []
'''
assert marker in src and 'GW1NS-4 GW_JTAG' not in src
src = src.replace(marker, marker + '    # local patch: GW1NS-4 GW_JTAG' + method, 1)
open(gp, 'w', encoding='utf-8', newline='\n').write(src)
print('gowin_pack patched')
