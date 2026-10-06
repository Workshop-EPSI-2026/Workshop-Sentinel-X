// Sentinel-X — brochage ESP32-S3 N16R8 (source unique, voir docs/cablage.md)
// Interdites : 0, 3, 45, 46 (démarrage) · 19, 20 (USB) · 35, 36, 37 (PSRAM) · 43, 44 (série)
#pragma once

#define PIN_DHT11        4    // DATA, 3V3
#define PIN_PIR          5    // OUT 3,3 V, PIR alimenté en 5 V
#define PIN_MQ2_AO       1    // ADC1, via pont 10k/10k (max 2,5 V)
#define PIN_MQ2_DO       6    // via pont 10k/15k (~3 V)
#define PIN_TAMPER_TOUCH 7    // T7, feuille de cuivre dans le couvercle
// Écran LCD 1602 en mode 4 bits (RW relié à GND : l'écran ne renvoie jamais de 5 V)
#define PIN_LCD_RS       8
#define PIN_LCD_E        9
#define PIN_LCD_D4       13
#define PIN_LCD_D5       14
#define PIN_LCD_D6       15
#define PIN_LCD_D7       16
#define PIN_BUZZER       10   // buzzer actif (alarme locale)
#define PIN_LED_GREEN    11   // LED verte
#define PIN_LED_RED      12   // LED rouge
#define PIN_RGB_STATUS   48   // LED RGB intégrée (38 sur certaines révisions)
