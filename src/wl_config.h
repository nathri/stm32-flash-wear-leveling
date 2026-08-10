#ifndef WL_CONFIG_H
#define WL_CONFIG_H

/*
 * Sélection de la cible : la configuration wear-leveling dépend du MCU.
 * Le define cible est fourni par le build system (Makefile / Keil / CubeMX).
 */
#if defined(STM32F767xx)

#include "wl_config_f767.h"

#else

/*
 * STM32F401 (défaut) : secteurs physiques 2 et 3 (16KB chacun, RM0368
 * Table 5). Tous les secteurs WL DOIVENT avoir la même taille (invariant
 * de capacité du garbage collector).
 *
 * Le code applicatif est confiné aux secteurs 0-1 :
 * le linker doit définir ROM LENGTH = 32K.
 */
#define WL_PAGE_COUNT   2U
#define WL_PAGE_SIZE    (16U * 1024U)

#endif

#endif
