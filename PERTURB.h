// ============================================================
//  PERTURB.h — Localización de tarjetas por perturbación
//  Compatible: ESP32 + MCv03 (BJT nuevo)
//
//  Principio:
//    En un string de paneles en serie, todos comparten la misma
//    corriente. Un nodo inyecta un tren de pulsos de descarga
//    (DescargaA). Todos los demás muestrean PIN_VI para detectar
//    si les llega la perturbación.
//    Si un nodo NO detecta la perturbación, hay una ruptura
//    eléctrica entre él y el nodo emisor.
//
//  Protocolo SUPERNOVA:
//    REQUEST:  PVSx//MAC//PERTURB          → este nodo inyecta
//    REQUEST:  PVSx//MAC//PERTURB_LISTEN   → este nodo escucha
//
//    DATA (resultado):
//      PVSx//MAC//PERTURB_TX              → confirma que inyectó
//      PVSx//MAC//PERTURB_RX//SI//magnitud → detectó perturbación
//      PVSx//MAC//PERTURB_RX//NO          → no detectó
// ============================================================

#ifndef PERTURB_H
#define PERTURB_H

#include <Arduino.h>

// ── Parámetros del tren de pulsos ────────────────────────────

// Número de pulsos emitidos
#define PERTURB_NUM_PULSOS       5

// Duración de cada pulso ON (ms)
#define PERTURB_PULSO_ON_MS     20

// Duración de cada pulso OFF (ms)
#define PERTURB_PULSO_OFF_MS    80

// Duración total de escucha (ms)
// 5 * (20+80) = 500ms → 1500ms da margen suficiente
#define PERTURB_ESCUCHA_MS    1500

// Umbral de detección (cuentas ADC)
// Si la variación de VI supera esto → detectado
// Ajustar según ruido del sistema (empezar con 40)
#define PERTURB_UMBRAL_ADC      40

// Número de muestras durante la escucha
#define PERTURB_NUM_MUESTRAS   150

// ── API pública ───────────────────────────────────────────────

// Inyectar tren de pulsos. Llamar cuando se recibe //PERTURB.
void perturb_inyectar();

// Escuchar y detectar perturbación de otro nodo.
// Devuelve true si detectó, false si no.
// magnitud_out: variación máxima en cuentas ADC.
bool perturb_escuchar(int& magnitud_out);

#endif
