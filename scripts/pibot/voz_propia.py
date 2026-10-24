"""La voz en español de la simulación (Piper, servicio scripts/voz) por el parlante del X2 real.

La voz de fábrica del X2 solo trae chino e inglés (su asistente reporta 'zh,en'), así que lee el español con acento
inglés. Esto genera cada frase con Piper, la misma voz de la simulación, y la manda al parlante por el tópico de audio
del robot, como el ejemplo oficial play_audio_stream.py: pedir el foco de audio, publicar el PCM al ritmo en que suena y
soltar el foco. El audio viaja por ROS, así que no hay que poner archivos en el computador de interacción (PC3).
"""

import array
import audioop
import io
import json
import threading
import time
import urllib.request
import wave

from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy

from aimdk_msgs.msg import AudioData, AudioInfo, AudioPlayback, CommonState, FocusRequester, FocusResponse
from aimdk_msgs.srv import AbandonAudioFocus, RequestAudioFocus

FRECUENCIA = 16000  # el robot remuestrea cualquier otra, pero el SDK recomienda 16 kHz mono
TROZO_S = 0.1       # cada mensaje lleva 100 ms de audio
ADELANTO_S = 0.5    # lo que va antes de que suene, para que no se corte si un mensaje se demora
PRIORIDAD = 8       # la del ejemplo oficial


class VozPropia:
    def __init__(self, node, voz_url, llamar):
        self.voz_url = voz_url.rstrip('/')
        self._llamar = llamar  # RobotMC._call: los servicios entre equipos a veces se pierden y se reintentan
        self.paquete = f'{node.get_name()}_voz'
        self._pedir = node.create_client(RequestAudioFocus, '/aimdk_5Fmsgs/srv/RequestAudioFocus')
        self._soltar = node.create_client(AbandonAudioFocus, '/aimdk_5Fmsgs/srv/AbandonAudioFocus')
        self._pub = node.create_publisher(AudioPlayback, '/aima/hal/audio/playback', 10)
        # Si el robot le da el parlante a otro (una alerta suya, por ejemplo), se deja de mandar audio enseguida
        self._perdido = threading.Event()
        qos = QoSProfile(reliability=QoSReliabilityPolicy.RELIABLE, history=QoSHistoryPolicy.KEEP_LAST, depth=10,
                         durability=QoSDurabilityPolicy.VOLATILE)  # la del ejemplo oficial
        node.create_subscription(FocusResponse, '/aima/hal/audio/focus_response', self._cambio_de_foco, qos)
        self._turno = threading.Lock()  # una frase a la vez
        self._con_foco = False

    def _cambio_de_foco(self, msg):
        if msg.pkg_name == self.paquete and not msg.focus_gain:
            self._perdido.set()

    def sintetizar(self, texto):
        """La frase en PCM de 16 bit, mono, a 16 kHz, con la voz de Piper del servicio de voz."""
        req = urllib.request.Request(f'{self.voz_url}/hablar', data=json.dumps({'texto': texto}).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as r:
            wav = r.read()
        with wave.open(io.BytesIO(wav)) as w:
            canales, ancho, frecuencia = w.getnchannels(), w.getsampwidth(), w.getframerate()
            pcm = w.readframes(w.getnframes())
        if ancho != 2:
            raise RuntimeError('el servicio de voz no entregó audio de 16 bit')
        if canales > 1:
            pcm = audioop.tomono(pcm, 2, 0.5, 0.5)
        if frecuencia != FRECUENCIA:
            pcm, _ = audioop.ratecv(pcm, 2, 1, frecuencia, FRECUENCIA, None)
        return pcm

    def _foco(self, cliente, srv, ganar):
        if not cliente.wait_for_service(timeout_sec=2.0):
            return False
        req = srv.Request()
        req.focus_requester = FocusRequester(pkg_name=self.paquete, priority=PRIORIDAD)
        res = self._llamar(cliente, req, timeout=0.5, retries=8)  # 8 intentos de 0.25 s en el ejemplo oficial
        if res is None or res.reponse.status.value != CommonState.SUCCESS:
            return False
        return res.focus_response.focus_gain if ganar else True

    def decir(self, texto):
        """Dice el texto y vuelve cuando terminó de sonar. False si el robot no dio el foco de audio."""
        pcm = self.sintetizar(texto)  # sin servicio de voz o sin Piper, lanza: quien llama usa la voz de fábrica
        paso = int(FRECUENCIA * TROZO_S) * 2
        with self._turno:
            self._perdido.clear()
            if not self._foco(self._pedir, RequestAudioFocus, ganar=True):
                return False
            self._con_foco = True
            try:
                ficha = f'{self.paquete}-{time.monotonic_ns()}'  # una ficha nueva corta lo que estuviera sonando
                inicio = time.monotonic()
                for i, desde in enumerate(range(0, len(pcm), paso)):
                    espera = inicio + i * TROZO_S - ADELANTO_S - time.monotonic()
                    if espera > 0 and self._perdido.wait(espera):
                        break
                    if self._perdido.is_set():
                        break  # el robot le dio el parlante a otro: no se le pisa
                    msg = AudioPlayback(pkg_name=self.paquete, token_id=ficha)
                    msg.info = AudioInfo(channels=1, sample_rate=FRECUENCIA)
                    msg.data = AudioData(data=array.array('B', pcm[desde:desde + paso]))
                    self._pub.publish(msg)
                fin = inicio + len(pcm) / 2 / FRECUENCIA + 0.3  # lo último que se mandó todavía está sonando
                self._perdido.wait(max(0.0, fin - time.monotonic()))
            finally:
                self.soltar()
        return True

    def soltar(self):
        """Devuelve el parlante (también al cerrar el puente a mitad de una frase: si no, nadie más podría usarlo)."""
        if self._con_foco:
            self._con_foco = not self._foco(self._soltar, AbandonAudioFocus, ganar=False)
