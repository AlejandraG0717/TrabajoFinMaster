# SolarMon — Sistema de Monitorización de Plantas Fotovoltaicas mediante Red Mesh y Protocolo MQTT

Trabajo Fin de Estudios — Máster en Microelectrónica, Escuela de Ingeniería de Bilbao, UPV/EHU.

**Autora:** Alejandra Garcés Gil
**Directores:** Eneko Ortega Martín, Gerardo Aranguren Aramendia

---

## Descripción del proyecto

SolarMon es un sistema embebido distribuido para la monitorización de plantas fotovoltaicas. Combina:

- **Nodos de medida (ESP32 + tarjeta MCv03)** que adquieren la curva I-V real de un panel o fracción de panel mediante descarga controlada de condensadores, con una técnica de doble barrida que sincroniza las medidas de corriente y tensión.
- **Red mesh híbrida WiFi** (painlessMesh), donde cada nodo elige automáticamente su modo de operación (DIRECTO / GATEWAY / NODO) según la calidad de señal RSSI hacia el router, permitiendo que nodos sin cobertura WiFi directa se comuniquen a través de otros nodos de la malla.
- **Protocolo MQTT sobre TLS** (bróker HiveMQ Cloud) para la transmisión de datos y comandos, con reenvío bidireccional de mensajes a través de la malla cuando un nodo no tiene conexión directa al bróker.
- **Detección de perturbaciones eléctricas** para identificar qué nodos están conectados al mismo string fotovoltaico, sin necesidad de documentación previa de la instalación.
- **Localización aproximada de nodos** mediante trilateración RSSI, sin infraestructura adicional.
- **Interfaz gráfica de monitorización (SolarMon GUI)**, desarrollada en Python, con visualización en tiempo real de curvas I-V, topología de red, perturbaciones y localización.

Este proyecto parte de una base de código proporcionada por los directores (un firmware de un único nodo con datos simulados y una interfaz de prueba mínima) y la desarrolla hasta convertirla en el sistema completo descrito en la memoria del trabajo.

---

## Estructura del repositorio

```
SolarMon/
├── firmware/
│   ├── MQTT/
│   │   └── MQTT.ino              # Sketch principal: callback MQTT, comandos, setup/loop
│   ├── MESH_HYBRID/
│   │   ├── MESH_HYBRID.cpp
│   │   └── MESH_HYBRID.h         # Red mesh híbrida: modos, elección de gateway, reenvío
│   ├── MCV03/
│   │   ├── MCV03.cpp
│   │   └── MCV03.h               # Adquisición I-V real, doble barrida, sensores atmosféricos
│   ├── PERTURB/
│   │   ├── PERTURB.cpp
│   │   └── PERTURB.h             # Inyección y detección de perturbaciones eléctricas
│   ├── STATUS/
│   │   ├── STATUS.cpp
│   │   └── STATUS.h              # Heartbeat y disponibilidad del nodo
│   ├── CONFIG/
│   │   ├── CONFIG.cpp
│   │   └── CONFIG.h              # Persistencia de PVSx en memoria no volátil
│   └── coms/
│       ├── coms.cpp
│       └── coms.h                # Conexión WiFi y MQTT
│
├── interfaz/
│   └── SolarMon_GUI.py           
│
├── docs/
│   ├── Trabajo_Fin_de_Estudios.docx
│   └── capturas/                 
│
├── .gitignore
└── README.md
```

---

## Hardware necesario

- Microcontrolador **ESP32** (probado con variantes ESP32-S3).
- Tarjeta de adquisición **MCv03** (placa propia): banco de condensadores, transistores BJT de descarga, acondicionamiento de señal de tensión/corriente, sensor de temperatura LM75A (I2C), 4 canales de luminiscencia.
- Panel o módulo fotovoltaico de pruebas.
- Router WiFi como punto de acceso de la malla.

## Software y dependencias

**Firmware (Arduino):**
- [Arduino IDE](https://www.arduino.cc/en/software) 2.x o superior, con el core de **ESP32** instalado (`esp32` by Espressif Systems).
- Librerías: `painlessMesh`, `PubSubClient`, `ArduinoJson`, `Preferences` (incluida en el core ESP32), `Wire` (incluida).

**Interfaz gráfica (Python):**
- Python 3.10+
- Dependencias:
  ```bash
  pip install paho-mqtt matplotlib numpy scipy
  ```
  (`tkinter` viene incluido en la instalación estándar de Python en la mayoría de sistemas; en Linux puede requerir `sudo apt install python3-tk`).

---

## Cómo compilar el firmware

1. Abre Arduino IDE y selecciona la placa ESP32 correspondiente (Herramientas → Placa).
2. Copia todos los archivos `.cpp`/`.h` de `firmware/` (excepto `MQTT.ino`) y tu `secrets.h` en la **misma carpeta** que `MQTT.ino`. Arduino IDE no soporta subcarpetas anidadas para los archivos del sketch.
3. Instala las librerías necesarias desde el Gestor de Librerías (Herramientas → Administrar Librerías): `painlessMesh`, `PubSubClient`, `ArduinoJson`.
4. Compila y sube el sketch a cada tarjeta ESP32.

## Cómo ejecutar la interfaz

```bash
cd interfaz
python3 SolarMon_GUI.py
```

---

## Estado de validación

- ✅ Adquisición real de curvas I-V (módulo completo, 2/3 y 1/3) validada experimentalmente.
- ✅ Red mesh híbrida y reenvío de comandos/datos validados con múltiples nodos.
- ✅ Interfaz gráfica validada en sesiones de laboratorio.
- ⚠️ Detección de perturbaciones (PERTURB): implementada y verificada a nivel de código; pendiente de validación experimental con dos o más tarjetas en el mismo string.
- ⚠️ Localización por trilateración RSSI: implementada y verificada a nivel de código; pendiente de validación experimental con tres o más nodos de referencia.

Más detalle sobre la metodología de pruebas y las limitaciones en la memoria (`docs/Trabajo_Fin_de_Estudios.docx`, Capítulo 8).

---

## Licencia

Proyecto académico desarrollado como Trabajo Fin de Estudios del Máster en Microelectrónica de la UPV/EHU. Uso educativo y de investigación.

## Agradecimientos

A Eneko Ortega y Gerardo Aranguren por la dirección de este trabajo y por proporcionar la base de partida sobre la que se ha construido el sistema.
