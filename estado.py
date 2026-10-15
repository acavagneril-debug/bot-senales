"""
Estado persistente: ID del último mensaje del canal origen ya publicado.

Se guarda en un JSON. En Railway, si el servicio tiene un volumen, el archivo
va dentro del volumen (RAILWAY_VOLUME_MOUNT_PATH) y sobrevive a los deploys.
"""
import json
import logging
import os

log = logging.getLogger(__name__)


def ruta_estado() -> str:
    if os.environ.get('ESTADO_FILE'):
        return os.environ['ESTADO_FILE']
    volumen = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')
    if volumen:
        return os.path.join(volumen, 'estado.json')
    if os.environ.get('RAILWAY_ENVIRONMENT'):
        log.warning(
            'Sin volumen en Railway: el estado se pierde en cada deploy y al '
            'reiniciar no se recuperarán las señales pendientes.'
        )
    return 'estado.json'


class Estado:
    def __init__(self, ruta: str):
        self.ruta = ruta
        self.ultimo_id: int | None = None
        try:
            with open(ruta, encoding='utf-8') as f:
                self.ultimo_id = json.load(f).get('ultimo_id')
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.error(f"No se pudo leer {ruta} ({e}); se arranca sin registro previo")

    def guardar(self, ultimo_id: int):
        if self.ultimo_id is not None and ultimo_id <= self.ultimo_id:
            return
        self.ultimo_id = ultimo_id
        carpeta = os.path.dirname(self.ruta)
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
        # Escritura atómica: si el proceso muere a mitad, queda el archivo anterior
        temporal = self.ruta + '.tmp'
        with open(temporal, 'w', encoding='utf-8') as f:
            json.dump({'ultimo_id': ultimo_id}, f)
        os.replace(temporal, self.ruta)
