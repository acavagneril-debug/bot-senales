"""
Cliente Telethon de SOLO LECTURA (la cuenta personal).

Cualquier petición que envíe, reenvíe, edite o suba algo a Telegram se bloquea
antes de salir: lanza EnvioBloqueadoError y queda en el log. Toda publicación
la hace el bot (ver publicador.py).
"""
import logging

from telethon import TelegramClient
from telethon.tl.functions import messages, upload

log = logging.getLogger(__name__)


class EnvioBloqueadoError(RuntimeError):
    """La sesión lectora intentó enviar algo a un chat."""


# Peticiones de messages.* que escriben en un chat aunque no empiecen por Send/Forward
_BLOQUEADAS = (
    messages.EditMessageRequest,
    messages.SaveDraftRequest,
    messages.SetTypingRequest,
    upload.SaveFilePartRequest,
    upload.SaveBigFilePartRequest,
)


def _es_envio(request) -> bool:
    if isinstance(request, _BLOQUEADAS):
        return True
    # SendMessage, SendMedia, SendMultiMedia, SendReaction, ForwardMessages, etc.
    return (
        type(request).__module__ == messages.__name__
        and type(request).__name__.startswith(('Send', 'Forward'))
    )


class ClienteLector(TelegramClient):
    # _call es el punto por el que pasan todas las peticiones de Telethon 1.x
    # (incluidas las descargas desde otros datacenters).
    async def _call(self, sender, request, *args, **kwargs):
        peticiones = request if isinstance(request, (list, tuple)) else [request]
        for peticion in peticiones:
            if _es_envio(peticion):
                nombre = type(peticion).__name__
                log.error(f"BLOQUEADO  | la sesión lectora intentó {nombre}; no se envió nada")
                raise EnvioBloqueadoError(
                    f'La sesión lectora no puede enviar a ningún chat ({nombre}).'
                )
        return await super()._call(sender, request, *args, **kwargs)
