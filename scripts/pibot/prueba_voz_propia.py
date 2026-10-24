#!/usr/bin/env python3
"""Prueba de la voz propia (voz_propia.py) sin robot: un parlante imitado da el foco de audio y recibe el PCM.

    ROS_DOMAIN_ID=77 python3 prueba_voz_propia.py [http://127.0.0.1:8097]

Necesita el servicio de voz con Piper (./x2 voz). Comprueba que llega todo el audio, a 16 kHz, al ritmo en que suena,
y que el foco se pide antes y se suelta después.
"""
import sys
import threading
import time

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from aimdk_msgs.msg import AudioPlayback, CommonState
from aimdk_msgs.srv import AbandonAudioFocus, RequestAudioFocus
from voz_propia import FRECUENCIA, VozPropia

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8097'


class Parlante(Node):
    """El hal_audio del robot, imitado: da el foco y anota el audio que le llega."""

    def __init__(self):
        super().__init__('parlante_imitado')
        self.eventos, self.audio, self.llegadas, self.fichas = [], bytearray(), [], set()
        self.create_service(RequestAudioFocus, '/aimdk_5Fmsgs/srv/RequestAudioFocus', self._pedir)
        self.create_service(AbandonAudioFocus, '/aimdk_5Fmsgs/srv/AbandonAudioFocus', self._soltar)
        self.create_subscription(AudioPlayback, '/aima/hal/audio/playback', self._sonar, 50)

    def _pedir(self, req, res):
        self.eventos.append(('pedir', req.focus_requester.pkg_name, time.monotonic()))
        res.reponse.status.value = CommonState.SUCCESS
        res.focus_response.focus_gain = True
        return res

    def _soltar(self, req, res):
        self.eventos.append(('soltar', req.focus_requester.pkg_name, time.monotonic()))
        res.reponse.status.value = CommonState.SUCCESS
        return res

    def _sonar(self, msg):
        assert msg.info.sample_rate == FRECUENCIA and msg.info.channels == 1
        self.audio += bytes(msg.data.data)
        self.llegadas.append(time.monotonic())
        self.fichas.add(msg.token_id)


def llamar(cliente, req, timeout=2.0, retries=4):  # como RobotMC._call
    for _ in range(retries):
        f = cliente.call_async(req)
        fin = time.monotonic() + timeout
        while not f.done() and time.monotonic() < fin:
            time.sleep(0.01)
        if f.done():
            return f.result()
    return None


rclpy.init()
parlante, robot = Parlante(), Node('robot_imitado')
ejecutor = MultiThreadedExecutor()
ejecutor.add_node(parlante)
ejecutor.add_node(robot)
threading.Thread(target=ejecutor.spin, daemon=True).start()

voz = VozPropia(robot, URL, llamar)
frase = 'Bienvenido a N Club. ¿Qué lo trae por aquí?'
esperado = len(voz.sintetizar(frase))
t0 = time.monotonic()
ok = voz.decir(frase)
dura = time.monotonic() - t0
time.sleep(0.3)

segundos = esperado / 2 / FRECUENCIA
fallas = 0
def comprobar(cond, texto):
    global fallas
    print(('OK    ' if cond else 'FALLA ') + texto)
    fallas += not cond
comprobar(ok, 'dijo la frase')
comprobar(len(parlante.audio) == esperado, f'llegó todo el audio ({len(parlante.audio)} de {esperado} bytes, {segundos:.1f} s)')
comprobar([e[0] for e in parlante.eventos] == ['pedir', 'soltar'], 'pidió el foco antes y lo soltó después')
comprobar(parlante.eventos[0][2] <= parlante.llegadas[0] and parlante.llegadas[-1] <= parlante.eventos[1][2], 'todo el audio llegó con el foco')
comprobar(len(parlante.fichas) == 1, 'una sola ficha por frase')
comprobar(segundos <= dura <= segundos + 1.5, f'volvió cuando terminó de sonar ({dura:.1f} s)')
ritmo = parlante.llegadas[-1] - parlante.llegadas[0]
comprobar(segundos - 1.0 <= ritmo <= segundos, f'mandó el audio al ritmo en que suena ({ritmo:.1f} s)')
print('todos correctos' if not fallas else f'{fallas} fallas')
rclpy.shutdown()
sys.exit(1 if fallas else 0)
