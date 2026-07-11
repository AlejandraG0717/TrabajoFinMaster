// ============================================================
// MQTT.ino — SolarMon con publicación de topología
// ============================================================

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <Preferences.h>

#include "MCV03.h"
#include "STATUS.h"
#include "CONFIG.h"
#include "COMS.h"
#include "MESH_HYBRID.h"
#include "PERTURB.h"

Preferences p;

// -------------------- WiFi --------------------
const char* ssid = "";
const char* password = "";

// -------------------- MQTT --------------------
const char* mqtt_server = "";
const int mqtt_port = 8883;
const char* mqtt_user = "";
const char* mqtt_password = "";

WiFiClientSecure espClient;
PubSubClient client(espClient);

// -------------------- SUPERNOVA Topics --------------------
const char* TOPIC_STATUS  = "STATUS";
const char* TOPIC_CONFIG  = "CONFIG";
const char* TOPIC_REQUEST = "REQUEST";
const char* TOPIC_DATA    = "DATA";

// -------------------- Identificación del nodo --------------------
String PVSx = "EMPTY";
String uC_name = "A";

static uint32_t lastHeartbeat = 0;
const uint32_t HEARTBEAT_INTERVAL_MS = 20000;  

// ============================================================
// BUFFER DE MENSAJES PENDIENTES (cuando MQTT desconectado)
// ============================================================
#define MAX_PENDING_MSGS 10
struct PendingMsg {
    String topic;
    String payload;
    uint32_t timestamp;
};
PendingMsg pendingMsgs[MAX_PENDING_MSGS];
int pendingCount = 0;

void addPendingMessage(const String& topic, const String& payload) {
    if (pendingCount >= MAX_PENDING_MSGS) {
        // Desplazar y descartar el más antiguo
        for (int i = 0; i < MAX_PENDING_MSGS - 1; i++) {
            pendingMsgs[i] = pendingMsgs[i + 1];
        }
        pendingCount = MAX_PENDING_MSGS - 1;
    }
    pendingMsgs[pendingCount] = {topic, payload, millis()};
    pendingCount++;
    Serial.printf("[MQTT] Mensaje pendiente agregado (%d/%d): %s\n", 
                  pendingCount, MAX_PENDING_MSGS, topic.c_str());
}

void flushPendingMessages() {
    if (!client.connected() || pendingCount == 0) return;

    Serial.printf("[MQTT] Enviando %d mensajes pendientes...\n", pendingCount);
    int enviados = 0;
    for (int i = 0; i < pendingCount; i++) {
        if (client.publish(pendingMsgs[i].topic.c_str(), pendingMsgs[i].payload.c_str())) {
            enviados++;
        } else {
            Serial.printf("[MQTT] Fallo al enviar pendiente: %s\n", pendingMsgs[i].topic.c_str());
        }
        delay(20);  // Pequeña pausa entre publicaciones
    }
    pendingCount = 0;
    Serial.printf("[MQTT] %d/%d mensajes pendientes enviados\n", enviados, pendingCount + enviados);
}

// ============================================================
// Publicación de la curva IV desde los buffers de medición
// ============================================================

void publishDataIV_fromBuffers() {
    int blockSize  = 25;
    int totalBlocks = (totalMuestras + blockSize - 1) / blockSize;

    for (int b = 0; b < totalBlocks; b++) {
        int start = b * blockSize;
        int end   = min(start + blockSize, totalMuestras);

        String sV = "", sI = "";
        for (int i = start; i < end; i++) {
            sV += String(BufferB[i]);   // voltaje (BufferB, ya corregido)
            sI += String(BufferA[i]);   // corriente (BufferA)
            if (i < end - 1) { sV += ","; sI += ","; }
        }

        String TOPIC  = PVSx + "/" + TOPIC_DATA;
        String msgOut = PVSx + "//" + uC_name + "//IVP//" +
                        String(b + 1) + "//" + String(totalBlocks) + "//" +
                        sV + "//" + sI;

        mesh_publicar(TOPIC, msgOut);
        delay(50);
    }
}

// ============================================================
// Conexión WiFi
// ============================================================

void setup_wifi() {
    Serial.print("MAC del dispositivo: ");
    Serial.println(WiFi.macAddress());
}

// ============================================================
// Reconexión MQTT
// ============================================================

void reconnect() {
    static uint32_t tsIntento = 0;
    uint32_t now = millis();

    if (client.connected()) return;
    if (WiFi.status() != WL_CONNECTED) {
      tsIntento = now;
      return;
    }

    if (now - tsIntento < 5000) return;
    tsIntento = now;

    Serial.println("Conectando a MQTT...");

    String clientId = "SolarMon_" + uC_name + "_" + String(now % 1000);

    if (client.connect(clientId.c_str(), mqtt_user, mqtt_password)) {
        Serial.println("MQTT conectado.");

        String TOPIC_C = PVSx + "/" + TOPIC_CONFIG;
        String TOPIC_R = PVSx + "/" + TOPIC_REQUEST;

        client.subscribe(TOPIC_C.c_str());
        client.subscribe(TOPIC_R.c_str());
        client.subscribe("solar/malla/topologia");

        if (mesh_esGateway) {
            client.subscribe("+/REQUEST");
            client.subscribe("+/CONFIG");
            Serial.println(" - +/REQUEST y +/CONFIG (wildcard, para reenvío a otros nodos)");
        }

        Serial.println("Suscrito a:");
        Serial.println(" - " + TOPIC_C);
        Serial.println(" - " + TOPIC_R);
        Serial.println(" - solar/malla/topologia");

        // Enviar mensajes pendientes que se acumularon mientras estaba desconectado
        flushPendingMessages();

        publishStatusAvailable();

    } else {
        Serial.print("Fallo MQTT, rc=");
        Serial.print(client.state());
        Serial.println(" — reintentando en 5s");
    }
}

// ============================================================
// Handler para comandos recibidos por la malla (GATEWAY → NODO).
// ============================================================
void onComandoPorMalla(const String& topic, const String& msg) {
    Serial.println("\n===== MALLA → SolarMon (comando reenviado) =====");
    Serial.println("Topic: " + topic);
    Serial.println("Payload: " + msg);

    int p1 = msg.indexOf("//");
    int p2 = msg.indexOf("//", p1 + 2);
    if (p1 == -1 || p2 == -1) return;

    String mac = msg.substring(p1 + 2, p2);
    if (mac != uC_name) return;  // no es para este nodo

    Serial.println("Comando confirmado para este nodo.");

    callback(const_cast<char*>(topic.c_str()),
             (byte*)msg.c_str(),
             msg.length());
}

// ============================================================
// CALLBACK MQTT — Procesa todos los mensajes recibidos
// ============================================================

void callback(char* topic, byte* payload, unsigned int length) {

    String t = String(topic);
    String msg = "";

    for (int i = 0; i < length; i++) msg += (char)payload[i];

    Serial.println("\n===== MQTT → SolarMon =====");
    Serial.println("Topic recibido: " + t);
    Serial.println("Payload recibido: " + msg);

    // -------------------- Verificación de MAC --------------------
    int p1 = msg.indexOf("//");
    int p2 = msg.indexOf("//", p1 + 2);

    if (p1 == -1 || p2 == -1) return;

    String mac = msg.substring(p1 + 2, p2);

    if (mac != uC_name) {
        if (mesh_esGateway && (t.endsWith("/REQUEST") || t.endsWith("/CONFIG"))) {
            Serial.println("[MESH ] Comando para otro nodo, reenviando por malla → " + mac);
            mesh_reenviarComando(t, msg);
        } else {
            Serial.println("Mensaje ignorado: MAC no coincide.");
        }
        return;
    }

    String TOPIC_C = PVSx + "/" + TOPIC_CONFIG;
    String TOPIC_R = PVSx + "/" + TOPIC_REQUEST;

    // ============================================================
    // --------------------------- CONFIG --------------------------
    // ============================================================

    if (t == TOPIC_C) {

        // Asignación de PVSx desde EMPTY
        if (msg.startsWith("EMPTY//")) {
            PVSx = msg.substring(p2 + 2);

            p.begin("CONFIG", false);
            p.putString("PVSx_NV", PVSx);
            p.end();

            Serial.println("Nuevo PVSx asignado: " + PVSx);

            publishStatusAvailable();
        }

        // Check → responder Available
        else if (msg.endsWith("//Check")) {
            publishStatusAvailable();
        }

        // Monit → devolver parámetros de monitorización
        else if (msg.endsWith("//Monit")) {
            Serial.println("Enviando parámetros de monitorización...");

            p.begin("CONFIG", false);
            int nm = p.getInt("num_muestras", 98);
            int ut = p.getInt("umbral_trigger", 200);
            float cap = p.getFloat("cap", 0.0);
            float del = p.getFloat("del", 0.0);
            float Rs = p.getFloat("ref_Rs", 0.0);
            float Rsh = p.getFloat("ref_Rsh", 0.0);
            float I0 = p.getFloat("ref_I0", 0.0);
            p.end();

            String TOPIC = PVSx + "/" + TOPIC_STATUS;
            String msgOut = PVSx + "//" + uC_name + "//Monit//" +
                            String(nm) + "//" + String(ut) + "//" +
                            String(cap) + "//" + String(del) + "//" +
                            String(Rs) + "//" + String(Rsh) + "//" +
                            String(I0);

            mesh_publicar(TOPIC, msgOut);
        }

        // Coms → devolver parámetros de comunicación
        else if (msg.endsWith("//Coms")) {
            Serial.println("Enviando parámetros de comunicación...");

            String TOPIC = PVSx + "/" + TOPIC_STATUS;

            String msgOut = PVSx + "//" + uC_name + "//Coms//" +
                            ssid + "//" + password + "//" +
                            mqtt_server + "//" + String(mqtt_port) + "//" +
                            mqtt_user + "//" + mqtt_password;

            mesh_publicar(TOPIC, msgOut);
        }

        // Reset → reiniciar el ESP32
        else if (msg.endsWith("//Reset")) {
            PVSx = "EMPTY";
            p.begin("CONFIG", false);         
            p.putString("PVSx_NV", PVSx);
            p.end();
            publishStatusAvailable();
            String TOPIC_C = PVSx + "/" + TOPIC_CONFIG;
            client.subscribe(TOPIC_C.c_str());
        }
    }

    // ============================================================
    // --------------------------- REQUEST -------------------------
    // ============================================================

    else if (t == TOPIC_R) {

        // IV → curva completa
        if (msg.endsWith("//IV")) { 
          Serial.println("Ejecutando monitorización IV..."); 
          MONI_BJT_nuevo("MO");
          publishDataIV_fromBuffers();
        }

        else if (msg.endsWith("//IV23")) {
          Serial.println("Ejecutando monitorización IV 2/3...");
          MONI_BJT_nuevo("MO23");
          publishDataIV_fromBuffers();

        }

        else if (msg.endsWith("//IV13")) {
            Serial.println("Ejecutando IV — 1/3 módulo (DescargaC)");
            MONI_BJT_nuevo("MO13");
            publishDataIV_fromBuffers();
        }

        // OP → punto de operación
        else if (msg.endsWith("//OP")) {
            Serial.println("Ejecutando OP...");
            const int NUM_MUESTRAS_I = 10;
            long sumaI = 0;
            for (int i = 0; i < NUM_MUESTRAS_I; i++) {
                sumaI += analogRead(I_string);
                delayMicroseconds(100);
            }
          
            int I = sumaI / NUM_MUESTRAS_I;

            int V = analogRead(V_MODULE);
            int V23 = analogRead(V23_MOD);
            int V13 = analogRead(V13_MOD);


            String TOPIC = PVSx + "/" + TOPIC_DATA;
            String msgOut = PVSx + "//" + uC_name + "//OP//" + String(V) + "//" + String(V23) + "//" + String(V13) + "//" + String(I);

            Serial.println("\n===== PUBLICADO A MQTT ====="); 
            Serial.println("Topic: " + TOPIC); 
            Serial.println("Payload: " + msgOut);

            mesh_publicar(TOPIC, msgOut);
        }

        // MPP → punto de máxima potencia estimado
        else if (msg.endsWith("//MPP")) {
            Serial.println("Ejecutando MPP...");

            const int NUM_MUESTRAS_I = 10;
            long sumaI = 0;
            for (int i = 0; i < NUM_MUESTRAS_I; i++) {
                sumaI += analogRead(I_string);
                delayMicroseconds(100);
            }
          
            int I = sumaI / NUM_MUESTRAS_I;
            int V = analogRead(V_MODULE);
            int P = V * I;

            String TOPIC = PVSx + "/" + TOPIC_DATA;
            String msgOut = PVSx + "//" + uC_name + "//MPP//" + String(V) + "//" + String(I) + "//" + String(P);

            mesh_publicar(TOPIC, msgOut);
        }

        // TGHI → temperatura + luminiscencia
        else if (msg.endsWith("//TGHI")) {
            Serial.println("Ejecutando TGHI...");

            leer_AT();

            int lum = BufferA[0];
            int lum2 = BufferA[1];
            int lum3 = BufferA[2];
            int lum4 = BufferA[3];

            int temp = BufferA[4];

            String TOPIC = PVSx + "/" + TOPIC_DATA;
            String msgOut = PVSx + "//" + uC_name + "//TGHI//" + String(lum) + "//" + String(lum2) + "//" + String(lum3) + "//" + String(lum4) + "//" +String(temp);

            mesh_publicar(TOPIC, msgOut);
        }

        // FULL → todas las mediciones juntas
        else if (msg.endsWith("//Full")) {
            Serial.println("Ejecutando FULL...");

            MONI_BJT_nuevo();
            leer_AT();

            String TOPIC = PVSx + "/" + TOPIC_DATA;

            String msgOut = PVSx + "//" + uC_name + "//FULL//";

            // Tensiones
            msgOut += "V:" + String(analogRead(V_MODULE)) + ",";
            msgOut += String(analogRead(V23_MOD)) + ",";
            msgOut += String(analogRead(V13_MOD)) + "//";

            // Corrientes
            msgOut += "I:" + String(analogRead(I_string)) + ",";
            msgOut += String(analogRead(VI)) + "//";

            // Luminiscencia
            msgOut += "L:" + String(BufferA[0]) + ",";
            msgOut += String(BufferA[1]) + ",";
            msgOut += String(BufferA[2]) + ",";
            msgOut += String(BufferA[3]) + "//";

            // Temperatura
            msgOut += "T:" + String(BufferA[4]);

            mesh_publicar(TOPIC, msgOut);
        }

        else if (msg.endsWith("//PERTURB")) {
            Serial.println("Ejecutando PERTURB (inyector)...");

            perturb_inyectar();

            String TOPIC = PVSx + "/" + TOPIC_DATA;

            mesh_publicar(TOPIC, PVSx + "//" + uC_name + "//PERTURB_TX");
        }

        else if (msg.endsWith("//PERTURB_LISTEN")) {
            Serial.println("Ejecutando PERTURB_LISTEN (oyente)...");

            int magnitud = 0;
            bool detectado = perturb_escuchar(magnitud);

            String TOPIC  = PVSx + "/" + TOPIC_DATA;
            String msgOut = PVSx + "//" + uC_name + "//PERTURB_RX//";

            if (detectado) {
                msgOut += "SI//" + String(magnitud);
                Serial.println("Resultado: DETECTADO, magnitud=" + String(magnitud));
            } else {
                msgOut += "NO";
                Serial.println("Resultado: NO DETECTADO");
            }

            mesh_publicar(TOPIC, msgOut);
        }

        else if (msg.endsWith("//LOCATE") || msg.endsWith("//Locate")) {
            Serial.println("Ejecutando Locate...");

            int rssiRouter = (WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : -100;

            String vecinos;
            if (mesh_modoActual == MESH_MODO_DIRECTO) {
                Serial.println("[LOCATE] Modo DIRECTO: usando scan WiFi para vecinos");
                vecinos = mesh_obtenerVecinosPorScan();
            } else {
                vecinos = mesh_obtenerVecinosRSSI();
            }

            String modo = mesh_nombreModo(mesh_modoActual);

            String TOPIC  = PVSx + "/" + TOPIC_DATA;
            String msgOut = PVSx + "//" + uC_name + "//LOCATE//"
                          + "RSSI_ROUTER:" + String(rssiRouter) + "//"
                          + "VECINOS:"     + vecinos + "//"
                          + "MODO:"        + modo    + "//"
                          + "STRING:"      + PVSx;

            Serial.println("[LOCATE] Respuesta: " + msgOut);
            mesh_publicar(TOPIC, msgOut);
        }
    }
}

// ============================================================
// PROCESAMIENTO DE MENSAJES DE LA MALLA (desde MESH_HYBRID)
// ============================================================

void procesarMensajeMalla(const String& topic, const String& payload) {
    Serial.println("\n===== MALLA → MQTT (Gateway) =====");
    Serial.println("Topic: " + topic);
    Serial.println("Payload: " + payload);

    if (!client.connected()) {
        Serial.println("[MALLA] MQTT no conectado, guardando en buffer pendiente");
        addPendingMessage(topic, payload);
        return;
    }

    bool ok = client.publish(topic.c_str(), payload.c_str());
    Serial.printf("[MALLA] Reenviado a MQTT: %s\n", ok ? "OK" : "FAIL");

    if (!ok) {
        addPendingMessage(topic, payload);
    }
}

// ============================================================
// SETUP — Inicialización del sistema
// ============================================================

void setup() {
    Serial.begin(115200);
    Serial.setRxBufferSize(1024);  // Aumentar buffer para logs de debug

    p.begin("CONFIG", false);
    PVSx = p.getString("PVSx_NV", "EMPTY");
    p.end();

    mesh_init(ssid, password, client, reconnect);
    mesh_onComandoRecibido(onComandoPorMalla);

    setup_wifi();
    uC_name = WiFi.macAddress();
    Serial.print("MAC REAL asignada a uC_name: ");
    Serial.println(uC_name);

    MCV03_setup();
    espClient.setInsecure();
    client.setServer(mqtt_server, mqtt_port);
    client.setCallback(callback);

    // Aumentar buffer MQTT para topología grande
    client.setBufferSize(4096);
    Serial.println("[MQTT] Buffer aumentado a 4096 bytes");

    Serial.println("Setup completo. Esperando eleccion de gateway...");
}

// ============================================================
// LOOP — Mantener viva la conexión MQTT
// ============================================================

void loop() {
    mesh_loop();

    uint32_t now = millis();
    if (now - lastHeartbeat >= HEARTBEAT_INTERVAL_MS) {
        lastHeartbeat = now;

        String TOPIC_HB = PVSx + "/" + TOPIC_STATUS;
        String msgHB    = PVSx + "//" + uC_name + "//HB//MESH_HB//" + mesh_nombreModo(mesh_modoActual);

        // CORRECCIÓN v2.1: Heartbeat condicional según modo de malla
        if (mesh_modoActual == MESH_MODO_DIRECTO) {
            // Modo DIRECTO: enviar directo por MQTT (tiene WiFi propia)
            if (client.connected()) {
                client.publish(TOPIC_HB.c_str(), msgHB.c_str());
                Serial.println("[HEARTBEAT] Enviado directo MQTT (DIRECTO): " + msgHB);
            } else {
                Serial.println("[HEARTBEAT] MQTT no conectado, heartbeat perdido");
            }
        } 
        else if (mesh_modoActual == MESH_MODO_GATEWAY) {
            // Modo GATEWAY: enviar directo por MQTT + por malla para nodos
            if (client.connected()) {
                client.publish(TOPIC_HB.c_str(), msgHB.c_str());
                Serial.println("[HEARTBEAT] Enviado directo MQTT (GATEWAY): " + msgHB);
            }
            // También enviar por malla para que otros nodos sepan que hay gateway activo
            mesh_publicar(TOPIC_HB, msgHB);
        } 
        else {
            // Modo NODO: enviar por malla (no tiene WiFi directa)
            mesh_publicar(TOPIC_HB, msgHB);
            Serial.println("[HEARTBEAT] Enviado por malla (NODO): " + msgHB);
        }

        // Si soy gateway, también publicar mi estado JSON directamente
        if (mesh_esGateway && client.connected()) {
            String estadoJSON = mesh_obtenerEstadoNodoJSON();
            client.publish(("solar/nodos/" + uC_name + "/estado").c_str(), 
                          estadoJSON.c_str());
            Serial.println("[HEARTBEAT] Estado JSON enviado directo (Gateway)");
        }
    }

    // Intentar enviar mensajes pendientes si MQTT se reconectó
    if (client.connected() && pendingCount > 0) {
        flushPendingMessages();
    }
}
