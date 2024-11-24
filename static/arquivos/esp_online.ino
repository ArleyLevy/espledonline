#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <WiFiClientSecure.h>

// Configurações da rede Wi-Fi
const char* ssid = "MILLENA";
const char* password = "millena1612";

// Configurações do broker MQTT
const char* mqtt_server = "1ef481efbcb74c5cba041287bb4703c0.s1.eu.hivemq.cloud";
const char* mqtt_username = "apiespled";
const char* mqtt_password = "Apiespled123.";
const int mqtt_port = 8883;

WiFiClientSecure wifiClient;
PubSubClient client(wifiClient);

// Pines dos LEDs
const int ledPins[] = {25, 26, 27, 33};  // GPIOs válidos
bool ledState[] = {false, false, false, false};

// Pines dos botões
const int buttonPins[] = {21, 22, 23, 32};  // GPIOs válidos
bool lastButtonState[] = {false, false, false, false}; // Último estado do botão
unsigned long lastDebounceTime[] = {0, 0, 0, 0};       // Para debounce
const unsigned long debounceDelay = 50;               // Tempo de debounce (50ms)

// Tópicos MQTT
const char* topic_command = "home/esp32/leds";
const char* topic_status = "home/esp32/status";

// Conexão Wi-Fi
void setupWiFi() {
  Serial.print("Conectando ao Wi-Fi");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWi-Fi conectado!");
}

// Callback do MQTT
void callback(char* topic, byte* payload, unsigned int length) {
  Serial.print("Mensagem recebida no tópico: ");
  Serial.println(topic);

  StaticJsonDocument<256> doc;
  DeserializationError error = deserializeJson(doc, payload, length);

  if (error) {
    Serial.println("Erro ao processar JSON recebido!");
    return;
  }

  // Atualiza os estados dos LEDs conforme mensagem recebida
  for (int i = 0; i < 4; i++) {
    String ledKey = "led" + String(i + 1);
    if (doc.containsKey(ledKey)) {
      bool newState = doc[ledKey];
      ledState[i] = newState;
      digitalWrite(ledPins[i], ledState[i] ? HIGH : LOW);
    }
  }
}

// Envia o status dos LEDs
void enviarStatus() {
  StaticJsonDocument<256> doc;
  for (int i = 0; i < 4; i++) {
    doc["led" + String(i + 1)] = ledState[i];
  }

  char buffer[256];
  size_t n = serializeJson(doc, buffer);
  client.publish(topic_status, buffer, n);
}

// Reconexão MQTT
void reconnectMQTT() {
  while (!client.connected()) {
    Serial.print("Reconectando ao MQTT...");
    if (client.connect("ESP32Client", mqtt_username, mqtt_password)) {
      Serial.println("Conectado!");
      client.subscribe(topic_command);
    } else {
      Serial.print("Falha. Tentando novamente em 5 segundos...");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);

  // Configuração dos LEDs
  for (int i = 0; i < 4; i++) {
    pinMode(ledPins[i], OUTPUT);
    digitalWrite(ledPins[i], LOW);
  }

  // Configuração dos botões
  for (int i = 0; i < 4; i++) {
    pinMode(buttonPins[i], INPUT_PULLUP); // Habilita resistor interno de pull-up
  }

  setupWiFi();

  wifiClient.setInsecure();  // TLS sem validação de certificado
  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(callback);

  reconnectMQTT();
}

void loop() {
  if (!client.connected()) {
    reconnectMQTT();
  }
  client.loop();

  // Verifica os botões com debounce
  for (int i = 0; i < 4; i++) {
    int leitura = digitalRead(buttonPins[i]);
    if (leitura == LOW && lastButtonState[i] == HIGH && (millis() - lastDebounceTime[i] > debounceDelay)) {
      lastDebounceTime[i] = millis();
      ledState[i] = !ledState[i];
      digitalWrite(ledPins[i], ledState[i] ? HIGH : LOW);
      enviarStatus(); // Publica o novo estado do LED
      Serial.println("Botão " + String(i + 1) + " pressionado");
    }
    lastButtonState[i] = leitura;
  }
}
