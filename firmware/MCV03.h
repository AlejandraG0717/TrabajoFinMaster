#ifndef MCV03_H
#define MCV03_H

#include <Arduino.h>
#include <Preferences.h>
#include <Wire.h>

// ---------------- Pines BJT nuevo ----------------
#define Carga       19
#define DescargaA   17
#define DescargaB   18
#define DescargaC   10

// ---------------- Pines analógicos ----------------
#define V_MODULE        11
#define V23_MOD         12
#define V13_MOD         14
#define I_string        8
#define VI              13

// ---------------- Pines luminiscencia ----------------
#define Ilm_IN      5
#define Ilm_OUT23   4
#define Ilm_Free2   6
#define Ilm_Free    7

// ---------------- Sensor I2C ----------------
#define SDA_PIN 33
#define SCL_PIN 34
const int I2Caddress = 0x48;

// ---------------- Buffers accesibles desde MQTT.ino ----------------
extern int16_t BufferA[100];
extern int16_t BufferB[100];
extern int16_t BufferC[100];
extern int16_t BufferD[100];

extern int muestras;
extern int umbral_tr;
extern int totalMuestras;

// ---------------- Funciones públicas ----------------
void MCV03_setup();
void MONI_BJT_nuevo(const String& orden = "MO");
void leer_AT();

#endif
