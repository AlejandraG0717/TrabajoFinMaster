// ============================================================
//  PERTURB.h — Localización de tarjetas por perturbación
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
#define PERTURB_UMBRAL_ADC      40

// Número de muestras durante la escucha
#define PERTURB_NUM_MUESTRAS   150

// ── API pública ───────────────────────────────────────────────

// Inyectar tren de pulsos. Llamar cuando se recibe //PERTURB.
void perturb_inyectar();
bool perturb_escuchar(int& magnitud_out);

#endif
