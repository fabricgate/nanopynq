#!/bin/bash
# Build M3 firmware for the Tang Nano 4K EMCU (reports/report_4k_mcu_tools.md 8).
# usage: build_fw.sh OUTDIR main.c [more .c]   ->  OUTDIR/fw.elf, fw.bin, fw.map
# Env: GMD = the GMD folder (its toolchain/gowin/gcc_arm is used), EMPU_SDK = the Gowin_EMPU(GW1NS-4C) V2.0
# folder (headers, startup, drivers and linker script are referenced there, never copied), LD = another linker
# script (default: the SDK's gmd one, 32 KB flash at 0x0, 16 KB RAM at 0x20000000).
set -e
OUT=$1; shift
L="$EMPU_SDK/library/libraries"
export PATH="$GMD/toolchain/gowin/gcc_arm/bin:$PATH"
arm-none-eabi-gcc -mcpu=cortex-m3 -mthumb -Os -g -ffunction-sections -fdata-sections -Wall \
  -I"$L/cmsis/cm3/device_support" -I"$L/cmsis/cm3/core_support/gmd" -I"$L/drivers/inc" "$@" \
  "$L/drivers/src/gw1ns4c_uart.c" "$L/cmsis/cm3/device_support/system_gw1ns4c.c" "$L/drivers/src/gw1ns4c_gpio.c" \
  "$L/cmsis/cm3/device_support/startup/gmd/startup_gw1ns4c.S" \
  -T "${LD:-$L/cmsis/cm3/device_support/startup/gmd/linker/gw1ns4c_flash.ld}" \
  -Wl,--gc-sections -Wl,-Map="$OUT/fw.map" --specs=nano.specs --specs=nosys.specs -o "$OUT/fw.elf"
arm-none-eabi-objcopy -O binary "$OUT/fw.elf" "$OUT/fw.bin"
arm-none-eabi-size "$OUT/fw.elf"
