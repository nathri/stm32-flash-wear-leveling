#ifndef WL_CONFIG_F767_H
#define WL_CONFIG_F767_H

/*
 * Configuration wear-leveling STM32F767 (RM0410) — carte mémoire 1MB.
 * Pour les variantes 2MB (ex: F767ZI), voir PORTING_F767.md § "Variante 2MB".
 *
 * Mode banque (option byte nDBANK, FLASH_OPTCR) :
 *   WL_F767_DUAL_BANK = 1 -> dual-bank   (nDBANK = 0)
 *   WL_F767_DUAL_BANK = 0 -> single-bank (nDBANK = 1, défaut using)
 *
 * La cohérence entre ce define et l'option byte réelle est vérifiée à
 * l'exècution dans WL_Init (hal->init) : mismatch => FLASH_ERROR.
 */
#ifndef WL_F767_DUAL_BANK
#define WL_F767_DUAL_BANK   1
#endif

#define WL_PAGE_COUNT       2U

#if (WL_F767_DUAL_BANK == 1)

/*
 * DUAL-BANK 1MB : Bank 2 = secteurs 12-19 (16KBx4 + 64KB + 128KBx3).
 * Wear-leveling sur les secteurs 18 et 19 (128KB chacun, fin de Bank 2).
 * Le code s'exécute en Bank 1 -> pas de stall du bus pendant erase/program.
 */
#define WL_PAGE_SIZE        (128U * 1024U)
#define WL_F7_SECTOR0_ADDR  0x080C0000UL
#define WL_F7_SECTOR0_SNB   18U
#define WL_F7_SECTOR1_ADDR  0x080E0000UL
#define WL_F7_SECTOR1_SNB   19U

#else

/*
 * SINGLE-BANK 1MB : secteurs 0-7 (32KBx4 + 128KB + 256KBx3).
 * Wear-leveling sur les secteurs 6 et 7 (256KB chacun, fin de Flash).
 * ATTENTION : le bus est stallé pendant l'erase (jusqu'à ~4s pour 256KB) ;
 * dimensionner l'IWDG en conséquence (hook wl_f7_watchdog_refresh).
 */
#define WL_PAGE_SIZE        (256U * 1024U)
#define WL_F7_SECTOR0_ADDR  0x08080000UL
#define WL_F7_SECTOR0_SNB   6U
#define WL_F7_SECTOR1_ADDR  0x080C0000UL
#define WL_F7_SECTOR1_SNB   7U

#endif

/*
 * Type de programmation Flash HAL — issue #4 :
 *   WL_F7_FLASH_PSIZE = FLASH_TYPEPROGRAM_BYTE       -> byte (8-bit)
 *   WL_F7_FLASH_PSIZE = FLASH_TYPEPROGRAM_HALFWORD   -> half-word (16-bit)
 *   WL_F7_FLASH_PSIZE = FLASH_TYPEPROGRAM_WORD       -> word (32-bit, défaut)
 *   WL_F7_FLASH_PSIZE = FLASH_TYPEPROGRAM_DOUBLEWORD -> double-word (64-bit)
 * Prérequis x32/x64 : VDD 2.7-3.6V (voir RM0410 §3.4).
 */
#ifndef WL_F7_FLASH_PSIZE
#define WL_F7_FLASH_PSIZE  FLASH_TYPEPROGRAM_WORD
#endif

/* Vérifications compile-time (C11) */
#if defined(__STDC_VERSION__) && (__STDC_VERSION__ >= 201112L)
_Static_assert(WL_PAGE_COUNT >= 2U, "wear-leveling: au moins 2 pages requises");
_Static_assert((WL_PAGE_SIZE % 32U) == 0U, "WL_PAGE_SIZE doit etre un multiple de FLASH_RECORD_SIZE");
_Static_assert(WL_F7_SECTOR0_ADDR != WL_F7_SECTOR1_ADDR, "les deux secteurs WL doivent etre distincts");
_Static_assert(WL_F7_SECTOR0_SNB != WL_F7_SECTOR1_SNB, "les deux SNB doivent etre distincts");
#endif

#endif