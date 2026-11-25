# Gowin IDE (gw_sh allwires_9k.tcl, run next to allwires_top.vg): GW_JTAG with every output on a pin, Tang Nano 9K.
# The netlist skips GowinSynthesis (and its RP0008 check). Read impl/pnr/*.fs with gowin_unpack -d GW1N-9C,
# then trace_unpacked.py; impl/pnr/*.pin.html gives which port went to which pin.
set_device -name GW1NR-9C GW1NR-LV9QN88PC6/I5
add_file -type netlist allwires_top.vg
set_option -top_module top
set_option -output_base_name allw
set_option -use_sspi_as_gpio 1
set_option -use_mspi_as_gpio 1
set_option -use_ready_as_gpio 1
set_option -use_done_as_gpio 1
run all
