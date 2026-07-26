#include "flash_manager.h"

int main(void)
{
    WL_Init();

    uint8_t data1[] = "Hello Flash";
    uint8_t data2[] = "Wear Leveling";
    uint8_t readbuf[32];
    uint16_t readlen;

    WL_WriteRecord(1, data1, sizeof(data1));
    WL_WriteRecord(2, data2, sizeof(data2));

    WL_ReadRecord(1, readbuf, sizeof(readbuf), &readlen);

    /* Loop forever — set a breakpoint here and inspect readbuf */
    while (1) {}
}