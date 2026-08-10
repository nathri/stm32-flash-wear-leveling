## STM32 Flash Wear-Leveling

![Build F401](https://github.com/nathri/stm32-flash-wear-leveling/actions/workflows/build.yml/badge.svg)

### Supported MCUs
- **STM32F401** (Cortex-M4, register-level HAL)
- **STM32F767** (Cortex-M7, HAL_FLASH, dual/single-bank)

### What's new in v2.0
- Fixed critical data-loss bugs C1-C7 (see commit history)
- Added STM32F767 support (issue #3)
- Added Python simulator with fault injection
- Added interactive HTML visualizer

# STM32 Flash Wear-Leveling Driver

Bare-metal C implementation of a Flash memory wear-leveling manager for STM32 microcontrollers. Designed for EEPROM emulation scenarios where limited erase cycles (typically ~10,000) must be distributed across multiple sectors to maximize lifetime.

## Features

- **Ring-buffer wear-leveling** across 2 Flash sectors
- **Record-level checksum** for data integrity (CRC-16-like)
- **Garbage collection** with automatic page rotation
- **Erase-count tracking** per sector for lifetime monitoring
- **Register-level Flash operations** — no HAL or LL dependency
- **MISRA-friendly** C11 code structure

## Target Hardware

- STM32F401 (ARM Cortex-M4, 256KB Flash)
- Easily portable to other STM32F4 / STM32L4 / STM32U5 variants

## Build

Requires: `arm-none-eabi-gcc`, `make`, `openocd` (optional, for flashing)

```bash
make        # build
make flash  # flash via ST-Link (requires openocd)
make clean  # reset