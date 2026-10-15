import subprocess
import sys
import re
import logging
import os
import asyncio
from datetime import datetime

# Instalar dependencias si no están disponibles
try:
    from telethon import events
    import telegram  # noqa: F401
except ImportError:
    print("Instalando dependencias...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    from telethon import events

from cliente_lector import ClienteLector, EnvioBloqueadoError
from publicador import Publicador, Publicacion
from estado import Estado, ruta_estado

# ── Configuración ──────────────────────────────────────────────────────────────

def parse_int_env(name: str, default: int = 0) -> int:
    value = os.environ.get(name, '')
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

API_ID        = parse_int_env('API_ID')
API_HASH      = os.environ.get('API_HASH', '').strip()

# Acepta IDs numéricos o nombres de chat/canal
def parse_chat_id(value: str):
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return value

CANAL_ORIGEN  = parse_chat_id(os.environ.get('CANAL_ORIGEN', ''))
CANAL_DESTINO = parse_chat_id(os.environ.get('CANAL_DESTINO', ''))
BOT_TOKEN     = os.environ.get('BOT_TOKEN', '').strip()
# Al arrancar, publicar las últimas N señales del origen (0 = no publicar histórico)
PUBLICAR_ULTIMAS = max(parse_int_env('PUBLICAR_ULTIMAS'), 0)
_session_string = os.environ.get('SESSION_STRING', '').strip()

# En Railway usa StringSession (string corto desde variable de entorno)
# En local usa el archivo sesion_trading.session
if _session_string:
    from telethon.sessions import StringSession
    try:
        SESION = StringSession(_session_string)
    except ValueError:
        raise RuntimeError(
            'SESSION_STRING no es un StringSession válido. Genera uno con exportar_sesion.py y copia el valor completo.'
        )
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
# httpx (usado por el bot) escribe cada URL en INFO, y la URL lleva el BOT_TOKEN
logging.getLogger('httpx').setLevel(logging.WARNING)

# ── Patrones de detección ──────────────────────────────────────────────────────

# Dirección del trade (obligatorio)
DIRECCION = re.compile(
    r'\b(BUY|SELL|LONG|SHORT|COMPRA|VENTA|LARGO|CORTO)\b',
    re.IGNORECASE
)

# Gestión de riesgo (obligatorio)
RIESGO = re.compile(
    r'\b(SL|TP|T\.P|S\.L|Stop\s*Loss|Take\s*Profit|Stop|Target|Objetivo|Objetivos|OBJETIVO|OBJETIVOS)\b',
    re.IGNORECASE
)

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


# ── Cliente lector, publicador y manejador de eventos ─────────────────────────
# La cuenta personal (ClienteLector) solo lee el canal origen; el bot publica.
client = None
publicador = None
estado = None
# Serializa publicaciones: mientras se recuperan las pendientes al arrancar, las
# señales nuevas esperan, así no se publica nada dos veces ni fuera de orden.
lock_publicacion = asyncio.Lock()


def crear_client() -> ClienteLector:
    if not API_ID or not API_HASH:
        raise RuntimeError(
            'Debe definir API_ID y API_HASH en el entorno antes de iniciar el bot.'
        )

    client = ClienteLector(SESION, API_ID, API_HASH)
    client.add_event_handler(
        manejar_mensaje,
        events.NewMessage(chats=CANAL_ORIGEN)
    )
    return client


async def preparar_publicacion(mensaje) -> Publicacion:
    """Copia el contenido de la señal; si trae imagen, la descarga con la sesión lectora."""
    pub = Publicacion(texto=mensaje.message or '', entidades=mensaje.entities)

    if mensaje.photo:
        pub.imagen = await mensaje.download_media(file=bytes)
    elif mensaje.document and (mensaje.file.mime_type or '').startswith('image/'):
        pub.imagen = await mensaje.download_media(file=bytes)
        pub.imagen_como_archivo = True
        pub.nombre_archivo = mensaje.file.name
    elif mensaje.media and not mensaje.web_preview:
        log.warning("La señal trae un adjunto que no es imagen; se publica solo el texto")

    return pub


async def manejar_mensaje(event):
    # .text (con formato) para el filtro: así detecta también links ocultos en el texto
    texto = event.message.text or ''
    preview = texto[:80].replace('\n', ' ')

    try:
        valido, motivo = es_señal(texto)

        if valido:
            async with lock_publicacion:
                if estado.ultimo_id is not None and event.message.id <= estado.ultimo_id:
                    log.info(f"YA PUBLICADO | id {event.message.id} | {preview!r}")
                    return
                await publicar_señal(event.message)
            log.info(f"PUBLICADO  | {motivo} | {preview!r}")
        else:
            log.info(f"IGNORADO   | {motivo} | {preview!r}")

    except EnvioBloqueadoError:
        pass  # ya quedó en el log de cliente_lector
    except Exception as e:
        log.error(f"ERROR al procesar mensaje: {e} | {preview!r}")


async def publicar_señal(mensaje):
    pub = await preparar_publicacion(mensaje)
    await publicador.publicar(pub)
    estado.guardar(mensaje.id)


# ── Pendientes: señales llegadas mientras el bot estaba apagado ────────────────
async def publicar_pendientes(client: ClienteLector):
    async with lock_publicacion:
        if PUBLICAR_ULTIMAS > 0:
            await publicar_ultimas(client, PUBLICAR_ULTIMAS)
            return

        if estado.ultimo_id is None:
            # Sin registro previo no se publica nada del historial; se toma el
            # último mensaje actual como punto de partida para el próximo reinicio.
            ultimos = await client.get_messages(CANAL_ORIGEN, limit=1)
            if ultimos:
                estado.guardar(ultimos[0].id)
            log.info(f"Sin registro previo: no se publica historial (punto de partida: id {estado.ultimo_id})")
            return

        log.info(f"Buscando señales posteriores al id {estado.ultimo_id}...")
        publicadas = revisados = 0

        # Del más antiguo al más reciente, para publicar en orden
        async for mensaje in client.iter_messages(CANAL_ORIGEN, min_id=estado.ultimo_id, reverse=True):
            texto = mensaje.text or ''
            if not texto.strip():
                continue

            revisados += 1
            valido, motivo = es_señal(texto)
            if not valido:
                continue

            preview = texto[:80].replace('\n', ' ')
            try:
                await publicar_señal(mensaje)
                log.info(f"PENDIENTE  | {motivo} | {preview!r}")
                publicadas += 1
                await asyncio.sleep(3)  # margen para el límite de ~20 mensajes/minuto en grupos
            except EnvioBloqueadoError:
                pass
            except Exception as e:
                log.error(f"ERROR pendiente: {e} | {preview!r}")

        log.info(f"Pendientes: {publicadas} señales publicadas (revisados {revisados} mensajes)\n")


async def publicar_ultimas(client: ClienteLector, cantidad: int):
    """Publica las últimas `cantidad` señales del origen, aunque ya se hubieran publicado."""
    log.info(f"PUBLICAR_ULTIMAS={cantidad}: buscando las últimas {cantidad} señales del origen...")
    señales = []
    async for mensaje in client.iter_messages(CANAL_ORIGEN, limit=500):
        if es_señal(mensaje.text or '')[0]:
            señales.append(mensaje)
            if len(señales) >= cantidad:
                break

    publicadas = 0
    for mensaje in reversed(señales):  # de la más antigua a la más reciente
        preview = (mensaje.text or '')[:80].replace('\n', ' ')
        try:
            await publicar_señal(mensaje)
            log.info(f"ÚLTIMAS    | id {mensaje.id} | {preview!r}")
            publicadas += 1
            await asyncio.sleep(3)  # margen para el límite de ~20 mensajes/minuto en grupos
        except EnvioBloqueadoError:
            pass
        except Exception as e:
            log.error(f"ERROR últimas: {e} | {preview!r}")

    log.info(
        f"Últimas: {publicadas} de {len(señales)} señales publicadas. "
        "Se repetirán en cada reinicio mientras PUBLICAR_ULTIMAS sea mayor que 0.\n"
    )


# ── Punto de entrada ───────────────────────────────────────────────────────────
async def main():
    global publicador, estado

    if not BOT_TOKEN:
        raise RuntimeError('Definí BOT_TOKEN (token de BotFather): el bot es quien publica en el grupo destino.')
    if not CANAL_DESTINO:
        raise RuntimeError('Definí CANAL_DESTINO (ID del grupo donde publica el bot).')

    estado = Estado(ruta_estado())
    log.info(f"Estado:                  {estado.ruta} (último id publicado: {estado.ultimo_id})")

    client = crear_client()

    if _session_string:
        # Conectar sin auth interactiva; falla claro si la sesión expiró
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError(
                'SESSION_STRING inválida o expirada. '
                'Regenerá una nueva con nueva_sesion.py y actualizá la variable en Railway.'
            )
    else:
        phone = os.environ.get('PHONE_NUMBER')
        if not phone:
            raise RuntimeError('Definí SESSION_STRING o PHONE_NUMBER para la sesión lectora.')
        await client.start(phone=phone)

    me = await client.get_me()
    log.info(f"Sesión lectora:          {me.first_name} (@{me.username}) — solo lectura")
    log.info(f"Escuchando canal origen: {CANAL_ORIGEN}")
    log.info(f"Canal destino:           {CANAL_DESTINO}")
    log.info(
        f"PUBLICAR_ULTIMAS:        {PUBLICAR_ULTIMAS}"
        + (" (publica las últimas señales al arrancar)" if PUBLICAR_ULTIMAS else " (solo pendientes desde el último id)")
    )

    publicador = Publicador(BOT_TOKEN, CANAL_DESTINO)
    await publicador.iniciar()

    try:
        # Publicar solo lo llegado mientras el bot estaba apagado
        await publicar_pendientes(client)

        log.info("Bot activo. Presiona Ctrl+C para detener.\n")
        await client.run_until_disconnected()
    finally:
        await publicador.cerrar()


if __name__ == '__main__':
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot detenido manualmente.")
