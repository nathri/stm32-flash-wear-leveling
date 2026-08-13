#ifndef WL_CONFIG_H
#define WL_CONFIG_H

/*
 * Selection de la cible : la configuration wear-leveling depend du MCU.
 * Le define cible est fourni par le build system (Makefile / Keil / CubeMX).
 */
#if defined(STM32F767xx)

#include "wl_config_f767.h"

#elif defined(STM32U385xx)

#include "wl_config_u385.h"

#else

/*
 * STM32F401 (defaut) : secteurs physiques 2 et 3 (16KB chacun, RM0368
 * Table 5). Tous les secteurs WL DOIVENT avoir la meme taille (invariant
 * de capacite du garbage collector).
 *
 * Le code applicatif est confine aux secteurs 0-1 :
 * le linker doit definir ROM LENGTH = 32K.
 */
#define WL_PAGE_COUNT   2U
#define WL_PAGE_SIZE    (16U * 1024U)

/*
 * Taille de programmation Flash (PSIZE) — issue #4 :
 *   WL_STM32_PSIZE = FLASH_CR_PSIZE_X8   -> byte (8-bit)
 *   WL_STM32_PSIZE = FLASH_CR_PSIZE_X16  -> half-word (16-bit)
 *   WL_STM32_PSIZE = FLASH_CR_PSIZE_X32  -> word (32-bit, defaut)
 *   WL_STM32_PSIZE = FLASH_CR_PSIZE_X64  -> double-word (64-bit)
 * Prerequis x32/x64 : VDD 2.7-3.6V (voir RM0368 §3.4).
 */
#ifndef WL_STM32_PSIZE
#define WL_STM32_PSIZE  FLASH_CR_PSIZE_X32
#endif

#endif

#endif