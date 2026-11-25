/* EMCU configuration check firmware (pairs with emcu_cfg_top.v; build with build_fw.sh). Linked for 16 KB RAM (stack at the top).
 * APB2 slot n (1..12) register 0 = 0xC0DE0000 | n. Slot 1 register 1 = result bits, 2 = heartbeat,
 * 3 = memtest error count. Result bits: 0 memtest, 1 UART0 loopback, 2 GPIO input, 3 AHB2, 4 APB2 readback,
 * 5 done. LED (GPIO0[0]) blinks at 2 Hz afterwards. FCLK = 27 MHz (SysTick timing). */
#include "gw1ns4c.h"

#define FCLK_HZ  27000000u
#define APB2_SLOT(n) ((volatile uint32_t *)(0x40002000u + 0x100u * ((n) + 3u)))
#define AHB2     ((volatile uint32_t *)0xA0000000u)
#define MT_START 0x20000100u
#define MT_END   0x20003000u   /* above the 8 KB boundary; stack lives in 0x20003000..0x20004000 */

static void delay_ms(uint32_t ms)
{
    SysTick->LOAD = FCLK_HZ / 1000u - 1u;
    SysTick->VAL = 0;
    SysTick->CTRL = SysTick_CTRL_CLKSOURCE_Msk | SysTick_CTRL_ENABLE_Msk;
    while (ms--)
        while (!(SysTick->CTRL & SysTick_CTRL_COUNTFLAG_Msk)) { }
    SysTick->CTRL = 0;
}

static uint32_t memtest(void)
{
    uint32_t err = 0;
    for (int pass = 0; pass < 2; pass++) {
        uint32_t x = pass ? 0xFFFFFFFFu : 0;
        for (volatile uint32_t *p = (uint32_t *)MT_START; p < (uint32_t *)MT_END; p++)
            *p = ((uint32_t)p * 2654435761u) ^ x;
        for (volatile uint32_t *p = (uint32_t *)MT_START; p < (uint32_t *)MT_END; p++)
            if (*p != (((uint32_t)p * 2654435761u) ^ x)) err++;
    }
    return err;
}

static int uart_loopback(void)
{
    UART_InitTypeDef u = {0};
    u.UART_BaudRate = 115200;
    u.UART_Mode.UARTMode_Tx = ENABLE;
    u.UART_Mode.UARTMode_Rx = ENABLE;
    UART_Init(UART0, &u);
    const char msg[] = "\x5a\xa5\x00\xff";
    for (int i = 0; i < 4; i++) {
        UART_SendChar(UART0, msg[i]);
        uint32_t t = 1000000;
        while (!UART_GetRxBufferFull(UART0))
            if (!--t) return 0;
        if (UART_ReceiveChar(UART0) != msg[i]) return 0;
    }
    return 1;
}

static int ahb2_check(void)
{
    static const uint32_t v[4] = {0x11223344u, 0xA5A55A5Au, 0x00000000u, 0xDEADBEEFu};
    for (int i = 0; i < 4; i++) AHB2[i] = v[i];
    for (int i = 0; i < 4; i++) if (AHB2[i] != v[i]) return 0;
    AHB2[3] = 0xCAFE0003u;  /* left for the host to read */
    return AHB2[3] == 0xCAFE0003u;
}

int main(void)
{
    GPIO_InitTypeDef g = {0};
    g.GPIO_Pin = GPIO_Pin_0;
    g.GPIO_Mode = GPIO_Mode_OUT;
    g.GPIO_Int = GPIO_Int_Disable;
    GPIO_Init(GPIO0, &g);

    uint32_t res = 0, err = memtest();
    if (err == 0) res |= 1u << 0;
    if (uart_loopback()) res |= 1u << 1;
    if ((GPIO0->DATA & 0xFFFEu) == (0xA55Au & 0xFFFEu)) res |= 1u << 2;
    if (ahb2_check()) res |= 1u << 3;
    int apb_ok = 1;
    for (uint32_t n = 1; n <= 12; n++) APB2_SLOT(n)[0] = 0xC0DE0000u | n;
    for (uint32_t n = 1; n <= 12; n++) if (APB2_SLOT(n)[0] != (0xC0DE0000u | n)) apb_ok = 0;
    if (apb_ok) res |= 1u << 4;
    res |= 1u << 5;
    APB2_SLOT(1)[1] = res;
    APB2_SLOT(1)[3] = err;

    for (uint32_t beat = 0;; beat++) {
        APB2_SLOT(1)[2] = beat;
        GPIO_ResetBit(GPIO0, GPIO_Pin_0);
        delay_ms(250);
        GPIO_SetBit(GPIO0, GPIO_Pin_0);
        delay_ms(250);
    }
}
