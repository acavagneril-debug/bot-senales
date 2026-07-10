import subprocess
import sys
import os

# Instalar telethon si no está disponible
try:
    from telethon import TelegramClient
    from telethon.tl.types import Channel, Chat, User
except ImportError:
    print("Instalando telethon...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "telethon"])
    from telethon import TelegramClient
    from telethon.tl.types import Channel, Chat, User

import asyncio

API_ID = int(os.environ.get('API_ID', '0'))
API_HASH = os.environ.get('API_HASH', '').strip()
SESION = 'sesion_trading'

if not API_ID or not API_HASH:
    raise RuntimeError('Definí API_ID y API_HASH en el entorno (ver .env.example).')

async def listar_dialogos():
    async with TelegramClient(SESION, API_ID, API_HASH) as client:
        canales = []
        grupos = []
        chats_privados = []

        # Recorrer todos los diálogos de la cuenta
        async for dialogo in client.iter_dialogs():
            entidad = dialogo.entity
            nombre = dialogo.name
            id_ = dialogo.id

            if isinstance(entidad, Channel):
                if entidad.broadcast:
                    # Es un canal (solo lectura / broadcast)
                    canales.append((nombre, id_))
                else:
                    # Es un supergrupo
                    grupos.append((nombre, id_))
            elif isinstance(entidad, Chat):
                # Grupo normal (no supergrupo)
                grupos.append((nombre, id_))
            elif isinstance(entidad, User):
                # Chat privado con una persona o bot
                chats_privados.append((nombre, id_))

        # Mostrar canales
        print("\n" + "=" * 50)
        print(f"  CANALES ({len(canales)})")
        print("=" * 50)
        for nombre, id_ in canales:
            print(f"  {nombre:<40} ID: {id_}")

        # Mostrar grupos
        print("\n" + "=" * 50)
        print(f"  GRUPOS ({len(grupos)})")
        print("=" * 50)
        for nombre, id_ in grupos:
            print(f"  {nombre:<40} ID: {id_}")

        # Mostrar chats privados
        print("\n" + "=" * 50)
        print(f"  CHATS PRIVADOS ({len(chats_privados)})")
        print("=" * 50)
        for nombre, id_ in chats_privados:
            print(f"  {nombre:<40} ID: {id_}")

        total = len(canales) + len(grupos) + len(chats_privados)
        print(f"\nTotal: {total} diálogos\n")

if __name__ == '__main__':
    asyncio.run(listar_dialogos())
