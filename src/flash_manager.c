#include "flash_manager.h"
#include "wl_config.h"
#include "wl_hal.h"
#include <string.h>

static uint32_t active_page = 0;
static uint32_t next_record_offset = sizeof(PageHeader_t);
static uint32_t g_page_addrs[WL_PAGE_COUNT];

/* ------------------------------------------------------------------ */
static uint32_t GetPageAddr(uint8_t idx)
{
    return g_page_addrs[idx];
}

static uint16_t CalcChecksum(const uint8_t *data, uint16_t len)
{
    uint16_t crc = 0xFFFF;
    for (uint16_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint8_t j = 0; j < 8; j++) {
            crc = (crc & 1) ? ((crc >> 1) ^ 0xA001) : (crc >> 1);
        }
    }
    return crc;
}

static bool IsPageActive(uint32_t page_addr)
{
    PageHeader_t *hdr = (PageHeader_t *)page_addr;
    return (hdr->magic == WL_MAGIC && hdr->status == WL_STATUS_ACTIVE);
}

static bool IsPageFull(uint32_t page_addr)
{
    PageHeader_t *hdr = (PageHeader_t *)page_addr;
    return (hdr->magic == WL_MAGIC && hdr->status == WL_STATUS_FULL);
}

/* ------------------------------------------------------------------ */
FlashStatus_t WL_Init(void)
{
    const wl_hal_t *hal = wl_hal_get();
    
    /* Init page addresses from HAL */
    for (uint8_t i = 0; i < WL_PAGE_COUNT; i++) {
        g_page_addrs[i] = hal->get_sector_addr(i);
    }

    /* Scan all pages to find the active one (highest sequence number) */
    uint32_t max_seq = 0;
    bool found_active = false;
    
    for (uint8_t i = 0; i < WL_PAGE_COUNT; i++) {
        PageHeader_t *hdr = (PageHeader_t *)g_page_addrs[i];
        if (hdr->magic == WL_MAGIC && hdr->status == WL_STATUS_ACTIVE) {
            if (hdr->sequence >= max_seq) {
                max_seq = hdr->sequence;
                active_page = i;
                found_active = true;
            }
        }
    }

    /* No active page found — initialize from scratch */
    if (!found_active) {
        for (uint8_t i = 0; i < WL_PAGE_COUNT; i++) {
            hal->erase(g_page_addrs[i]);
        }
        PageHeader_t hdr = {WL_MAGIC, 0, WL_STATUS_ACTIVE, 1}; /* sequence starts at 1 */
        hal->program(g_page_addrs[0], (uint8_t *)&hdr, sizeof(hdr));
        active_page = 0;
    }

    /* Find next free record slot */
    uint32_t addr = GetPageAddr(active_page) + sizeof(PageHeader_t);
    next_record_offset = sizeof(PageHeader_t);

    while (next_record_offset < FLASH_PAGE_SIZE) {
        FlashRecord_t *rec = (FlashRecord_t *)addr;
        if (rec->len == 0xFFFFU) break;
        next_record_offset += sizeof(FlashRecord_t);
        addr += sizeof(FlashRecord_t);
    }

    return FLASH_OK;
}

FlashStatus_t WL_WriteRecord(uint16_t id, const uint8_t *data, uint16_t len)
{
    const wl_hal_t *hal = wl_hal_get();
    
    if (len > (FLASH_RECORD_SIZE - 8U)) return FLASH_ERROR;

    WL_DeleteRecord(id);

    if ((next_record_offset + sizeof(FlashRecord_t)) > FLASH_PAGE_SIZE) {
        FlashStatus_t st = WL_GarbageCollect();
        if (st != FLASH_OK) return FLASH_FULL;
    }

    FlashRecord_t rec;
    memset(&rec, 0, sizeof(rec));
    rec.id = id;
    rec.len = len;
    memcpy(rec.data, data, len);
    rec.checksum = CalcChecksum(data, len);

    uint32_t addr = GetPageAddr(active_page) + next_record_offset;
    FlashStatus_t st = (hal->program(addr, (uint8_t *)&rec, sizeof(rec)) == 0) ? FLASH_OK : FLASH_ERROR;
    if (st != FLASH_OK) return st;

    next_record_offset += sizeof(FlashRecord_t);
    return FLASH_OK;
}

FlashStatus_t WL_ReadRecord(uint16_t id, uint8_t *out, uint16_t max_len, uint16_t *out_len)
{
    for (uint8_t p = 0; p < WL_PAGE_COUNT; p++) {
        uint32_t page_addr = GetPageAddr(p);
        if (!IsPageActive(page_addr) && !IsPageFull(page_addr)) continue;

        uint32_t offset = sizeof(PageHeader_t);
        while (offset < FLASH_PAGE_SIZE) {
            FlashRecord_t *rec = (FlashRecord_t *)(page_addr + offset);
            if (rec->len == 0xFFFFU) break;

            if (rec->id == id && rec->len != 0) {
                uint16_t crc = CalcChecksum(rec->data, rec->len);
                if (crc != rec->checksum) return FLASH_CRC_ERROR;

                uint16_t copy_len = (rec->len < max_len) ? rec->len : max_len;
                memcpy(out, rec->data, copy_len);
                if (out_len) *out_len = rec->len;
                return FLASH_OK;
            }
            offset += sizeof(FlashRecord_t);
        }
    }
    return FLASH_NOT_FOUND;
}

FlashStatus_t WL_DeleteRecord(uint16_t id)
{
    const wl_hal_t *hal = wl_hal_get();
    uint32_t page_addr = GetPageAddr(active_page);
    uint32_t offset = sizeof(PageHeader_t);

    while (offset < FLASH_PAGE_SIZE) {
        FlashRecord_t *rec = (FlashRecord_t *)(page_addr + offset);
        if (rec->len == 0xFFFFU) break;

        if (rec->id == id && rec->len != 0) {
            uint32_t addr = page_addr + offset + offsetof(FlashRecord_t, len);
            uint16_t zero = 0;
            hal->program(addr, (uint8_t *)&zero, sizeof(zero));
            return FLASH_OK;
        }
        offset += sizeof(FlashRecord_t);
    }
    return FLASH_NOT_FOUND;
}

FlashStatus_t WL_GarbageCollect(void)
{
    const wl_hal_t *hal = wl_hal_get();
    uint32_t src_page = active_page;
    uint8_t dst_idx = 0xFF;
    uint32_t min_seq = 0xFFFFFFFF;

    /* 1. Try to find an EMPTY page first */
    for (uint8_t i = 0; i < WL_PAGE_COUNT; i++) {
        if (i == src_page) continue;
        PageHeader_t *hdr = (PageHeader_t *)g_page_addrs[i];
        if (hdr->magic != WL_MAGIC || hdr->status == WL_STATUS_EMPTY) {
            dst_idx = i;
            break;
        }
    }

    /* 2. Otherwise, pick the page with the lowest sequence (oldest) */
    if (dst_idx == 0xFF) {
        for (uint8_t i = 0; i < WL_PAGE_COUNT; i++) {
            if (i == src_page) continue;
            PageHeader_t *hdr = (PageHeader_t *)g_page_addrs[i];
            if (hdr->sequence < min_seq) {
                min_seq = hdr->sequence;
                dst_idx = i;
            }
        }
    }

    if (dst_idx == 0xFF) return FLASH_ERROR;

    /* 3. Erase destination */
    hal->erase(g_page_addrs[dst_idx]);

    /* 4. Copy valid records from source to destination */
    uint32_t dst_offset = sizeof(PageHeader_t);
    uint32_t src_offset = sizeof(PageHeader_t);

    while (src_offset < FLASH_PAGE_SIZE) {
        FlashRecord_t *rec = (FlashRecord_t *)(g_page_addrs[src_page] + src_offset);
        if (rec->len == 0xFFFFU) break;

        if (rec->len != 0) {
            hal->program(g_page_addrs[dst_idx] + dst_offset, (uint8_t *)rec, sizeof(FlashRecord_t));
            dst_offset += sizeof(FlashRecord_t);
        }
        src_offset += sizeof(FlashRecord_t);
    }

    /* 5. Update headers */
    PageHeader_t *old_hdr = (PageHeader_t *)g_page_addrs[src_page];
    uint32_t new_erase_count = old_hdr->erase_count + 1;
    uint32_t new_seq = old_hdr->sequence + 1;

    PageHeader_t hdr_src = {WL_MAGIC, 0, WL_STATUS_ERASED, 0};
    PageHeader_t hdr_dst = {WL_MAGIC, new_erase_count, WL_STATUS_ACTIVE, new_seq};

    hal->program(g_page_addrs[src_page], (uint8_t *)&hdr_src, sizeof(hdr_src));
    hal->program(g_page_addrs[dst_idx], (uint8_t *)&hdr_dst, sizeof(hdr_dst));

    active_page = dst_idx;
    next_record_offset = dst_offset;

    return FLASH_OK;
}

uint32_t WL_GetEraseCount(uint8_t page_idx)
{
    if (page_idx >= WL_PAGE_COUNT) return 0;
    PageHeader_t *hdr = (PageHeader_t *)g_page_addrs[page_idx];
    return hdr->erase_count;
}