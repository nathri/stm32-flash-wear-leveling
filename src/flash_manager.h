#ifndef FLASH_MANAGER_H
#define FLASH_MANAGER_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "wl_config.h"

#define FLASH_RECORD_SIZE       32U

/* Record : 8 octets d'en-tête + 24 octets de données = 32 octets */
typedef struct {
    uint16_t id;
    uint16_t len;           /* longueur réelle ; 0 = supprimé, 0xFFFF = slot vierge */
    uint16_t checksum;
    uint16_t reserved;
    uint8_t  data[FLASH_RECORD_SIZE - 8U];
} __attribute__((packed)) FlashRecord_t;

typedef enum {
    FLASH_OK = 0,
    FLASH_ERROR,
    FLASH_FULL,
    FLASH_NOT_FOUND,
    FLASH_CRC_ERROR,
    FLASH_INVALID
} FlashStatus_t;

/* En-tête de page (16 octets, en début de chaque secteur WL) */
typedef struct {
    uint32_t magic;         /* 0x574C424D = "WLBM" */
    uint32_t erase_count;
    uint32_t status;
    uint32_t sequence;
} __attribute__((packed)) PageHeader_t;

#define WL_MAGIC            0x574C424DUL

/*
 * Valeurs de statut choisies pour que chaque transition légale ne fasse
 * QUE passer des bits de 1 vers 0 => programmable in-place sans erase :
 *
 *   EMPTY (0xFFFFFFFF) -> COPYING (0xFFFFAAAA) -> ACTIVE (0x5555AAAA) -> INVALID (0x00000000)
 */
#define WL_STATUS_EMPTY     0xFFFFFFFFUL
#define WL_STATUS_COPYING   0xFFFFAAAAUL
#define WL_STATUS_ACTIVE    0x5555AAAAUL
#define WL_STATUS_INVALID   0x00000000UL

FlashStatus_t WL_Init(void);
FlashStatus_t WL_WriteRecord(uint16_t id, const uint8_t *data, uint16_t len);
FlashStatus_t WL_ReadRecord(uint16_t id, uint8_t *out, uint16_t max_len, uint16_t *out_len);
FlashStatus_t WL_DeleteRecord(uint16_t id);
FlashStatus_t WL_GarbageCollect(void);
uint32_t WL_GetEraseCount(uint8_t page_idx);

#endif
