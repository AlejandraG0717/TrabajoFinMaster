//Incluir libreria 
#include "MCV03.h"

Preferences preferences;

// ---------------- Buffers globales ----------------
int16_t BufferA[100];
int16_t BufferB[100];
int16_t BufferC[100];
int16_t BufferD[100];

// Variables para la cantidad de muestras y el umbral 
int muestras = 100;
int umbral_tr = 300;
int totalMuestras = 0;


// ============================================================
// SETUP de la tarjeta MCv03 (solo BJT nuevo)
// ============================================================

void MCV03_setup() {
    Serial.begin(115200);
    delay(300);

    Serial.println("Inicializando tarjeta MCv03 (BJT nuevo)...");

    // Pines BJT nuevo
    pinMode(Carga, OUTPUT);
    pinMode(DescargaA, OUTPUT);
    pinMode(DescargaB, OUTPUT);
    pinMode(DescargaC, OUTPUT);

    digitalWrite(Carga, 0);
    digitalWrite(DescargaA, 0);
    digitalWrite(DescargaB, 0);
    digitalWrite(DescargaC, 0);

    // Pines analógicos
    pinMode(V_MODULE, ANALOG);
    pinMode(V23_MOD, ANALOG);
    pinMode(V13_MOD, ANALOG);
    pinMode(I_string, ANALOG);
    pinMode(VI, ANALOG);

    // Pines luminiscencia
    pinMode(Ilm_IN, ANALOG);
    pinMode(Ilm_OUT23, ANALOG);
    pinMode(Ilm_Free2, ANALOG);
    pinMode(Ilm_Free, ANALOG);

    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);

    // I2C
    Wire.begin(SDA_PIN, SCL_PIN, 400000);

    // Memoria no volátil
    preferences.begin("CONFIG");
    muestras = preferences.getInt("num_muestras", 90);
    umbral_tr = preferences.getInt("umbral_trigger", 200);
    preferences.end();

    // Protección contra valores inválidos
    if (muestras < 10 || muestras > 90) {
        Serial.println("Valor de muestras inválido. Restaurando a 90.");
        muestras = 90;
    }
}

// ============================================================
// Monitorización real del panel (BJT nuevo)
// ============================================================

void MONI_BJT_nuevo(const String& orden) {
    Serial.println("\n=== INICIO MEDICIÓN IV (dos barridas) ===");
    Serial.println("Orden: " + orden);

    // Seleccionar pin de descarga según el comando recibido
    int pinDescarga;
    if      (orden == "MO")   pinDescarga = DescargaA;  // Módulo completo
    else if (orden == "MO23") pinDescarga = DescargaB;  // 2/3 de módulo
    else if (orden == "MO13") pinDescarga = DescargaC;  // 1/3 de módulo
    else {
        Serial.println("Orden desconocida, usando DescargaA por defecto");
        pinDescarga = DescargaA;
    }

    // ── BARRIDA 1: CORRIENTE (BufferA) ──────────────────────
    digitalWrite(Carga,    1);
    digitalWrite(DescargaA, 0);
    digitalWrite(DescargaB, 0);
    digitalWrite(DescargaC, 0);
    delay(600);

    digitalWrite(Carga, 0);
    delay(1);

    // Pre-adquisición corriente (10 muestras antes de la descarga)
    for (int i = 0; i < 10; i++) {
        BufferA[i] = analogRead(I_string);
        delayMicroseconds(150);
    }

    // Descarga + adquisición principal corriente
    digitalWrite(pinDescarga, 1);
    for (int i = 10; i < 100; i++) {
        BufferA[i] = analogRead(I_string);
        delayMicroseconds(150);
    }
    digitalWrite(pinDescarga, 0);
    digitalWrite(Carga, 0);

    delay(500);  // Pausa entre barridas — deja recuperar el panel

    // ── BARRIDA 2: VOLTAJE (BufferB) ────────────────────────
    digitalWrite(Carga,    1);
    digitalWrite(DescargaA, 0);
    digitalWrite(DescargaB, 0);
    digitalWrite(DescargaC, 0);
    delay(600);

    digitalWrite(Carga, 0);
    delay(1);

    // Pre-adquisición voltaje
    for (int i = 0; i < 10; i++) {
        BufferB[i] = analogRead(VI);
        delayMicroseconds(150);
    }

    // Descarga + adquisición principal voltaje
    digitalWrite(pinDescarga, 1);
    for (int i = 10; i < 100; i++) {
        BufferB[i] = analogRead(VI);
        delayMicroseconds(150);
    }
    digitalWrite(pinDescarga, 0);
    digitalWrite(Carga, 0);

    totalMuestras = 100;
    Serial.printf("=== FIN MEDICIÓN [%s] — %d puntos IV ===\n",
                  orden.c_str(), totalMuestras);
}

// ============================================================
// Lectura de sensores atmosféricos (AT)
// ============================================================

void leer_AT() {

    // Luminiscencia
    BufferA[0] = analogRead(Ilm_IN);
    BufferA[1] = analogRead(Ilm_OUT23);
    BufferA[2] = analogRead(Ilm_Free2);
    BufferA[3] = analogRead(Ilm_Free);

    // Temperatura I2C
    Wire.beginTransmission(I2Caddress);
    Wire.write(0x00);
    Wire.endTransmission();
    Wire.requestFrom(I2Caddress, 2);

    if (Wire.available()>= 2) {
        uint8_t msb = Wire.read();
        uint8_t lsb = Wire.read();
        
        Serial.printf("[AT] I2C raw: MSB=0x%02X LSB=0x%02X\n", msb, lsb);
        
        int16_t temp_x2 = ((int16_t)(msb << 8 | lsb)) >> 7;
        
        BufferA[4] = temp_x2 * 5;
        
        Serial.printf("[AT] Temperatura: %d.%d°C (raw=%d)\n", 
                      BufferA[4] / 10, abs(BufferA[4] % 10), temp_x2);
        Serial.print("Datos sensores: Luminiscencia = ");
        Serial.println(BufferA[0]);
        Serial.println(BufferA[1]);       
        Serial.println(BufferA[2]);       
        Serial.println(BufferA[3]);       
    } else {
        BufferA[4] = 0xFFFF;
    }
}