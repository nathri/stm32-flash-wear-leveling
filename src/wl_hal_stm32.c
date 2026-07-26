#include "wl_hal.h"
#include "wl_config.h"
#include <string.h>

/* ------------------------------------------------------------------ */
/* Manual register definitions — no CMSIS dependency                    */
/* ------------------------------------------------------------------ */
#define FLASH_BASE_ADDR     0x08000000UL
#define FLASH_R_BASE        0x40023C00UL

#define FLASH_ACR           (*(volatile uint32_t *)(FLASH_R_BASE + 0x00))
#define FLASH_KEYR          (*(volatile uint32_t *)(FLASH_R_BASE + 0x04))
#define FLASH_SR            (*(volatile uint32_t *)(FLASH_R_BASE + 0x0C))
#define FLASH_CR            (*(volatile uint32_t *)(FLASH_R_BASE + 0x10))
#define FLASH_AR            (*(volatile uint32_t *)(FLASH_R_BASE + 0x14))

#define FLASH_SR_BSY        (1UL << 16)
#define FLASH_SR_PGSERR     (1UL << 7)
#define FLASH_SR_PGPERR     (1UL << 6)
#define FLASH_SR_PGAERR     (1UL << 5)
#define FLASH_CR_LOCK       (1UL << 31)
#define FLASH_CR_PER        (1UL << 1)
#define FLASH_CR_PG         (1UL << 0)
#define FLASH_CR_STRT       (1UL << 16)

#define FLASH_TOTAL_SIZE    (256U * 1024U)

/* ------------------------------------------------------------------ */
static bool stm32_flash_init(void)
{
    return true;
}

static int stm32_flash_erase(uint32_t page_addr)
{
    if (FLASH_CR & FLASH_CR_LOCK) {
        FLASH_KEYR = 0x45670123;
        FLASH_KEYR = 0xCDEF89AB;
    }

    while (FLASH_SR & FLASH_SR_BSY);

    FLASH_CR |= FLASH_CR_PER;
    FLASH_AR  = page_addr;
    FLASH_CR |= FLASH_CR_STRT;

    while (FLASH_SR & FLASH_SR_BSY);

    if (FLASH_SR & (FLASH_SR_PGSERR | FLASH_SR_PGPERR | FLASH_SR_PGAERR)) {
        FLASH_SR |= (FLASH_SR_PGSERR | FLASH_SR_PGPERR | FLASH_SR_PGAERR);
        FLASH_CR &= ~FLASH_CR_PER;
        FLASH_CR |= FLASH_CR_LOCK;
        return -1;
    }

    FLASH_CR &= ~FLASH_CR_PER;
    FLASH_CR |= FLASH_CR_LOCK;
    return 0;
}

static int stm32_flash_program(uint32_t addr, const uint8_t *data, uint32_t len)
{
    if (addr & 0x3U) return -1;

    if (FLASH_CR & FLASH_CR_LOCK) {
        FLASH_KEYR = 0x45670123;
        FLASH_KEYR = 0xCDEF89AB;
    }

    FLASH_CR |= FLASH_CR_PG;

    for (uint32_t i = 0; i < len; i += 4) {
        while (FLASH_SR & FLASH_SR_BSY);

        uint32_t word = 0xFFFFFFFFUL;
        uint32_t copy = (len - i < 4) ? (len - i) : 4;
        memcpy(&word, &data[i], copy);

        *(volatile uint32_t *)(addr + i) = word;

        while (FLASH_SR & FLASH_SR_BSY);
    }

    FLASH_CR &= ~FLASH_CR_PG;
    FLASH_CR |= FLASH_CR_LOCK;
    return 0;
}

static int stm32_flash_read(uint32_t addr, uint8_t *data, uint32_t len)
{
    memcpy(data, (const void *)addr, len);
    return 0;
}

static uint32_t stm32_get_sector_size(uint8_t idx)
{
    (void)idx;
    return WL_PAGE_SIZE;
}

static uint32_t stm32_get_sector_addr(uint8_t idx)
{
    const uint32_t wl_base = FLASH_BASE_ADDR + FLASH_TOTAL_SIZE - (WL_PAGE_COUNT * WL_PAGE_SIZE);
    return wl_base + (idx * WL_PAGE_SIZE);
}

/* ------------------------------------------------------------------ */
static const wl_hal_t stm32_hal = {
    .init            = stm32_flash_init,
    .erase           = stm32_flash_erase,
    .program         = stm32_flash_program,
    .read            = stm32_flash_read,
    .get_sector_size = stm32_get_sector_size,
    .get_sector_addr = stm32_get_sector_addr,
};

const wl_hal_t *wl_hal_get(void)
{
    return &stm32_hal;
}