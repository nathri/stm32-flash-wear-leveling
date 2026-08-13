/*
 * STM32U385 wear-leveling demo — CubeMX + MDK-ARM (Keil) integration
 *
 * This file is NOT main() — CubeMX generates main() separately.
 * Integration:
 *   1. Generate project in CubeMX:
 *      - Select STM32U385RG-Q
 *      - RCC: Enable external crystal (8 MHz)
 *      - GPIO: Configure LEDs (optional)
 *      - USART1: Asynchronous, 115200, 8N1 (debug output)
 *      - Project Manager: Generate code
 *   2. Add src/flash_manager.c, src/wl_config_u385.c, src/main_u385.c to Keil project
 *   3. In main(): after MX_USART1_UART_Init(), call wl_demo_u385()
 *   4. Build and flash via ST-Link
 */

#if defined(STM32U385xx)

#include "stm32u3xx_hal.h"
#include "flash_manager.h"
#include <stdio.h>
#include <string.h>

extern UART_HandleTypeDef huart1;

/* Retarget printf to USART1 (Keil MDK-ARM) */
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

void wl_demo_u385(void)
{
    uint8_t buf[24];
    uint16_t rlen = 0U;

    printf("\r\n=== Wear-leveling demo STM32U385 ===\r\n");
    printf("page size: %lu KB, pages: %u\r\n",
           (unsigned long)(WL_PAGE_SIZE / 1024U), (unsigned)WL_PAGE_COUNT);

    /* --- Init --- */
    if (WL_Init() != FLASH_OK) {
        printf("WL_Init FAILED\r\n");
        return;
    }
    printf("WL_Init OK\r\n");
    print_page_state("init");

    /* --- Write / Read --- */
    if (WL_WriteRecord(1U, (const uint8_t *)"HELLO U385", 10U) != FLASH_OK) {
        printf("write FAILED\r\n");
        return;
    }
    if (WL_ReadRecord(1U, buf, sizeof(buf), &rlen) == FLASH_OK) {
        printf("read id=1: %.*s (len=%u)\r\n", (int)rlen, (const char *)buf,
               (unsigned)rlen);
    }

    /* --- Update --- */
    (void)WL_WriteRecord(1U, (const uint8_t *)"UPDATED", 7U);
    (void)WL_ReadRecord(1U, buf, sizeof(buf), &rlen);
    printf("after update: %.*s\r\n", (int)rlen, (const char *)buf);

    /* --- Delete --- */
    (void)WL_DeleteRecord(1U);
    printf("after delete: %s\r\n",
           (WL_ReadRecord(1U, buf, sizeof(buf), &rlen) == FLASH_NOT_FOUND)
               ? "NOT_FOUND (ok)" : "UNEXPECTED");

    /* --- Force GC --- */
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

#endif /* STM32U385xx */