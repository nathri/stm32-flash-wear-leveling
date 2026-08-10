# Makefile corrigé
MCU ?= STM32F401

# Common flags
CFLAGS = -O2 -Wall -g -ffunction-sections -fdata-sections -std=c11 -MMD -MP
LDFLAGS = -Wl,--gc-sections -specs=nano.specs -specs=nosys.specs

# MCU-specific configuration
ifeq ($(MCU),STM32F401)
    CPU_FLAGS = -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
    DEFS = -DSTM32F401 -DSTM32F401xx
    LINKER = linker/STM32F401CCUX_FLASH.ld
    SRCS = src/flash_manager.c src/wl_hal_stm32.c src/main.c

else ifeq ($(MCU),STM32F767)
    CPU_FLAGS = -mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard
    DEFS = -DSTM32F767 -DSTM32F767xx
    LINKER = linker/STM32F767ZITX_FLASH.ld
    SRCS = src/flash_manager.c src/wl_hal_stm32f7.c src/main_f767.c
endif

CFLAGS += $(CPU_FLAGS) $(DEFS)
LDFLAGS += $(CPU_FLAGS) -T $(LINKER)

OBJS = $(SRCS:.c=.o)
DEPS = $(SRCS:.c=.d)

.PHONY: all clean

all: flash_wear_leveling.bin

flash_wear_leveling.elf: $(OBJS)
	$(CC) $(LDFLAGS) $(OBJS) -o $@

flash_wear_leveling.bin: flash_wear_leveling.elf
	$(OBJCOPY) -O binary $< $@

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(DEPS) flash_wear_leveling.elf flash_wear_leveling.bin flash_wear_leveling.hex

-include $(DEPS)