"""Los sentidos del X2 real para PIBOT: la cámara de la cabeza (quién llega) y el micrófono (qué responde).

Las fotos van al servicio de reconocimiento facial (scripts/rostro, ./x2 rostro) y cada frase que el robot oye, al de
voz a texto (scripts/voz, ./x2 voz). Nada se guarda: se mandan a esos servicios locales y se descartan.

El micrófono es el del sistema de interacción del robot (/agent/process_audio_output): ya viene sin ruido y cortado
en frases con detección de voz. Para que lo publique, el asistente de fábrica debe estar en modo 'only_voice' y hay
que decir su palabra de activación una vez (ver real/README.md).
"""

import collections
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from rclpy.qos import QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy, qos_profile_sensor_data
from rclpy.serialization import deserialize_message
from sensor_msgs.msg import CompressedImage

from aimdk_msgs.msg import AudioVadStateType, ProcessedAudioOutput

CAMARA = '/aima/hal/sensor/rgb_head_front_center/rgb_image/compressed'
MICROFONO = '/agent/process_audio_output'
RANGO = ['identified', 'ambiguous', 'unknown', 'insufficient_quality', 'multiple_faces', 'no_face', 'invalid_image',
         'not_ready']


def _post(url, datos, tipo='application/octet-stream', timeout=10.0):
    req = urllib.request.Request(url, data=datos, method='POST', headers={'Content-Type': tipo})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f'el servicio {url.rsplit("/", 1)[0]} no responde ({e})') from None


class Sentidos:
    def __init__(self, node, rostro_url=None, voz_url=None, camara=CAMARA, microfono=MICROFONO):
        self.rostro_url, self.voz_url = rostro_url, voz_url
        self._foto, self._foto_t = None, 0.0
        self._frases = collections.deque(maxlen=8)  # (inicio, fin, pcm) de lo que el robot oyó
        self._oyendo, self._oyendo_desde = None, 0.0
        self._cambio = threading.Condition()
        self.callado_desde = 0.0  # cuándo terminó de hablar el robot: lo que se oye antes es su propia voz
        self._dejar = threading.Event()  # para dejar de escuchar cuando alguien ya respondió por el visitante en PIBOT
        if rostro_url:
            # Sin deserializar: la cámara manda ~30 fotos de 340 KB por segundo y solo se usan unas pocas; convertir
            # cada una ocupaba un tercio de un núcleo del Orin (2026-10-24) y Whisper se volvía 10 veces más lento
            node.create_subscription(CompressedImage, camara, self._on_foto, qos_profile_sensor_data, raw=True)
        if voz_url:
            # Cola honda, como el ejemplo oficial: al empezar una frase llegan muchos trozos de golpe
            qos = QoSProfile(history=QoSHistoryPolicy.KEEP_LAST, depth=500, reliability=QoSReliabilityPolicy.BEST_EFFORT)
            node.create_subscription(ProcessedAudioOutput, microfono, self._on_audio, qos)

    # --- Cámara ---

    def _on_foto(self, crudo):
        self._foto, self._foto_t = crudo, time.monotonic()

    def foto(self, max_edad=2.0):
        """La última foto de la cámara de la cabeza (JPEG), si es reciente."""
        if self._foto is None or time.monotonic() - self._foto_t > max_edad:
            return None
        return bytes(deserialize_message(self._foto, CompressedImage).data)

    def hay_camara(self):
        return self.foto() is not None

    def identificar(self, intentos=3, pausa=0.3):
        """Quién está frente al robot: la primera foto que reconoce gana; si ninguna, la respuesta más informativa."""
        if not self.rostro_url:
            raise RuntimeError('el puente no tiene reconocimiento facial (--rostro)')
        mejor = None
        for i in range(intentos):
            foto = self.foto()
            if foto is None:
                raise RuntimeError('no llegan fotos de la cámara de la cabeza')
            r = _post(f'{self.rostro_url}/identificar', foto, 'image/jpeg')
            if r['status'] == 'identified':
                return r
            if mejor is None or RANGO.index(r['status']) < RANGO.index(mejor['status']):
                mejor = r
            if i < intentos - 1:
                time.sleep(pausa)
        return mejor

    def dejar(self):
        """Corta la escucha que esté en curso."""
        self._dejar.set()
        with self._cambio:
            self._cambio.notify_all()

    def alguien_cerca(self):
        """True si hay una cara lo bastante grande (cerca) en la foto actual."""
        foto = self.foto()
        if foto is None or not self.rostro_url:
            return False
        return _post(f'{self.rostro_url}/detectar', foto, 'image/jpeg', timeout=5.0).get('cerca', False)

    # --- Micrófono ---

    def _on_audio(self, msg):
        estado, datos = msg.audio_vad_state.value, bytes(msg.audio_data)
        with self._cambio:
            if estado == AudioVadStateType.AUDIO_VAD_STATE_BEGIN:
                self._oyendo, self._oyendo_desde = bytearray(datos), time.monotonic()
            elif estado == AudioVadStateType.AUDIO_VAD_STATE_PROCESSING and self._oyendo is not None:
                self._oyendo += datos
            elif estado == AudioVadStateType.AUDIO_VAD_STATE_END and self._oyendo is not None:
                self._oyendo += datos
                self._frases.append((self._oyendo_desde, time.monotonic(), bytes(self._oyendo)))
                self._oyendo = None
                self._cambio.notify_all()

    def escuchar(self, timeout=8.0, contexto=''):
        """Lo próximo que diga alguien, en texto ('' si nadie habla a tiempo). Ignora lo que el robot oyó de sí mismo."""
        if not self.voz_url:
            raise RuntimeError('el puente no tiene voz a texto (--voz)')
        fin = time.monotonic() + timeout
        self._dejar.clear()
        with self._cambio:
            while True:
                if self._dejar.is_set():
                    return ''
                frase = next((f for f in self._frases if f[0] > self.callado_desde - 0.2), None)
                if frase:
                    self._frases.clear()
                    break
                # Si alguien está hablando al vencer el tiempo, se le deja terminar (hasta 6 s más)
                limite = fin + (6.0 if self._oyendo is not None else 0.0)
                if time.monotonic() >= limite:
                    return ''
                self._cambio.wait(timeout=0.2)
        inicio, termino, pcm = frase
        if termino - inicio < 0.3 or len(pcm) < 16000 * 2 * 0.3:
            return ''  # un ruido corto, no una frase
        # contexto: lo que se espera oír (las opciones, los códigos del club), para que Whisper lo escriba igual
        consulta = f'?contexto={urllib.parse.quote(contexto[:600])}' if contexto else ''
        return _post(f'{self.voz_url}/transcribir{consulta}', pcm, timeout=30.0).get('texto', '').strip()
