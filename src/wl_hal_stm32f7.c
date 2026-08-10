/*
 * HAL wear-leveling pour STM32F767 — implémentation basée sur HAL_FLASH
 * (issue #3 : cible CubeMX + MDK-KEIL + HAL + printf UART1).
 *
 * Prérequis projet :
 *  - stm32f7xx_hal_flash.c / stm32f7xx_hal_flash_ex.c activés (CubeMX)
 *  - VDD 2.7-3.6V supposé (FLASH_VOLTAGE_RANGE_3 => parallélisme x32).
 *    Pour VDD < 2.7V, utiliser FLASH_VOLTAGE_RANGE_1 (voir PORTING_F767.md).
 */
#if defined(STM32F767xx)

#include "wl_hal.h"
#include "wl_config.h"
#include "stm32f7xx_hal.h"
#include <string.h>

typedef struct {
    uint32_t addr;
    uint32_t size;
    uint32_t snb;       /* numéro de secteur logique HAL ; l'encodage SNB
                           matériel dual-bank (offset +4 au-delà du secteur
                           11) est géré en interne par HAL_FLASHEx_Erase */
} flash_sector_t;

static const flash_sector_t wl_sectors[WL_PAGE_COUNT] = {
    { WL_F7_SECTOR0_ADDR, WL_PAGE_SIZE, WL_F7_SECTOR0_SNB },
    { WL_F7_SECTOR1_ADDR, WL_PAGE_SIZE, WL_F7_SECTOR1_SNB },
};

/*
 * Hook watchdog : HAL_FLASHEx_Erase est BLOQUANT (~1-2s par secteur 128KB,
 * jusqu'à ~4s pour 256KB). Redéfinir dans l'application si IWDG actif :
 *
 *   void wl_f7_watchdog_refresh(void) { HAL_IWDG_Refresh(&hiwdg); }
 *
 * et dimensionner le timeout IWDG > 2x le temps d'erase max du secteur.
 */
__weak void wl_f7_watchdog_refresh(void)
{
}

/* ------------------------------------------------------------------ */
/* Cortex-M7 : maintenance D-cache autour des opérations Flash.
 * SCB_*DCache_by_Addr exige une adresse et une taille alignées sur 32. */
static void dcache_clean_range(uint32_t addr, uint32_t len)
{
    if ((SCB->CCR & SCB_CCR_DC_Msk) == 0U) return;   /* D-cache inactif */
    const uint32_t start = addr & ~31UL;
    const uint32_t size  = ((addr + len + 31UL) & ~31UL) - start;
    SCB_CleanDCache_by_Addr((uint32_t *)start, (int32_t)size);
}

static void dcache_invalidate_range(uint32_t addr, uint32_t len)
{
    if ((SCB->CCR & SCB_CCR_DC_Msk) == 0U) return;
    const uint32_t start = addr & ~31UL;
    const uint32_t size  = ((addr + len + 31UL) & ~31UL) - start;
    SCB_InvalidateDCache_by_Addr((uint32_t *)start, (int32_t)size);
}

/* ------------------------------------------------------------------ */
static bool f7_flash_init(void)
{
    /* Cohérence entre WL_F767_DUAL_BANK et l'option byte nDBANK (RM0410) :
     * nDBANK = 0 -> dual-bank ; nDBANK = 1 -> single-bank.
     * Un mismatch remapperait tous les secteurs => refus de démarrer. */
    const bool hw_dual_bank = ((FLASH->OPTCR & FLASH_OPTCR_nDBANK) == 0U);
#if (WL_F767_DUAL_BANK == 1)
    return hw_dual_bank;
#else
    return !hw_dual_bank;
#endif
}

static int f7_flash_erase(uint32_t sector_addr)
{
    int idx = -1;
    for (uint8_t i = 0U; i < WL_PAGE_COUNT; i++) {
        if (wl_sectors[i].addr == sector_addr) { idx = (int)i; break; }
    }
    if (idx < 0) return -1;    /* refuse tout erase hors zone WL */

    dcache_clean_range(wl_sectors[idx].addr, wl_sectors[idx].size);

    if (HAL_FLASH_Unlock() != HAL_OK) return -1;
    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_EOP | FLASH_FLAG_OPERR | FLASH_FLAG_WRPERR |
                           FLASH_FLAG_PGAERR | FLASH_FLAG_PGPERR | FLASH_FLAG_ERSERR);

    FLASH_EraseInitTypeDef erase;
    uint32_t bad_sector = 0xFFFFFFFFU;
    erase.TypeErase    = FLASH_TYPEERASE_SECTORS;
    erase.Sector       = wl_sectors[idx].snb;
    erase.NbSectors    = 1U;
    erase.VoltageRange = FLASH_VOLTAGE_RANGE_3;   /* x32, VDD 2.7-3.6V */

    wl_f7_watchdog_refresh();                     /* erase bloquant */
    const HAL_StatusTypeDef st = HAL_FLASHEx_Erase(&erase, &bad_sector);
    (void)HAL_FLASH_Lock();

    /* Le D-cache peut contenir les anciennes données du secteur */
    dcache_invalidate_range(wl_sectors[idx].addr, wl_sectors[idx].size);

    return (st == HAL_OK) ? 0 : -1;   /* détail : HAL_FLASH_GetError() */
}

static int f7_flash_program(uint32_t addr, const uint8_t *data, uint32_t len)
{
    if (((addr & 0x3UL) != 0UL) || (data == NULL) || (len == 0UL)) return -1;

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

    dcache_clean_range(addr, len);

    if (HAL_FLASH_Unlock() != HAL_OK) return -1;
    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_EOP | FLASH_FLAG_OPERR | FLASH_FLAG_WRPERR |
                           FLASH_FLAG_PGAERR | FLASH_FLAG_PGPERR | FLASH_FLAG_ERSERR);

    int rc = 0;
    for (uint32_t i = 0UL; i < len; i += 4UL) {
        uint32_t word = 0xFFFFFFFFUL;
        const uint32_t chunk = ((len - i) < 4UL) ? (len - i) : 4UL;
        memcpy(&word, &data[i], chunk);

        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, addr + i,
                              (uint64_t)word) != HAL_OK) {
            rc = -1;               /* détail : HAL_FLASH_GetError() */
            break;
        }
    }

    (void)HAL_FLASH_Lock();
    dcache_invalidate_range(addr, len);
    return rc;
}

static int f7_flash_read(uint32_t addr, uint8_t *data, uint32_t len)
{
    memcpy(data, (const void *)addr, len);
    return 0;
}

static uint32_t f7_get_sector_size(uint8_t idx)
{
    return (idx < WL_PAGE_COUNT) ? wl_sectors[idx].size : 0UL;
}

static uint32_t f7_get_sector_addr(uint8_t idx)
{
    return (idx < WL_PAGE_COUNT) ? wl_sectors[idx].addr : 0UL;
}

/* ------------------------------------------------------------------ */
static const wl_hal_t f7_hal = {
    .init            = f7_flash_init,
    .erase           = f7_flash_erase,
    .program         = f7_flash_program,
    .read            = f7_flash_read,
    .get_sector_size = f7_get_sector_size,
    .get_sector_addr = f7_get_sector_addr,
};

const wl_hal_t *wl_hal_get(void)
{
    return &f7_hal;
}

#endif /* STM32F767xx */
