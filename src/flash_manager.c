#include "flash_manager.h"
#include "wl_config.h"
#include "wl_hal.h"
#include <string.h>

static uint8_t  active_page = 0U;
static uint32_t next_record_offset = sizeof(PageHeader_t);
static uint32_t g_page_addrs[WL_PAGE_COUNT];

/* ------------------------------------------------------------------ */
static uint16_t CalcChecksum(const uint8_t *data, uint16_t len)
{
    uint16_t crc = 0xFFFFU;
    for (uint16_t i = 0U; i < len; i++) {
        crc ^= data[i];
        for (uint8_t j = 0U; j < 8U; j++) {
            crc = ((crc & 1U) != 0U) ? (uint16_t)((crc >> 1) ^ 0xA001U)
                                     : (uint16_t)(crc >> 1);
        }
    }
    return crc;
}

static uint32_t PageStatus(uint8_t idx)
{
    const volatile PageHeader_t *hdr = (const volatile PageHeader_t *)g_page_addrs[idx];
    if (hdr->magic != WL_MAGIC) {
        return WL_STATUS_EMPTY;    /* effacée ou jamais formatée */
    }
    return hdr->status;
}

static uint32_t PageSequence(uint8_t idx)
{
    return ((const volatile PageHeader_t *)g_page_addrs[idx])->sequence;
}

static uint32_t PageEraseCount(uint8_t idx)
{
    return ((const volatile PageHeader_t *)g_page_addrs[idx])->erase_count;
}

static int ProgramStatus(uint8_t idx, uint32_t status)
{
    const wl_hal_t *hal = wl_hal_get();
    const uint32_t addr = g_page_addrs[idx] + offsetof(PageHeader_t, status); /* offset 8, aligné 4 */
    return hal->program(addr, (const uint8_t *)&status, sizeof(status));
}

static bool RecordSlotErased(const volatile FlashRecord_t *rec)
{
    return (rec->len == 0xFFFFU);
}

static bool RecordValid(const volatile FlashRecord_t *rec)
{
    return (rec->len != 0U) && (rec->len != 0xFFFFU) &&
           (rec->len <= (uint16_t)sizeof(rec->data));
}

/* C6 : adresse de la DERNIÈRE occurrence valide de l'id dans la page
 * active (append-only => la plus récente). 0 si absente. */
static uint32_t FindLastRecordAddr(uint16_t id)
{
    const uint32_t page_addr = g_page_addrs[active_page];
    uint32_t offset = sizeof(PageHeader_t);
    uint32_t found = 0U;

    while ((offset + sizeof(FlashRecord_t)) <= WL_PAGE_SIZE) {
        const volatile FlashRecord_t *rec =
            (const volatile FlashRecord_t *)(page_addr + offset);
        if (RecordSlotErased(rec)) break;
        if (RecordValid(rec) && (rec->id == id)) {
            found = page_addr + offset;
        }
        offset += sizeof(FlashRecord_t);
    }
    return found;
}

static void FindNextFreeOffset(void)
{
    const uint32_t page_addr = g_page_addrs[active_page];
    uint32_t offset = sizeof(PageHeader_t);

    while ((offset + sizeof(FlashRecord_t)) <= WL_PAGE_SIZE) {
        const volatile FlashRecord_t *rec =
            (const volatile FlashRecord_t *)(page_addr + offset);
        if (RecordSlotErased(rec)) break;
        offset += sizeof(FlashRecord_t);
    }
    next_record_offset = offset;
}

static FlashStatus_t FormatAll(void)
{
    const wl_hal_t *hal = wl_hal_get();

    for (uint8_t i = 0U; i < WL_PAGE_COUNT; i++) {
        if (hal->erase(g_page_addrs[i]) != 0) return FLASH_ERROR;
    }

    const PageHeader_t hdr = { WL_MAGIC, 1U, WL_STATUS_ACTIVE, 1U };
    if (hal->program(g_page_addrs[0], (const uint8_t *)&hdr, sizeof(hdr)) != 0) {
        return FLASH_ERROR;
    }
    active_page = 0U;
    next_record_offset = sizeof(PageHeader_t);
    return FLASH_OK;
}

/* ------------------------------------------------------------------ */
FlashStatus_t WL_Init(void)
{
    const wl_hal_t *hal = wl_hal_get();

    /* Contrôles matériels du HAL (ex: cohérence dual/single-bank sur F7) */
    if ((hal->init != NULL) && !hal->init()) {
        return FLASH_ERROR;
    }

    for (uint8_t i = 0U; i < WL_PAGE_COUNT; i++) {
        g_page_addrs[i] = hal->get_sector_addr(i);
        if (g_page_addrs[i] == 0UL) return FLASH_ERROR;
    }

    /* C3 recovery 1 : une page COPYING = GC interrompu en pleine copie.
     * Sa source est encore ACTIVE ; on abandonne simplement la copie. */
    for (uint8_t i = 0U; i < WL_PAGE_COUNT; i++) {
        if (PageStatus(i) == WL_STATUS_COPYING) {
            (void)ProgramStatus(i, WL_STATUS_INVALID);
        }
    }

    /* C3 recovery 2 : si deux pages ACTIVE (GC interrompu entre la
     * promotion de dst et l'invalidation de src), la plus haute
     * sequence gagne, l'autre est invalidée. */
    bool found = false;
    uint32_t max_seq = 0U;
    for (uint8_t i = 0U; i < WL_PAGE_COUNT; i++) {
        if (PageStatus(i) == WL_STATUS_ACTIVE) {
            const uint32_t seq = PageSequence(i);
            if (!found || (seq > max_seq)) {
                max_seq = seq;
                active_page = i;
                found = true;
            }
        }
    }

    if (found) {
        for (uint8_t i = 0U; i < WL_PAGE_COUNT; i++) {
            if ((i != active_page) && (PageStatus(i) == WL_STATUS_ACTIVE)) {
                if (ProgramStatus(i, WL_STATUS_INVALID) != 0) return FLASH_ERROR;
            }
        }
        FindNextFreeOffset();
        return FLASH_OK;
    }

    /* Aucune page active : premier démarrage -> format initial */
    return FormatAll();
}

FlashStatus_t WL_WriteRecord(uint16_t id, const uint8_t *data, uint16_t len)
{
    const wl_hal_t *hal = wl_hal_get();

    if ((data == NULL) || (len == 0U) || (len > (FLASH_RECORD_SIZE - 8U))) {
        return FLASH_INVALID;
    }

    if ((next_record_offset + sizeof(FlashRecord_t)) > WL_PAGE_SIZE) {
        const FlashStatus_t st = WL_GarbageCollect();
        if (st != FLASH_OK) return st;
        /* C7 : le GC peut rendre une page encore pleine (records tous vivants) */
        if ((next_record_offset + sizeof(FlashRecord_t)) > WL_PAGE_SIZE) {
            return FLASH_FULL;
        }
    }

    /* C4 : repérer l'ancienne version MAINTENANT, ne l'invalider
     * qu'APRÈS l'écriture réussie de la nouvelle. */
    const uint32_t old_addr = FindLastRecordAddr(id);

    FlashRecord_t rec;
    memset(&rec, 0xFF, sizeof(rec));   /* padding = état effacé */
    rec.id = id;
    rec.len = len;
    memcpy(rec.data, data, len);
    rec.checksum = CalcChecksum(data, len);

    const uint32_t addr = g_page_addrs[active_page] + next_record_offset;
    if (hal->program(addr, (const uint8_t *)&rec, sizeof(rec)) != 0) {
        return FLASH_ERROR;
    }
    next_record_offset += sizeof(FlashRecord_t);

    /* Invalidation de l'ancienne version : premier mot (id+len) -> 0.
     * Un échec ici n'est pas fatal : la lecture "dernier gagne" (C6)
     * fait déjà prévaloir le nouveau record. */
    if (old_addr != 0U) {
        const uint32_t zero = 0U;
        (void)hal->program(old_addr, (const uint8_t *)&zero, sizeof(zero));
    }
    return FLASH_OK;
}

FlashStatus_t WL_ReadRecord(uint16_t id, uint8_t *out, uint16_t max_len, uint16_t *out_len)
{
    if (out == NULL) return FLASH_INVALID;

    const uint32_t addr = FindLastRecordAddr(id);   /* C6 : dernier record gagne */
    if (addr == 0U) return FLASH_NOT_FOUND;

    const volatile FlashRecord_t *rec = (const volatile FlashRecord_t *)addr;
    const uint16_t len = rec->len;                  /* borné à 24 par RecordValid */

    if (CalcChecksum((const uint8_t *)rec->data, len) != rec->checksum) {
        return FLASH_CRC_ERROR;
    }

    const uint16_t copy_len = (len < max_len) ? len : max_len;
    memcpy(out, (const void *)rec->data, copy_len);
    if (out_len != NULL) *out_len = len;
    return FLASH_OK;
}

FlashStatus_t WL_DeleteRecord(uint16_t id)
{
    const wl_hal_t *hal = wl_hal_get();
    bool deleted = false;
    uint32_t addr;

    /* C5 : invalidation par programmation du premier MOT 32 bits du record
     * (début de record = multiple de 32 => aligné 4). Boucle pour purger
     * d'éventuels doublons hérités d'une invalidation échouée. */
    while ((addr = FindLastRecordAddr(id)) != 0U) {
        const uint32_t zero = 0U;
        if (hal->program(addr, (const uint8_t *)&zero, sizeof(zero)) != 0) {
            return FLASH_ERROR;
        }
        deleted = true;
    }
    return deleted ? FLASH_OK : FLASH_NOT_FOUND;
}

FlashStatus_t WL_GarbageCollect(void)
{
    const wl_hal_t *hal = wl_hal_get();
    const uint8_t src = active_page;
    uint8_t dst = 0xFFU;
    uint32_t min_erase = 0xFFFFFFFFU;

    /* Destination : page EMPTY en priorité, sinon la page INVALID (ou
     * COPYING abandonnée) au plus faible erase_count. Jamais la source. */
    for (uint8_t i = 0U; i < WL_PAGE_COUNT; i++) {
        if (i == src) continue;
        const uint32_t st = PageStatus(i);
        if (st == WL_STATUS_EMPTY) { dst = i; break; }
        if ((st == WL_STATUS_INVALID) || (st == WL_STATUS_COPYING)) {
            const uint32_t ec = PageEraseCount(i);
            if ((dst == 0xFFU) || (ec < min_erase)) { min_erase = ec; dst = i; }
        }
    }
    if (dst == 0xFFU) return FLASH_ERROR;

    /* Compteur d'usure : celui de la page destination elle-même,
     * lu AVANT son effacement. */
    uint32_t new_ec = 1U;
    if (PageStatus(dst) != WL_STATUS_EMPTY) {
        new_ec = PageEraseCount(dst) + 1U;
    }
    const uint32_t new_seq = PageSequence(src) + 1U;

    if (hal->erase(g_page_addrs[dst]) != 0) return FLASH_ERROR;

    /* C3 étape 1 : header en COPYING. Coupure entre ici et la promotion
     * ACTIVE => WL_Init jette cette page, la source reste valide. */
    const PageHeader_t hdr = { WL_MAGIC, new_ec, WL_STATUS_COPYING, new_seq };
    if (hal->program(g_page_addrs[dst], (const uint8_t *)&hdr, sizeof(hdr)) != 0) {
        return FLASH_ERROR;
    }

    /* C3 étape 2 : copie des records vivants */
    uint32_t dst_offset = sizeof(PageHeader_t);
    uint32_t src_offset = sizeof(PageHeader_t);

    while ((src_offset + sizeof(FlashRecord_t)) <= WL_PAGE_SIZE) {
        const volatile FlashRecord_t *rec =
            (const volatile FlashRecord_t *)(g_page_addrs[src] + src_offset);
        if (RecordSlotErased(rec)) break;

        if (RecordValid(rec)) {
            if (hal->program(g_page_addrs[dst] + dst_offset,
                             (const uint8_t *)(g_page_addrs[src] + src_offset),
                             sizeof(FlashRecord_t)) != 0) {
                return FLASH_ERROR;
            }
            dst_offset += sizeof(FlashRecord_t);
        }
        src_offset += sizeof(FlashRecord_t);
    }

    /* C3 étape 3 : promotion ACTIVE de dst AVANT invalidation de src.
     * Il n'existe aucun instant sans page ACTIVE valide. */
    if (ProgramStatus(dst, WL_STATUS_ACTIVE) != 0) return FLASH_ERROR;

    /* C3 étape 4 : invalidation de la source. En cas de coupure avant la
     * fin, WL_Init garde la sequence la plus haute (dst) et invalide src. */
    (void)ProgramStatus(src, WL_STATUS_INVALID);

    active_page = dst;
    next_record_offset = dst_offset;
    return FLASH_OK;
}

uint32_t WL_GetEraseCount(uint8_t page_idx)
{
    if (page_idx >= WL_PAGE_COUNT) return 0U;
    const volatile PageHeader_t *hdr =
        (const volatile PageHeader_t *)g_page_addrs[page_idx];
    return (hdr->magic == WL_MAGIC) ? hdr->erase_count : 0U;
}
