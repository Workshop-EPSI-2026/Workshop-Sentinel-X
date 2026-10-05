// Sentinel-X — brochage ESP32-S3 N16R8 (source unique, voir docs/cablage.md)
// Interdites : 0, 3, 45, 46 (démarrage) · 19, 20 (USB) · 35, 36, 37 (PSRAM) · 43, 44 (série)
#pragma once

#define PIN_DHT11        4    // DATA, 3V3
#define PIN_PIR          5    // OUT 3,3 V, PIR alimenté en 5 V
#define PIN_MQ2_AO       1    // ADC1, via pont 10k/10k (max 2,5 V)
#define PIN_MQ2_DO       6    // via pont 10k/15k (~3 V)
#define PIN_TAMPER_TOUCH 7    // T7, feuille de cuivre dans le couvercle
#define PIN_I2C_SDA      8    // OLED (si disponible)
#define PIN_I2C_SCL      9
#define PIN_BUZZER       10   // si disponible
#define PIN_LED_GREEN    11   // si disponible
#define PIN_LED_RED      12   // si disponible
#define PIN_RGB_STATUS   48   // LED RGB intégrée (38 sur certaines révisions)
