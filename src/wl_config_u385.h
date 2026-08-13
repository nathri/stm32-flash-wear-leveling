#ifndef WL_CONFIG_U385_H
#define WL_CONFIG_U385_H

/*
 * Configuration wear-leveling STM32U385 / NUCLEO-U385RG-Q (RM0487)
 *
 * Flash organization (1 MB dual-bank):
 *   Bank 1: 128 pages x 4 KB = 512 KB @ 0x0800_0000
 *   Bank 2: 128 pages x 4 KB = 512 KB @ 0x0808_0000
 *
 * Wear-leveling uses the last 2 pages of Bank 2 so the application
 * can execute from Bank 1 during erase/program (read-while-write).
 *
 *   WL Page 0  -> Physical Page 126 of Bank 2 @ 0x080F_E000
 *   WL Page 1  -> Physical Page 127 of Bank 2 @ 0x080F_F000
 *
 * For 512 KB variants (STM32U375), Bank 2 base is 0x0804_0000.
 * Adjust WL_U3_PAGE{0,1}_ADDR accordingly.
 */

#define WL_PAGE_COUNT       2U
#define WL_PAGE_SIZE        (4U * 1024U)   /* 4 KB physical page */

#define WL_U3_BANK          FLASH_BANK_2
#define WL_U3_PAGE0         126U
#define WL_U3_PAGE1         127U
#define WL_U3_PAGE0_ADDR    0x080FE000UL
#define WL_U3_PAGE1_ADDR    0x080FF000UL

/*
 * Programming granularity — issue #6 / U3 specific:
 *   STM32U3 main Flash programs in 128-bit (16-byte) quad-words.
 *   Address must be 16-byte aligned.
 *
 *   FLASH_TYPEPROGRAM_QUADWORD  -> 128-bit (16 bytes), default
 *
 * OTP and high-cycle areas support 16-bit (half-word) programming,
 * but wear-leveling operates on main Flash only.
 */
#ifndef WL_U3_FLASH_PSIZE
#define WL_U3_FLASH_PSIZE  FLASH_TYPEPROGRAM_QUADWORD
#endif

/* Compile-time checks (C11) */
#if defined(__STDC_VERSION__) && (__STDC_VERSION__ >= 201112L)
_Static_assert(WL_PAGE_COUNT >= 2U,
    "wear-leveling: au moins 2 pages requises");
_Static_assert((WL_PAGE_SIZE % 16U) == 0U,
    "WL_PAGE_SIZE doit etre un multiple de 16 (granularite de programmation 128-bit)");
_Static_assert(WL_U3_PAGE0_ADDR != WL_U3_PAGE1_ADDR,
    "les deux pages WL doivent etre distinctes");
_Static_assert(WL_U3_PAGE0 != WL_U3_PAGE1,
    "les deux numeros de page WL doivent etre distincts");
#endif

#endif