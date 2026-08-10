# Portage STM32F767 (issue #3)

Portage du driver wear-leveling sur STM32F767 pour un environnement
CubeMX + MDK-ARM (Keil) + HAL + printf UART1.

## Différences F401 vs F767

| | STM32F401 (référence) | STM32F767 (ce portage) |
|---|---|---|
| Cœur | Cortex-M4 | Cortex-M7 (D-cache + I-cache) |
| Manuel | RM0368 | RM0410 |
| Implémentation HAL | Register-level (`wl_hal_stm32.c`) | ST HAL_FLASH (`wl_hal_stm32f7.c`) |
| Organisation Flash | Fixe, secteurs 16/64/128KB | Dual-bank OU single-bank (option byte nDBANK) |
| Secteurs WL | 2 et 3 (2x16KB) | 18+19 (2x128KB, dual) ou 6+7 (2x256KB, single) |
| Cache | ART accelerator (flush via FLASH_ACR) | D-cache M7 (SCB_Clean/InvalidateDCache_by_Addr) |
| Erreur erase | PGSERR | ERSERR |

L'architecture modulaire est conservée : `flash_manager.c` est inchangé
(hors ajout de l'appel `hal->init()`), seul le backend `wl_hal_t` change.
Le HAL ST reste injectable/remplaçable.

## Choix des secteurs

**Règle : les pages de wear-leveling doivent être des secteurs physiques
réels et de même taille.** Découper un gros secteur en pages logiques est
interdit : un erase physique détruirait toutes les pages d'un coup.

- **Dual-bank (recommandé)** : secteurs **18 + 19** (128KB chacun, fin de
  Bank 2 sur la map 1MB : `0x080C0000` / `0x080E0000`). Le code s'exécute
  en Bank 1 : l'effacement en Bank 2 **ne stalle pas le bus** — le CPU
  continue à tourner pendant l'erase.
- **Single-bank** : secteurs **6 + 7** (256KB chacun : `0x08080000` /
  `0x080C0000`). 512KB restent disponibles pour le code. Attention : le
  bus est stallé pendant l'erase (jusqu'à ~4s).

Sélection dans `src/wl_config_f767.h` via `WL_F767_DUAL_BANK` (1 par défaut).

### Variante 2MB (ex: F767ZI)

Le F767ZI embarque généralement **2MB** de Flash. Dans ce cas, ajuster
`wl_config_f767.h` :

- Dual-bank 2MB : Bank 2 démarre à `0x08100000`, secteurs 12-23
  (16KBx4 + 64KB + 128KBx7). Derniers secteurs 128KB : **22**
  (`0x081C0000`) et **23** (`0x081E0000`).
- Single-bank 2MB : 12 secteurs (32KBx4 + 128KB + 256KBx7). Derniers
  secteurs 256KB : **10** (`0x08180000`) et **11** (`0x081C0000`).

## Configuration CubeMX

- **System Core > CORTEX_M7** : activer I-Cache et D-Cache (le HAL WL gère
  la maintenance D-cache ; s'ils sont désactivés, les appels SCB sont
  sautés automatiquement).
- **RCC / Clocks** : Flash latency automatique via CubeMX (7 WS à 216MHz
  / 3.3V). ART accelerator + prefetch activables ; aucune manipulation
  manuelle de FLASH_ACR n'est requise pour erase/program sur F7 (RM0410),
  contrairement au F4 où le flush ART était manuel.
- **USART1** : mode asynchrone, 115200 8N1 (printf de la démo).
- **Project Manager** : cocher les modules HAL `FLASH`.
- Le define `STM32F767xx` est posé automatiquement par CubeMX/Keil.

Intégration Keil : ajouter `src/flash_manager.c`, `src/wl_hal_stm32f7.c`,
`src/main_f767.c` au projet, puis appeler `wl_demo_f767()` depuis `main()`
après l'init UART. Ne PAS ajouter `src/main.c` ni `src/wl_hal_stm32.c`
(guardés F401, mais autant les exclure du build).

## Dual-bank vs single-bank

- Lecture/écriture du mode : bit **nDBANK** dans FLASH_OPTCR, modifiable
  via STM32CubeProgrammer (Option Bytes). `nDBANK=0` => dual-bank.
- `WL_Init()` vérifie la cohérence entre `WL_F767_DUAL_BANK` et l'option
  byte réel et retourne `FLASH_ERROR` en cas de mismatch (les adresses de
  secteurs seraient sinon toutes fausses).
- **Avantages dual-bank** : erase/program en Bank 2 sans stall du CPU
  (code en Bank 1) ; le watchdog peut être rafraîchi pendant l'erase.
- **Risques dual-bank** :
  - Une IT ou un DMA qui LIT la Bank 2 pendant un erase reçoit des
    données invalides / stalle : ne placer dans la Bank 2 que la zone WL.
  - Changer nDBANK **remappe tous les secteurs** : données WL perdues,
    adresses à reconfigurer, code à re-flasher.
  - En dual-bank la largeur de lecture passe de 256 à 128 bits (impact
    marginal avec les caches M7 actifs).

## Temps d'effacement (ordres de grandeur, VDD 3.3V, x32)

| Taille secteur | Typique | Max |
|---|---|---|
| 16KB | ~0.25s | ~0.6s |
| 64KB | ~1s | ~1.2s |
| 128KB | ~2s | ~2.6s |
| 256KB | ~2-3s | ~4s |

Valeurs indicatives : mesurer sur cible (la démo affiche la durée du GC)
et dimensionner le timeout IWDG > 2x le max du secteur choisi.

**Watchdog** : `HAL_FLASHEx_Erase` est bloquant. Le hook faible
`wl_f7_watchdog_refresh()` est appelé juste avant chaque erase — le
redéfinir avec `HAL_IWDG_Refresh(&hiwdg)`. En single-bank c'est la seule
protection possible (bus stallé) ; en dual-bank on peut aussi rafraîchir
pendant l'erase depuis la Bank 1.

## Tension d'alimentation et PSIZE

Le HAL utilise `FLASH_VOLTAGE_RANGE_3` (VDD 2.7-3.6V, parallélisme x32) —
le cas nominal à 3.3V. **Si VDD < 2.7V**, x32 est interdit : remplacer par
`FLASH_VOLTAGE_RANGE_1` (programmation par octet, nettement plus lente)
dans `wl_hal_stm32f7.c`, et adapter les temps d'erase (plus longs).

## Caches Cortex-M7

- Avant erase/program : `SCB_CleanDCache_by_Addr()` sur la plage ciblée.
- Après erase/program : `SCB_InvalidateDCache_by_Addr()` (sinon relecture
  de données périmées depuis le cache).
- `SCB_InvalidateICache()` : nécessaire uniquement si du CODE exécutable
  est modifié en Flash — pas le cas ici (zone WL = données pures), donc
  non appelé.
- Les deux maintenances sont sautées automatiquement si le D-cache est
  désactivé (`SCB->CCR` testé à l'exécution).

## Limitations connues

- Records fixes de 32 octets (24 octets utiles) ; scan linéaire O(n) de la
  page active à chaque accès — avec des pages de 128/256KB (4095/8191
  slots), prévoir un index RAM si les accès deviennent fréquents.
- Un GC copie jusqu'à une page entière : prévoir la latence correspondante
  dans les tâches temps-réel (surtout en single-bank).
- Adresses par défaut = map 1MB fournie dans l'issue ; adapter pour 2MB
  (voir § Variante 2MB).
- Pas de protection contre les accès concurrents (pas de RTOS lock) —
  appeler l'API depuis un seul contexte.
