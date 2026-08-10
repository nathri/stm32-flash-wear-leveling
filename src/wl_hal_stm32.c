/* HAL wear-leveling STM32F401 — compilé uniquement si STM32F401xx est
 * défini (voir Makefile), pour coexister avec wl_hal_stm32f7.c. */
#if defined(STM32F401xx)

#include "wl_hal.h"
#include "wl_config.h"
#include <string.h>

/* ------------------------------------------------------------------- */
/* Registres Flash STM32F401 — RM368 §3.8 (pas de CMSIS)              */
/* ------------------------------------------------------------------- */
#define FLASH_R_BASE        0x40023C00UL

#define FLASH_ACR           (*(volatile uint32_t *)(FLASH_R_BASE + 0x00U))
#define FLASH_KEYR          (*(volatile uint32_t *)(FLASH_R_BASE + 0x04U))
#define FLASH_SR            (*(volatile uint32_t *)(FLASH_R_BASE + 0x0CU))
#define FLASH_CR            (*(volatile uint32_t *)(FLASH_R_BASE + 0x10U))

/* FLASH_SR */
#define FLASH_SR_EOP        (1UL << 0)
#define FLASH_SR_OPERR      (1UL << 1)
#define FLASH_SR_WRPERR     (1UL << 4)
#define FLASH_SR_PGAERR     (1UL << 5)
#define FLASH_SR_PGPERR     (1UL << 6)
#define FLASH_SR_PGSERR     (1UL << 7)
#define FLASH_SR_RDERR      (1UL << 8)
#define FLASH_SR_BSY        (1UL << 16)
#define FLASH_SR_ERRORS     (FLASH_SR_OPERR | FLASH_SR_WRPERR | FLASH_SR_PGAERR | \
                             FLASH_SR_PGPERR | FLASH_SR_PGSERR | FLASH_SR_RDERR)

/* FLASH_CR */
#define FLASH_CR_PG         (1UL << 0)
#define FLASH_CR_SER        (1UL << 1)
#define FLASH_CR_SNB_POS    3U
#define FLASH_CR_SNB_MSK    (0xFUL << FLASH_CR_SNB_POS)
#define FLASH_CR_PSIZE_MSK  (0x3UL << 8)
#define FLASH_CR_PSIZE_X8   (0x0UL << 8)    /* byte (8-bit) */
#define FLASH_CR_PSIZE_X16  (0x1UL << 8)    /* half-word (16-bit) */
#define FLASH_CR_PSIZE_X32  (0x2UL << 8)    /* word (32-bit), VDD 2.7-3.6V */
#define FLASH_CR_PSIZE_X64  (0x3UL << 8)    /* double-word (64-bit), VDD 2.7-3.6V */
#define FLASH_CR_STRT       (1UL << 16)
#define FLASH_CR_LOCK       (1UL << 31)

/* FLASH_ACR (accélérateur ART) */
#define FLASH_ACR_DCEN      (1UL << 10)
#define FLASH_ACR_DCRST     (1UL << 12)

/* -------------------------------------------------------------------- */
/* Secteurs physiques réservés au wear-leveling (RM368 Table 5)        */
/* ------------------------------------------------------------------- */
typedef struct {
    uint32_t addr;
    uint32_t size;
    uint8_t  snb;       /* numéro de secteur pour CR.SNB */
} flash_sector_t;

static const flash_sector_t wl_sectors[WL_PAGE_COUNT] = {
    { 0x08008000UL, 16U * 1024U, 2U },
    { 0x0800C000UL, 16U * 1024U, 3U },
};

/* ------------------------------------------------------------------- */
static int flash_unlock(void)
{
    if ((FLASH_CR & FLASH_CR_LOCK) != 0UL) {
        FLASH_KEYR = 0x45670123UL;
        FLASH_KEYR = 0xCDEF89ABUL;
    }
    return ((FLASH_CR & FLASH_CR_LOCK) != 0UL) ? -1 : 0;
}

static void flash_lock(void)
{
    FLASH_CR |= FLASH_CR_LOCK;
}

static void flash_wait_bsy(void)
{
    while ((FLASH_SR & FLASH_SR_BSY) != 0UL) { }
}

static void flash_clear_errors(void)
{
    FLASH_SR = FLASH_SR_ERRORS | FLASH_SR_EOP;   /* write-1-to-clear */
}

/* RM0368 §3.4.2 : le D-cache ART doit être désactivé pendant son reset.
 * Obligatoir après erase/program, sinon relecture de données périmées. */
static void art_flush_dcache(void)
{
    const uint32_t acr = FLASH_ACR;
    FLASH_ACR = acr & ~FLASH_ACR_DCEN;
    FLASH_ACR |= FLASH_ACR_DCRST;
    FLASH_ACR &= ~FLASH_ACR_DCRST;
    if ((acr & FLASH_ACR_DCEN) != 0UL) {
        FLASH_ACR |= FLASH_ACR_DCEN;
    }
}

/* ------------------------------------------------------------------ */
static bool stm32_flash_init(void)
{
    return true;
}

static int stm32_flash_erase(uint32_t sector_addr)
{
    int idx = -1;
    for (uint8_t i = 0U; i < WL_PAGE_COUNT; i++) {
        if (wl_sectors[i].addr == sector_addr) { idx = (int)i; break; }
    }
    if (idx < 0) return -1;    /* refuse tout erase hors zone WL */

    if (flash_unlock() != 0) return -1;
    flash_wait_bsy();
    flash_clear_errors();

    uint32_t cr = FLASH_CR & ~(FLASH_CR_SNB_MSK | FLASH_CR_PSIZE_MSK | FLASH_CR_PG);
    cr |= FLASH_CR_SER
        | ((uint32_t)wl_sectors[idx].snb << FLASH_CR_SNB_POS)
        | FLASH_CR_PSIZE_X32;
    FLASH_CR  = cr;
    FLASH_CR |= FLASH_CR_STRT;

    flash_wait_bsy();
    FLASH_CR &= ~(FLASH_CR_SER | FLASH_CR_SNB_MSK);

    const int rc = ((FLASH_SR & FLASH_SR_ERRORS) != 0UL) ? -1 : 0;
    flash_clear_errors();
    art_flush_dcache();
    flash_lock();
    return rc;
}

static int stm32_flash_program(uint32_t addr, const uint8_t *data, uint32_t len)
{
    uint32_t align_mask;
    uint32_t psize_bytes;

    if (WL_STM32_PSIZE == FLASH_CR_PSIZE_X8) {
        align_mask = 0x0UL;
        psize_bytes = 1U;
    } else if (WL_STM32_PSIZE == FLASH_CR_PSIZE_X16) {
        align_mask = 0x1UL;
        psize_bytes = 2U;
    } else if (WL_STM32_PSIZE == FLASH_CR_PSIZE_X32) {
        align_mask = 0x3UL;
        psize_bytes = 4U;
    } else if (WL_STM32_PSIZE == FLASH_CR_PSIZE_X64) {
        align_mask = 0x7UL;
        psize_bytes = 8U;
    } else {
        return -1;
    }

    if (((addr & align_mask) != 0UL) || (data == NULL) || (len == 0UL)) return -1;

    /* Bounds check : la plage entière doit tenir dans UN secteur WL */
    int idx = -1;
    for (uint8_t i = 0U; i < WL_PAGE_COUNT; i++) {
        if ((addr >= wl_sectors[i].addr) &&
            ((addr + len) <= (wl_sectors[i].addr + wl_sectors[i].size))) {
            idx = (int)i;
            break;
        }
    }
    if (idx < 0) return -1;

    if (flash_unlock() != 0) return -1;
    flash_wait_bsy();
    flash_clear_errors();

    FLASH_CR = (FLASH_CR & ~FLASH_CR_PSIZE_MSK) | WL_STM32_PSIZE;
    FLASH_CR |= FLASH_CR_PG;

    int rc = 0;
    for (uint32_t i = 0UL; i < len; i += psize_bytes) {
        uint64_t value = 0xFFFFFFFFFFFFFFFFULL;
        const uint32_t chunk = ((len - i) < psize_bytes) ? (len - i) : psize_bytes;
        memcpy(&value, &data[i], chunk);

        if (psize_bytes == 1U) {
            *(volatile uint8_t *)(addr + i)  = (uint8_t)value;
        } else if (psize_bytes == 2U) {
            *(volatile uint16_t *)(addr + i) = (uint16_t)value;
        } else if (psize_bytes == 4U) {
            *(volatile uint32_t *)(addr + i) = (uint32_t)value;
        } else {
            *(volatile uint64_t *)(addr + i) = value;
        }
        flash_wait_bsy();

        if ((FLASH_SR & FLASH_SR_ERRORS) != 0UL) { rc = -1; break; }
    }

    FLASH_CR &= ~FLASH_CR_PG;
    flash_clear_errors();
    art_flush_dcache();
    flash_lock();
    return rc;
}

static int stm32_flash_read(uint32_t addr, uint8_t *data, uint32_t len)
{
    memcpy(data, (const void *)addr, len);
    return 0;
}

static uint32_t stm32_get_sector_size(uint8_t idx)
{
    return (idx < WL_PAGE_COUNT) ? wl_sectors[idx].size : 0UL;
}

static uint32_t stm32_get_sector_addr(uint8_t idx)
{
    return (idx < WL_PAGE_COUNT) ? wl_sectors[idx].addr : 0UL;
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

#endif /* STM32F401xx */