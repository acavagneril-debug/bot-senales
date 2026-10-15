"""
Publicación en el grupo destino con el BOT (token de BotFather).

Siempre publica como mensaje nuevo (nunca forward), así no aparece
"Reenviado de". Las imágenes llegan ya descargadas como bytes, porque los
file_id de la cuenta lectora no sirven para el bot.
"""
import logging
from dataclasses import dataclass

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telethon.extensions import html

log = logging.getLogger(__name__)

LIMITE_CAPTION = 1024  # Telegram limita el pie de foto a 1024 caracteres


@dataclass
class Publicacion:
    texto: str                  # texto sin formato (Message.message de Telethon)
    entidades: list | None      # entidades de formato de Telethon (negrita, links...)
    imagen: bytes | None = None
    imagen_como_archivo: bool = False  # imagen enviada como documento en el origen
    nombre_archivo: str | None = None

    @property
    def html(self) -> str:
        return html.unparse(self.texto, self.entidades or [])


def _largo_telegram(texto: str) -> int:
    # Telegram cuenta en unidades UTF-16 (los emojis cuentan doble)
    return len(texto.encode('utf-16-le')) // 2


class Publicador:
    def __init__(self, token: str, chat_destino):
        self.bot = Bot(token)
        self.chat_destino = chat_destino

    async def iniciar(self):
        await self.bot.initialize()
        yo = self.bot.bot
        try:
            chat = await self.bot.get_chat(self.chat_destino)
        except Exception as e:
            raise RuntimeError(
                f'El bot @{yo.username} no puede acceder al grupo destino {self.chat_destino}: {e}. '
                'Agrégalo al grupo como admin y revisa CANAL_DESTINO.'
            ) from e
        log.info(f"Bot publicador:          @{yo.username} -> {chat.title!r}")

    async def cerrar(self):
        await self.bot.shutdown()

    async def publicar(self, pub: Publicacion):
        if pub.imagen is None:
            await self._texto(pub)
        elif _largo_telegram(pub.texto) <= LIMITE_CAPTION:
            await self._imagen(pub, con_caption=True)
        else:
            # El texto no cabe como pie de foto: imagen sola y luego el texto
            await self._imagen(pub, con_caption=False)
            await self._texto(pub)

    async def _texto(self, pub: Publicacion):
        try:
            await self.bot.send_message(self.chat_destino, pub.html, parse_mode=ParseMode.HTML)
        except BadRequest as e:
            log.warning(f"Formato no aceptado por el bot ({e}); se publica sin formato")
            await self.bot.send_message(self.chat_destino, pub.texto)

    async def _imagen(self, pub: Publicacion, con_caption: bool):
        enviar = self.bot.send_document if pub.imagen_como_archivo else self.bot.send_photo
        campo = 'document' if pub.imagen_como_archivo else 'photo'
        archivo = {campo: pub.imagen}
        if pub.imagen_como_archivo:
            archivo['filename'] = pub.nombre_archivo or 'imagen.jpg'

        if not con_caption:
            await enviar(self.chat_destino, **archivo)
            return
        try:
            await enviar(self.chat_destino, caption=pub.html, parse_mode=ParseMode.HTML, **archivo)
        except BadRequest as e:
            log.warning(f"Formato no aceptado por el bot ({e}); se publica sin formato")
            await enviar(self.chat_destino, caption=pub.texto, **archivo)
