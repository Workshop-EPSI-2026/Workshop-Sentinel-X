// =============================================================================
//  Sentinel-X — boîtier ESP32-S3 : liaison Wi-Fi + MQTT vers le PC serveur (tâche m2, prépare mo1 et mo2)
//
//  Arduino IDE 2 · carte « ESP32S3 Dev Module » (cœur esp32 d'Espressif 3.x)
//    Outils > USB CDC On Boot : Enabled (moniteur série sur le port USB natif)
//    Outils > Flash Size : 16MB · PSRAM : OPI PSRAM
//  Bibliothèques (Gestionnaire de bibliothèques) :
//    PubSubClient (Nick O'Leary) · ArduinoJson 7 (Benoit Blanchon) · DHT sensor library + Adafruit Unified Sensor
//
//  Avant de téléverser : copier secrets.example.h en secrets.h (même dossier, ignoré par Git) et le remplir.
//  Messages conformes à docs/contracts.md : telemetry (2 s), event (immédiat), health (30 s), status (dernière volonté).
// =============================================================================
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <time.h>
#include <esp_system.h>
#include "secrets.h"
#if MQTT_USE_TLS
#include "certs.h"            // CA_CERT (et CLIENT_CERT / CLIENT_KEY en TLS mutuel), fourni par Lisa
#endif

// ---- Brochage : mêmes valeurs que firmware/include/pins.h — À ADAPTER si votre câblage de test diffère ----
#define PIN_DHT11   4         // DATA, 3V3
#define PIN_PIR     5         // OUT du HW-416-B (actif à l'état haut)
#define PIN_MQ2_AO  1         // ADC1, via pont 10k/10k
#define PIN_MQ2_DO  6         // via pont ; le module passe à l'état BAS quand son seuil est dépassé
#define MQ2_DO_ACTIVE_LOW 1

#define FW_VERSION       "0.2.0-m2"
#define TELEMETRY_MS     2000
#define HEALTH_MS        30000
#define LEARNING_S       600   // 10 min d'apprentissage de la ligne de base du gaz
#define MIN_VALID_EPOCH  1767225600UL   // 1er janvier 2026 : avant, l'heure n'est pas encore reçue

DHT dht(PIN_DHT11, DHT11);
#if MQTT_USE_TLS
WiFiClientSecure net;
#else
WiFiClient net;
#endif
PubSubClient mqtt(net);

String topicBase = String("sentinel/") + DEVICE_ID;
char bootId[9];
uint32_t seq = 0;
uint32_t wifiDisconnects = 0, mqttReconnects = 0, mqttFailures = 0;
unsigned long lastTelemetry = 0, lastHealth = 0, lastMqttTry = 0, lastNtpTry = 0, bootMs = 0;
float gasBaseline = 0;        // moyenne glissante du gaz en air habituel
float lastTemp = NAN, lastHum = NAN;
bool lastPir = false, lastGasDo = false, bootEventSent = false;
unsigned long pirTimes[32];   // horodatages (ms) des déclenchements PIR, pour pir_count sur 60 s
uint8_t pirHead = 0;

// ------------------------------------------------------------------ outils
bool timeValid() { return time(nullptr) > (time_t)MIN_VALID_EPOCH; }
unsigned long nowTs() { return (unsigned long)time(nullptr); }
const char* deviceMode() { return (millis() - bootMs) / 1000 < LEARNING_S ? "learning" : "armed"; }

int readGasMv() {             // moyenne de 16 lectures, en mV, après le pont diviseur
  uint32_t sum = 0;
  for (int i = 0; i < 16; i++) { sum += analogReadMilliVolts(PIN_MQ2_AO); delay(2); }
  return sum / 16;
}
bool readGasDo() { return MQ2_DO_ACTIVE_LOW ? digitalRead(PIN_MQ2_DO) == LOW : digitalRead(PIN_MQ2_DO) == HIGH; }
bool readPir() { return digitalRead(PIN_PIR) == HIGH; }

int pirCount() {
  int n = 0;
  for (int i = 0; i < 32; i++) if (pirTimes[i] && millis() - pirTimes[i] < 60000UL) n++;
  return n;
}

bool publishJson(const char* kind, JsonDocument& doc, bool retained = false) {
  char buf[768];
  size_t len = serializeJson(doc, buf, sizeof(buf));
  String topic = topicBase + "/" + kind;
  bool ok = mqtt.connected() && mqtt.publish(topic.c_str(), (const uint8_t*)buf, len, retained);
  Serial.printf("%s %s %s\n", ok ? "->" : "!! (non envoyé)", topic.c_str(), buf);
  return ok;
}

void sendEvent(const char* type, JsonVariantConst value, const char* detail = nullptr) {
  if (!timeValid()) return;
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID; doc["seq"] = ++seq; doc["boot_id"] = bootId; doc["ts"] = nowTs();
  doc["type"] = type; doc["value"] = value;
  JsonObject d = doc["details"].to<JsonObject>();
  if (detail) d["info"] = detail;
  publishJson("event", doc);
}

// ------------------------------------------------------------------ réseau
void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Wi-Fi : connexion à %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(500); Serial.print('.'); }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nWi-Fi OK : adresse %s, passerelle %s, RSSI %d dBm\n", WiFi.localIP().toString().c_str(),
                  WiFi.gatewayIP().toString().c_str(), WiFi.RSSI());
  } else {
    Serial.println("\nWi-Fi KO : SSID en 2,4 GHz ? mot de passe ? (nouvel essai dans 5 s)");
  }
}

void syncTime() {
  configTime(0, 0, NTP_SERVER, "pool.ntp.org");   // le PC d'abord, Internet en secours
  Serial.print("Heure : attente du serveur NTP");
  for (int i = 0; i < 30 && !timeValid(); i++) { delay(500); Serial.print('.'); }
  Serial.println(timeValid() ? " OK" : " KO (serveur-pc.ps1 -Action Ntp sur le PC ; les mesures attendront)");
}

void onCommand(char* topic, byte* payload, unsigned int len) {
  // Les commandes (alarme, LED, mode...) arrivent avec mo1 ; pour l'instant on les affiche.
  Serial.printf("<- %s %.*s\n", topic, (int)len, (const char*)payload);
}

void connectMqtt() {
  if (mqtt.connected() || millis() - lastMqttTry < 5000) return;
  lastMqttTry = millis();
  String willTopic = topicBase + "/status";
  Serial.printf("MQTT : connexion à %s:%d ... ", MQTT_HOST, MQTT_PORT);
  bool ok = mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASSWORD, willTopic.c_str(), 1, true, "offline");
  if (!ok) {
    mqttFailures++;
    // -2 : serveur injoignable (adresse, pare-feu 1883, broker arrêté) · 4 : identifiants refusés · 5 : ACL / non autorisé
    Serial.printf("KO (état %d)\n", mqtt.state());
    return;
  }
  mqttReconnects++;
  Serial.println("OK");
  mqtt.publish(willTopic.c_str(), "online", true);
  mqtt.subscribe((topicBase + "/cmd").c_str(), 1);
  mqtt.subscribe((topicBase + "/config").c_str(), 1);
  if (!bootEventSent && timeValid()) {
    JsonDocument v; v.set(esp_reset_reason());
    sendEvent("boot", v.as<JsonVariantConst>(), FW_VERSION);
    bootEventSent = true;
  }
}

// ------------------------------------------------------------------ messages
void sendTelemetry() {
  float t = dht.readTemperature(), h = dht.readHumidity();
  if (!isnan(t)) lastTemp = t;        // le DHT11 rate parfois une lecture : on garde la précédente
  if (!isnan(h)) lastHum = h;
  int gasMv = readGasMv();
  if (gasBaseline <= 0) gasBaseline = gasMv;
  if (strcmp(deviceMode(), "learning") == 0) gasBaseline = 0.98f * gasBaseline + 0.02f * gasMv;  // apprend l'air habituel
  float ratio = gasBaseline > 0 ? gasMv / gasBaseline : 1.0f;

  if (!timeValid() || isnan(lastTemp) || isnan(lastHum)) {
    Serial.println("mesure non envoyée : heure ou DHT11 pas encore prêts");
    return;
  }
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID; doc["seq"] = ++seq; doc["boot_id"] = bootId; doc["ts"] = nowTs();
  doc["temp_c"] = lastTemp; doc["hum_pct"] = lastHum;
  doc["gas_mv"] = gasMv; doc["gas_ratio"] = serialized(String(ratio, 3));
  doc["gas_do"] = readGasDo(); doc["pir"] = readPir(); doc["pir_count"] = pirCount();
  doc["mode"] = deviceMode(); doc["edge_score"] = 0;   // garde locale : tâche mo1
  doc["replay"] = false;                         // tampon PSRAM rejoué : tâche mo1
  publishJson("telemetry", doc);
}

void sendHealth() {
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID; doc["ts"] = timeValid() ? nowTs() : 0;
  doc["uptime_s"] = (millis() - bootMs) / 1000; doc["heap_free"] = ESP.getFreeHeap();
  doc["psram_free"] = ESP.getFreePsram(); doc["rssi"] = WiFi.RSSI();
  doc["chip_temp_c"] = serialized(String(temperatureRead(), 1)); doc["reset_reason"] = (int)esp_reset_reason();
  doc["buffer_len"] = 0; doc["wifi_disconnects"] = wifiDisconnects; doc["mqtt_reconnects"] = mqttReconnects;
  doc["tls_errors"] = MQTT_USE_TLS ? mqttFailures : 0; doc["fw_version"] = FW_VERSION;
  publishJson("health", doc);
}

void watchInputs() {                  // événements immédiats : front montant du PIR, seuil matériel du MQ-2
  bool pir = readPir();
  if (pir && !lastPir) {
    pirTimes[pirHead] = millis(); pirHead = (pirHead + 1) % 32;
    JsonDocument v; v.set(true);
    sendEvent("pir", v.as<JsonVariantConst>());
  }
  lastPir = pir;
  bool gasDo = readGasDo();
  if (gasDo != lastGasDo) {
    JsonDocument v; v.set(gasDo);
    sendEvent("gas_do", v.as<JsonVariantConst>());
  }
  lastGasDo = gasDo;
}

// ------------------------------------------------------------------ setup / loop
void setup() {
  Serial.begin(115200);
  delay(1500);
  bootMs = millis();
  snprintf(bootId, sizeof(bootId), "%08lx", (unsigned long)esp_random());
  Serial.printf("\nSentinel-X %s · %s · boot_id %s\n", FW_VERSION, DEVICE_ID, bootId);

  pinMode(PIN_PIR, INPUT);
  pinMode(PIN_MQ2_DO, INPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_MQ2_AO, ADC_11db);
  dht.begin();

  WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t) { wifiDisconnects++; }, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
  connectWifi();
  syncTime();

#if MQTT_USE_TLS
  net.setCACert(CA_CERT);
#if MQTT_USE_MTLS
  net.setCertificate(CLIENT_CERT);
  net.setPrivateKey(CLIENT_KEY);
#endif
#endif
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(1024);           // 256 octets par défaut : trop petit pour la télémétrie
  mqtt.setKeepAlive(15);
  mqtt.setCallback(onCommand);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) { connectWifi(); delay(5000); return; }
  if (!timeValid() && millis() - lastNtpTry > 30000UL) { lastNtpTry = millis(); syncTime(); }
  connectMqtt();
  mqtt.loop();
  watchInputs();
  if (millis() - lastTelemetry >= TELEMETRY_MS) { lastTelemetry = millis(); sendTelemetry(); }
  if (millis() - lastHealth >= HEALTH_MS) { lastHealth = millis(); sendHealth(); }
  delay(20);
}
