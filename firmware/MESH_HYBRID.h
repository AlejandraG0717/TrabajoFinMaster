// ============================================================
//  MESH_HYBRID.h 
// ============================================================

#ifndef MESH_HYBRID_H
#define MESH_HYBRID_H

#include <painlessMesh.h>
#include <PubSubClient.h>

// ══════════════════════════════════════════════════════════════
//  CONSTANTES DE CONFIGURACIÓN
// ══════════════════════════════════════════════════════════════

#define MESH_PREFIX       "SolarMesh"
#define MESH_PASSWORD     "solar12345"
#define MESH_PORT         5555

#define MESH_INTERVALO_MS       5000
#define MESH_TIMEOUT_GW_MS      15000
#define MESH_MAX_NODOS          20

#define RSSI_DIRECTO            -60
#define RSSI_GATEWAY            -75
#define RSSI_HISTERESIS         5
#define RSSI_MARGEN_GW          5

// ══════════════════════════════════════════════════════════════
//  ENUMS Y ESTRUCTURAS
// ══════════════════════════════════════════════════════════════

enum ModoMesh {
    MESH_MODO_DIRECTO,
    MESH_MODO_GATEWAY,
    MESH_MODO_NODO
};

struct MeshNodo {
    uint32_t meshId;
    String   nombre;
    int      rssi;
    bool     esGW;
    ModoMesh modo;
    uint32_t lastSeen;
    bool     enMalla;      // ← AGREGADO: para compatibilidad con código existente
};

// ══════════════════════════════════════════════════════════════
//  VARIABLES GLOBALES
// ══════════════════════════════════════════════════════════════

extern ModoMesh  mesh_modoActual;
extern bool      mesh_esGateway;
extern String    mesh_nodeID;
extern String    mesh_idGateway;
extern int       mesh_miRSSI;

extern MeshNodo  mesh_nodos[];
extern int       mesh_totalNodos;

// ══════════════════════════════════════════════════════════════
//  FUNCIONES PÚBLICAS
// ══════════════════════════════════════════════════════════════

void   mesh_init(const char* wifiSSID, const char* wifiPass,
                 PubSubClient& client, void (*reconnectFn)());
void   mesh_loop();
void   mesh_publicar(const String& topic, const String& payload);

const char* mesh_nombreModo(ModoMesh m);
String mesh_nombreDesdeMeshId(uint32_t meshId);
String mesh_obtenerVecinosRSSI();
String mesh_obtenerVecinosPorScan();

// Topología
String mesh_obtenerTopologiaJSON();
void   mesh_publicarTopologia();

// ← AGREGADO: Estado del nodo para heartbeat (NO usa _mesh privado)
String mesh_obtenerEstadoNodoJSON();

// ── Reenvío de comandos GATEWAY → NODO ──────────────────────────
void mesh_onComandoRecibido(void (*fn)(const String& topic, const String& payload));
void mesh_reenviarComando(const String& topic, const String& payload);

#endif
