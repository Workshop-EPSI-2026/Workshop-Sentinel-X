# Câblage du boîtier — Momo et Michel (tâche m1)

| Composant | Broche ESP8266 | Alimentation | Remarque |
|---|---|---|---|
| DHT22 | | 3,3 V | Lecture toutes les 2 s minimum (`millis()`) |
| OLED SSD1306 | D1 (SCL) / D2 (SDA) | 3,3 V | |
| PIR | | 5 V | Éviter D3, D4, D8 |
| MQ-2 | A0 via pont diviseur | 5 V | Préchauffage : alimenter dès le branchement |
| Buzzer | | | Éviter D3, D4, D8 |
| LEDs | | | Résistances série |
