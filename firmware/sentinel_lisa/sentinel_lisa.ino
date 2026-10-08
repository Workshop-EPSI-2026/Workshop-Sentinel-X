// =============================================================================
//  Sentinel-X : boitier ESP32-S3 (cablage de Lisa) relie au serveur Sentinel-X
//
//  Capteurs : PIR GPIO 5, MQ-2 GPIO 6 (ADC1, pont diviseur si alimente en 5 V), DHT11 GPIO 4, buzzer GPIO 7.
//  Temps reel : PIR 50 ms, gaz 200 ms (lissage + hysteresis), DHT11 2 s, telemetrie 2 s, sante 30 s.
//  Messages conformes a docs/contracts.md (sentinel/esp-01/telemetry, event, health, status).
//
//  Commandes du dashboard (sentinel/esp-01/cmd), une commande de plus de 30 s ou deja vue est ignoree :
//    alarm on   -> sirene continue jusqu'a "alarm off"
//    alarm off  -> silence, meme pendant une alerte gaz, jusqu'au retour au calme (au plus 5 min)
//    mode maintenance / armed -> buzzer muet en maintenance (indique dans la telemetrie)
//    recalibrate -> reapprend l'air habituel du MQ-2 ;  reboot -> redemarre ;  led -> LED RGB integree
//
//  Securite : MQTT_USE_TLS 1 dans secrets.h -> port 8883 chiffre, certificat du serveur verifie avec la CA
//  locale (certs.h, genere par security/pki/pki.py). Sans TLS : 1883 en clair (mise au point seulement).
//
//  Arduino IDE 2, carte "ESP32S3 Dev Module" (coeur esp32 3.x). Bibliotheques : PubSubClient (Nick O'Leary),
//  DHT sensor library + Adafruit Unified Sensor. Reglages : secrets.h (copie de secrets.example.h, jamais sur Git).
// =============================================================================
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <time.h>
#include <esp_system.h>
#include "secrets.h"
#if MQTT_USE_TLS
#include "certs.h"            // CA_CERT : copie par security/pki/pki.py (jamais sur Git)
#endif

// ---- Cablage ----
#define PIRPIN     5
#define MQ2PIN     6
#define DHTPIN     4
#define DHTTYPE    DHT11
#define BUZZER_PIN 7
DHT dht(DHTPIN, DHTTYPE);

// ---- Temps reel ----
const unsigned long DUREE_PRECHAUFFAGE = 60000;   // prechauffage du MQ-2 avant d'apprendre l'air habituel
const unsigned long INTERVALLE_ENVOI   = 2000;
const unsigned long INTERVALLE_SANTE   = 30000;
const unsigned long INTERVALLE_PIR     = 50;
const unsigned long INTERVALLE_GAZ     = 200;
const unsigned long INTERVALLE_DHT     = 2000;
const unsigned long INTERVALLE_RECO    = 5000;
const unsigned long SILENCE_MAX        = 300000;  // "couper l'alarme" : 5 min au plus
const float SEUIL_ALERTE_ON  = 1.4;               // alerte locale si gaz > base * 1.4
const float SEUIL_ALERTE_OFF = 1.3;               // retour au calme si gaz < base * 1.3
const time_t HEURE_VALIDE    = 1767225600;        // 1er janvier 2026 : avant, l'heure NTP n'est pas recue
const double COMMANDE_MAX_S  = 30;                // commande plus vieille : ignoree (rejeu)
#define FW_VERSION "lisa-2.0"

#if MQTT_USE_TLS
WiFiClientSecure espClient;
#else
WiFiClient espClient;
#endif
PubSubClient client(espClient);

char topicTelemetry[48], topicEvent[48], topicHealth[48], topicStatus[48], topicCmd[48];
char bootId[9];
unsigned long seq = 0;

bool pirActif = false;
unsigned long pirMoments[32];
int pirTete = 0;

bool capteursPrets = false, alerteGaz = false;
float baseGaz = 0, gazLisse = 0;
unsigned long debutPrechauffage = 0;

float temperature = NAN, humidite = NAN;
unsigned long wifiCoupures = 0, mqttConnexions = 0, erreursTls = 0;
bool bootEnvoye = false;

// Alarme pilotee par le dashboard
bool sireneForcee = false;         // "Declencher l'alarme"
bool silence = false;              // "Couper l'alarme"
unsigned long silenceDepuis = 0;
bool maintenance = false;          // "Passer en maintenance"
char derniersIds[8][40];           // commandes deja executees (anti-rejeu)
int idTete = 0;

unsigned long dernierEnvoi = 0, dernierSante = 0, dernierPIR = 0, dernierGaz = 0, dernierDHT = 0;
unsigned long dernierEssaiWiFi = 0, dernierEssaiMQTT = 0, dernierBip = 0;
bool buzzerOn = false;
unsigned long buzzerOffA = 0;

// ============================================ outils
bool heureValide() { return time(nullptr) > HEURE_VALIDE; }

int pirCount() {
  int n = 0;
  for (int i = 0; i < 32; i++) if (pirMoments[i] && millis() - pirMoments[i] < 60000UL) n++;
  return n;
}

int edgeScore() {
  if (alerteGaz) return 80;
  if (pirActif) return 40;
  return 0;
}

const char* modeActuel() {
  if (maintenance) return "maintenance";
  return capteursPrets ? "armed" : "learning";
}

bool publier(const char* topic, const char* message, bool conserve = false) {
  bool ok = client.connected() && client.publish(topic, message, conserve);
  Serial.print(ok ? "-> " : "!! non envoye ");
  Serial.print(topic);
  Serial.print(" ");
  Serial.println(message);
  return ok;
}

void envoyerEvenement(const char* type, const char* value, const char* info = nullptr) {
  if (!heureValide()) return;
  char details[96] = "{}";
  if (info) snprintf(details, sizeof(details), "{\"info\":\"%s\"}", info);
  char message[300];
  snprintf(message, sizeof(message),
           "{\"device_id\":\"%s\",\"seq\":%lu,\"boot_id\":\"%s\",\"ts\":%lu,\"type\":\"%s\",\"value\":%s,"
           "\"details\":%s}",
           DEVICE_ID, ++seq, bootId, (unsigned long)time(nullptr), type, value, details);
  publier(topicEvent, message);
}

void envoyerTelemetrie() {
  if (!heureValide() || isnan(temperature) || isnan(humidite)) {
    Serial.println("mesure non envoyee : heure NTP ou DHT11 pas encore prets");
    return;
  }
  float ratio = (capteursPrets && baseGaz > 0) ? gazLisse / baseGaz : 1.0;
  char message[360];
  snprintf(message, sizeof(message),
           "{\"device_id\":\"%s\",\"seq\":%lu,\"boot_id\":\"%s\",\"ts\":%lu,\"temp_c\":%.1f,\"hum_pct\":%.1f,"
           "\"gas_mv\":%d,\"gas_ratio\":%.3f,\"gas_do\":%s,\"pir\":%s,\"pir_count\":%d,\"mode\":\"%s\","
           "\"edge_score\":%d,\"replay\":false}",
           DEVICE_ID, ++seq, bootId, (unsigned long)time(nullptr), temperature, humidite,
           (int)gazLisse, ratio, alerteGaz ? "true" : "false", pirActif ? "true" : "false", pirCount(),
           modeActuel(), edgeScore());
  publier(topicTelemetry, message);
}

void envoyerSante() {
  if (!heureValide()) return;
  char message[360];
  snprintf(message, sizeof(message),
           "{\"device_id\":\"%s\",\"ts\":%lu,\"uptime_s\":%lu,\"heap_free\":%lu,\"psram_free\":%lu,\"rssi\":%d,"
           "\"chip_temp_c\":%.1f,\"reset_reason\":%d,\"buffer_len\":0,\"wifi_disconnects\":%lu,"
           "\"mqtt_reconnects\":%lu,\"tls_errors\":%lu,\"fw_version\":\"%s\"}",
           DEVICE_ID, (unsigned long)time(nullptr), millis() / 1000, (unsigned long)ESP.getFreeHeap(),
           (unsigned long)ESP.getFreePsram(), WiFi.RSSI(), temperatureRead(), (int)esp_reset_reason(),
           wifiCoupures, mqttConnexions, erreursTls, FW_VERSION);
  publier(topicHealth, message);
}

void calibrerGaz() {
  float somme = 0;
  for (int i = 0; i < 20; i++) { somme += analogReadMilliVolts(MQ2PIN); delay(100); }
  baseGaz = somme / 20;
  gazLisse = baseGaz;
  capteursPrets = true;
  Serial.print("Base gaz (mV) : ");
  Serial.println(baseGaz);
  Serial.println("CAPTEURS PRETS : mode armed");
}

// ============================================ buzzer (sans delay : la boucle reste temps reel)
void bip(unsigned long dureeMs) {
  digitalWrite(BUZZER_PIN, HIGH);
  buzzerOn = true;
  buzzerOffA = millis() + dureeMs;
}

void gererAlarme(unsigned long maintenant) {
  if (buzzerOn && (long)(maintenant - buzzerOffA) >= 0) { digitalWrite(BUZZER_PIN, LOW); buzzerOn = false; }
  if (silence && (maintenant - silenceDepuis >= SILENCE_MAX)) silence = false;   // le silence ne dure pas

  if (sireneForcee) {                                   // sirene demandee par l'operateur
    if (maintenant - dernierBip >= 500) { dernierBip = maintenant; bip(300); }
    return;
  }
  if (maintenance || silence) return;                   // maintenance ou alarme coupee : muet
  if (alerteGaz) {                                      // gaz : bip rapide (danger immediat)
    if (maintenant - dernierBip >= 200) { dernierBip = maintenant; bip(50); }
  } else if (pirActif) {                                // mouvement : bip lent (surveillance)
    if (maintenant - dernierBip >= 1000) { dernierBip = maintenant; bip(50); }
  }
}

void led(const char* couleur) {
#ifdef RGB_BUILTIN
  uint8_t r = 0, g = 0, b = 0;
  if (!strcmp(couleur, "red")) r = 64;
  else if (!strcmp(couleur, "green")) g = 64;
  else if (!strcmp(couleur, "blue")) b = 64;
  else if (!strcmp(couleur, "orange")) { r = 64; g = 24; }
  else if (!strcmp(couleur, "violet")) { r = 40; b = 64; }
  else if (!strcmp(couleur, "white")) { r = 48; g = 48; b = 48; }
  rgbLedWrite(RGB_BUILTIN, r, g, b);
#else
  (void)couleur;
#endif
}

// ============================================ commandes du dashboard
// Lecture minimale du JSON de l'API : {"id":"...","ts":1791...,"cmd":"alarm","on":true}
bool champTexte(const char* json, const char* nom, char* dest, size_t taille) {
  char cle[24];
  snprintf(cle, sizeof(cle), "\"%s\"", nom);
  const char* p = strstr(json, cle);
  if (!p) return false;
  p = strchr(p + strlen(cle), ':');
  if (!p) return false;
  while (*++p == ' ') {}
  if (*p != '"') return false;
  size_t i = 0;
  for (p++; *p && *p != '"' && i + 1 < taille; p++) dest[i++] = *p;
  dest[i] = 0;
  return true;
}

bool champNombre(const char* json, const char* nom, double* valeur) {
  char cle[24];
  snprintf(cle, sizeof(cle), "\"%s\"", nom);
  const char* p = strstr(json, cle);
  if (!p) return false;
  p = strchr(p + strlen(cle), ':');
  if (!p) return false;
  *valeur = strtod(p + 1, nullptr);
  return true;
}

bool champVrai(const char* json, const char* nom) {
  char cle[24];
  snprintf(cle, sizeof(cle), "\"%s\"", nom);
  const char* p = strstr(json, cle);
  if (!p) return false;
  p = strchr(p + strlen(cle), ':');
  if (!p) return false;
  while (*++p == ' ') {}
  return strncmp(p, "true", 4) == 0;
}

void recevoirCommande(char* topic, byte* charge, unsigned int longueur) {
  char json[256];
  unsigned int n = longueur < sizeof(json) - 1 ? longueur : sizeof(json) - 1;
  memcpy(json, charge, n);
  json[n] = 0;
  Serial.print("<- ");
  Serial.print(topic);
  Serial.print(" ");
  Serial.println(json);

  char id[40] = "", cmd[16] = "", valeur[16] = "";
  double ts = 0;
  champTexte(json, "id", id, sizeof(id));
  champTexte(json, "cmd", cmd, sizeof(cmd));
  champNombre(json, "ts", &ts);
  if (heureValide() && (ts <= 0 || fabs((double)time(nullptr) - ts) > COMMANDE_MAX_S)) {
    Serial.println("   commande ignoree : trop ancienne ou sans horodatage (rejeu ?)");
    return;
  }
  for (int i = 0; i < 8; i++) {
    if (id[0] && !strcmp(derniersIds[i], id)) { Serial.println("   commande ignoree : deja executee"); return; }
  }
  strncpy(derniersIds[idTete], id, sizeof(derniersIds[0]) - 1);
  idTete = (idTete + 1) % 8;

  if (!strcmp(cmd, "alarm")) {
    if (champVrai(json, "on")) {
      sireneForcee = true;
      silence = false;
      Serial.println("   ALARME declenchee depuis le dashboard");
      envoyerEvenement("edge_alarm", "true", "dashboard");
    } else {
      sireneForcee = false;
      silence = true;
      silenceDepuis = millis();
      digitalWrite(BUZZER_PIN, LOW);
      Serial.println("   alarme coupee (silence jusqu'au retour au calme, 5 min au plus)");
      envoyerEvenement("edge_alarm", "false", "dashboard");
    }
  } else if (!strcmp(cmd, "mode") && champTexte(json, "value", valeur, sizeof(valeur))) {
    maintenance = !strcmp(valeur, "maintenance");
    if (maintenance) { sireneForcee = false; digitalWrite(BUZZER_PIN, LOW); }
    Serial.println(maintenance ? "   mode maintenance : buzzer muet" : "   mode surveillance");
    char v[24];
    snprintf(v, sizeof(v), "\"%s\"", modeActuel());
    envoyerEvenement("mode_change", v, "dashboard");
  } else if (!strcmp(cmd, "recalibrate")) {
    Serial.println("   recalibrage du MQ-2 (2 s)...");
    alerteGaz = false;
    calibrerGaz();
  } else if (!strcmp(cmd, "led") && champTexte(json, "color", valeur, sizeof(valeur))) {
    led(valeur);
  } else if (!strcmp(cmd, "reboot")) {
    Serial.println("   redemarrage demande par le dashboard");
    client.publish(topicStatus, "offline", true);
    delay(300);
    ESP.restart();
  } else {
    Serial.println("   commande inconnue, ignoree");
  }
}

// ============================================ reseau
void gererReseau(unsigned long maintenant) {
  if (WiFi.status() != WL_CONNECTED) {
    if (maintenant - dernierEssaiWiFi >= INTERVALLE_RECO) {
      dernierEssaiWiFi = maintenant;
      wifiCoupures++;
      Serial.println("Wi-Fi perdu, reconnexion...");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
    return;
  }
  if (!client.connected()) {
    if (maintenant - dernierEssaiMQTT >= INTERVALLE_RECO) {
      dernierEssaiMQTT = maintenant;
      Serial.print("Connexion MQTT a ");
      Serial.print(MQTT_HOST);
      Serial.print(":");
      Serial.print(MQTT_PORT);
      Serial.print(MQTT_USE_TLS ? " (TLS)... " : " (en clair)... ");
      if (client.connect(DEVICE_ID, MQTT_USER, MQTT_PASSWORD, topicStatus, 1, true, "offline")) {
        mqttConnexions++;
        Serial.println("OK");
        client.publish(topicStatus, "online", true);
        client.subscribe(topicCmd, 1);
        if (!bootEnvoye && heureValide()) {
          char raison[8];
          snprintf(raison, sizeof(raison), "%d", (int)esp_reset_reason());
          envoyerEvenement("boot", raison, FW_VERSION);
          bootEnvoye = true;
        }
      } else {
        // -2 : serveur injoignable (adresse, pare-feu, Sentinel-X arrete) ou certificat refuse en TLS
        // 4 / 5 : mot de passe ou droits refuses
        Serial.print("echec, code = ");
        Serial.println(client.state());
#if MQTT_USE_TLS
        char err[100];
        int code = espClient.lastError(err, sizeof(err));
        if (code) {
          erreursTls++;
          Serial.print("   TLS : ");
          Serial.println(err);   // ex. certificat non reconnu : MQTT_HOST absent du certificat, ou mauvais certs.h
        }
#endif
      }
    }
  } else {
    client.loop();
  }
}

// ============================================ setup
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("=================================");
  Serial.println("  SENTINEL-X : boitier " DEVICE_ID " " FW_VERSION);
  Serial.println("=================================");

  pinMode(PIRPIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  analogReadResolution(12);
  analogSetPinAttenuation(MQ2PIN, ADC_11db);
  dht.begin();

  snprintf(bootId, sizeof(bootId), "%08lx", (unsigned long)esp_random());
  snprintf(topicTelemetry, sizeof(topicTelemetry), "sentinel/%s/telemetry", DEVICE_ID);
  snprintf(topicEvent,     sizeof(topicEvent),     "sentinel/%s/event",     DEVICE_ID);
  snprintf(topicHealth,    sizeof(topicHealth),    "sentinel/%s/health",    DEVICE_ID);
  snprintf(topicStatus,    sizeof(topicStatus),    "sentinel/%s/status",    DEVICE_ID);
  snprintf(topicCmd,       sizeof(topicCmd),       "sentinel/%s/cmd",       DEVICE_ID);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connexion Wi-Fi");
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(500); Serial.print("."); }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Wi-Fi OK, IP : ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("Wi-Fi indisponible (reseau 2,4 GHz ? mot de passe sans accent ?), nouvel essai en arriere-plan");
  }

  configTime(0, 0, NTP_SERVER, "pool.ntp.org");
  Serial.print("Heure NTP");
  for (int i = 0; i < 30 && !heureValide(); i++) { delay(500); Serial.print("."); }
  Serial.println(heureValide() ? " OK" : " pas encore (les mesures attendront)");

#if MQTT_USE_TLS
  espClient.setCACert(CA_CERT);   // le boitier ne parle qu'au serveur dont le certificat est signe par la CA locale
#endif
  client.setServer(MQTT_HOST, MQTT_PORT);
  client.setCallback(recevoirCommande);
  client.setBufferSize(512);
  client.setKeepAlive(15);
  client.setSocketTimeout(5);

  humidite = dht.readHumidity();
  temperature = dht.readTemperature();
  debutPrechauffage = millis();
  Serial.println("Prechauffage MQ-2 (60 s) : mode learning, le reste fonctionne deja...");
}

// ============================================ loop
void loop() {
  unsigned long maintenant = millis();

  if (!capteursPrets && maintenant - debutPrechauffage >= DUREE_PRECHAUFFAGE) calibrerGaz();

  // 1. PIR (50 ms) : evenement immediat au debut du mouvement
  if (maintenant - dernierPIR >= INTERVALLE_PIR) {
    dernierPIR = maintenant;
    bool etat = (digitalRead(PIRPIN) == HIGH);
    if (etat != pirActif) {
      pirActif = etat;
      Serial.println(pirActif ? ">>> MOUVEMENT DETECTE !" : ">>> Fin du mouvement");
      if (pirActif) {
        pirMoments[pirTete] = maintenant;
        pirTete = (pirTete + 1) % 32;
        envoyerEvenement("pir", "true");
      }
    }
  }

  // 2. Gaz (200 ms) : lissage + alerte locale avec hysteresis
  if (maintenant - dernierGaz >= INTERVALLE_GAZ) {
    dernierGaz = maintenant;
    float brut = analogReadMilliVolts(MQ2PIN);
    gazLisse = gazLisse <= 0 ? brut : (gazLisse * 3 + brut) / 4;
    if (capteursPrets) {
      if (!alerteGaz && gazLisse > baseGaz * SEUIL_ALERTE_ON) {
        alerteGaz = true;
        Serial.println("!!! ALERTE GAZ");
        envoyerEvenement("gas_do", "true");
      } else if (alerteGaz && gazLisse < baseGaz * SEUIL_ALERTE_OFF) {
        alerteGaz = false;
        silence = false;                 // fuite terminee : une prochaine alerte sonnera de nouveau
        Serial.println("Gaz revenu a la normale");
        envoyerEvenement("gas_do", "false");
      }
    }
  }

  // 3. DHT11 (2 s) : derniere valeur valide gardee
  if (maintenant - dernierDHT >= INTERVALLE_DHT) {
    dernierDHT = maintenant;
    float h = dht.readHumidity(), t = dht.readTemperature();
    if (!isnan(h)) humidite = h;
    if (!isnan(t)) temperature = t;
  }

  // 4. Buzzer
  gererAlarme(maintenant);

  // 5. Reseau (et commandes recues)
  gererReseau(maintenant);

  // 6. Telemetrie (2 s) et sante (30 s)
  if (maintenant - dernierEnvoi >= INTERVALLE_ENVOI) { dernierEnvoi = maintenant; envoyerTelemetrie(); }
  if (maintenant - dernierSante >= INTERVALLE_SANTE) { dernierSante = maintenant; envoyerSante(); }
}
