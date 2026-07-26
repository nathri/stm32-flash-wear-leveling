#ifndef WL_HAL_H
#define WL_HAL_H

#include <stdint.h>
#include <stdbool.h>

typedef struct {
    bool     (*init)(void);
    int      (*erase)(uint32_t sector_addr);
    int      (*program)(uint32_t addr, const uint8_t *data, uint32_t len);
    int      (*read)(uint32_t addr, uint8_t *data, uint32_t len);
    uint32_t (*get_sector_size)(uint8_t sector_idx);
    uint32_t (*get_sector_addr)(uint8_t sector_idx);
} wl_hal_t;

const wl_hal_t *wl_hal_get(void);

#endif