// ============================================================
//  MESH_HYBRID.cpp — Implementación
//============================================================

#include "MESH_HYBRID.h"
#include <ArduinoJson.h>
#include <WiFi.h>
#include "esp_wifi.h"  

// ══════════════════════════════════════════════════════════════
//  Variables públicas (definición)
// ══════════════════════════════════════════════════════════════

ModoMesh  mesh_modoActual  = MESH_MODO_NODO;
bool      mesh_esGateway   = false;
String    mesh_nodeID      = "";
String    mesh_idGateway   = "";
int       mesh_miRSSI      = -100;

MeshNodo  mesh_nodos[MESH_MAX_NODOS];
int       mesh_totalNodos  = 0;

// ══════════════════════════════════════════════════════════════
//  Variables privadas
// ══════════════════════════════════════════════════════════════

static painlessMesh   _mesh;
static Scheduler      _scheduler;

static PubSubClient*  _client       = nullptr;
static void         (*_reconnectFn)() = nullptr;
static void         (*_comandoFn)(const String&, const String&) = nullptr;

static const char*    _wifiSSID     = nullptr;
static const char*    _wifiPass     = nullptr;

static bool           _wifiAntes    = false;
static int            _rssiGateway  = -100;

// Mejor RSSI visto entre vecinos NO-gateway (evita que dos nodos sin
// gateway se postulen simultáneamente cuando ninguno lo es aún).
static int             _mejorRSSIVecinoNoGW = -100;
static uint32_t         _tsMejorRSSIVecino   = 0;
const uint32_t          VECINO_RSSI_VIGENCIA_MS = 12000;
static uint32_t       _tsAnuncioGW  = 0;
static int            _rssiEscaneado = -100;
static bool           _meshActiva   = false;

static bool           _enTransicion = false;

static volatile bool  _pedirActivarGW = false;
static uint32_t       _tsTransicion = 0;
static const uint32_t TRANSICION_COOLDOWN_MS = 3000;

static uint32_t       _tsEvalDirecto = 0;
static const uint32_t EVAL_DIRECTO_MS = 3000;

static uint32_t       _tsWifiDesconectado = 0;
static const uint32_t WIFI_DESCONECTADO_TIMEOUT_MS = 10000;

static uint32_t       _tsTopologia    = 0;
static const uint32_t TOPOLOGIA_INTERVALO_MS = 15000;

static uint32_t       _tsEvalGWPostulacion = 0;
static const uint32_t GW_POSTULACION_INTERVALO_MS = 5000;

// ══════════════════════════════════════════════════════════════
//  Declaraciones adelantadas
// ══════════════════════════════════════════════════════════════

static void _difundirRSSI();
static void _revisarRol();
static void _tomarGateway();
static void _cederGateway();
static void _activarModoDirecto();
static void _activarModoGateway();
static void _activarModoNodo();
static void _ajustarPotenciaAntena();
static void _reiniciarMalla();


static int _detectarCanalRouter() {
    WiFi.mode(WIFI_STA);
    delay(100);
    int n = WiFi.scanNetworks(false, true);
    int canal = 0;
    for (int i = 0; i < n; i++) {
        if (strcmp(WiFi.SSID(i).c_str(), _wifiSSID) == 0) {
            canal = WiFi.channel(i);
            Serial.printf("[MESH ] Canal del router detectado: %d\n", canal);
            break;
        }
    }
    WiFi.scanDelete();
    if (canal == 0) {
        Serial.println("[MESH ] No se detectó el router, usando canal 1 por defecto");
        canal = 1;
    }
    return canal;
}

static int _canalMallaFijo = 0;
static void _evaluarCambioDeModo();
static void _recibirMensaje(uint32_t from, String& msg);
static int  _medirRSSI();
static void _procesarScan();
static void _registrarNodo(uint32_t meshId, const String& nombre,
                            int rssi, bool gw, ModoMesh modo);
static String _obtenerTopologiaJSON();
static void _publicarTopologia();
static void _evaluarPostulacionGW();

static void _reenviarHeartbeatMQTT(const String& pvsx, const String& mac, 
                                   const String& modoStr);

// ══════════════════════════════════════════════════════════════
//  DECLARACIÓN EXTERNA: función en MQTT.ino para reenvío robusto
// ══════════════════════════════════════════════════════════════
extern void procesarMensajeMalla(const String& topic, const String& payload);

// ══════════════════════════════════════════════════════════════
//  TAREAS del Scheduler
// ══════════════════════════════════════════════════════════════

static Task _taskDifundir(MESH_INTERVALO_MS, TASK_FOREVER, &_difundirRSSI);
static Task _taskRevisar (MESH_INTERVALO_MS, TASK_FOREVER, &_revisarRol);

// ══════════════════════════════════════════════════════════════
//  UTILIDADES
// ══════════════════════════════════════════════════════════════

const char* mesh_nombreModo(ModoMesh m) {
    switch (m) {
        case MESH_MODO_DIRECTO:  return "DIRECTO";
        case MESH_MODO_GATEWAY:  return "GATEWAY";
        case MESH_MODO_NODO:     return "NODO";
        default:                 return "?";
    }
}

static ModoMesh _calcularModo(int rssi) {
    if (rssi < 0 && rssi > -110) {
        if (rssi > RSSI_DIRECTO)  return MESH_MODO_DIRECTO;
        if (rssi > RSSI_GATEWAY)  return MESH_MODO_GATEWAY;
    }
    return MESH_MODO_NODO;
}

static void _registrarNodo(uint32_t meshId, const String& nombre,
                            int rssi, bool gw, ModoMesh modo) {
    for (int i = 0; i < mesh_totalNodos; i++) {
        if (mesh_nodos[i].nombre == nombre) {
            mesh_nodos[i].meshId = meshId;
            mesh_nodos[i].rssi   = rssi;
            mesh_nodos[i].esGW   = gw;
            mesh_nodos[i].modo   = modo;
            mesh_nodos[i].lastSeen = millis();
            mesh_nodos[i].enMalla = true;
            return;
        }
    }
    if (mesh_totalNodos < MESH_MAX_NODOS) {
        mesh_nodos[mesh_totalNodos] = { meshId, nombre, rssi, gw, modo, millis(), true };
        mesh_totalNodos++;
    }
}

String mesh_nombreDesdeMeshId(uint32_t meshId) {
    for (int i = 0; i < mesh_totalNodos; i++)
        if (mesh_nodos[i].meshId == meshId) return mesh_nodos[i].nombre;
    char buf[12];
    snprintf(buf, sizeof(buf), "nodo#%u", meshId % 10000);
    return String(buf);
}

String mesh_obtenerVecinosRSSI() {
    String resultado = "";
    for (int i = 0; i < mesh_totalNodos; i++) {
        if (mesh_nodos[i].nombre == mesh_nodeID) continue;
        if (resultado.length() > 0) resultado += ",";
        resultado += mesh_nodos[i].nombre + "@" + String(mesh_nodos[i].rssi);
    }
    if (resultado.length() == 0) resultado = "NINGUNO";
    return resultado;
}

String mesh_obtenerVecinosPorScan() {
    Serial.println("[LOCATE] Iniciando scan WiFi bloqueante...");
    int n = WiFi.scanNetworks(false, true);  

    if (n <= 0) {
        Serial.println("[LOCATE] Scan sin resultados");
        return "NINGUNO";
    }

    String resultado = "";
    for (int i = 0; i < n; i++) {
        String ssid = WiFi.SSID(i);
        int    rssi = WiFi.RSSI(i);

        Serial.printf("[LOCATE] Red encontrada: SSID='%s' RSSI=%d\n", ssid.c_str(), rssi);

        if (ssid.startsWith(MESH_PREFIX)) {
            String nodeId = ssid.substring(String(MESH_PREFIX).length());
            int rssi = WiFi.RSSI(i);

            String nombreReal = "";
            for (int j = 0; j < mesh_totalNodos; j++) {
                char buf[12];
                snprintf(buf, sizeof(buf), "%X", mesh_nodos[j].meshId);
                if (nodeId.equalsIgnoreCase(String(buf))) {
                    nombreReal = mesh_nodos[j].nombre;
                    break;
                }
            }

            if (nombreReal.length() == 0) {
                nombreReal = "MESH_" + nodeId;
            }

            if (resultado.length() > 0) resultado += ",";
            resultado += nombreReal + "@" + String(rssi);
        }
    }

    WiFi.scanDelete();

    return resultado.length() > 0 ? resultado : "NINGUNO";
}

// ══════════════════════════════════════════════════════════════
//  TOPOLOGÍA DE LA MALLA EN JSON
// ══════════════════════════════════════════════════════════════

static String _obtenerTopologiaJSON() {
    StaticJsonDocument<4096> doc;

    doc["nodo_local"] = mesh_nodeID;
    doc["mesh_id_local"] = _mesh.getNodeId();
    doc["modo_local"] = mesh_nombreModo(mesh_modoActual);
    doc["es_gateway"] = mesh_esGateway;
    doc["rssi_local"] = mesh_miRSSI;
    doc["timestamp"] = millis();
    doc["wifi_conectado"] = (WiFi.status() == WL_CONNECTED);
    doc["ip_local"] = WiFi.localIP().toString();

    doc["gateway_id"] = mesh_idGateway.isEmpty() ? "NINGUNO" : mesh_idGateway;
    doc["gateway_rssi"] = _rssiGateway;

    String topoRaw = _mesh.subConnectionJson();
    JsonObject topologia = doc.createNestedObject("topologia_raw");
    if (topoRaw.length() > 0) {
        StaticJsonDocument<2048> topoDoc;
        DeserializationError err = deserializeJson(topoDoc, topoRaw);
        if (!err) {
            topologia.set(topoDoc.as<JsonObject>());
        } else {
            topologia["error"] = "No se pudo parsear topología interna";
            topologia["raw"] = topoRaw;
        }
    } else {
        topologia["error"] = "Topología no disponible";
    }

    JsonArray nodosArray = doc.createNestedArray("nodos_registrados");
    for (int i = 0; i < mesh_totalNodos; i++) {
        if (mesh_nodos[i].nombre == mesh_nodeID) continue;

        JsonObject nodo = nodosArray.createNestedObject();
        nodo["nombre"] = mesh_nodos[i].nombre;
        nodo["mesh_id"] = mesh_nodos[i].meshId;
        nodo["rssi"] = mesh_nodos[i].rssi;
        nodo["modo"] = mesh_nombreModo(mesh_nodos[i].modo);
        nodo["es_gateway"] = mesh_nodos[i].esGW;

        bool conectadoAhora = false;
        auto nodeList = _mesh.getNodeList();
        for (auto& id : nodeList) {
            if (id == mesh_nodos[i].meshId) {
                conectadoAhora = true;
                break;
            }
        }
        nodo["conectado_malla"] = conectadoAhora;

        uint32_t inactivo = millis() - mesh_nodos[i].lastSeen;
        nodo["ms_inactivo"] = inactivo;
        nodo["activo"] = (inactivo < 120000);
    }

    auto nodeList = _mesh.getNodeList();
    JsonArray nodosExtra = doc.createNestedArray("nodos_mesh_sin_beacon");
    for (auto& nodeId : nodeList) {
        String nombre = mesh_nombreDesdeMeshId(nodeId);
        bool conocido = false;
        for (int i = 0; i < mesh_totalNodos; i++) {
            if (mesh_nodos[i].meshId == nodeId) {
                conocido = true;
                break;
            }
        }
        if (!conocido && nombre != mesh_nodeID) {
            JsonObject nodo = nodosExtra.createNestedObject();
            nodo["nombre"] = nombre;
            nodo["mesh_id"] = nodeId;
            nodo["nota"] = "Presente en malla pero sin beacon RSSI reciente";
        }
    }

    doc["total_nodos_registrados"] = mesh_totalNodos;
    doc["total_nodos_malla"] = (int)nodeList.size() + 1;

    String resultado;
    serializeJson(doc, resultado);
    return resultado;
}

static void _publicarTopologia() {
    String json = _obtenerTopologiaJSON();

    if (mesh_esGateway && _client && _client->connected()) {
        String topic = "solar/malla/topologia";
        bool ok = _client->publish(topic.c_str(), json.c_str());
        Serial.printf("[MESH ] Topología publicada MQTT: %s\n", ok ? "OK" : "FAIL");
    }

    StaticJsonDocument<256> doc;
    doc["tipo"] = "topologia";
    doc["origen"] = mesh_nodeID;
    doc["payload"] = json;

    String msg;
    serializeJson(doc, msg);
    _mesh.sendBroadcast(msg);

    Serial.printf("[MESH ] Topología broadcast enviada (%d bytes)\n", msg.length());
}

String mesh_obtenerTopologiaJSON() {
    return _obtenerTopologiaJSON();
}

void mesh_publicarTopologia() {
    _publicarTopologia();
}

String mesh_obtenerEstadoNodoJSON() {
    String json = "{";
    json += "\"t\":\"estado_nodo\",";
    json += "\"id\":\"" + mesh_nodeID + "\",";
    json += "\"mid\":\"" + mesh_nodeID + "\",";  
    json += "\"rssi\":" + String(mesh_miRSSI) + ",";
    json += "\"m\":\"" + String(mesh_nombreModo(mesh_modoActual)) + "\",";
    json += "\"gw\":" + String(mesh_esGateway ? "true" : "false") + ",";
    json += "\"gw_id\":\"" + mesh_idGateway + "\",";
    json += "\"wifi\":" + String(WiFi.status() == WL_CONNECTED ? "true" : "false") + ",";
    json += "\"up\":" + String(millis());
    json += "}";
    return json;
}

// ══════════════════════════════════════════════════════════════
//  MEDIR RSSI
// ══════════════════════════════════════════════════════════════

static void _ajustarPotenciaAntena() {
    WiFi.setTxPower(WIFI_POWER_2dBm);
    Serial.println("[MESH ] Potencia WiFi ajustada a 2dBm (antena casera)");
}

static void _procesarScan() {
    int n = WiFi.scanComplete();
    if (n == WIFI_SCAN_RUNNING) return;
    if (n == WIFI_SCAN_FAILED || n == 0) {
        WiFi.scanDelete();
        WiFi.scanNetworks(true, true);
        return;
    }
    for (int i = 0; i < n; i++) {
        if (WiFi.SSID(i) == _wifiSSID) {
            int r = WiFi.RSSI(i);
            if (r < 0 && r > -110) _rssiEscaneado = r;
            break;
        }
    }
    WiFi.scanDelete();
    WiFi.scanNetworks(true, true);
}

static int _medirRSSI() {
    if (mesh_modoActual == MESH_MODO_DIRECTO) {
        if (WiFi.status() == WL_CONNECTED) {
            int r = WiFi.RSSI();
            if (r < 0 && r > -110) { _rssiEscaneado = r; return r; }
        }
        return _rssiEscaneado;
    }
    if (mesh_modoActual == MESH_MODO_GATEWAY) {
        if (WiFi.status() == WL_CONNECTED) {
            int r = WiFi.RSSI();
            if (r < 0 && r > -110) { _rssiEscaneado = r; return r; }
        }
        _procesarScan();
        return _rssiEscaneado;
    }
    return _rssiEscaneado;
}

// ══════════════════════════════════════════════════════════════
//  EVALUACIÓN Y TRANSICIÓN DE MODO
// ══════════════════════════════════════════════════════════════

static void _evaluarCambioDeModo() {
    if (_enTransicion) {
        uint32_t elapsed = millis() - _tsTransicion;
        if (elapsed < TRANSICION_COOLDOWN_MS) return;
        _enTransicion = false;
    }

    ModoMesh deseado = _calcularModo(mesh_miRSSI);
    if (deseado == mesh_modoActual) return;

    bool irADirecto = (deseado == MESH_MODO_DIRECTO) &&
                      (mesh_miRSSI > RSSI_DIRECTO + RSSI_HISTERESIS);
    bool irAGateway = (deseado == MESH_MODO_GATEWAY) && (
                      (mesh_modoActual == MESH_MODO_NODO    && mesh_miRSSI > RSSI_GATEWAY) ||
                      (mesh_modoActual == MESH_MODO_DIRECTO && mesh_miRSSI < RSSI_DIRECTO - RSSI_HISTERESIS));
    bool irANodo    = (deseado == MESH_MODO_NODO) &&
                      (mesh_miRSSI < RSSI_GATEWAY - RSSI_HISTERESIS);

    if (irADirecto) {
        Serial.printf("[MESH ] %s → DIRECTO (RSSI %d dBm)\n",
                      mesh_nombreModo(mesh_modoActual), mesh_miRSSI);
        _activarModoDirecto();
    } else if (irAGateway) {
        Serial.printf("[MESH ] %s → GATEWAY (RSSI %d dBm)\n",
                      mesh_nombreModo(mesh_modoActual), mesh_miRSSI);
        _activarModoGateway();
    } else if (irANodo) {
        Serial.printf("[MESH ] %s → NODO (RSSI %d dBm)\n",
                      mesh_nombreModo(mesh_modoActual), mesh_miRSSI);
        _activarModoNodo();
    }
}

// NUEVO: Evaluar si debemos postularnos como GW cuando no hay ninguno
static void _evaluarPostulacionGW() {
    if (mesh_modoActual != MESH_MODO_NODO) return;
    if (!mesh_idGateway.isEmpty()) return;  // Ya hay GW conocido
    if (_enTransicion) return;

    uint32_t ahora = millis();
    if (ahora - _tsEvalGWPostulacion < GW_POSTULACION_INTERVALO_MS) return;
    _tsEvalGWPostulacion = ahora;

    static uint32_t _tsArranqueModo = 0;
    if (_tsArranqueModo == 0) _tsArranqueModo = millis();
    if (ahora - _tsArranqueModo < 20000) {
        Serial.printf("[MESH ] Esperando estabilización malla (%lus/20s)...\n",
                      (ahora - _tsArranqueModo) / 1000);
        return;
    }

    bool datoVecinoVigente = (ahora - _tsMejorRSSIVecino) < VECINO_RSSI_VIGENCIA_MS;
    int  rssiPropio        = _rssiEscaneado;

    if (datoVecinoVigente && _mejorRSSIVecinoNoGW > (rssiPropio + RSSI_MARGEN_GW)) {
        Serial.printf("[MESH ] Vecino tiene mejor señal (%d vs mi %d) → le doy prioridad\n",
                      _mejorRSSIVecinoNoGW, rssiPropio);
        return;
    }

    if (rssiPropio > RSSI_GATEWAY && rssiPropio < 0) {
        mesh_miRSSI = rssiPropio;
        Serial.printf("[MESH ] No hay GW. Mi RSSI (%d) > umbral (%d). Solicitando GATEWAY...\n",
                     rssiPropio, RSSI_GATEWAY);
        _pedirActivarGW = true;
    } else {
        Serial.printf("[MESH ] No hay GW. Mi RSSI (%d) insuficiente para postular (umbral: %d). Esperando...\n",
                     rssiPropio, RSSI_GATEWAY);
    }
}

// ══════════════════════════════════════════════════════════════
//  ACTIVAR MODOS
// ══════════════════════════════════════════════════════════════

static void _activarModoDirecto() {
    if (_enTransicion) return;
    _enTransicion = true;
    _tsTransicion = millis();

    if (mesh_esGateway) _cederGateway();

    mesh_modoActual = MESH_MODO_DIRECTO;
    _wifiAntes      = false;
    _tsWifiDesconectado = 0;

    _taskDifundir.disable();
    _taskRevisar.disable();

    if (_meshActiva) {
        _mesh.stop();
        _meshActiva = false;
        delay(300);
    }

    WiFi.disconnect(true);
    delay(200);
    WiFi.mode(WIFI_STA);
    _ajustarPotenciaAntena();
    delay(100);
    WiFi.begin(_wifiSSID, _wifiPass);

    Serial.println("[MESH ] DIRECTO: Malla detenida, WiFi exclusivo para TLS");
}

static void _activarModoGateway() {
    if (_enTransicion) return;
    _enTransicion = true;
    _tsTransicion = millis();

    if (_meshActiva) {
        _mesh.stop();
        _meshActiva = false;
        delay(300);
    }
    WiFi.disconnect(true);
    delay(200);

    _reiniciarMalla();

    mesh_modoActual = MESH_MODO_GATEWAY;
    if (!_taskDifundir.isEnabled()) _taskDifundir.enable();
    if (!_taskRevisar.isEnabled())  _taskRevisar.enableDelayed(2000);

    Serial.println("[MESH ] GATEWAY: malla + WiFi + MQTT");
    _tomarGateway();
}

static void _activarModoNodo() {
    if (_enTransicion) return;
    _enTransicion = true;
    _tsTransicion = millis();

    if (mesh_esGateway) _cederGateway();

    mesh_modoActual = MESH_MODO_NODO;
    _reiniciarMalla();

    if (!_taskDifundir.isEnabled()) _taskDifundir.enable();
    if (!_taskRevisar.isEnabled())  _taskRevisar.enableDelayed(2000);

    _tsEvalGWPostulacion = millis();
    _mejorRSSIVecinoNoGW = -100;
    _tsMejorRSSIVecino   = 0;

    Serial.println("[MESH ] NODO: solo malla");
}

static void _reiniciarMalla() {
    WiFi.disconnect(true);   
    delay(100);
    WiFi.mode(WIFI_AP_STA);
    _ajustarPotenciaAntena();
    delay(100);

    if (_canalMallaFijo == 0) {
        _canalMallaFijo = _detectarCanalRouter();
    }

    _mesh.init(MESH_PREFIX, MESH_PASSWORD, &_scheduler, MESH_PORT,
               WIFI_AP_STA, _canalMallaFijo);
    _mesh.setRoot(false);
    _mesh.setContainsRoot(true);

    _mesh.onReceive(&_recibirMensaje);

    _mesh.onNewConnection([](uint32_t nodeId) {
        Serial.printf("[MESH ] Nodo unido: %s | Total: %d\n",
                      mesh_nombreDesdeMeshId(nodeId).c_str(),
                      (int)_mesh.getNodeList().size() + 1);
    });

    _mesh.onDroppedConnection([](uint32_t nodeId) {
        Serial.printf("[MESH ] Nodo salió: %s | Total: %d\n",
                      mesh_nombreDesdeMeshId(nodeId).c_str(),
                      (int)_mesh.getNodeList().size() + 1);
    });

    _mesh.onChangedConnections([]() {
        Serial.printf("[MESH ] Topología cambiada: %d nodos\n",
                      (int)_mesh.getNodeList().size() + 1);
    });

    _meshActiva = true;

    // Informar si hay nodos conocidos para reconectar
    if (mesh_totalNodos > 0) {
        int gwConocidos = 0;
        for (int i = 0; i < mesh_totalNodos; i++) {
            if (mesh_nodos[i].esGW) gwConocidos++;
        }
        Serial.printf("[MESH ] Malla reiniciada. Nodos conocidos: %d (GW: %d)\n",
                     mesh_totalNodos, gwConocidos);
    } else {
        Serial.println("[MESH ] Malla reiniciada. Esperando descubrimiento de nodos...");
    }

    delay(100);
}

// ══════════════════════════════════════════════════════════════
//  TOMAR / CEDER GATEWAY
// ══════════════════════════════════════════════════════════════

static void _tomarGateway() {
    mesh_esGateway   = true;
    mesh_idGateway   = mesh_nodeID;
    _rssiGateway     = mesh_miRSSI;
    _tsAnuncioGW     = millis();
    _wifiAntes       = false;

    _mesh.setRoot(true);
    _mesh.setContainsRoot(true);
    delay(100);
    _mesh.stationManual(_wifiSSID, _wifiPass);

    Serial.printf("[MESH ] Soy GATEWAY: %s (%d dBm)\n", mesh_nodeID.c_str(), mesh_miRSSI);
    Serial.println("[MESH ] Intentando conectar al WiFi...");
}

static void _cederGateway() {
    if (_client && _client->connected()) {
        _client->publish(("solar/nodos/" + mesh_nodeID + "/estado").c_str(),
                        "offline", true);
        _client->disconnect();
        delay(100);
    }

    mesh_esGateway    = false;
    mesh_idGateway    = "";
    _rssiGateway      = -100;
    _wifiAntes        = false;
    _mejorRSSIVecinoNoGW = -100;
    _tsMejorRSSIVecino   = 0;

    _mesh.setRoot(false);
    delay(100);
    WiFi.disconnect(false);
    Serial.printf("[MESH ] Gateway cedido (RSSI conservado: %d dBm)\n", mesh_miRSSI);
}

// ══════════════════════════════════════════════════════════════
//  DIFUNDIR RSSI
// ══════════════════════════════════════════════════════════════

static void _difundirRSSI() {
    mesh_miRSSI = _medirRSSI();

    if (mesh_modoActual == MESH_MODO_DIRECTO) return;

    StaticJsonDocument<256> doc;
    doc["tipo"]  = "rssi";
    doc["id"]    = mesh_nodeID;
    doc["mac"]   = WiFi.macAddress();
    doc["rssi"]  = mesh_miRSSI;
    doc["es_gw"] = mesh_esGateway;
    doc["modo"]  = mesh_nombreModo(mesh_modoActual);

    String msg;
    serializeJson(doc, msg);
    _mesh.sendBroadcast(msg);

    if (mesh_esGateway) {
        _tsAnuncioGW = millis();
        _rssiGateway = mesh_miRSSI;
    }

    Serial.printf("[MESH ] [%s] %s %d dBm | GW: %s (%d) | WiFi: %s | MQTT: %s | Nodos malla: %d\n",
                mesh_nombreModo(mesh_modoActual),
                mesh_nodeID.c_str(),
                mesh_miRSSI,
                mesh_idGateway.isEmpty() ? "NINGUNO" : mesh_idGateway.c_str(),
                _rssiGateway,
                WiFi.status() == WL_CONNECTED ? "OK" : "---",
                (_client && _client->connected()) ? "OK" : "---",
                (int)_mesh.getNodeList().size());

    _evaluarCambioDeModo();
}

// ══════════════════════════════════════════════════════════════
//  REVISAR ROL GATEWAY
// ══════════════════════════════════════════════════════════════

static void _revisarRol() {
    uint32_t ahora = millis();

    // === MODO NODO: verificar timeout del GW y postulación ===
    if (mesh_modoActual == MESH_MODO_NODO) {
        // Verificar si el GW conocido sigue activo
        if (!mesh_idGateway.isEmpty() && (ahora - _tsAnuncioGW) > MESH_TIMEOUT_GW_MS) {
            Serial.printf("[MESH ] GW %s perdido (timeout %lums)\n", 
                         mesh_idGateway.c_str(), ahora - _tsAnuncioGW);
            mesh_idGateway = "";
            _rssiGateway = -100;
        }

        // Si no hay GW, evaluar si debemos postularnos
        if (mesh_idGateway.isEmpty()) {
            _evaluarPostulacionGW();
        }
        return;
    }

    // === MODO GATEWAY: verificar si debo ceder ===
    if (mesh_modoActual == MESH_MODO_GATEWAY) {
        // Publicar topología periódicamente
        if (ahora - _tsTopologia >= TOPOLOGIA_INTERVALO_MS) {
            _tsTopologia = ahora;
            _publicarTopologia();
        }

        // Si mi señal cayó por debajo del umbral, ceder
        if (mesh_miRSSI < RSSI_GATEWAY - RSSI_HISTERESIS) {
            Serial.printf("[MESH ] Mi señal cayó a %d dBm (umbral GW: %d), cediendo GW...\n",
                         mesh_miRSSI, RSSI_GATEWAY);
            _cederGateway();
            _activarModoNodo();
        }
        return;
    }

    
}

// ══════════════════════════════════════════════════════════════
//  REENVÍO DE HEARTBEAT POR MQTT
// ══════════════════════════════════════════════════════════════

static void _reenviarHeartbeatMQTT(const String& pvsx, const String& mac, 
                                   const String& modoStr) {
    if (!mesh_esGateway) return;
    if (!_client || !_client->connected()) return;

    String topic = pvsx + "/STATUS";
    String payload = pvsx + "//" + mac + "//HB//MESH_HB//" + modoStr;

    bool ok = _client->publish(topic.c_str(), payload.c_str());
    Serial.printf("[MESH ] Heartbeat reenviado a MQTT: %s | %s -> %s\n", 
                  ok ? "OK" : "FAIL", mac.c_str(), topic.c_str());
}

// ══════════════════════════════════════════════════════════════
//  RECIBIR MENSAJES DE LA MALLA
// ══════════════════════════════════════════════════════════════

static void _recibirMensaje(uint32_t from, String& msg) {
    StaticJsonDocument<512> doc;
    if (deserializeJson(doc, msg) != DeserializationError::Ok) return;

    String tipo = doc["tipo"] | "";

    if (tipo == "topologia") {
        String origen = doc["origen"] | "desconocido";
        Serial.printf("[MESH ] Topología recibida de %s\n", origen.c_str());
        return;
    }

    if (tipo == "rssi") {
        String   idRemoto   = doc["id"]    | "";
        String macRemoto  = doc["mac"]   | ""; 
        int      rssiRemoto = doc["rssi"]  | -100;
        bool     esGWRemoto = doc["es_gw"] | false;
        String   modoStr    = doc["modo"]  | "NODO";

        if (idRemoto == mesh_nodeID) return;

        ModoMesh modoRemoto = MESH_MODO_NODO;
        if      (modoStr == "DIRECTO") modoRemoto = MESH_MODO_DIRECTO;
        else if (modoStr == "GATEWAY") modoRemoto = MESH_MODO_GATEWAY;

        String nombreClave = macRemoto.length() > 0 ? macRemoto : idRemoto;
        _registrarNodo(from, nombreClave, rssiRemoto, esGWRemoto, modoRemoto);

        Serial.printf("[MESH ] %s %d dBm [%s]%s\n",
                    idRemoto.c_str(), rssiRemoto,
                    modoStr.c_str(),
                    esGWRemoto ? " [GW]" : "");

        // Si NO es GW, verificar si debería serlo (yo soy GW y él tiene mejor señal)
        if (!esGWRemoto) {
            if (mesh_esGateway && rssiRemoto > (mesh_miRSSI + RSSI_MARGEN_GW)) {
                Serial.printf("[MESH ] %s tiene mejor señal (%d vs %d), cediendo GW...\n",
                             idRemoto.c_str(), rssiRemoto, mesh_miRSSI);
                _cederGateway();
                _activarModoNodo();
            }

            if (rssiRemoto > _mejorRSSIVecinoNoGW) {
                _mejorRSSIVecinoNoGW = rssiRemoto;
            }
            _tsMejorRSSIVecino = millis();

            return;  // No es GW, no procesar como gateway
        }

        // Si ES gateway, procesar normalmente
        bool gwNuevo = mesh_idGateway.isEmpty();
        bool esMismo = (mesh_idGateway == idRemoto);
        bool mejor   = (rssiRemoto > _rssiGateway);

        if (gwNuevo || esMismo || mejor) {
            mesh_idGateway = idRemoto;
            _rssiGateway   = rssiRemoto;
            _tsAnuncioGW   = millis();

            if (gwNuevo) {
                Serial.printf("[MESH ] GW descubierto: %s (%d dBm)\n",
                            mesh_idGateway.c_str(), _rssiGateway);
            }
        }

        // Si soy GW y este otro GW me supera, ceder (conflicto de GW)
        if (mesh_esGateway && mesh_miRSSI < 0 && mesh_miRSSI > -110 &&
            rssiRemoto > (mesh_miRSSI + RSSI_MARGEN_GW)) {
            Serial.printf("[MESH ] %s GW me supera (%d vs %d), cediendo...\n",
                        idRemoto.c_str(), rssiRemoto, mesh_miRSSI);
            _cederGateway();
            _activarModoNodo();
        }
        return;
    }

    // Reenvío de heartbeats que vienen por malla
    if (tipo == "heartbeat") {
        String pvsxHb = doc["pvsx"] | "EMPTY";
        String macHb  = doc["mac"]  | "";
        String modoHb = doc["modo"] | "NODO";

        Serial.printf("[MESH ] Heartbeat recibido de %s (%s) por malla\n", 
                      macHb.c_str(), pvsxHb.c_str());

        // Si soy gateway, reenviar por MQTT
        if (mesh_esGateway) {
            _reenviarHeartbeatMQTT(pvsxHb, macHb, modoHb);
        } else {
            // Si no soy gateway, propagar hacia el gateway
            Serial.println("[MESH ] Propagando heartbeat hacia gateway...");
        }
        return;
    }

    // Reenvío robusto de mensajes "data" al broker MQTT
    if (tipo == "data" && mesh_esGateway) {
        String topic   = doc["topic"]   | "";
        String payload = doc["payload"] | "";
        if (topic.isEmpty() || payload.isEmpty()) return;
        Serial.printf("[MESH ] Reenviando datos de nodo remoto → MQTT: %s\n", topic.c_str());
        procesarMensajeMalla(topic, payload);
        return;
    }

    if (tipo == "comando") {
        String topic   = doc["topic"]   | "";
        String payload = doc["payload"] | "";
        if (topic.isEmpty() || payload.isEmpty()) return;
        Serial.printf("[MESH ] Comando recibido por malla: %s\n", payload.c_str());
        if (_comandoFn) _comandoFn(topic, payload);
        return;
    }
}

// ══════════════════════════════════════════════════════════════
//  API PÚBLICA: reenvío de comandos (GATEWAY → NODO por malla)
// ══════════════════════════════════════════════════════════════

void mesh_onComandoRecibido(void (*fn)(const String&, const String&)) {
    _comandoFn = fn;
}

void mesh_reenviarComando(const String& topic, const String& payload) {
    if (!mesh_esGateway || !_meshActiva) return;
    StaticJsonDocument<512> doc;
    doc["tipo"]    = "comando";
    doc["topic"]   = topic;
    doc["payload"] = payload;
    String msg;
    serializeJson(doc, msg);
    _mesh.sendBroadcast(msg);
    Serial.printf("[MESH ] Comando reenviado por malla: %s\n", payload.c_str());
}

// ══════════════════════════════════════════════════════════════
//  API PÚBLICA: mesh_publicar()
// ══════════════════════════════════════════════════════════════

void mesh_publicar(const String& topic, const String& payload) {
    bool esHeartbeat = payload.indexOf("//HB") >= 0;

    if (esHeartbeat) {
        // Extraer PVSx, MAC y modo del payload
        int p1 = payload.indexOf("//");
        int p2 = payload.indexOf("//", p1 + 2);
        int p3 = payload.indexOf("//", p2 + 2);
        int p4 = payload.indexOf("//", p3 + 2);

        String pvsxHb = payload.substring(0, p1);
        String macHb  = payload.substring(p1 + 2, p2);
        String modoHb = (p4 > 0) ? payload.substring(p4 + 2) : mesh_nombreModo(mesh_modoActual);

        // Si soy DIRECTO: la malla está detenida, NO intentar enviar por malla
        if (mesh_modoActual == MESH_MODO_DIRECTO) {
            Serial.println("[MESH ] DIRECTO: Heartbeat debe enviarse por MQTT directo, no por malla");
            return;  // El código en MQTT.ino ya se encarga de enviar por client.publish()
        }

        // Si soy GATEWAY: enviar directo por MQTT y también por malla (para visibilidad)
        if (mesh_modoActual == MESH_MODO_GATEWAY) {
            if (_client && _client->connected()) {
                _client->publish(topic.c_str(), payload.c_str());
                Serial.printf("[MESH ] Gateway: Heartbeat enviado directo MQTT: %s\n", macHb.c_str());
            }
        }

        // Enviar por malla (NODO siempre, GATEWAY también para visibilidad)
        // Esto permite que otros nodos sepan que este nodo sigue activo
        StaticJsonDocument<256> doc;
        doc["tipo"]  = "heartbeat";
        doc["pvsx"]  = pvsxHb;
        doc["mac"]   = macHb;
        doc["modo"]  = modoHb;
        doc["topic"] = topic;
        doc["payload"] = payload;

        String msg;
        serializeJson(doc, msg);
        _mesh.sendBroadcast(msg);

        Serial.printf("[MESH ] Heartbeat enviado por malla: %s\n", macHb.c_str());
        return;
    }

    // Para mensajes NO heartbeat (datos normales):

    if (mesh_modoActual == MESH_MODO_DIRECTO) {
        if (WiFi.status() == WL_CONNECTED && _client) {
            if (!_client->connected() && _reconnectFn) _reconnectFn();
            if (_client->connected()) {
                _client->publish(topic.c_str(), payload.c_str());
                return;
            }
        }
        Serial.println("[MESH ] DIRECTO: Sin WiFi/MQTT, mensaje perdido");
        return;
    }

    if (mesh_modoActual == MESH_MODO_GATEWAY && WiFi.status() == WL_CONNECTED && _client) {
        if (!_client->connected() && _reconnectFn) _reconnectFn();
        if (_client->connected()) {
            _client->publish(topic.c_str(), payload.c_str());
            return;
        }
    }

    StaticJsonDocument<512> doc;
    doc["tipo"]    = "data";
    doc["topic"]   = topic;
    doc["payload"] = payload;

    String msg;
    serializeJson(doc, msg);
    _mesh.sendBroadcast(msg);
    Serial.println("[MESH ] Datos enviados por malla → gateway");
}

// ══════════════════════════════════════════════════════════════
//  API PÚBLICA: mesh_init()
// ══════════════════════════════════════════════════════════════

void mesh_init(const char* wifiSSID,
               const char* wifiPass,
               PubSubClient& client,
               void (*reconnectFn)()) {
    _wifiSSID   = wifiSSID;
    _wifiPass   = wifiPass;
    _client     = &client;
    _reconnectFn = reconnectFn;

    mesh_nodeID = "ESP32_" + String((uint32_t)ESP.getEfuseMac(), HEX);
    for (auto& c : mesh_nodeID) c = toupper(c);

    Serial.println();
    Serial.println("================================");
    Serial.println("  MESH_HYBRID v6.4 - " + mesh_nodeID);
    Serial.println("================================");
    Serial.printf("  DIRECTO  si RSSI > %d dBm\n",  RSSI_DIRECTO);
    Serial.printf("  GATEWAY  si RSSI > %d dBm\n",  RSSI_GATEWAY);
    Serial.printf("  NODO     si RSSI < %d dBm\n",  RSSI_GATEWAY);
    Serial.println("================================");

    _reiniciarMalla();

    Serial.printf("[MESH ] Escaneando '%s' (bloqueante inicial)...\n", wifiSSID);
    int n = WiFi.scanNetworks(false, true);
    if (n > 0) {
        for (int i = 0; i < n; i++) {
            if (WiFi.SSID(i) == wifiSSID) {
                _rssiEscaneado = WiFi.RSSI(i);
                mesh_miRSSI = _rssiEscaneado;
                Serial.printf("[MESH ] RSSI inicial: %d dBm\n", mesh_miRSSI);
                break;
            }
        }
    }
    WiFi.scanDelete();

    ModoMesh modoInicial = _calcularModo(mesh_miRSSI);
    if (modoInicial == MESH_MODO_DIRECTO) {
        _activarModoDirecto();
    } else if (modoInicial == MESH_MODO_GATEWAY) {
        _activarModoGateway();
    } else {
        _activarModoNodo();
    }

    WiFi.scanNetworks(true, true);
    Serial.printf("[MESH ] Escaneo asíncrono iniciado para mediciones posteriores\n");

    _scheduler.addTask(_taskDifundir);
    _scheduler.addTask(_taskRevisar);

    _taskDifundir.enable();
    _taskRevisar.enableDelayed(5000);

    Serial.println("[MESH ] Iniciado. Modo inicial evaluado por RSSI.");
}

// ══════════════════════════════════════════════════════════════
//  API PÚBLICA: mesh_loop()
// ══════════════════════════════════════════════════════════════

void mesh_loop() {
    if (_meshActiva) {
        _mesh.update();
    }

    if (mesh_modoActual == MESH_MODO_DIRECTO) {
        uint32_t now = millis();
        if (now - _tsEvalDirecto >= EVAL_DIRECTO_MS) {
            _tsEvalDirecto = now;
            if (_enTransicion) {
                if ((now - _tsTransicion) >= TRANSICION_COOLDOWN_MS) {
                    Serial.println("[MESH ] [DIRECTO-EVAL] Cooldown terminado");
                    _enTransicion = false;
                }
            }
            if (!_enTransicion) {
                int prev = mesh_miRSSI;
                mesh_miRSSI = _medirRSSI();
                if (prev != mesh_miRSSI)
                    Serial.printf("[MESH ] [DIRECTO-EVAL] RSSI: %d → %d dBm\n", prev, mesh_miRSSI);
                if (WiFi.status() != WL_CONNECTED) {
                    if (_tsWifiDesconectado == 0) _tsWifiDesconectado = now;
                    else if (now - _tsWifiDesconectado > WIFI_DESCONECTADO_TIMEOUT_MS) {
                        Serial.println("[MESH ] [DIRECTO-EVAL] WiFi >10s caído → NODO");
                        mesh_miRSSI = -100; _tsWifiDesconectado = 0;
                    }
                } else { _tsWifiDesconectado = 0; }
                _evaluarCambioDeModo();
            }
        }
    }

    static uint32_t tsMqttDirecto = 0;
    if (mesh_modoActual == MESH_MODO_DIRECTO) {
        uint32_t now = millis();
        if (now - tsMqttDirecto >= 5000) {
            tsMqttDirecto = now;
            if (_client && _reconnectFn) {
                wl_status_t ws = WiFi.status();
                if (ws != WL_CONNECTED && ws != WL_IDLE_STATUS) {
                    WiFi.disconnect(true); delay(50); WiFi.begin(_wifiSSID, _wifiPass);
                }
            }
        }
    }

    bool tieneWifi = (WiFi.status() == WL_CONNECTED);

    // ── MODO GATEWAY: watchdog WiFi ───────────────────────────────────────────
    static uint32_t tsGatewayStart = 0;
    if (mesh_modoActual == MESH_MODO_GATEWAY && !tieneWifi) {
        if (tsGatewayStart == 0) tsGatewayStart = millis();
        else if (millis() - tsGatewayStart > 10000) {
            Serial.println("[MESH ] GATEWAY: WiFi no conecta tras 10s, reconectando...");
            WiFi.reconnect();
            tsGatewayStart = millis();
        }
    } else { tsGatewayStart = 0; }

    static uint32_t tsScanNodo    = 0;
    static bool     scanPendiente = false;

    if (mesh_modoActual == MESH_MODO_NODO) {
        if (!scanPendiente && millis() - tsScanNodo >= 20000) {
            tsScanNodo    = millis();
            scanPendiente = true;
            wifi_scan_config_t cfg = {};
            cfg.ssid        = (uint8_t*)_wifiSSID;
            cfg.bssid       = nullptr;
            cfg.channel     = 0;
            cfg.show_hidden = false;
            cfg.scan_type   = WIFI_SCAN_TYPE_PASSIVE;
            cfg.scan_time.passive = 120;
            if (esp_wifi_scan_start(&cfg, false) != ESP_OK) scanPendiente = false;
        }
        if (scanPendiente) {
            uint16_t n = 0;
            if (esp_wifi_scan_get_ap_num(&n) == ESP_OK && n > 0) {
                scanPendiente = false;
                wifi_ap_record_t* recs = new wifi_ap_record_t[n];
                if (recs && esp_wifi_scan_get_ap_records(&n, recs) == ESP_OK) {
                    for (int i = 0; i < n; i++) {
                        if (strcmp((char*)recs[i].ssid, _wifiSSID) == 0) {
                            int r = recs[i].rssi;
                            if (r < 0 && r > -110) {
                                _rssiEscaneado = r;
                                mesh_miRSSI    = r;
                                Serial.printf("[MESH ] [NODO] Scan pasivo: RSSI router = %d dBm\n", r);
                            }
                            break;
                        }
                    }
                }
                delete[] recs;
            }
        }
    }

    // ── MODO NODO: procesar bandera _pedirActivarGW (seguro fuera del scheduler) ─
    if (_pedirActivarGW && mesh_modoActual == MESH_MODO_NODO && !_enTransicion) {
        _pedirActivarGW = false;
        if (_rssiEscaneado > RSSI_GATEWAY && _rssiEscaneado < 0) {
            mesh_miRSSI = _rssiEscaneado;
            Serial.printf("[MESH ] [mesh_loop] Activando GATEWAY (RSSI %d dBm)\n", mesh_miRSSI);
            _activarModoGateway();
        }
    }

    // ── MODO NODO: watchdog sin gateway (40s) ────────────────────────────────
    static uint32_t tsNodoSinGW = 0;
    if (mesh_modoActual == MESH_MODO_NODO) {
        bool sinGW = mesh_idGateway.isEmpty() ||
                     (millis() - _tsAnuncioGW) > (MESH_TIMEOUT_GW_MS * 2);
        if (sinGW) {
            if (tsNodoSinGW == 0) tsNodoSinGW = millis();
            if (millis() - tsNodoSinGW > 40000) {
                tsNodoSinGW = 0;
                if (_rssiEscaneado > RSSI_GATEWAY && _rssiEscaneado < 0) {
                    Serial.printf("[MESH ] [NODO] >40s sin GW, señal %d dBm → GATEWAY\n", _rssiEscaneado);
                    _pedirActivarGW = false;
                    _activarModoGateway();
                } else {
                    Serial.printf("[MESH ] [NODO] >40s sin GW, señal %d → reinicio malla\n", _rssiEscaneado);
                    _reiniciarMalla();
                }
            }
        } else { tsNodoSinGW = 0; }
    }

    // ── Detección cambio WiFi — SOLO GATEWAY y DIRECTO usan MQTT ──────────────
    if (tieneWifi && !_wifiAntes &&
        (mesh_modoActual == MESH_MODO_GATEWAY || mesh_modoActual == MESH_MODO_DIRECTO)) {
        _wifiAntes = true;
        Serial.printf("[MESH ] WiFi conectado. IP: %s | RSSI: %d dBm | Modo: %s\n",
                      WiFi.localIP().toString().c_str(), WiFi.RSSI(),
                      mesh_nombreModo(mesh_modoActual));
        if (_client && _reconnectFn) _reconnectFn();
    }
    if (!tieneWifi && _wifiAntes) {
        _wifiAntes = false;
        Serial.println("[MESH ] WiFi desconectado");
    }

    if (tieneWifi && _client &&
        (mesh_modoActual == MESH_MODO_GATEWAY || mesh_modoActual == MESH_MODO_DIRECTO)) {
        if (!_client->connected() && _reconnectFn) _reconnectFn();
        if (_client->connected()) _client->loop();
    }
}
