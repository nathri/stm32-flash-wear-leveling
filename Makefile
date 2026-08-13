# STM32 Flash Wear-Leveling — Makefile
# Supports: STM32F401, STM32F767, STM32U385

MCU ?= STM32F401

# Cross-compiler
CC      = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
SIZE    = arm-none-eabi-size

# Common flags
CFLAGS  = -O2 -Wall -g -ffunction-sections -fdata-sections -std=c11 -MMD -MP
LDFLAGS = -Wl,--gc-sections -specs=nano.specs -specs=nosys.specs

# MCU-specific
ifeq ($(MCU),STM32F401)
    CPU_FLAGS = -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
    DEFS      = -DSTM32F401 -DSTM32F401xx
    LINKER    = linker/STM32F401CCUX_FLASH.ld
    SRCS      = src/flash_manager.c src/wl_hal_stm32.c src/main.c

else ifeq ($(MCU),STM32F767)
    CPU_FLAGS = -mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard
    DEFS      = -DSTM32F767 -DSTM32F767xx
    LINKER    = linker/STM32F767ZITX_FLASH.ld
    SRCS      = src/flash_manager.c src/wl_hal_stm32f7.c src/main_f767.c

else ifeq ($(MCU),STM32U385)
    CPU_FLAGS = -mcpu=cortex-m33 -mthumb -mfpu=fpv5-sp-d16 -mfloat-abi=hard
    DEFS      = -DSTM32U385 -DSTM32U385xx
    LINKER    = linker/STM32U385xx_FLASH.ld
    SRCS      = src/flash_manager.c src/wl_hal_stm32u3.c src/main_u385.c

else
    $(error Unknown MCU: $(MCU). Use STM32F401, STM32F767, or STM32U385)
endif

CFLAGS  += $(CPU_FLAGS) $(DEFS)
LDFLAGS += $(CPU_FLAGS) -T $(LINKER)

OBJS = $(SRCS:.c=.o)
DEPS = $(SRCS:.c=.d)

TARGET = flash_wear_leveling

.PHONY: all clean size

all: $(TARGET).bin

$(TARGET).elf: $(OBJS)
	$(CC) $(LDFLAGS) $(OBJS) -o $@
	@echo "Linked: $@"
	$(SIZE) $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@
	@echo "Binary: $@"

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(DEPS) $(TARGET).elf $(TARGET).bin $(TARGET).hex

size: $(TARGET).elf
	$(SIZE) $(TARGET).elf

-include $(DEPS)