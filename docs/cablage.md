# Câblage du boîtier — Momo et Michel

Carte : **ESP32-S3 N16R8** (deux ports USB-C : **COM** pour téléverser et lire le moniteur série, **USB** natif).
Brochage figé dans `firmware/include/pins.h` : toute modification se fait dans les deux fichiers.

## Broches à ne pas utiliser
0, 3, 45, 46 (démarrage) · 19, 20 (USB) · 35, 36, 37 (PSRAM octale de la N16R8) · 43, 44 (série).
Entrées analogiques utilisables avec le Wi-Fi actif : **GPIO 1 à 10** uniquement.

## Brochage

| Composant | Broche du module | Broche ESP32-S3 | Alimentation | Remarque |
| --- | --- | --- | --- | --- |
| DHT11 | DATA | GPIO 4 | 3V3 | Résistance de tirage déjà sur le module |
| PIR HW-416-B | OUT | GPIO 5 | 5V | Sortie 3,3 V ; cavalier en **H**, sensibilité au maximum, délai au minimum |
| MQ-2 | AO | GPIO 1 | 5V | **Pont diviseur 10 kΩ / 10 kΩ** (AO → 10 kΩ → GPIO 1 → 10 kΩ → GND) |
| MQ-2 | DO | GPIO 6 | — | **Pont 10 kΩ / 15 kΩ** (≈ 3 V) ; 15 kΩ = 10 kΩ + 4,7 kΩ en série si besoin |
| Effraction | feuille de cuivre | GPIO 7 (T7) | — | Fil court vers la feuille collée dans le couvercle |
| LCD 1602 | RS / E | GPIO 8 / 9 | 5V (VDD) | Mode 4 bits, voir ci-dessous |
| LCD 1602 | D4 / D5 / D6 / D7 | GPIO 13 / 14 / 15 / 16 | — | D0 à D3 non branchées |
| Buzzer actif | + | GPIO 10 | — | Alarme sonore locale |
| LED verte / rouge | anode | GPIO 11 / 12 | — | Résistance 220 Ω en série |
| LED RGB intégrée | — | GPIO 48 | — | Voyant d'état (GPIO 38 sur certaines révisions) |

### Écran LCD 1602 (16 broches, sans module I2C)

| Broche LCD | Branchement |
| --- | --- |
| 1 VSS | GND |
| 2 VDD | 5V |
| 3 V0 (contraste) | Curseur d'un potentiomètre 10 kΩ entre 5V et GND (à défaut : 1 à 2,2 kΩ vers GND) |
| 4 RS | GPIO 8 |
| 5 RW | **GND** (écriture seule : l'écran ne renvoie jamais de 5 V vers l'ESP32-S3) |
| 6 E | GPIO 9 |
| 7 à 10 D0 à D3 | Non branchées |
| 11 à 14 D4 à D7 | GPIO 13, 14, 15, 16 |
| 15 A (rétroéclairage +) | 5V, avec 220 Ω en série si le module n'a pas déjà sa résistance |
| 16 K (rétroéclairage −) | GND |

Souder une barrette de 16 broches sur l'écran. Alimenté en 5 V, il accepte les niveaux 3,3 V de l'ESP32-S3.
Écran vide ou rangée de carrés noirs : régler le contraste (V0) avant de soupçonner le code.

Toutes les masses (GND) sont communes. Le 5 V vient de la broche **5Vin** de la carte, alimentée par l'USB du PC serveur (ou un chargeur 5 V).

## Ordre de test

1. Blink sur la LED RGB.
2. DHT11 seul, une lecture toutes les 2 s.
3. PIR seul : vérifier le réglage des potentiomètres et du cavalier.
4. MQ-2 : brancher tout de suite (préchauffage), vérifier au multimètre que GPIO 1 ne dépasse pas 2,5 V.
5. Effraction : valeur tactile au repos, puis main posée sur la feuille ; noter les deux valeurs.
6. Buzzer et LEDs, puis LCD : contraste réglé, « Sentinel-X » affiché sur la première ligne.

## Mesures relevées

| Mesure | Valeur |
| --- | --- |
| MQ-2 au repos après préchauffage (mV) | |
| Tactile au repos / main posée | |
| Adresse MAC de l'ESP32-S3 | |
