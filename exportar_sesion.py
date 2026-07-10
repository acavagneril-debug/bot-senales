import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID   = int(os.environ.get('API_ID', '0'))
API_HASH = os.environ.get('API_HASH', '').strip()

if not API_ID or not API_HASH:
    raise RuntimeError('Definí API_ID y API_HASH en el entorno (ver .env.example).')

# Carga la sesión existente y la exporta como string corto
with TelegramClient('sesion_trading', API_ID, API_HASH) as client:
    print("\n=== TU SESSION STRING ===")
    print(StringSession.save(client.session))
    print("=========================\n")
