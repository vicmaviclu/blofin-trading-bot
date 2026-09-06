# -*- coding: utf-8 -*-
import asyncio
import re
import time
import hmac
import hashlib
import base64
import json
import uuid
import requests
from telethon import TelegramClient, events
import os

# === VARIABLES DE ENTORNO ===
API_ID = os.environ["API_ID"]
API_HASH = os.environ["API_HASH"]
BLOFIN_API_KEY = os.environ["BLOFIN_API_KEY"]
BLOFIN_API_SECRET = os.environ["BLOFIN_API_SECRET"]
BLOFIN_API_PASSPHRASE = os.environ["BLOFIN_API_PASSPHRASE"]

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# === CONFIGURACIÓN TELEGRAM ===
TARGET_NAMES = ["miau", "Trading Pockets SEÑALES"]
SESSION_NAME = "session_crypto"

# === CONFIGURACIÓN BLOFIN ===
BLOFIN_BASE_URL = "https://openapi.blofin.com" 

# === PERSISTENCIA JSON ===
STATE_FILE = 'structural_trades.json'


BOT_ALERTS_PREFIXES = (
    "🚨 **MENSAJE DE CIERRE DEL GRUP" + "O:**",
    "🔥 Cierre de Posición Activo (Forzado)",
    "❌ Error al colocar la orden de ENTRADA",
    "🔔 Cierre Automático Detectado",
    "🚀 ¡ORDEN AUTOMÁTICA EJECUTADA! 🚀",
    "🛡️ SL Modificado en BloFin",
    "🔔 ¡🟢 GANANCIA DETECTADA!", 
    "🔔 ¡🔴 PÉRDIDA DETECTADA!", 
    "⚠️ Fallo al modificar SL para",
    "🔔 ALERTA DE BE DETECTADA:", 
    "❌ FALLO AL MOVER SL",
    "⚡ Ya hay posición abierta",
    "⚠️ Hito ignorado:",
    "🛡️ ¡HITÓ" 
)


# === TELEGRAM CLIENT ===
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# === VARIABLE GLOBAL PARA MONITOREAR TRADES ===
NOTIFIED_ORDER_IDS = set() 

# === GESTIÓN ESTRUCTURAL DE RIESGO ===
STRUCTURAL_TRADES = {}

# ----------------------------------------------------------------------
#           [INICIO] FUNCIONES DE PERSISTENCIA JSON
# ----------------------------------------------------------------------

def save_trades_to_file():
    """Guarda el diccionario STRUCTURAL_TRADES en un archivo JSON."""
    global STRUCTURAL_TRADES
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(STRUCTURAL_TRADES, f, indent=4)
        print(f"🧠 Estado guardado en {STATE_FILE}. Trades activos: {len(STRUCTURAL_TRADES)}")
    except Exception as e:
        print(f"❌ Error fatal al GUARDAR estado: {e}")

def load_trades_from_file():
    """Carga STRUCTURAL_TRADES desde el archivo JSON al iniciar."""
    global STRUCTURAL_TRADES
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                STRUCTURAL_TRADES = json.load(f)
            print(f"🧠 Estado cargado de {STATE_FILE}. Trades recuperados: {len(STRUCTURAL_TRADES)}")
        except Exception as e:
            print(f"❌ Error fatal al CARGAR estado (archivo corrupto?): {e}")
            STRUCTURAL_TRADES = {} # Empezar vacío si el archivo está corrupto
    else:
        print(f"🧠 No se encontró {STATE_FILE}. Iniciando con estado vacío.")
        STRUCTURAL_TRADES = {}

# --- [FIN] FUNCIONES DE PERSISTENCIA JSON ---

# ----------------------------------------------------------------------
#                 FUNCIONES AUXILIARES
# ----------------------------------------------------------------------

def get_inst_id(symbol):
    return f"{symbol.upper()}-USDT"

def create_signature(secret_key, path, method, timestamp, nonce, body=None):
    if body:
        if isinstance(body, dict):
            body_str = json.dumps(body, separators=(",", ":"), sort_keys=True)
        elif isinstance(body, list):
            body_str = json.dumps(body, separators=(",", ":"))
        else:
            body_str = body
        prehash = f"{path}{method}{timestamp}{nonce}{body_str}"
    else:
        prehash = f"{path}{method}{timestamp}{nonce}"
        body_str = ""
        
    signature = hmac.new(secret_key.encode(), prehash.encode(), hashlib.sha256).hexdigest().encode()
    return base64.b64encode(signature).decode(), body_str

def private_request(method, path, body=None):
    url = BLOFIN_BASE_URL + path
    timestamp = str(int(time.time() * 1000))
    nonce = str(uuid.uuid4())
    
    body_for_signature = body
    body_for_request = body
    
    if method == "POST":
        if isinstance(body, list):
            body_str = json.dumps(body, separators=(",", ":"))
            body_for_signature = body_str
            body_for_request = body_str
        elif isinstance(body, dict):
            body_str = json.dumps(body, separators=(",", ":"), sort_keys=True)
            body_for_signature = body_str
            body_for_request = body_str

    signature, body_str_unused = create_signature(BLOFIN_API_SECRET, path, method, timestamp, nonce, body_for_signature)

    headers = {
        "ACCESS-KEY": BLOFIN_API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-NONCE": nonce,
        "ACCESS-PASSPHRASE": BLOFIN_API_PASSPHRASE,
        "Content-Type": "application/json"
    }

    if method == "GET":
        response = requests.get(url, headers=headers)
    else:
        response = requests.post(url, headers=headers, data=body_for_request)

    try:
        return response.json()
    except Exception:
        return {"error": response.text, "status_code": response.status_code}

# ----------------------------------------------------------------------
#                 FUNCIONES DE BLOFIN
# ----------------------------------------------------------------------

def get_available_balance():
    res = private_request("GET", "/api/v1/asset/balances?accountType=futures")
    if res.get("code") == "0" and res.get("data"):
        return float(res["data"][0]["available"])
    print(f"❌ Error al obtener balance: {res}")
    return 0

def set_leverage(symbol, leverage, margin_mode="isolated"):
    path = "/api/v1/account/set-leverage"
    body = {
        "instId": get_inst_id(symbol),
        "leverage": str(leverage),
        "marginMode": margin_mode
    }
    result = private_request("POST", path, body)
    
    if result.get("code") == "0":
        return True
    
    print(f"⚠️ Fallo en set_leverage para {symbol}: {result}")
    return False

def get_instrument_info(symbol):
    inst_id = get_inst_id(symbol)
    url = f"{BLOFIN_BASE_URL}/api/v1/market/instruments?instId={inst_id}"
    response = requests.get(url)
    try:
        data = response.json()
        if data.get("code") != "0" or not data.get("data"):
            print(f"❌ Error obteniendo info de {symbol} (InstId: {inst_id}): {data}")
            return None
        return data["data"][0]
    except Exception as e:
        print(f"❌ Error procesando respuesta de instrumentos: {e}")
        return None

def get_open_positions(symbol):
    res = private_request("GET", f"/api/v1/account/positions?instId={get_inst_id(symbol)}") 
    
    if res.get("code") == "0" and res.get("data"):
        active_positions = []
        for pos in res["data"]:
            try:
                position_qty = float(pos.get("positions", 0))
                
                if position_qty != 0 and pos.get("positionSide") == "net":
                    pos['size'] = str(abs(position_qty))
                    pos['side'] = 'Buy' if position_qty > 0 else 'Sell'
                    active_positions.append(pos)
            except ValueError:
                continue
        return active_positions
    return []

def get_total_position_size(symbol):
    positions = get_open_positions(symbol)
    if positions:
        return float(positions[0].get('size', 0))
    return 0.0

def close_all_positions(symbol):
    path = "/api/v1/trade/close-position"
    open_positions = get_open_positions(symbol)
    
    if symbol in STRUCTURAL_TRADES:
        del STRUCTURAL_TRADES[symbol]
        save_trades_to_file() 
        print(f"✅ Monitor estructural detenido para {symbol} debido a cierre manual/forzado.")
    
    if not open_positions:
        return True, f"✅ No se encontró ninguna posición de {symbol} para cerrar."

    body = {
        "instId": get_inst_id(symbol),
        "marginMode": "isolated",
        "positionSide": "net" 
    }
    
    result = private_request("POST", path, body)

    if result.get("code") == "0":
        return True, f"✅ Orden de cierre de posición {symbol} enviada con éxito (Mercado)."
    else:
        if result.get('code') == '102008':
            return True, f"✅ Posición de {symbol} ya cerrada o inexistente."
        return False, f"❌ Error al intentar cerrar posición: {json.dumps(result)}"

def get_last_fill_pnl(symbol):
    path = f"/api/v1/trade/fills-history?instId={get_inst_id(symbol)}&limit=1"
    time.sleep(1.5) 
    
    result = private_request("GET", path)

    if result.get("code") == "0" and result.get("data"):
        last_trade = result["data"][0]
        if 'fillPnl' in last_trade:
            pnl = float(last_trade.get("fillPnl", 0))
            return f"{pnl:.4f} USDT"
    
    return "N/A (PNL no registrado en historial de trades)."

def get_tpsl_info(symbol):
    path = f"/api/v1/trade/orders-tpsl-pending?instId={get_inst_id(symbol)}"
    result = private_request("GET", path)
    
    if result.get("code") == "0" and result.get("data"):
        return result["data"] 
    return []

def cancel_all_tpsl_orders(symbol):
    tpsl_orders = get_tpsl_info(symbol)
    if not tpsl_orders:
        return True, "✅ No había órdenes SL/TP previas para cancelar."
        
    cancellation_list = []
    for order in tpsl_orders:
        cancellation_list.append({
            "instId": get_inst_id(symbol),
            "tpslId": order['tpslId']
        })
    
    path = "/api/v1/trade/cancel-tpsl"
    result = private_request("POST", path, cancellation_list)

    if result.get("code") == "0" and result.get("data"):
        successful_cancellations = True
        for res in result["data"]:
            if res.get("code") not in ["0", "500", "501"]: 
                successful_cancellations = False
                
        if successful_cancellations:
            return True, f"✅ {len(cancellation_list)} órdenes SL/TP previas canceladas con éxito."
        else:
            return False, f"❌ Fallo parcial/total al cancelar SL/TP: {json.dumps(result)}"
    
    return False, f"❌ Fallo de API al cancelar SL/TP: {json.dumps(result)}"

# ----------------------------------------------------------------------
#                 LÓGICA DE GESTIÓN DE RIESGO
# ----------------------------------------------------------------------

def set_multiple_tpsl(symbol, stop_loss_price=None, take_profit_prices=None):
    take_profit_prices = take_profit_prices or []
    
    # --- validaciones básicas ---
    inst_info = get_instrument_info(symbol)
    if not inst_info:
        return False, f"❌ Fallo al obtener información del instrumento {symbol}."

    inst_id = get_inst_id(symbol)
    
    # 1. CANCELACIÓN EXPLÍCITA (Siempre, ya que no gestionamos IDs)
    success_cancel, msg_cancel = cancel_all_tpsl_orders(symbol)
    if not success_cancel:
        return False, f"❌ Fallo ABORTADO en la cancelación de SL/TP: {msg_cancel}"
        
    open_positions = get_open_positions(symbol)
    if not open_positions:
        if symbol in STRUCTURAL_TRADES: 
            del STRUCTURAL_TRADES[symbol]
            save_trades_to_file()
        return True, "Gestión de riesgo omitida (posición no encontrada o ya cerrada)."

    position = open_positions[0]
    closing_side = 'sell' if position.get('side') == 'Buy' else 'buy'
    path = "/api/v1/trade/order-tpsl"
    
    # 2. DETERMINAR NIVELES DE PRECIO (Principal, Respaldo y Emergencia)
    # -------------------------------------------------------------------
    sl_trigger_input = str(stop_loss_price) if stop_loss_price else ""
    
    # Variables para la lógica de cascada
    target_sl = sl_trigger_input      # El que queremos poner AHORA
    fallback_sl = None                # El nivel anterior (si falla el target)
    emergency_sl = sl_trigger_input   # El SL inicial (último recurso)
    
    division_log_be = ""

    if symbol in STRUCTURAL_TRADES:
        levels = STRUCTURAL_TRADES[symbol].get('levels', [])
        if levels:
            # Asumimos que levels[0] es el MÁS RECIENTE (Hito actual)
            target_sl = str(levels[0])
            division_log_be = f"⚠️ *SL Trailing*: Intentando mover a `{target_sl}`."
            
            # Definimos los respaldos basados en la estructura
            if len(levels) > 1:
                fallback_sl = str(levels[1])  # El nivel anterior
                emergency_sl = str(levels[-1]) # El SL original/inicial
            elif len(levels) == 1:
                 # Si solo hay un nivel, el respaldo es el mismo (o el input original si existe)
                 emergency_sl = str(levels[0])

    if not target_sl:
        return False, "❌ Error: No hay precio de Stop Loss definido."

    # 3. EJECUCIÓN CON RED DE SEGURIDAD (TRY -> FALLBACK -> EMERGENCY)
    # -------------------------------------------------------------------
    sl_placed_successfully = False
    division_log = ""
    num_tps = len(take_profit_prices)

    # --- INTENTO 1: ORDEN PRINCIPAL (Con TP OCO si corresponde) ---
    if num_tps >= 1:
        tp_final = str(take_profit_prices[-1])
        body_main = {
            "instId": inst_id, "marginMode": "isolated", "positionSide": "net",
            "side": closing_side, 
            "tpTriggerPrice": tp_final, "tpOrderPrice": "-1", 
            "slTriggerPrice": target_sl, "slOrderPrice": "-1",
            "size": "-1", "reduceOnly": "true"
        }
    else:
        body_main = {
            "instId": inst_id, "marginMode": "isolated", "positionSide": "net",
            "side": closing_side, 
            "slTriggerPrice": target_sl, "slOrderPrice": "-1",
            "size": "-1", "reduceOnly": "true"
        }

    res_main = private_request("POST", path, body_main)

    if res_main.get("code") == "0":
        sl_placed_successfully = True
        division_log = f"✅ SL colocado en **{target_sl}**. {division_log_be}"
    else:
        # === FALLO DEL PRINCIPAL: INICIA PROTOCOLO DE RESCATE ===
        err_msg = res_main.get('msg', 'Error API')
        division_log = f"❌ Fallo Principal ({target_sl}): {err_msg}."
        
        # --- INTENTO 2: FALLBACK (Nivel Anterior) ---
        # Nota: Enviamos SOLO SL (sin TP) para maximizar probabilidad de éxito
        if fallback_sl and fallback_sl != target_sl:
            division_log += f"\n🔄 Intentando Fallback (Nivel previo): {fallback_sl}..."
            
            body_fallback = {
                "instId": inst_id, "marginMode": "isolated", "positionSide": "net",
                "side": closing_side, 
                "slTriggerPrice": fallback_sl, "slOrderPrice": "-1",
                "size": "-1", "reduceOnly": "true"
            }
            res_fallback = private_request("POST", path, body_fallback)
            
            if res_fallback.get("code") == "0":
                sl_placed_successfully = True
                division_log += f" ✅ **RESCATADO:** SL en {fallback_sl}."
            else:
                division_log += f" ❌ Falló."
        
        # --- INTENTO 3: EMERGENCIA (SL Inicial) ---
        # Si falló el principal Y (falló el fallback o no existía)
        if not sl_placed_successfully and emergency_sl:
            # Evitar reintentar si el de emergencia es igual al que ya falló
            if emergency_sl != target_sl and emergency_sl != fallback_sl:
                division_log += f"\n🛡️ Intentando SL de Emergencia (Inicial): {emergency_sl}..."
                
                body_emergency = {
                    "instId": inst_id, "marginMode": "isolated", "positionSide": "net",
                    "side": closing_side, 
                    "slTriggerPrice": emergency_sl, "slOrderPrice": "-1",
                    "size": "-1", "reduceOnly": "true"
                }
                res_emer = private_request("POST", path, body_emergency)
                
                if res_emer.get("code") == "0":
                    sl_placed_successfully = True
                    division_log += f" ✅ **ASEGURADO:** SL Inicial en {emergency_sl}."
                else:
                    division_log += f" 💀 **CRÍTICO:** SL Inicial también rechazado."
            else:
                 division_log += f"\n💀 No quedan niveles seguros para probar."

    # 4. RESUMEN FINAL
    if sl_placed_successfully:
        return True, f"✅ Gestión completada. {division_log}"
    else:
        # Si llegamos aquí, la posición está desnuda
        return False, f"❌❌ PELIGRO: POSICIÓN SIN SL. Detalle: {division_log}"

# ----------------------------------------------------------------------
#                 MONITORES ASÍNCRONOS
# ----------------------------------------------------------------------

async def load_initial_filled_orders():
    global NOTIFIED_ORDER_IDS
    path = "/api/v1/trade/orders-history?limit=49" 
    loop = asyncio.get_event_loop()
    
    result = await loop.run_in_executor(None, private_request, "GET", path)
    
    if result.get("code") == "0" and result.get("data"):
        for order in result["data"]:
            if order.get("state") == "filled" or order.get("state") == "partially_canceled":
                NOTIFIED_ORDER_IDS.add(order.get("orderId"))
    print(f"🧠 Cargados {len(NOTIFIED_ORDER_IDS)} IDs de órdenes iniciales.")

async def order_fill_monitor():
    """ Monitorea el historial de órdenes completadas para notificar ganancias. """
    global NOTIFIED_ORDER_IDS
    
    print("🧠 Iniciando monitor de historial de órdenes...")
    await load_initial_filled_orders()
    
    while True:
        await asyncio.sleep(21600)
        
        try:
            path = "/api/v1/trade/orders-history?limit=5" 
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, private_request, "GET", path)

            if result.get("code") == "0" and result.get("data"):
                
                for order in result["data"]:
                    order_id = order.get("orderId")
                    state = order.get("state")
                    
                    if order_id not in NOTIFIED_ORDER_IDS and (state == "filled" or state == "partially_canceled"):
                        
                        pnl = float(order.get("pnl", 0))
                        
                        if pnl != 0 or order.get('reduceOnly') == 'true':
                            
                            trigger_type = "Cierre Manual/Market"
                            if order.get('orderCategory') == 'tp':
                                trigger_type = "TAKE PROFIT (TP)"
                            elif order.get('orderCategory') == 'sl':
                                trigger_type = "STOP LOSS (SL)"
                            
                            pnl_sign = "🟢 GANANCIA" if pnl >= 0 else "🔴 PÉRDIDA"
                            closure_type = "PARCIAL" if float(order.get('filledSize', 0)) < float(order.get('size', 0)) else "TOTAL"

                            notification_msg = (
                                f"🔔 *¡{pnl_sign} DETECTADA! ({trigger_type} {closure_type})* 🔔\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"**PAR:** `{order.get('instId')}`\n"
                                f"**LADO:** `{order.get('side').upper()}` @ `{float(order.get('averagePrice', 0)):.4f}`\n"
                                f"**CANTIDAD:** `{float(order.get('filledSize', 0)):.6f}` contratos\n"
                                f"**PNL REALIZADO:** **{pnl:.4f} USDT**\n"
                                f"**COMISIÓN:** `{float(order.get('fee', 0)):.4f}` USDT"
                            )
                            
                            await send_notification(notification_msg)
                            
                            NOTIFIED_ORDER_IDS.add(order_id)
                
                if len(NOTIFIED_ORDER_IDS) > 500:
                    temp_list = sorted(list(NOTIFIED_ORDER_IDS), reverse=True)[:500] 
                    NOTIFIED_ORDER_IDS = set(temp_list)

        except Exception as e:
            print(f"❌ Error en el monitor de fills: {e}")
            await asyncio.sleep(60) 

# ----------------------------------------------------------------------
#                 FUNCIONES DE TELEGRAM Y MAIN
# ----------------------------------------------------------------------

def send_telegram_bot_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

async def send_notification(message):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, send_telegram_bot_message, message)

# === FUNCIÓN AUXILIAR: NORMALIZACIÓN INTELIGENTE DE PRECIOS ===
def smart_normalize_price(price_str):
    if price_str is None:
        return None

    price_str = price_str.replace(' ', '')
    
    # 1. Regex Flexible: Busca un separador (punto o coma) seguido de UNO O MÁS dígitos (\d+) al final.
    #    Esto cubre 2,2180, 0,4681, 45000.50 y 1.234,56
    decimal_regex = r'([.,])(\d+)$'
    decimal_match = re.search(decimal_regex, price_str) 
    
    if decimal_match:
        decimal_separator = decimal_match.group(1)
        
        # Asume que el otro separador es el de miles (o se ignora)
        thousands_separator = ',' if decimal_separator == '.' else '.'
        
        # Elimina el separador de miles.
        cleaned_price = price_str.replace(thousands_separator, '')
        
        # Reemplaza el separador decimal por el estándar '.'
        final_price_str = cleaned_price.replace(decimal_separator, '.')
        
        try:
            return float(final_price_str)
        except ValueError:
            return None
        
    # 2. CONVERSIÓN DE FALLBACK (Para números sin formato decimal visible, como 45000)
    try:
        # Intenta convertir directamente (quitando comas por si son separador de miles)
        return float(price_str.replace(',', ''))
    except ValueError:
        try:
            # Último intento: asume que todos los puntos y comas eran separadores de miles
            return float(price_str.replace('.', '').replace(',', ''))
        except:
            return None

# === PARSEAR SEÑAL ==
async def parse_signal(text, capital_base=2000):
    
    # === PATRONES (Actualizados) ===
    
    # 1. ACTUALIZACIÓN DE SÍMBOLO:
    # Prioriza (LTC)USDT o (LTC)/USDT (Grupo 1)
    # Luego busca (LTC) SELL/COMPRA (Grupo 2)
    pair_match = re.search(
        r"([A-Z]{2,5})(?:USDT|\/USDT)(?!\w)"  # Caso 1: LTCUSDT o LTC/USDT
        r"|([A-Z]{2,5})(?:\s+(?:SELL|BUY)\/(?:VENTA|COMPRA))?", # Caso 2: LTC SELL...
        text, 
        re.IGNORECASE
    )

    side_match = re.search(r"(BUY|LONG|SELL|SHORT|COMPRA|VENTA)", text, re.IGNORECASE) 
    leverage_match = re.search(r"[xX]\s?(\d+)", text)
    
    # 2. ACTUALIZACIÓN DE ENTRADA:
    # Busca solo "entrada" para ser tolerante a "recio de entrada" o "Precio de entrada"
    entry_match = re.search(r"entrada[:\s]*([\d.,]+)", text, re.IGNORECASE) 
    
    tp_matches = re.findall(r"TP\s?\d*[:\s]*([\d.,]+)", text, re.IGNORECASE) 
    sl_match = re.search(r"(?:⛔️|SL)[:\s]*([\d.,]+)", text, re.IGNORECASE)
    percent_match = re.search(r"(\d+)%\s+DE\s+LA\s+CUENTA", text, re.IGNORECASE)

    if not pair_match or not side_match or not entry_match:
        return None 

    # La extracción de símbolo ahora usa ambos grupos
    symbol = (pair_match.group(1) or pair_match.group(2)).upper()
    side_text = side_match.group(0).upper() 
    leverage = int(leverage_match.group(1)) if leverage_match else 1
    
    try:
        entry_price = smart_normalize_price(entry_match.group(1))
        stop_loss = smart_normalize_price(sl_match.group(1)) if sl_match else None
        
        if entry_price is None or (sl_match and stop_loss is None):
            raise ValueError("Precio de entrada/SL no pudo ser normalizado a float.")
        
        is_short = 'SELL' in side_text or 'SHORT' in side_text or 'VENTA' in side_text
        
        take_profit_prices_all = []
        for tp_str in tp_matches:
            cleaned_tp = smart_normalize_price(tp_str)
            if cleaned_tp is not None:
                take_profit_prices_all.append(cleaned_tp)
        
        # Ordenar TPs (SHORT: mayor a menor; LONG: menor a mayor)
        take_profit_prices_all = sorted(take_profit_prices_all, reverse=is_short) 
        
    except ValueError as e:
        print(f"❌ Error al convertir precio a float: {e} en el mensaje: {text[:100]}...")
        return None
    except Exception as e:
        print(f"❌ Error desconocido en parse_signal: {e}")
        return None

    final_tp_order = take_profit_prices_all[-1] if take_profit_prices_all else None
    percent_match = re.search(r"(\d+)%\s+DE\s+LA\s+CUENTA", text, re.IGNORECASE)
    percent_account = float(percent_match.group(1)) if percent_match else 20
    position_size = capital_base * (percent_account / 100)

    return {
        "type": "LONG" if "BUY" in side_text or "LONG" in side_text or 'COMPRA' in side_text else "SHORT",
        "symbol": symbol,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit_prices_all": take_profit_prices_all,
        "take_profit_final": final_tp_order,
        "position_size": position_size,
        "leverage": leverage,
    }


async def place_order(signal):
    inst_info = get_instrument_info(signal['symbol'])
    if not inst_info:
        await send_notification(f"❌ No se pudo obtener información del instrumento {signal['symbol']}.")
        return

    # === Lógica de cálculo de tamaño y posición existente ===
    contract_value = float(inst_info["contractValue"])
    min_size = float(inst_info["minSize"])
    lot_size = float(inst_info["lotSize"])
    available_balance = get_available_balance()
    margin_safety = 0.965
    position_size_usd = min(signal["position_size"], available_balance * margin_safety)
    size_to_add = (position_size_usd * signal["leverage"]) / (signal["entry_price"] * contract_value)
    size_to_add = max(round(size_to_add / lot_size) * lot_size, min_size)
    size_to_add = float(f"{size_to_add:.6f}")
    if size_to_add <= min_size / 2:
        await send_notification(f"⚠️ Tamaño de orden calculado es insignificante ({size_to_add}). Orden {signal['symbol']} cancelada.")
        return
    open_positions = get_open_positions(signal['symbol'])
    existing_position = None
    expected_side = "Buy" if signal["type"] == "LONG" else "Sell"
    for pos in open_positions:
        if pos.get("side") == expected_side:
            existing_position = pos
            break
    order_size = size_to_add
    order_price = signal["entry_price"]
    entry_price_notif = signal["entry_price"] 
    leverage_needed = signal['leverage']
    if existing_position:
        existing_leverage = int(existing_position.get("leverage", 0))
        if leverage_needed != existing_leverage:
            discard_msg = (
                f"❌ *SEÑAL DESCARTADA: Apalancamiento no coincide.*\n"
                f"Señal pide x{leverage_needed}, pero la posición abierta tiene **x{existing_leverage}**. "
            )
            await send_notification(discard_msg)
            return
        msg = f"⚡ Ya hay posición abierta en {signal['symbol']} ({signal['type']}). Se añadirá nueva orden para promediar (x{existing_leverage})."
        await send_notification(msg)
        total_size = float(existing_position["size"]) + size_to_add
        entry_price_notif = (
            float(existing_position["averagePrice"]) * float(existing_position["size"]) + signal["entry_price"] * size_to_add
        ) / total_size
        order_size = size_to_add
        order_price = signal["entry_price"]
    else:
        set_leverage(signal['symbol'], leverage_needed)
    # === Fin Lógica de cálculo de tamaño y posición existente ===

    # 2. Construir y enviar la orden de ENTRADA
    order_body = {
        "instId": get_inst_id(signal['symbol']),
        "marginMode": "isolated",
        "positionSide": "net",
        "side": "buy" if signal["type"] == "LONG" else "sell",
        "orderType": "limit",
        "price": str(order_price),
        "size": str(order_size),
        "leverage": str(leverage_needed),
    }

    if(signal.get("stop_loss")):
        order_body.update({"slTriggerPrice": str(signal["stop_loss"])})
        order_body.update({"slOrderPrice": "-1"})

    if(signal.get("take_profit_final")):
        order_body.update({"tpTriggerPrice": str(signal["take_profit_final"])})
        order_body.update({"tpOrderPrice": "-1"})


    result = private_request("POST", "/api/v1/trade/order", order_body)
        
    final_tps_all = signal.get("take_profit_prices_all", [])
    final_sl = signal.get("stop_loss")
    final_tp_order = signal.get("take_profit_final")
    
    if result.get("code") == "0":
        await asyncio.sleep(2) 
        
        # === Aplicar el TP Final y SL Inicial (OCO) ===
        if final_sl and final_tp_order:

            
            # --- REGISTRO PARA MONITOREO ESTRUCTURAL ---
            if len(final_tps_all) > 1:
                # La lista de niveles se guarda como: [SL_INICIAL, Entry, TP1, TP2, TP_FINAL]
                levels_list = [signal['stop_loss'], entry_price_notif] + final_tps_all
                
                STRUCTURAL_TRADES[signal['symbol']] = {
                    'side': signal['type'],
                    'levels': levels_list,
                    'entry': entry_price_notif # Precio de entrada para Break Even
                }
                save_trades_to_file() # --- [MODIFICADO] PERSISTENCIA JSON ---
                print(f"✅ Estrategia estructural de Trailing SL iniciada para {signal['symbol']}.")
            # -------------------------------------------
            
            risk_management_detail = "✅ Gestión de riesgo aplicada con SL inicial y TP final (OCO)."
        else:
            risk_management_detail = "🛑 Gestión de riesgo omitida (No SL/TP inicial)."

        # --- CONSTRUCCIÓN DE LA NOTIFICACIÓN MEJORADA ---
        tp_list_str = ""
        if len(final_tps_all) >= 1:
            tp_lines = [f"🎯 **TP{i+1}:** `{tp}`" for i, tp in enumerate(final_tps_all)]
            tp_list_str = "\n".join(tp_lines) + " (Trailing SL)"
        else:
            tp_list_str = "❌ No especificado."

        msg = (
            f"🚀 *¡ORDEN AUTOMÁTICA EJECUTADA!* 🚀\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 **PAR:** `{signal['symbol']}/USDT`\n"
            f"➡️ **DIRECCIÓN:** **{signal['type']}**\n"
            f"⚙️ **APALANCAMIENTO:** `x{leverage_needed}`\n"
            f"💰 **INVERSIÓN:** `{position_size_usd:.2f}` USDT\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 **PRECIO DE ENTRADA:** `{signal['entry_price']}`\n"
            f"📊 **ENTRADA PROMEDIO EST. (Total):** `{entry_price_notif:.4f}`\n"
            f"🛑 **STOP LOSS (Inicial):** `{final_sl}`\n"
            f"{tp_list_str}\n" 
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ *ESTADO DE GESTIÓN DE RIESGO (BloFin)*\n"
            f"{risk_management_detail}" 
        )

    else:
        msg = (
            f"❌ *Error al colocar la orden de ENTRADA*\n"
            f"**{signal['symbol']} ({signal['type']})**\n"
            f"💬 Mensaje: `{(json.dumps(result, indent=2))}`"
        )

    await send_notification(msg)

# === FILTRAR GRUPOS (Mantenido) ===
def match_title(title):
    return any(name.lower() in title.lower() for name in TARGET_NAMES) if title else False

# ----------------------------------------------------------------------
#                 NUEVA FUNCIÓN DE PROCESAMIENTO
# ----------------------------------------------------------------------

async def process_new_message(text):
    """ Contiene toda la lógica de manejo de señales, cierres y modificaciones. """
    
    # === CORRECCIÓN: FILTRADO POR TEXTO DEL BOT (Evitar bucles) ===
    # La tupla BOT_ALERTS_PREFIXES ahora es global.
    # [MODIFICADO] Usamos .strip() por seguridad
    if text.strip().startswith(BOT_ALERTS_PREFIXES):
        # Si el mensaje comienza con alguna de nuestras alertas, lo ignoramos.
        return
    # ============================================
    
    # === DETECCIÓN DE BE AISLADO ===
    # Utilizamos una expresión regular para buscar 'BE' rodeado de límites de palabra (\b)
    if re.search(r'\bBE\b', text, re.IGNORECASE):
        # Reenviar el mensaje original al canal de alertas 
        await send_notification(f"🔔 **ALERTA DE BE DETECTADA:**\n\nOriginal: {text}")
        return
    # ===============================================
    
    # --- Detección de Hitos (TP1, TP2, etc.) ---
    
    # [MODIFICADO] Regex corregido para aceptar LINKUSDT, LINK/USDT o LINK y hasta 10 caracteres.
    tp_milestone_match = re.search(
        r"\b([A-Z]{2,5})(?:USDT|/USDT)?\b.*?TP(\d+)",
        text,
        re.IGNORECASE
    )
    sl_mod_match = re.search(r"(SL|Stop[- ]?Loss) modificado para (\w+) - ([\d.]+)", text, re.IGNORECASE)
    closed_match = re.search(r"CERRADA\s+([A-Z]+)\s+\((LONG|SHORT)\)(.*)", text, re.IGNORECASE) 

    
    # 2. Manejo de Hitos (TP1, TP2, etc.)
    if tp_milestone_match:
        symbol = tp_milestone_match.group(1).upper()
        tp_index = int(tp_milestone_match.group(2))
        
        if symbol in STRUCTURAL_TRADES:
            trade_data = STRUCTURAL_TRADES[symbol]
            # Copiamos la lista para evitar problemas de referencia si algo falla
            levels = list(trade_data['levels'])
            
            # levels: [SL_ACTUAL, Entry, TP1, TP2, TP_FINAL]
            # El índice de niveles está desfasado en 1 (TP1 está en levels[2])
            level_index_for_tp = tp_index + 1 
            
            if level_index_for_tp >= len(levels):
                await send_notification(f"⚠️ Hito ignorado para {symbol}: TP{tp_index} ya fue superado o es el final.")
                return
            
            # 1. Determinar el nuevo SL (Es el precio del nivel inmediatamente inferior)
            # El nivel para TP1 (índice 2) usa el nivel de Entry (índice 1) como nuevo SL
            new_sl_price = levels[level_index_for_tp - 1] 
            
            # 2. Determinar el nivel al que se mueve el SL para la notificación
            if level_index_for_tp - 1 == 1: # Si el nuevo SL es el precio de Entrada
                level_name = "ENTRADA (Break Even)"
            else:
                level_name = f"TP{tp_index - 1}"
                
            # 3. Determinar el TP Final (Se mantiene el último TP de la orden OCO inicial)
            final_tp_order = levels[-1] 
            
            # --- LÓGICA DE ACTUALIZACIÓN DEL TRACKER ANTES DE ENVIAR A LA API (CRÍTICO) ---
            
            # A. AVANCE DEL TRAILING SL: Actualizar la lista de niveles
            # El nuevo SL se pone en la posición 0
            STRUCTURAL_TRADES[symbol]['levels'][0] = new_sl_price
            save_trades_to_file() # --- [MODIFICADO] PERSISTENCIA JSON ---
            
            # 4. Enviar Orden de Modificación de SL: 
            # set_multiple_tpsl leerá el SL actualizado de STRUCTURAL_TRADES.
            success, api_message = set_multiple_tpsl(
                symbol, 
                stop_loss_price=final_tp_order, # El SL se lee desde STRUCTURAL_TRADES
                take_profit_prices=[final_tp_order] # El TP final se mantiene
            )

            if success:
                await send_notification(
                    f"🛡️ *¡HITÓ TP{tp_index} DETECTADO!* 🛡️\n"
                    f"**{symbol}** ({trade_data['side']}): SL movido a **{level_name}** (`{new_sl_price:.4f}`).\n"
                    f"Gestión de Riesgo: {api_message}"
                )
            else:
                # Si falla (ej. 102040), notificamos el fallo pero el tracker ya tiene el nuevo SL
                await send_notification(f"❌ FALLO AL MOVER SL DE {symbol} ALCANZAR TP{tp_index}: {api_message}")
        else:
            await send_notification(f"⚠️ Hito ignorado: No hay posición activa o estrategia de Trailing SL registrada para {symbol}.")
        return
    
    elif sl_mod_match:
        # --- MODIFICACIÓN MANUAL: CANCELA EL TRAILING SL ---
        symbol = sl_mod_match.group(2).upper()
        new_sl_price = smart_normalize_price(sl_mod_match.group(3))
        
        if symbol in STRUCTURAL_TRADES:
            del STRUCTURAL_TRADES[symbol]
            save_trades_to_file() # --- [MODIFICADO] PERSISTENCIA JSON ---
            print(f"⚠️ Monitor estructural detenido para {symbol} debido a modificación manual de SL.")
        
        # Colocamos el nuevo SL (sin Trailing SL)
        if get_total_position_size(symbol) > 0:
            final_tp_order = None 
            success, api_message = set_multiple_tpsl(symbol, stop_loss_price=new_sl_price, take_profit_prices=[] if final_tp_order is None else [final_tp_order])
        else:
            success, api_message = False, "Posición no encontrada para modificar SL."

        if success:
            msg = (
                f"🛡️ *SL Modificado en BloFin*\n"
                f"**{symbol}**: Nuevo SL = `{new_sl_price}`\n"
                f"{api_message}"
            )
        else:
            msg = (
                f"⚠️ Fallo al modificar SL para {symbol}.\n"
                f"Razón: {api_message}"
            )
        await send_notification(msg)
        print(msg)
        return

    elif closed_match:
        symbol = closed_match.group(1).upper()
        full_text = closed_match.group(0) 
        
        await send_notification(f"🚨 **MENSAJE DE CIERRE DEL GRUPO:** `{full_text}`")
        
        is_auto_closed = "POR SL" in full_text.upper() or "POR TP" in full_text.upper()
        
        if is_auto_closed:
            cancel_all_tpsl_orders(symbol)
            ganancia_real = get_last_fill_pnl(symbol)
            
            if symbol in STRUCTURAL_TRADES:
                del STRUCTURAL_TRADES[symbol] 
                save_trades_to_file() # --- [MODIFICADO] PERSISTENCIA JSON ---
                print(f"✅ Monitor estructural detenido para {symbol} (Cierre Externo).")
            
            msg = (
                f"🔔 *Cierre Automático Detectado*\n"
                f"**{symbol}** (Cierre Externo)\n"
                f"Ganancia Realizada (fillPnl): **{ganancia_real}**\n"
                f"Se omite el cierre forzado ya que el SL/TP de BloFin ya actuó."
            )
            await send_notification(msg)
            print(msg)
            return
        
        # Cierre Forzado (Manual desde el grupo)
        # close_all_positions ya se encarga de borrar de STRUCTURAL_TRADES y guardar el JSON
        success_close, msg_close = close_all_positions(symbol)
        cancel_all_tpsl_orders(symbol) 
        
        ganancia_real = "N/A"
        if success_close:
            ganancia_real = get_last_fill_pnl(symbol)
    
        msg = (
            f"🔥 *Cierre de Posición Activo (Forzado)*\n"
            f"**{symbol}**\n"
            f"Ganancia Realizada (fillPnl): **{ganancia_real}**\n"
            f"Estado del Cierre Forzado en BloFin: {msg_close}"
        )
        await send_notification(msg)
        print(msg)
        return
        
    
    signal = await parse_signal(text)
    if signal:
        print(f"\n📩 Nueva señal: {signal}")
        await place_order(signal)

# ----------------------------------------------------------------------
#                         MAIN
# ----------------------------------------------------------------------

# [FUNCIÓN ACTUALIZADA]
async def main():
    
    # --- [INICIO] PERSISTENCIA JSON ---
    # Carga los trades guardados en memoria al arrancar
    load_trades_from_file()
    # --- [FIN] PERSISTENCIA JSON ---
    
    await client.start()
    
    # 🚨 INICIAR EL MONITOR DE GANANCIAS EN SEGUNDO PLAN 🚨
    asyncio.create_task(order_fill_monitor())
    
    entities = []
    async for d in client.iter_dialogs():
        if match_title(d.title):
            entities.append(d.entity)

    if not entities:
        print("❌ No se encontraron grupos target.")
        return

    print("✅ Escuchando mensajes en grupos target...")

    @client.on(events.NewMessage(chats=entities))
    async def handler(event):
        """ 
        Detecta, filtra mensajes de bot, espera 60s, y LUEGO procesa.
        """
        
        message = event.message
        message_id = message.id
        chat_id = event.chat_id

        # --- PASO 1: FILTRADO RÁPIDO ---
        # Obtener el texto original para el filtro rápido
        original_text = message.message or ""
        
        # [MODIFICADO] Usamos .strip() para un filtro más robusto
        stripped_text = original_text.strip()
        
        if stripped_text.startswith(BOT_ALERTS_PREFIXES):
            # Es un mensaje de nuestro propio bot, ignorar inmediatamente.
            print(f"[{time.strftime('%H:%M:%S')}] 🤖 Mensaje de bot (ID: {message_id}) ignorado inmediatamente.")
            return # Salir sin esperar
        
        # --- PASO 2: ESPERA POR EDICIONES ---
        # Si no es un mensaje de bot, entonces sí esperamos
        print(f"[{time.strftime('%H:%M:%S')}] 📩 Nuevo mensaje detectado (ID: {message_id}). Esperando 60 segundos para capturar ediciones...")
        
        await asyncio.sleep(60) 
        
        # --- PASO 3: RE-OBTENCIÓN Y PROCESAMIENTO ---
        try:
            # Volvemos a pedir el mensaje a Telegram usando su ID.
            # Esto nos dará el texto MÁS RECIENTE (editado).
            updated_message = await client.get_messages(chat_id, ids=message_id)
            
            if not updated_message:
                print(f"⚠️ Mensaje {message_id} fue eliminado durante la espera. Ignorando.")
                return

            text = updated_message.message or ""
            
        except Exception as e:
            print(f"❌ Error al re-obtener el mensaje {message_id}: {e}")
            # Usar el texto original como plan B si falla la re-obtención
            text = original_text

        if not text:
             print(f"⏳ Mensaje {message_id} está vacío. Ignorando.")
             return

        print(f"[{time.strftime('%H:%M:%S')}] ⏳...Procesando mensaje (ID: {message_id}) ahora: {text[:70]}...")
        
        # Delegar todo el procesamiento a la función externa
        await process_new_message(text)

    print("📡 Esperando nuevas señales...")
    await client.run_until_disconnected()

# === EJECUCIÓN ===
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Interrumpido por usuario.")
    except Exception as e:
        print(f"\n❌ Un error fatal ocurrió: {e}")