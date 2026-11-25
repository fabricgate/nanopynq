# Third-party notices

`src/nanopynq/sensors/ov2640.py` is ported from [espressif/esp32-camera](https://github.com/espressif/esp32-camera)
(commit 281d951f75b6559adec3cdb8cf076366da103880):

- Register tables from `sensors/private_include/ov2640_settings.h`:
  Copyright 2015-2016 Espressif Systems (Shanghai) PTE LTD, Apache License 2.0 (`licenses/esp32-camera-LICENSE`).
- The window/zoom calculation from `sensors/ov2640.c` and the register names from
  `sensors/private_include/ov2640_regs.h`: part of the OpenMV project, Copyright (c) 2013/2014 Ibrahim Abdelkader,
  MIT license (`licenses/openmv-ov2640-LICENSE`).

`src/nanopynq/rtl/ddr3/` holds files of [e-karge/gowin-ddr3](https://github.com/e-karge/gowin-ddr3)
(commit 84a1a11681082fa599c61d3445ee173bc60ae659): `ddr3_cmd.sv`, `ddr3_init.sv`, `ddr3_calib.sv`,
`ddr3_phy_2to1.sv` unchanged, and `ddr3_ctrl.sv` and `ddr3_phy_slow.sv`. Eric Karge, Apache License 2.0 (`licenses/gowin-ddr3-LICENSE`). Its controller
core is derived from nand2mario's DDR3 controller for the Tang Primer 20K
([nand2mario/ddr3-tang-primer-20k](https://github.com/nand2mario/ddr3-tang-primer-20k), Apache License 2.0).
`ddr3_phy_slow.sv` is changed for nanopynq: the IDDR parameter reads DQ through IDDR in the IO blocks.
`ddr3_ctrl.sv` is changed for nanopynq: burst, din_burst and be_burst write all 8 words of a BL8 burst.

`tools/p0/gwjtag4k/bbasm_noboost_main.cc` is taken from a file of [YosysHQ/nextpnr](https://github.com/YosysHQ/nextpnr):
Copyright (C) 2018 Claire Xenia Wolf and Miodrag Milanovic, ISC license (the full notice is in the file).
