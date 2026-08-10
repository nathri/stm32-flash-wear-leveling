/*
 * Exemple d'intégration STM32F767 — CubeMX + MDK-ARM (Keil) + HAL.
 *
 * Ce fichier ne définit PAS main() : CubeMX génère le sien.
 * Intégration :
 *   1. Générer le projet CubeMX (clocks, USART1, caches actifs — voir
 *      PORTING_F767.md).
 *   2. Ajouter les fichiers src/ du driver au projet Keil
 *      (flash_manager.c, wl_hal_stm32f7.c, main_f767.c).
 *   3. Déclarer  void wl_demo_f767(void);  et l'appeler dans main()
 *      après MX_USART1_UART_Init() (section USER CODE 2).
 *   4. Si IWDG actif : redéfinir wl_f7_watchdog_refresh() (voir
 *      wl_hal_stm32f7.c).
 */
#if defined(STM32F767xx)

#include "stm32f7xx_hal.h"
#include "flash_manager.h"
#include <stdio.h>
#include <string.h>

extern UART_HandleTypeDef huart1;   /* généré par CubeMX */

/* Retarget printf vers UART1 (MDK-ARM / Keil) */
int fputc(int ch, FILE *f)
{
    (void)f;
    uint8_t c = (uint8_t)ch;
    (void)HAL_UART_Transmit(&huart1, &c, 1U, 100U);
    return ch;
}

static void print_page_state(const char *tag)
{
    printf("[%s] erase counts: page0=%lu  page1=%lu\r\n", tag,
           (unsigned long)WL_GetEraseCount(0U),
           (unsigned long)WL_GetEraseCount(1U));
}

void wl_demo_f767(void)
{
    uint8_t buf[24];
    uint16_t rlen = 0U;

    printf("\r\n=== Wear-leveling demo STM32F767 ===\r\n");
    printf("page size: %lu KB, pages: %u\r\n",
           (unsigned long)(WL_PAGE_SIZE / 1024U), (unsigned)WL_PAGE_COUNT);

    /* --- Init (vérifie aussi la cohérence dual/single-bank) --- */
    if (WL_Init() != FLASH_OK) {
        printf("WL_Init FAILED — verifier nDBANK (FLASH_OPTCR) vs "
               "WL_F767_DUAL_BANK\r\n");
        return;
    }
    printf("WL_Init OK\r\n");
    print_page_state("init");

    /* --- Ecriture / lecture --- */
    if (WL_WriteRecord(1U, (const uint8_t *)"HELLO F767", 10U) != FLASH_OK) {
        printf("write FAILED\r\n");
        return;
    }
    if (WL_ReadRecord(1U, buf, sizeof(buf), &rlen) == FLASH_OK) {
        printf("read id=1: %.*s (len=%u)\r\n", (int)rlen, (const char *)buf,
               (unsigned)rlen);
    }

    /* --- Mise a jour : le dernier record gagne --- */
    (void)WL_WriteRecord(1U, (const uint8_t *)"UPDATED", 7U);
    (void)WL_ReadRecord(1U, buf, sizeof(buf), &rlen);
    printf("after update: %.*s\r\n", (int)rlen, (const char *)buf);

    /* --- Suppression --- */
    (void)WL_DeleteRecord(1U);
    printf("after delete: %s\r\n",
           (WL_ReadRecord(1U, buf, sizeof(buf), &rlen) == FLASH_NOT_FOUND)
               ? "NOT_FOUND (ok)" : "UNEXPECTED");

    /* --- GC forcé : remplir la page active, mesurer la durée --- */
    const uint32_t n_writes = (WL_PAGE_SIZE / FLASH_RECORD_SIZE) + 8U;
    printf("forcing GC (%lu writes)... ", (unsigned long)n_writes);

    (void)WL_WriteRecord(42U, (const uint8_t *)"KEEPME", 6U);
    const uint32_t t0 = HAL_GetTick();
    for (uint32_t i = 0U; i < n_writes; i++) {
        if (WL_WriteRecord(2U, (const uint8_t *)&i, 4U) != FLASH_OK) {
            printf("\r\nwrite #%lu FAILED\r\n", (unsigned long)i);
            return;
        }
    }
    printf("done in %lu ms\r\n", (unsigned long)(HAL_GetTick() - t0));

    printf("record 42 survived GC: %s\r\n",
           ((WL_ReadRecord(42U, buf, sizeof(buf), &rlen) == FLASH_OK) &&
            (memcmp(buf, "KEEPME", 6U) == 0)) ? "YES" : "NO");
    print_page_state("after GC");

    printf("=== demo complete ===\r\n");
}

#endif /* STM32F767xx */
