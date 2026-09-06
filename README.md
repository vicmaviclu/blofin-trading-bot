# 🤖 BloFin Telegram Trading Bot

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Telethon](https://img.shields.io/badge/Telethon-Telegram_API-blue.svg)
![BloFin](https://img.shields.io/badge/API-BloFin-green.svg)

Un bot de trading automatizado y asíncrono desarrollado en Python que conecta Telegram con el exchange BloFin. Diseñado para escuchar señales de trading en canales específicos de Telegram, parsear los datos mediante expresiones regulares (regex) y ejecutar automáticamente las órdenes de compra/venta con su respectiva gestión de riesgo.

## ✨ Características Principales

* **👂 Escucha Asíncrona (Telethon):** Monitorea canales de Telegram en tiempo real ("miau", "Trading Pockets SEÑALES") usando la API de Telegram.
* **🧠 Parseo Inteligente de Señales:** Extrae de manera robusta el par de trading (ej. BTC/USDT), dirección (LONG/SHORT), apalancamiento, precio de entrada, niveles de Take Profit (Múltiples TPs) y Stop Loss.
* **⚙️ Cálculo de Tamaño de Posición:** Calcula automáticamente el tamaño de la orden (Lot Size) asegurando no exceder el riesgo predeterminado del balance de la cuenta, y considerando márgenes de seguridad.
* **🚀 Ejecución Automática (BloFin OpenAPI):** 
  * Coloca órdenes Limit de entrada.
  * Gestiona automáticamente el apalancamiento.
  * Establece órdenes OCO (One-Cancels-the-Other) para Stop Loss y Take Profit final.
* **🛡️ Gestión Dinámica de Riesgo (Trailing Stop Estructural):** Guarda un estado persistente en JSON (`structural_trades.json`) para mover dinámicamente el Stop Loss (Break Even, Trailing) conforme el precio va alcanzando los objetivos (Hitos/TPs). En caso de fallo de red, tiene protocolos de emergencia para asegurar que ninguna orden se quede sin SL.
* **🔔 Notificaciones PnL en Tiempo Real:** Monitoriza continuamente el historial de órdenes del exchange e informa al usuario por Telegram sobre cierres, ganancias (🟢) o pérdidas (🔴) de forma automática.

## 🛠️ Tecnologías y Librerías

* `Python 3.x`
* `telethon` (Interacción con Telegram MTProto)
* `asyncio` (Ejecución asíncrona de monitores y cliente)
* `requests` (Conexión HTTP con API REST de BloFin)
* `hmac` & `hashlib` (Firma de peticiones y autenticación)
* `re` (Expresiones regulares para extraer datos del texto libre)

## 🔒 Seguridad (¡Importante!)

El script principal (`main.py`) está diseñado para leer las claves sensibles desde **Variables de Entorno**. 
Nunca subas tus claves privadas a repositorios públicos.

```env
API_ID="Tu_Telegram_API_ID"
API_HASH="Tu_Telegram_API_HASH"
BLOFIN_API_KEY="Tu_BloFin_Key"
BLOFIN_API_SECRET="Tu_BloFin_Secret"
BLOFIN_API_PASSPHRASE="Tu_BloFin_Passphrase"
BOT_TOKEN="Tu_Token_Bot_Telegram"
CHAT_ID="ID_Chat_Destino"
```

## 🚀 Uso

1. Configura tus variables de entorno.
2. Instala los requerimientos: `pip install -r requirements.txt` (asegúrate de incluir telethon y requests).
3. Inicia el bot: `python main.py`
4. En el primer inicio, Telegram te pedirá iniciar sesión. Se creará un archivo `.session`.

## ☁️ Despliegue en Google Cloud

Este proyecto fue diseñado para estar en ejecución 24/7 mediante su despliegue en **Google Cloud Platform (GCP)**. Usando una instancia de Compute Engine o un entorno contenedorizado, el bot se mantiene escuchando las señales ininterrumpidamente sin depender de una máquina local.

---
*Desarrollado para la automatización eficiente y gestión de riesgo disciplinada.*
