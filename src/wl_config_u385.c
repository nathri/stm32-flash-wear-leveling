/*
 * HAL wear-leveling pour STM32U385 (NUCLEO-U385RG-Q)
 *
 * Base sur HAL_FLASH STM32U3xx — issue #6.
 *
 * Prerequis projet :
 *  - stm32u3xx_hal_flash.c / stm32u3xx_hal_flash_ex.c actives (CubeMX)
 *  - TrustZone desactive ou page WL en non-secure (defaut Nucleo)
 *  - VDD >= 1.71V (QUADWORD supporte toute la plage U3)
 *
 * Architecture Flash U3 (RM0487) :
 *  - 4 KB pages, dual-bank
 *  - Programmation main Flash : 128-bit (16 bytes) aligne
 *  - ECC 72-bit (64 data + 8 ECC) par 128-bit word
 *  - Read-while-write entre banques
 */
#if defined(STM32U385xx)

#include "wl_hal.h"
#include "wl_config.h"
#include "stm32u3xx_hal.h"   /* CubeMX genere stm32u3xx_hal.h ou equivalent */
#include <string.h>

typedef struct {
    uint32_t addr;
    uint32_t page;
    uint32_t bank;
} flash_page_t;

static const flash_page_t wl_pages[WL_PAGE_COUNT] = {
    { WL_U3_PAGE0_ADDR, WL_U3_PAGE0, WL_U3_BANK },
    { WL_U3_PAGE1_ADDR, WL_U3_PAGE1, WL_U3_BANK },
};

/* -------------------------------------------------------------------- */
/* Maintenance cache (Cortex-M33 : ICACHE + DCACHE)                     */
/* -------------------------------------------------------------------- */
static void dcache_clean_range(uint32_t addr, uint32_t len)
{
    if ((SCB->CCR & SCB_CCR_DC_Msk) == 0U) return;
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

/* -------------------------------------------------------------------- */
static bool u3_flash_init(void)
{
    /* Optionnel : verifier que DBANK=1 (dual-bank actif).
     * Sur U3, lire FLASH_OPTR.DBANK. Si mismatch, retourner false.
     * Simplifie ici : on suppose la config Nucleo par defaut. */
    return true;
}

static int u3_flash_erase(uint32_t page_addr)
{
    int idx = -1;
    for (uint8_t i = 0U; i < WL_PAGE_COUNT; i++) {
        if (wl_pages[i].addr == page_addr) { idx = (int)i; break; }
    }
    if (idx < 0) return -1;    /* refuse erase hors zone WL */

    dcache_clean_range(wl_pages[idx].addr, WL_PAGE_SIZE);

    if (HAL_FLASH_Unlock() != HAL_OK) return -1;
    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);

    FLASH_EraseInitTypeDef erase;
    uint32_t page_error = 0xFFFFFFFFU;
    erase.TypeErase = FLASH_TYPEERASE_PAGES;
    erase.Banks     = wl_pages[idx].bank;
    erase.Page      = wl_pages[idx].page;
    erase.NbPages   = 1U;

    const HAL_StatusTypeDef st = HAL_FLASHEx_Erase(&erase, &page_error);
    (void)HAL_FLASH_Lock();

    dcache_invalidate_range(wl_pages[idx].addr, WL_PAGE_SIZE);
    return (st == HAL_OK) ? 0 : -1;
}

static int u3_flash_program(uint32_t addr, const uint8_t *data, uint32_t len)
{
    /* U3 main Flash : programmation 128-bit (16 octets), alignement 16 */
    if (((addr & 0xFUL) != 0UL) || (data == NULL) || (len == 0UL)) return -1;

    /* Bounds check : la plage doit tenir dans UNE page WL */
    int idx = -1;
    for (uint8_t i = 0U; i < WL_PAGE_COUNT; i++) {
        if ((addr >= wl_pages[i].addr) &&
            ((addr + len) <= (wl_pages[i].addr + WL_PAGE_SIZE))) {
            idx = (int)i;
            break;
        }
    }
    if (idx < 0) return -1;

    dcache_clean_range(addr, len);

    if (HAL_FLASH_Unlock() != HAL_OK) return -1;
    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);

    int rc = 0;
    /* Boucle en chunks de 16 octets (128-bit quad-word) */
    for (uint32_t i = 0UL; i < len; i += 16U) {
        uint32_t quad[4];
        const uint32_t chunk = ((len - i) < 16U) ? (len - i) : 16U;

        /* Remplir avec 0xFF (etat efface), puis copier les donnees reelles */
        quad[0] = 0xFFFFFFFFU;
        quad[1] = 0xFFFFFFFFU;
        quad[2] = 0xFFFFFFFFU;
        quad[3] = 0xFFFFFFFFU;
        memcpy(quad, &data[i], chunk);

        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_QUADWORD,
                              addr + i,
                              (uint32_t)(uintptr_t)quad) != HAL_OK) {
            rc = -1;
            break;
        }
    }

    (void)HAL_FLASH_Lock();
    dcache_invalidate_range(addr, len);
    return rc;
}

static int u3_flash_read(uint32_t addr, uint8_t *data, uint32_t len)
{
    memcpy(data, (const void *)addr, len);
    return 0;
}

static uint32_t u3_get_page_size(uint8_t idx)
{
    return (idx < WL_PAGE_COUNT) ? WL_PAGE_SIZE : 0UL;
}

static uint32_t u3_get_page_addr(uint8_t idx)
{
    return (idx < WL_PAGE_COUNT) ? wl_pages[idx].addr : 0UL;
}

/* -------------------------------------------------------------------- */
static const wl_hal_t u3_hal = {
    .init            = u3_flash_init,
    .erase           = u3_flash_erase,
    .program         = u3_flash_program,
    .read            = u3_flash_read,
    .get_sector_size = u3_get_page_size,
    .get_sector_addr = u3_get_page_addr,
};

const wl_hal_t *wl_hal_get(void)
{
    return &u3_hal;
}

#endif /* STM32U385xx */