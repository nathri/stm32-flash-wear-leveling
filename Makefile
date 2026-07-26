TARGET = flash_wear_leveling
MCU = STM32F401xx
CPU = -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard

CC = arm-none-eabi-gcc
LD = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
SIZE = arm-none-eabi-size

CFLAGS = $(CPU) -D$(MCU) -O2 -Wall -g \
         -ffunction-sections -fdata-sections \
         -std=c11 -MMD -MP

CFLAGS = $(CPU) -D$(MCU) -DSTM32F401xx -O2 -Wall -g \
         -ffunction-sections -fdata-sections \
         -std=c11 -MMD -MP

LDFLAGS = $(CPU) -T linker/STM32F401CCUX_FLASH.ld \
          -Wl,--gc-sections -specs=nano.specs -specs=nosys.specs

SRCS = $(wildcard src/*.c)
OBJS = $(SRCS:.c=.o)

.PHONY: all clean flash

all: $(TARGET).elf $(TARGET).bin
	$(SIZE) $(TARGET).elf

$(TARGET).elf: $(OBJS)
	$(LD) $(LDFLAGS) $^ -o $@

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

flash: $(TARGET).bin
	openocd -f interface/stlink.cfg -f target/stm32f4x.cfg \
	-c "program $(TARGET).bin 0x08000000 verify reset exit"

clean:
	rm -f $(OBJS) $(TARGET).elf $(TARGET).bin $(TARGET).hex $(SRCS:.c=.d)
