// ============================================================
//  PERTURB.cpp — Implementación
// ============================================================

#include "PERTURB.h"
#include "MCV03.h"    // Pines: DescargaA, PIN_VI, Carga, etc.

// ══════════════════════════════════════════════════════════════
//  INYECTAR PERTURBACIÓN
//
//  Secuencia:
//    1. Asegurar estado inicial seguro (todo LOW)
//    2. Emitir N pulsos: DescargaA ON → delay → DescargaA OFF → delay
//    3. Volver al estado seguro
//
// ══════════════════════════════════════════════════════════════

void perturb_inyectar() {
    Serial.println("[PERTURB] Iniciando inyección de perturbación...");
    Serial.printf("[PERTURB] %d pulsos de %dms ON / %dms OFF\n",
                  PERTURB_NUM_PULSOS, PERTURB_PULSO_ON_MS, PERTURB_PULSO_OFF_MS);

    // Estado seguro inicial
    digitalWrite(Carga,      LOW);
    digitalWrite(DescargaA,  LOW);
    digitalWrite(DescargaB,  LOW);
    digitalWrite(DescargaC,  LOW);
    delay(50);

    // Emitir tren de pulsos
    for (int i = 0; i < PERTURB_NUM_PULSOS; i++) {
        digitalWrite(DescargaA, HIGH);
        delay(PERTURB_PULSO_ON_MS);
        digitalWrite(DescargaA, LOW);
        delay(PERTURB_PULSO_OFF_MS);
        Serial.printf("[PERTURB] Pulso %d/%d emitido\n", i + 1, PERTURB_NUM_PULSOS);
    }

    // Estado seguro final
    digitalWrite(DescargaA, LOW);
    digitalWrite(Carga,     LOW);

    Serial.println("[PERTURB] Inyección completada");
}

// ══════════════════════════════════════════════════════════════
//  ESCUCHAR Y DETECTAR PERTURBACIÓN
//
//  Algoritmo:
//    1. Tomar N muestras de PIN_VI distribuidas en PERTURB_ESCUCHA_MS
//    2. Calcular la línea base (promedio de las primeras muestras)
//    3. Calcular la variación máxima respecto a la base
//    4. Si la variación supera PERTURB_UMBRAL_ADC → detectado
// ══════════════════════════════════════════════════════════════

bool perturb_escuchar(int& magnitud_out) {
    Serial.println("[PERTURB] Escuchando perturbación...");

    // Buffer de muestras (en stack para evitar heap)
    int16_t muestras_vi[PERTURB_NUM_MUESTRAS];

    // Intervalo entre muestras (µs)
    uint32_t intervalo_us = (PERTURB_ESCUCHA_MS * 1000UL) / PERTURB_NUM_MUESTRAS;

    // Muestrear PIN_VI durante PERTURB_ESCUCHA_MS
    for (int i = 0; i < PERTURB_NUM_MUESTRAS; i++) {
        muestras_vi[i] = analogRead(VI);
        delayMicroseconds(intervalo_us);
    }

    // ── Calcular línea base (promedio de las primeras 20 muestras) ──
    // Las primeras muestras son antes de que llegue la perturbación
    long suma_base = 0;
    int  n_base    = 20;
    for (int i = 0; i < n_base; i++) suma_base += muestras_vi[i];
    int base = suma_base / n_base;

    Serial.printf("[PERTURB] Línea base VI: %d ADC\n", base);

    // ── Buscar variación máxima respecto a la base ───────────────
    int variacion_max = 0;
    int idx_max       = 0;

    for (int i = n_base; i < PERTURB_NUM_MUESTRAS; i++) {
        int variacion = abs(muestras_vi[i] - base);
        if (variacion > variacion_max) {
            variacion_max = variacion;
            idx_max       = i;
        }
    }

    magnitud_out = variacion_max;

    Serial.printf("[PERTURB] Variación máxima: %d ADC (muestra %d)\n",
                  variacion_max, idx_max);

    // ── Decisión ─────────────────────────────────────────────────
    bool detectado = (variacion_max >= PERTURB_UMBRAL_ADC);

    if (detectado) {
        Serial.printf("[PERTURB] ✓ DETECTADO (umbral: %d)\n", PERTURB_UMBRAL_ADC);
    } else {
        Serial.printf("[PERTURB] ✗ NO DETECTADO (umbral: %d)\n", PERTURB_UMBRAL_ADC);
    }

    // Imprimir muestra de los datos para debug
    Serial.println("[PERTURB] Muestra de datos (cada 10):");
    for (int i = 0; i < PERTURB_NUM_MUESTRAS; i += 10) {
        Serial.printf("  [%3d] VI=%d  Δ=%d\n",
                      i, muestras_vi[i], abs(muestras_vi[i] - base));
    }

    return detectado;
}
