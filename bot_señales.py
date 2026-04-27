import subprocess
import sys
import re
import logging
import os
from datetime import datetime

# Instalar telethon si no está disponible
try:
    from telethon import TelegramClient, events
except ImportError:
    print("Instalando telethon...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "telethon"])
    from telethon import TelegramClient, events

# ── Configuración ──────────────────────────────────────────────────────────────
API_ID        = int(os.environ.get('API_ID', 0))
API_HASH      = os.environ.get('API_HASH', '')
CANAL_ORIGEN  = int(os.environ.get('CANAL_ORIGEN', 0))
CANAL_DESTINO = int(os.environ.get('CANAL_DESTINO', 0))
_session_string = os.environ.get('SESSION_STRING')

# En Railway usa StringSession (string corto desde variable de entorno)
# En local usa el archivo sesion_trading.session
if _session_string:
    from telethon.sessions import StringSession
    SESION = StringSession(_session_string)
else:
    SESION = 'sesion_trading'

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),                        # consola
        logging.FileHandler('bot_señales.log', encoding='utf-8'),  # archivo
    ]
)
log = logging.getLogger(__name__)

# ── Patrones de detección ──────────────────────────────────────────────────────

# Dirección del trade (obligatorio)
DIRECCION = re.compile(r'\b(BUY|SELL)\b', re.IGNORECASE)

# Gestión de riesgo (obligatorio)
RIESGO = re.compile(r'\b(SL|TP|T\.P|S\.L|Stop\s*Loss|Take\s*Profit)\b', re.IGNORECASE)

# Precio numérico SIN símbolo $ (obligatorio): entero o decimal, ej: 4700, 1.3527, 2345.50
PRECIO = re.compile(r'(?<!\$)\b\d{3,6}([.,]\d{1,5})?\b')

# ── Lista de bloqueo — publicidad, cripto, links ───────────────────────────────
PALABRAS_BLOQUEADAS = re.compile(
    r'subscription|promo|lifetime|payment\s*method|'
    r'bitcoin|usdt|ethereum|crypto|'
    r'contact\s*now|t\.me/|https?://|'
    r'membership|one.off\s*payment',
    re.IGNORECASE
)

# Precios en dólares con símbolo $ (señal de publicidad, no de trading)
PRECIO_DOLAR = re.compile(r'\$\s*\d+')


def es_señal(texto: str) -> tuple[bool, str]:
    """
    Devuelve (True, motivo) si el mensaje es una señal de trading válida.
    Requiere las tres condiciones obligatorias y ninguna condición de bloqueo.
    """
    if not texto or not texto.strip():
        return False, 'mensaje vacío'

    # Primero verificar bloqueos
    bloqueo = PALABRAS_BLOQUEADAS.search(texto)
    if bloqueo:
        return False, f"bloqueado por '{bloqueo.group()}'"

    if PRECIO_DOLAR.search(texto):
        return False, 'contiene precio en dólares ($)'

    # Las tres condiciones son obligatorias
    faltantes = []
    if not DIRECCION.search(texto):
        faltantes.append('BUY/SELL')
    if not RIESGO.search(texto):
        faltantes.append('SL/TP')
    if not PRECIO.search(texto):
        faltantes.append('precio numérico')

    if faltantes:
        return False, f"falta: {', '.join(faltantes)}"

    return True, 'señal válida (BUY/SELL + SL/TP + precio)'


# ── Cliente y manejador de eventos ────────────────────────────────────────────
client = TelegramClient(SESION, API_ID, API_HASH)


@client.on(events.NewMessage(chats=CANAL_ORIGEN))
async def manejar_mensaje(event):
    texto = event.message.text or ''
    preview = texto[:80].replace('\n', ' ')

    try:
        valido, motivo = es_señal(texto)

        if valido:
            # Reenviar el mensaje tal cual (sin exponer el origen)
            await client.send_message(CANAL_DESTINO, texto)
            log.info(f"REENVIADO  | {motivo} | {preview!r}")
        else:
            log.info(f"IGNORADO   | {motivo} | {preview!r}")

    except Exception as e:
        log.error(f"ERROR al procesar mensaje: {e} | {preview!r}")


# ── Histórico: reenvía los últimos N mensajes que pasen el filtro ──────────────
async def reenviar_historico(limite_señales: int = 5):
    log.info(f"Buscando las últimas {limite_señales} señales en el historial...")
    señales_encontradas = 0
    mensajes_revisados = 0

    # Recorre mensajes del más reciente al más antiguo
    async for mensaje in client.iter_messages(CANAL_ORIGEN, limit=200):
        texto = mensaje.text or ''
        if not texto.strip():
            continue

        mensajes_revisados += 1
        valido, motivo = es_señal(texto)

        if valido:
            preview = texto[:80].replace('\n', ' ')
            try:
                await client.send_message(CANAL_DESTINO, texto)
                log.info(f"HISTÓRICO  | {motivo} | {preview!r}")
                señales_encontradas += 1
            except Exception as e:
                log.error(f"ERROR histórico: {e}")

        if señales_encontradas >= limite_señales:
            break

    log.info(f"Histórico: {señales_encontradas} señales reenviadas (revisados {mensajes_revisados} mensajes)\n")


# ── Punto de entrada ───────────────────────────────────────────────────────────
async def main():
    bot_token = os.environ.get('BOT_TOKEN')
    phone     = os.environ.get('PHONE_NUMBER')

    if bot_token:
        await client.start(bot_token=bot_token)
    elif phone:
        await client.start(phone=phone)
    else:
        # SESSION_STRING ya tiene la sesión completa, no necesita teléfono
        await client.start()

    me = await client.get_me()
    log.info(f"Sesión iniciada como: {me.first_name} (@{me.username})")
    log.info(f"Escuchando canal origen: {CANAL_ORIGEN}")
    log.info(f"Canal destino:           {CANAL_DESTINO}")

    # Reenviar las últimas 5 señales del historial antes de escuchar en tiempo real
    await reenviar_historico(limite_señales=5)

    log.info("Bot activo. Presiona Ctrl+C para detener.\n")
    await client.run_until_disconnected()


if __name__ == '__main__':
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot detenido manualmente.")
