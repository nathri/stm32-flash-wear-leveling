#ifndef FLASH_MANAGER_H
#define FLASH_MANAGER_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#define FLASH_RECORD_SIZE       32U
#define FLASH_PAGE_SIZE         16384U  /* F401 has 1KB pages. Adjust if yours differs */
#define FLASH_PAGES_FOR_WL      2U      /* last 2 pages reserved for wear-leveling */

/* Record header: 8 bytes + 24 bytes data = 32 bytes total */
typedef struct {
    uint16_t id;
    uint16_t len;           /* actual data length, 0 = deleted/empty */
    uint16_t checksum;
    uint16_t reserved;
    uint8_t  data[FLASH_RECORD_SIZE - 8];
} __attribute__((packed)) FlashRecord_t;

typedef enum {
    FLASH_OK = 0,
    FLASH_ERROR,
    FLASH_FULL,
    FLASH_NOT_FOUND,
    FLASH_CRC_ERROR,
    FLASH_INVALID
} FlashStatus_t;

/* Page header at the start of each wear-leveling page */
typedef struct {
    uint32_t magic;         /* 0x574C424D = "WLBM" */
    uint32_t erase_count;
    uint32_t status;        /* 0xAABBCCDD = ACTIVE, 0x11223344 = FULL, 0x00000000 = ERASED */
    uint32_t reserved;
} __attribute__((packed)) PageHeader_t;

#define WL_MAGIC            0x574C424DUL
#define WL_STATUS_ACTIVE    0xAABBCCDDUL
#define WL_STATUS_FULL      0x11223344UL
#define WL_STATUS_ERASED    0x00000000UL

FlashStatus_t WL_Init(void);
FlashStatus_t WL_WriteRecord(uint16_t id, const uint8_t *data, uint16_t len);
FlashStatus_t WL_ReadRecord(uint16_t id, uint8_t *out, uint16_t max_len, uint16_t *out_len);
FlashStatus_t WL_DeleteRecord(uint16_t id);
FlashStatus_t WL_GarbageCollect(void);
uint32_t WL_GetEraseCount(uint8_t page_idx);

#endif