# Portage STM32U385 (issue #6)

Portage du driver wear-leveling sur STM32U385 (NUCLEO-U385RG-Q) pour un
environnement CubeMX + MDK-ARM (Keil) + HAL + printf UART1.

## Caractéristiques U385

| | STM32U385 (ce portage) |
|---|---|
| Cœur | Cortex-M33 (TrustZone, cache) |
| Manuel | RM0487 |
| Implémentation Flash | ST HAL_FLASH (stm32u3xx_hal_flash.c) |
| Organisation Flash | Dual-bank, 1 MB (512 KB par banque) |
| Granularité page | 4 KB (pages physiques) |
| Secteurs WL | Pages 126-127 de Bank 2 (2 × 4 KB) |
| Programmation | 128-bit (16 octets) quadword, alignement 16 |
| ECC | 72-bit (64 data + 8 ECC) par quadword |
| Cache | Cortex-M33 D-cache + I-cache |
| Tension | 1.71–3.6 V (quadword supporté partout) |

## Choix des pages

**Règle** : les pages de wear-leveling DOIVENT être des pages physiques
réelles et de même taille. U385 propose 4 KB pages, donc utiliser deux pages
complètes.

**Sélection** : pages **126 et 127** de Bank 2 (fin de la mémoire Flash).
Avantages :
- Le code applicatif s'exécute en Bank 1 => pas de stall du bus pendant
  erase/program (read-while-write).
- Les deux pages WL sont contiguës en mémoire : adresses prédictibles.

**Adresses** :
- Page 126 : `0x080FE000`
- Page 127 : `0x080FF000`

### Variante 512 KB (ex: STM32U375)

Pour les variantes 512 KB, Bank 2 démarre à `0x0804_0000` :
- Page 126 : `0x0805_E000`
- Page 127 : `0x0805_F000`

Adapter dans `wl_config_u385.h`.

## Configuration CubeMX

1. **STM32CubeMX : New Project**
   - Board: Nucleo-U385RG-Q (ou STM32U385RG via device selector)
   - Toolchain: MDK-ARM (Keil)

2. **RCC (Clock Configuration)**
   - External oscillator: 8 MHz (default sur Nucleo)
   - System Clock: 160 MHz (PLL config automatique)

3. **USART1 (Debug output)**
   - Mode: Asynchronous
   - Baud rate: 115200
   - Data bits: 8
   - Stop bits: 1
   - Parity: None
   - Flow control: Disabled

4. **GPIO (Optional)**
   - LD1 (PA5): GPIO Output (status LED)

5. **Cortex M33**
   - I-Cache: Enable
   - D-Cache: Enable
   - (Le driver WL gère la maintenance D-cache automatiquement)

6. **FLASH (HAL module)**
   - Enable FLASH in Project Manager

7. **TrustZone (STM32U3 only)**
   - Disable TrustZone OR ensure WL pages 126-127 are non-secure (default)
   - (On Nucleo-U385RG-Q, TrustZone is disabled by default)

8. **Project Manager**
   - Target Device: STM32U385RGTx
   - Generate Code

## Intégration Keil

1. Copier dans le projet Keil :
   
   - src/flash_manager.c src/wl_config_u385.c src/main_u385.c

2. Ne PAS ajouter :

   - src/main.c (F401, non utilisé) src/wl_hal_stm32.c (F401, non utilisé) 
   - src/wl_hal_stm32f7.c (F767, non utilisé) src/main_f767.c (F767, non utilisé)

3. Dans `main()` (généré par CubeMX), après `MX_USART1_UART_Init()` :
```c
   printf("Starting wear-leveling demo...\r\n");
   wl_demo_u385();
```

4. Compiler (Build) et vérifier : zéro erreur, zéro warning.

5. Flasher via ST-Link dans l'IDE Keil (Download button).

## Validation Hardware

Sur la console UART1 (115200, 8N1) :
Starting wear-leveling demo...

=== Wear-leveling demo STM32U385 ===
 page size: 4 KB, pages: 2 WL_Init OK [init] erase counts: page0=0 page1=0 read id=1: HELLO U385 (len=10) after update: UPDATED after delete: NOT_FOUND (ok) forcing GC (256 writes)... done in 120 ms record 42 survived GC: YES [after GC] erase counts: page0=0 page1=1 

=== demo complete ===
Succès si :
- ✅ WL_Init OK (pas d'erreur de configuration)
- ✅ Lecture/écriture correctes (chaînes lisibles)
- ✅ Suppression fonctionne
- ✅ GC complète (pas de hang)
- ✅ Erase count augmente après GC
- ✅ Record 42 survive au GC

## Temps d'effacement (ordres de grandeur, VDD 3.3V)

| Taille | Typique | Max |
|---|---|---|
| 4 KB | ~10–20 ms | ~30 ms |

Les pages U385 sont **beaucoup plus rapides** que F767 (128 KB ~2s).

## Limitations connues

- Records fixes de 32 octets (24 octets utiles) ; scan linéaire O(n).
- Avec pages de 4 KB (128 slots), prévoir index RAM pour >100 accès/sec.
- Pas de protection contre accès concurrents (pas de RTOS lock).
- TrustZone : si activé, vérifier que pages 126-127 sont accessibles depuis
  NS context.

## Troubleshooting

| Symptôme | Cause | Solution |
|---|---|---|
| Linker error: `undefined reference to 'dcache_...'` | Typo dans nom de fonction | Vérifier noms identiques en définition et appel |
| WL_Init FAILED | Configuration matérielle incorrecte | Vérifier que pages 126-127 existent (RM0487) |
| Flash erase timeout | Watchdog trop court | Augmenter IWDG timeout > 100 ms |
| Data mismatch après read | Cache stale | Vérifier maintenance D-cache dans wl_config_u385.c |

---

## Ressources

- RM0487: STM32U3xx Reference Manual (Flash architecture)
- STM32CubeMX: Project generation
- STM32CubeProgrammer: Flash algorithm & option bytes
- Nucleo-U385RG-Q User Manual: Pin mapping, ST-Link config