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
    def __init__(self, token: str, chat_destino, tema: int | None = None):
        self.bot = Bot(token)
        self.chat_destino = chat_destino
        # Grupos con temas: message_thread_id del tema donde publicar (None = General)
        self.destino = {'chat_id': chat_destino, 'message_thread_id': tema}

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
        tema = self.destino['message_thread_id']
        log.info(f"Bot publicador:          @{yo.username} -> {chat.title!r}" + (f" (tema {tema})" if tema else ""))
        if chat.is_forum and not tema:
            log.warning("El grupo tiene temas y no hay TEMA_DESTINO: se publicará en el tema General")

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
            await self.bot.send_message(text=pub.html, parse_mode=ParseMode.HTML, **self.destino)
        except BadRequest as e:
            log.warning(f"Formato no aceptado por el bot ({e}); se publica sin formato")
            await self.bot.send_message(text=pub.texto, **self.destino)

    async def _imagen(self, pub: Publicacion, con_caption: bool):
        enviar = self.bot.send_document if pub.imagen_como_archivo else self.bot.send_photo
        campo = 'document' if pub.imagen_como_archivo else 'photo'
        archivo = {campo: pub.imagen}
        if pub.imagen_como_archivo:
            archivo['filename'] = pub.nombre_archivo or 'imagen.jpg'

        if not con_caption:
            await enviar(**self.destino, **archivo)
            return
        try:
            await enviar(caption=pub.html, parse_mode=ParseMode.HTML, **self.destino, **archivo)
        except BadRequest as e:
            log.warning(f"Formato no aceptado por el bot ({e}); se publica sin formato")
            await enviar(caption=pub.texto, **self.destino, **archivo)
