#include "flash_manager.h"
#include <string.h>

/* ------------------------------------------------------------------ */
/* Manual register definitions — no CMSIS dependency                    */
/* ------------------------------------------------------------------ */
#define FLASH_BASE_ADDR     0x08000000UL
#define FLASH_R_BASE        0x40023C00UL

#define FLASH_ACR           (*(volatile uint32_t *)(FLASH_R_BASE + 0x00))
#define FLASH_KEYR          (*(volatile uint32_t *)(FLASH_R_BASE + 0x04))
#define FLASH_SR            (*(volatile uint32_t *)(FLASH_R_BASE + 0x0C))
#define FLASH_CR            (*(volatile uint32_t *)(FLASH_R_BASE + 0x10))
#define FLASH_AR            (*(volatile uint32_t *)(FLASH_R_BASE + 0x14))

#define FLASH_SR_BSY        (1UL << 16)
#define FLASH_SR_PGSERR     (1UL << 7)
#define FLASH_SR_PGPERR     (1UL << 6)
#define FLASH_SR_PGAERR     (1UL << 5)
#define FLASH_CR_LOCK       (1UL << 31)
#define FLASH_CR_PER        (1UL << 1)
#define FLASH_CR_PG         (1UL << 0)
#define FLASH_CR_STRT       (1UL << 16)

#define FLASH_TOTAL_SIZE    (256U * 1024U)
#define WL_BASE_ADDR        (FLASH_BASE_ADDR + FLASH_TOTAL_SIZE - (FLASH_PAGES_FOR_WL * FLASH_PAGE_SIZE))

#define PAGE0_ADDR          WL_BASE_ADDR
#define PAGE1_ADDR          (WL_BASE_ADDR + FLASH_PAGE_SIZE)

static uint32_t active_page = 0;
static uint32_t next_record_offset = sizeof(PageHeader_t);

/* ------------------------------------------------------------------ */
static uint32_t GetPageAddr(uint8_t idx)
{
    return (idx == 0) ? PAGE0_ADDR : PAGE1_ADDR;
}

static FlashStatus_t Flash_ErasePage(uint32_t page_addr)
{
    (void)page_addr; /* unused for F401 — we erase by sector, not arbitrary addr */

    /* Unlock */
    if (FLASH_CR & FLASH_CR_LOCK) {
        FLASH_KEYR = 0x45670123;
        FLASH_KEYR = 0xCDEF89AB;
    }

    while (FLASH_SR & FLASH_SR_BSY);

    FLASH_CR |= FLASH_CR_PER;
    FLASH_AR  = page_addr;
    FLASH_CR |= FLASH_CR_STRT;

    while (FLASH_SR & FLASH_SR_BSY);

    if (FLASH_SR & (FLASH_SR_PGSERR | FLASH_SR_PGPERR | FLASH_SR_PGAERR)) {
        FLASH_SR |= (FLASH_SR_PGSERR | FLASH_SR_PGPERR | FLASH_SR_PGAERR);
        FLASH_CR &= ~FLASH_CR_PER;
        FLASH_CR |= FLASH_CR_LOCK;
        return FLASH_ERROR;
    }

    FLASH_CR &= ~FLASH_CR_PER;
    FLASH_CR |= FLASH_CR_LOCK;
    return FLASH_OK;
}

static FlashStatus_t Flash_Program(uint32_t addr, const uint8_t *data, uint16_t len)
{
    if (addr & 0x3U) return FLASH_ERROR;

    if (FLASH_CR & FLASH_CR_LOCK) {
        FLASH_KEYR = 0x45670123;
        FLASH_KEYR = 0xCDEF89AB;
    }

    FLASH_CR |= FLASH_CR_PG;

    for (uint16_t i = 0; i < len; i += 4) {
        while (FLASH_SR & FLASH_SR_BSY);

        uint32_t word = 0xFFFFFFFFUL;
        uint16_t copy = (len - i < 4) ? (len - i) : 4;
        memcpy(&word, &data[i], copy);

        *(volatile uint32_t *)(addr + i) = word;

        while (FLASH_SR & FLASH_SR_BSY);
    }

    FLASH_CR &= ~FLASH_CR_PG;
    FLASH_CR |= FLASH_CR_LOCK;
    return FLASH_OK;
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
    bool p0_active = IsPageActive(PAGE0_ADDR);
    bool p1_active = IsPageActive(PAGE1_ADDR);
    bool p0_full   = IsPageFull(PAGE0_ADDR);

    if (p0_active && !p1_active) {
        active_page = 0;
    } else if (p1_active && !p0_active) {
        active_page = 1;
    } else if (!p0_active && !p1_active) {
        Flash_ErasePage(PAGE0_ADDR);
        PageHeader_t hdr = {WL_MAGIC, 0, WL_STATUS_ACTIVE, 0};
        Flash_Program(PAGE0_ADDR, (uint8_t *)&hdr, sizeof(hdr));
        active_page = 0;
    } else if (p0_full && !p1_active) {
        Flash_ErasePage(PAGE1_ADDR);
        PageHeader_t hdr = {WL_MAGIC, 0, WL_STATUS_ACTIVE, 0};
        Flash_Program(PAGE1_ADDR, (uint8_t *)&hdr, sizeof(hdr));
        active_page = 1;
    } else {
        Flash_ErasePage(PAGE0_ADDR);
        Flash_ErasePage(PAGE1_ADDR);
        PageHeader_t hdr = {WL_MAGIC, 0, WL_STATUS_ACTIVE, 0};
        Flash_Program(PAGE0_ADDR, (uint8_t *)&hdr, sizeof(hdr));
        active_page = 0;
    }

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
    FlashStatus_t st = Flash_Program(addr, (uint8_t *)&rec, sizeof(rec));
    if (st != FLASH_OK) return st;

    next_record_offset += sizeof(FlashRecord_t);
    return FLASH_OK;
}

FlashStatus_t WL_ReadRecord(uint16_t id, uint8_t *out, uint16_t max_len, uint16_t *out_len)
{
    for (uint8_t p = 0; p < 2; p++) {
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
    uint32_t page_addr = GetPageAddr(active_page);
    uint32_t offset = sizeof(PageHeader_t);

    while (offset < FLASH_PAGE_SIZE) {
        FlashRecord_t *rec = (FlashRecord_t *)(page_addr + offset);
        if (rec->len == 0xFFFFU) break;

        if (rec->id == id && rec->len != 0) {
            uint32_t addr = page_addr + offset + offsetof(FlashRecord_t, len);
            uint16_t zero = 0;
            Flash_Program(addr, (uint8_t *)&zero, sizeof(zero));
            return FLASH_OK;
        }
        offset += sizeof(FlashRecord_t);
    }
    return FLASH_NOT_FOUND;
}

FlashStatus_t WL_GarbageCollect(void)
{
    uint32_t src_page = active_page;
    uint32_t dst_page = (active_page == 0) ? 1 : 0;

    Flash_ErasePage(GetPageAddr(dst_page));

    uint32_t dst_offset = sizeof(PageHeader_t);
    uint32_t src_offset = sizeof(PageHeader_t);

    while (src_offset < FLASH_PAGE_SIZE) {
        FlashRecord_t *rec = (FlashRecord_t *)(GetPageAddr(src_page) + src_offset);
        if (rec->len == 0xFFFFU) break;

        if (rec->len != 0) {
            Flash_Program(GetPageAddr(dst_page) + dst_offset, (uint8_t *)rec, sizeof(FlashRecord_t));
            dst_offset += sizeof(FlashRecord_t);
        }
        src_offset += sizeof(FlashRecord_t);
    }

    PageHeader_t hdr_src = {WL_MAGIC, 0, WL_STATUS_ERASED, 0};
    PageHeader_t hdr_dst = {WL_MAGIC, 0, WL_STATUS_ACTIVE, 0};

    PageHeader_t *old_hdr = (PageHeader_t *)GetPageAddr(src_page);
    hdr_dst.erase_count = old_hdr->erase_count + 1;

    Flash_Program(GetPageAddr(src_page), (uint8_t *)&hdr_src, sizeof(hdr_src));
    Flash_Program(GetPageAddr(dst_page), (uint8_t *)&hdr_dst, sizeof(hdr_dst));

    active_page = dst_page;
    next_record_offset = dst_offset;

    return FLASH_OK;
}

uint32_t WL_GetEraseCount(uint8_t page_idx)
{
    if (page_idx > 1) return 0;
    PageHeader_t *hdr = (PageHeader_t *)GetPageAddr(page_idx);
    return hdr->erase_count;
}