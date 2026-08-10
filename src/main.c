#include "flash_manager.h"
#include <string.h>

/* Suite de validation sur cible (Nucleo-F401) des correctifs C1-C7.
 * En cas d'échec, fail_stage contient l'étape fautive (breakpoint sur la
 * boucle infinie et inspecter). fail_stage == 0 en fin = tout est passé. */

static volatile uint32_t fail_stage = 0U;

static void check(bool ok, uint32_t stage)
{
    if (!ok) { fail_stage = stage; while (1) {} }
}

int main(void)
{
    uint8_t buf[24];
    uint16_t rlen;

    /* T1 - C1/C2 : init, écriture et relecture sur les vrais secteurs 2-3 */
    check(WL_Init() == FLASH_OK, 1U);
    check(WL_WriteRecord(1U, (const uint8_t *)"HELLO", 5U) == FLASH_OK, 2U);
    check((WL_ReadRecord(1U, buf, sizeof(buf), &rlen) == FLASH_OK) &&
          (rlen == 5U) && (memcmp(buf, "HELLO", 5U) == 0), 3U);

    /* T2 - C4/C6 : mise à jour -> le dernier record gagne */
    check(WL_WriteRecord(1U, (const uint8_t *)"WORLD!", 6U) == FLASH_OK, 4U);
    check((WL_ReadRecord(1U, buf, sizeof(buf), &rlen) == FLASH_OK) &&
          (rlen == 6U) && (memcmp(buf, "WORLD!", 6U) == 0), 5U);

    /* T3 - C5 : la suppression fonctionne réellement */
    check(WL_DeleteRecord(1U) == FLASH_OK, 6U);
    check(WL_ReadRecord(1U, buf, sizeof(buf), &rlen) == FLASH_NOT_FOUND, 7U);

    /* T4 - C3 : forcer un GC (511 slots/page), la donnée doit survivre */
    check(WL_WriteRecord(42U, (const uint8_t *)"KEEPME", 6U) == FLASH_OK, 8U);
    for (uint32_t i = 0U; i < 600U; i++) {
        check(WL_WriteRecord(2U, (const uint8_t *)&i, 4U) == FLASH_OK, 9U);
    }
    check((WL_ReadRecord(42U, buf, sizeof(buf), &rlen) == FLASH_OK) &&
          (memcmp(buf, "KEEPME", 6U) == 0), 10U);
    check((WL_GetEraseCount(0U) + WL_GetEraseCount(1U)) >= 1U, 11U);

    /* T5 - C7 : remplissage avec ids uniques -> FLASH_FULL propre, pas de hardfault */
    FlashStatus_t st = FLASH_OK;
    uint16_t id = 100U;
    while ((st == FLASH_OK) && (id < 2000U)) {
        st = WL_WriteRecord(id, (const uint8_t *)"X", 1U);
        id++;
    }
    check(st == FLASH_FULL, 12U);

    while (1) {} /* succès si fail_stage == 0 */
}
