/*
  Belladonna greenhouse/weather node v2.0(ish)
  ----------------------------------
  ESP32 sensor logger for:
    - BME280: temperature, relative humidity, pressure
    - BH1750: light level
    - GY-SGP41 / SGP41: raw VOC and NOx gas signals

  Data flow:
    1. Read sensors over the dedicated I2C sensor bus.
    2. Format one CSV row.
    3. Send the row to the Belladonna/Khadas receiver over TCP.

  CSV payload after the existing receiver prefix:
    tC,rH,hPa,lux,srawVoc,srawNox

  Notes:
    - Buttons and potentiometer sampling control have been removed.
    - Sampling is fixed at SAMPLE_INTERVAL_MS.
    - The SGP41 raw signals are humidity/temperature compensated using the BME280 reading.
    - If you later add Sensirion's Gas Index Algorithm library, these raw values can be converted
      into VOC Index and NOx Index values on-device or server-side.
*/

#include "config.h"
#include "secrets.h"  // WiFi credentials, server settings, TZ/NTP, etc.

#include <Adafruit_BME280.h>
#include <Adafruit_Sensor.h>
#include <BH1750.h>
#include <ESPmDNS.h>
#include <IPAddress.h>
#include <SensirionCore.h>
#include <SensirionI2CSgp41.h>
#include <WiFi.h>
#include <WiFiMulti.h>
#include <Wire.h>
#include <math.h>
#include <time.h>

// -------------------------------------------------------------------------------------------------
// Types
// -------------------------------------------------------------------------------------------------

struct Sample {
  float tC = NAN;
  float rh = NAN;
  float hPa = NAN;
  float lux = NAN;
  uint16_t srawVoc = 0;
  uint16_t srawNox = 0;
  bool sgp41Ok = false;
};

struct MyNetworkServer {
  const char* ssid;
  IPAddress serverIP;
};

// -------------------------------------------------------------------------------------------------
// Constants
// -------------------------------------------------------------------------------------------------

static const uint32_t WIFI_CONNECT_TIMEOUT_MS = 10000UL;
static const uint32_t WIFI_RECONNECT_TIMEOUT_MS = 3000UL;
static const uint32_t SAMPLE_INTERVAL_MS = 5UL * 1000UL;
static const uint32_t SERVER_IP_CACHE_MS = 60UL * 1000UL;
static const char* ESP32_MDNS_NAME = "esp32-node";
static const char* PAYLOAD_PREFIX = "8355";

static const MyNetworkServer NETWORK_SERVERS[] = {
  { "GREENHOUSE", IPAddress(192, 168, 1, 145) },  // Khadas / Belladonna receiver
  { "iPhone", IPAddress(192, 0, 0, 2) },
  { "BT-HZCMZ5", IPAddress(192, 168, 1, 131) }
};

static const size_t NETWORK_SERVER_COUNT = sizeof(NETWORK_SERVERS) / sizeof(NETWORK_SERVERS[0]);

// -------------------------------------------------------------------------------------------------
// Globals
// -------------------------------------------------------------------------------------------------

TwoWire I2C_SENSOR_BUS = TwoWire(1);
Adafruit_BME280 bme;
BH1750 lightMeter(ADDR_LM);
SensirionI2CSgp41 sgp41;

WiFiClient client;
WiFiMulti wifiMulti;

static bool g_wifiMultiConfigured = false;
static IPAddress g_serverIP(0, 0, 0, 0);
static uint32_t g_serverIP_ts = 0;
static uint32_t g_lastSampleMs = 0;

// -------------------------------------------------------------------------------------------------
// Forward declarations
// -------------------------------------------------------------------------------------------------

static void configureWiFiMultiOnce();
static bool waitForWiFi(uint32_t timeoutMs);
static void initTime();
static bool startMDNS();
static bool serverIPResolver(IPAddress& out);
static bool getServerIPCached(IPAddress& out, uint32_t maxAgeMs = SERVER_IP_CACHE_MS);
static bool testServerConnOnce();
static bool sendToServer(const String& payload);

static void i2cScan(TwoWire& bus, int sda, int scl, uint32_t hz, const char* tag);
static bool initSensors();
static bool initSgp41();
static bool readSensors(Sample& s);
static bool readSgp41(const float rh, const float tC, uint16_t& srawVoc, uint16_t& srawNox);
static uint16_t sgp41RhTicks(float rh);
static uint16_t sgp41TempTicks(float tC);
static void printSensirionError(const char* action, uint16_t error);

static String toCSV(const Sample& s);
static void logSample(const Sample& s);

// -------------------------------------------------------------------------------------------------
// WiFi / network helpers
// -------------------------------------------------------------------------------------------------

static void configureWiFiMultiOnce() {
  if (g_wifiMultiConfigured) return;

  wifiMulti.addAP(SSID_GREENHOUSE, PW_GREENHOUSE);
  wifiMulti.addAP(SSID_IPHONE, PW_IPHONE);
  wifiMulti.addAP(SSID_BT, PW_BT);

  g_wifiMultiConfigured = true;
}

static bool waitForWiFi(uint32_t timeoutMs) {
  Serial.println("\nWiFi:");

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  configureWiFiMultiOnce();

  const uint32_t start = millis();
  Serial.print(" * Connecting with WiFiMulti: ");

  while (WiFi.status() != WL_CONNECTED && (millis() - start) < timeoutMs) {
    wifiMulti.run();
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(" * ERROR: WiFi connection timed out");
    return false;
  }

  Serial.printf(" * Connected\n"
                "   - SSID: %s\n"
                "   - RSSI: %d dBm\n"
                "   - ESP32 IP: %s\n",
                WiFi.SSID().c_str(),
                WiFi.RSSI(),
                WiFi.localIP().toString().c_str());

  // Clear cached server IP after any network transition.
  g_serverIP = IPAddress(0, 0, 0, 0);
  g_serverIP_ts = 0;

  return true;
}

static void initTime() {
  configTzTime(TZ_STRING, NTP_SERVER);
}

static bool startMDNS() {
  Serial.println("\nmDNS:");

  if (!MDNS.begin(ESP32_MDNS_NAME)) {
    Serial.println(" * ERROR: mDNS responder failed to start");
    return false;
  }

  Serial.printf(" * Started as %s.local\n", ESP32_MDNS_NAME);
  return true;
}

static bool serverIPResolver(IPAddress& out) {
  Serial.println("\nServer resolver:");

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(" * WiFi is not connected");
    return false;
  }

  const String currentSSID = WiFi.SSID();
  Serial.printf(" * Current SSID: %s\n", currentSSID.c_str());

  for (size_t i = 0; i < NETWORK_SERVER_COUNT; ++i) {
    if (currentSSID == NETWORK_SERVERS[i].ssid) {
      out = NETWORK_SERVERS[i].serverIP;
      Serial.print(" * Resolved from SSID mapping: ");
      Serial.println(out);
      return true;
    }
  }

  IPAddress ip;
  Serial.printf(" * No SSID mapping; trying host: %s\n", SERVER_HOST_LABEL);

  if (WiFi.hostByName(SERVER_HOST_LABEL, ip) == 1 && ip != IPAddress(0, 0, 0, 0)) {
    out = ip;
    Serial.print(" * Resolved by hostByName: ");
    Serial.println(out);
    return true;
  }

  Serial.println(" * ERROR: server IP could not be resolved");
  return false;
}

static bool getServerIPCached(IPAddress& out, uint32_t maxAgeMs) {
  const uint32_t now = millis();

  if (g_serverIP != IPAddress(0, 0, 0, 0) && (now - g_serverIP_ts) < maxAgeMs) {
    out = g_serverIP;
    return true;
  }

  IPAddress fresh;
  if (!serverIPResolver(fresh)) return false;

  g_serverIP = fresh;
  g_serverIP_ts = now;
  out = g_serverIP;
  return true;
}

static bool testServerConnOnce() {
  Serial.println("\nServer connection test:");

  IPAddress ip;
  if (!serverIPResolver(ip)) {
    Serial.println(" * Resolve failed");
    return false;
  }

  WiFiClient testClient;
  if (!testClient.connect(ip, SERVER_PORT)) {
    Serial.printf(" * Connect FAILED -> %s:%d\n", ip.toString().c_str(), SERVER_PORT);
    return false;
  }

  Serial.printf(" * Connect OK -> %s:%d\n", ip.toString().c_str(), SERVER_PORT);
  testClient.stop();
  return true;
}

static bool sendToServer(const String& payload) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(" * No WiFi; sample not sent");
    return false;
  }

  IPAddress serverIP;
  if (!getServerIPCached(serverIP)) {
    Serial.println(" * ERROR: no server IP; sample not sent");
    return false;
  }

  if (!client.connect(serverIP, SERVER_PORT)) {
    Serial.printf(" * Connect failed -> %s:%d\n", serverIP.toString().c_str(), SERVER_PORT);
    return false;
  }

  client.println(String(PAYLOAD_PREFIX) + payload);
  client.stop();

  Serial.printf(" * Sent -> %s:%d\n", serverIP.toString().c_str(), SERVER_PORT);
  return true;
}

// -------------------------------------------------------------------------------------------------
// I2C / sensor helpers
// -------------------------------------------------------------------------------------------------

static void i2cScan(TwoWire& bus, int sda, int scl, uint32_t hz, const char* tag) {
  bus.begin(sda, scl, hz);
  delay(50);

  Serial.printf("\nI2C scan on %s (SDA=%d, SCL=%d) @ %lu Hz:\n", tag, sda, scl, hz);

  uint8_t found = 0;
  for (uint8_t addr = 1; addr < 127; ++addr) {
    bus.beginTransmission(addr);
    if (bus.endTransmission() == 0) {
      Serial.printf(" * 0x%02X\n", addr);
      found++;
    }
    delay(2);
  }

  if (!found) Serial.println(" * No I2C devices found");
  bus.end();
}

static bool initSensors() {
  Serial.println("\nSensors:");

  I2C_SENSOR_BUS.begin(I2C_SDA, I2C_SCL, I2C_HZ);

  if (!bme.begin(ADDR_BME, &I2C_SENSOR_BUS)) {
    Serial.println(" * ERROR: BME280 not found");
    return false;
  }
  Serial.println(" * BME280 OK");

  if (!lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, ADDR_LM, &I2C_SENSOR_BUS)) {
    Serial.println(" * ERROR: BH1750 not found");
    return false;
  }
  Serial.println(" * BH1750 OK");

  if (!initSgp41()) {
    Serial.println(" * ERROR: SGP41 init failed");
    return false;
  }
  Serial.println(" * SGP41 OK");

  return true;
}

static bool initSgp41() {
  sgp41.begin(I2C_SENSOR_BUS);

  uint16_t error = 0;
  uint16_t serialNumber[3] = { 0, 0, 0 };

  error = sgp41.getSerialNumber(serialNumber);
  if (error) {
    printSensirionError("getSerialNumber", error);
    return false;
  }

  Serial.printf(" * SGP41 serial: 0x%04X%04X%04X\n", serialNumber[0], serialNumber[1], serialNumber[2]);

  uint16_t testResult = 0;
  error = sgp41.executeSelfTest(testResult);
  if (error) {
    printSensirionError("executeSelfTest", error);
    return false;
  }

  if (testResult != 0xD400) {
    Serial.printf(" * ERROR: SGP41 self-test failed: 0x%04X\n", testResult);
    return false;
  }

  Serial.println(" * SGP41 conditioning for 10 seconds");

  // Sensirion recommends 10 seconds of NOx conditioning after restart.
  // Do not exceed 10 seconds.
  for (uint8_t i = 0; i < 10; ++i) {
    const float rh = bme.readHumidity();
    const float tC = bme.readTemperature();
    uint16_t srawVoc = 0;

    error = sgp41.executeConditioning(sgp41RhTicks(rh), sgp41TempTicks(tC), srawVoc);
    if (error) {
      printSensirionError("executeConditioning", error);
      return false;
    }

    delay(1000);
  }

  return true;
}

static bool readSensors(Sample& s) {
  s.tC = bme.readTemperature();
  s.rh = bme.readHumidity();
  s.hPa = bme.readPressure() / 100.0f;
  s.lux = lightMeter.readLightLevel();

  const bool bmeBhOk = isfinite(s.tC) && isfinite(s.rh) && isfinite(s.hPa) && isfinite(s.lux);
  if (!bmeBhOk) {
    Serial.println(" * ERROR: BME280/BH1750 returned non-finite value(s)");
    return false;
  }

  s.sgp41Ok = readSgp41(s.rh, s.tC, s.srawVoc, s.srawNox);
  return true;
}

static bool readSgp41(const float rh, const float tC, uint16_t& srawVoc, uint16_t& srawNox) {
  uint16_t error = sgp41.measureRawSignals(sgp41RhTicks(rh), sgp41TempTicks(tC), srawVoc, srawNox);

  if (error) {
    printSensirionError("measureRawSignals", error);
    srawVoc = 0;
    srawNox = 0;
    return false;
  }

  return true;
}

static uint16_t sgp41RhTicks(float rh) {
  if (!isfinite(rh)) return 0x8000;  // Default: 50 %RH, compensation disabled-ish/defaulted.

  rh = constrain(rh, 0.0f, 100.0f);
  return (uint16_t)lroundf((rh * 65535.0f) / 100.0f);
}

static uint16_t sgp41TempTicks(float tC) {
  if (!isfinite(tC)) return 0x6666;  // Default: 25 °C.

  tC = constrain(tC, -45.0f, 130.0f);
  return (uint16_t)lroundf(((tC + 45.0f) * 65535.0f) / 175.0f);
}

static void printSensirionError(const char* action, uint16_t error) {
  char errorMessage[256];
  errorToString(error, errorMessage, sizeof(errorMessage));
  Serial.printf(" * ERROR: SGP41 %s failed: %s\n", action, errorMessage);
}

// -------------------------------------------------------------------------------------------------
// Logging / payload formatting
// -------------------------------------------------------------------------------------------------

static String toCSV(const Sample& s) {
  char buf[96];
  snprintf(buf,
           sizeof(buf),
           "%.2f,%.2f,%.2f,%.2f,%u,%u",
           s.tC,
           s.rh,
           s.hPa,
           s.lux,
           s.srawVoc,
           s.srawNox);

  return String(buf);
}

static void logSample(const Sample& s) {
  Serial.printf(" * Temperature:   %.2f °C\n", s.tC);
  Serial.printf(" * Humidity:      %.2f %%\n", s.rh);
  Serial.printf(" * Pressure:      %.2f hPa\n", s.hPa);
  Serial.printf(" * Light:         %.2f lx\n", s.lux);

  if (s.sgp41Ok) {
    Serial.printf(" * SGP41 VOC raw: %u\n", s.srawVoc);
    Serial.printf(" * SGP41 NOx raw: %u\n", s.srawNox);
  } else {
    Serial.println(" * SGP41:         read failed; logged 0,0");
  }
}

// -------------------------------------------------------------------------------------------------
// Arduino setup / loop
// -------------------------------------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("[ BOOT ] Belladonna greenhouse/weather node");

  i2cScan(I2C_SENSOR_BUS, I2C_SDA, I2C_SCL, I2C_HZ, "SENSOR BUS");

  if (!initSensors()) {
    Serial.println("\nFatal sensor init failure. Check wiring, I2C addresses, and library installs.");
    while (true) delay(1000);
  }

  if (waitForWiFi(WIFI_CONNECT_TIMEOUT_MS)) {
    initTime();
    startMDNS();
    testServerConnOnce();
  } else {
    Serial.println(" * Continuing without WiFi; will retry in loop");
  }

  g_lastSampleMs = millis() - SAMPLE_INTERVAL_MS;  // Take first sample immediately.

  Serial.println("\n[ READY ] Sampling started");
}

void loop() {
  const uint32_t now = millis();

  if (WiFi.status() != WL_CONNECTED) {
    waitForWiFi(WIFI_RECONNECT_TIMEOUT_MS);
  }

  if (now - g_lastSampleMs >= SAMPLE_INTERVAL_MS) {
    g_lastSampleMs = now;

    Sample s;
    if (readSensors(s)) {
      struct tm tmNow;
      if (getLocalTime(&tmNow)) {
        char ts[32];
        strftime(ts, sizeof(ts), "%Y-%m-%d %H:%M:%S", &tmNow);
        Serial.printf("\n[%s]\n", ts);
      } else {
        Serial.printf("\n[uptime %lu ms]\n", millis());
      }

      logSample(s);
      sendToServer(toCSV(s));
    }
  }

  delay(10);
}
