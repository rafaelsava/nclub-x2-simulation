#!/usr/bin/env python3
"""Prueba, sin el robot, cómo guía el puente al X2 real (robot.py en modo real, con guia_real.py).

    python3 scripts/pibot/prueba_guia_real.py [orientacion.csv]

Un modelo del X2 (avanza y gira con el retardo de MC) recibe las órdenes de robot.py con un reloj simulado, así que
corre en segundos. Repite la prueba del 2026-10-24: el Gimnasio a 2.2 m, casi detrás del robot. Con la ley anterior,
que giraba siempre avanzando, el robot se alejaba y el freno lo detenía; con la nueva tiene que llegar. También
comprueba que se detiene a tiempo si el giro va al revés, si la orientación está mal o si la posición salta.

Con orientacion.csv (la grabación de la caminata con el control remoto de ese día) revisa además que la
comprobación de dirección de la guía no se dispare con datos reales.
"""

import contextlib
import csv
import io
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import robot as modulo_robot  # noqa: E402
from guia_real import GuiaReal, normalizar  # noqa: E402


class X2Falso:
    """Un X2 visto desde arriba: sigue la velocidad pedida con un retardo, como MC."""

    def __init__(self, x, y, rumbo, signo_giro=1.0, gira_quieto=True, desfase=0.0, salto_en=None, retardo=0.4):
        self.x, self.y, self.yaw = x, y, math.radians(rumbo)
        self.signo_giro, self.gira_quieto, self.desfase, self.salto_en, self.retardo = (
            signo_giro, gira_quieto, math.radians(desfase), salto_en, retardo)
        self.v = self.w = self.t = 0.0
        self.camino = [(x, y)]

    def avanzar(self, dt, orden):
        avance, _, giro = orden
        giro *= self.signo_giro
        if not self.gira_quieto and avance == 0.0:
            giro = 0.0
        a = 1 - math.exp(-dt / self.retardo)
        self.v += (avance - self.v) * a
        self.w += (giro - self.w) * a
        self.yaw += self.w * dt
        self.x += self.v * math.cos(self.yaw) * dt
        self.y += self.v * math.sin(self.yaw) * dt
        self.t += dt
        self.camino.append((self.x, self.y))

    def lectura(self):
        """Lo que diría la odometría: con el desfase de orientación y el salto, si los hay."""
        salto = 5.0 if self.salto_en is not None and self.t >= self.salto_en else 0.0
        return self.x + salto, self.y, normalizar(self.yaw + self.desfase)


class Reloj:
    """Reemplaza time en robot.py: dormir hace avanzar al X2 falso."""

    def __init__(self, x2, robot):
        self.x2, self.robot = x2, robot

    def monotonic(self):
        return self.x2.t

    def sleep(self, segundos):
        for _ in range(max(1, round(segundos / 0.02))):
            self.x2.avanzar(0.02, self.robot._velocidad)
            x, y, yaw = self.x2.lectura()
            self.robot._pose = (x, y, 0.6, yaw)


def guiar(x2, destino, ley='nueva'):
    """Corre robot.py contra el X2 falso. Devuelve (llegó, lo que imprimió, el X2)."""
    robot = modulo_robot.RobotMC(velocidad=0.2, real=True)
    robot.de_pie = lambda: True
    modulo_robot.time = Reloj(x2, robot)
    x, y, yaw = x2.lectura()
    robot._pose = (x, y, 0.6, yaw)
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        if ley == 'nueva':
            llego = robot.ir_a(*destino)
        else:  # la del 2026-10-24: gira siempre avanzando, con el freno de 30 cm
            cerca = [math.inf]

            def guia(px, py, _):
                d = math.hypot(destino[0] - px, destino[1] - py)
                if d < 0.35:
                    return None
                if d > cerca[0] + 0.3:
                    print(f'  se está alejando del destino ({d:.1f} m): me detengo')
                    return False
                cerca[0] = min(cerca[0], d)
                return math.atan2(destino[1] - py, destino[0] - px)
            llego = robot._conducir(guia, timeout=48.0)
    return llego, salida.getvalue().strip(), x2


fallos = 0


def comprobar(ok, texto):
    global fallos
    print(f'{"OK   " if ok else "FALLA"} {texto}')
    fallos += 0 if ok else 1


RECEPCION, GIMNASIO = (47.1, 24.9), (48.0, 22.9)  # los lugares marcados en el robot real el 2026-10-24
d0 = math.dist(RECEPCION, GIMNASIO)

# 1. El caso del registro, con la ley anterior: el robot mira a 105° (como quedó tras la caminata con el control) y el
#    Gimnasio está a -66°, casi detrás. Debe reproducir lo que pasó: se aleja y el freno lo detiene a ~2.5 m.
llego, dijo, x2 = guiar(X2Falso(*RECEPCION, 105), GIMNASIO, ley='anterior')
comprobar(not llego and 'alejando del destino (2.5 m)' in dijo, f'ley anterior: se aleja y frena como en el robot real («{dijo}»)')

# 2. La misma situación con la ley nueva: gira en el sitio y llega sin alejarse
llego, dijo, x2 = guiar(X2Falso(*RECEPCION, 105), GIMNASIO)
alejado = max(math.dist(p, GIMNASIO) for p in x2.camino) - d0
comprobar(llego and alejado < 0.1, f'ley nueva: llega en {x2.t:.0f} s y se aleja a lo sumo {alejado * 100:.0f} cm')

# 3. Cualquier orientación inicial y cualquier dirección del destino (2 m): siempre llega, sin alejarse
peores, anteriores = [], 0
for rumbo in range(-180, 180, 15):
    for hacia in range(-180, 180, 45):
        destino = (RECEPCION[0] + 2 * math.cos(math.radians(hacia)), RECEPCION[1] + 2 * math.sin(math.radians(hacia)))
        llego, dijo, x2 = guiar(X2Falso(*RECEPCION, rumbo), destino)
        peores.append((llego, max(math.dist(p, destino) for p in x2.camino) - 2, x2.t, rumbo, hacia, dijo))
        anteriores += not guiar(X2Falso(*RECEPCION, rumbo), destino, ley='anterior')[0]
llegaron = sum(p[0] for p in peores)
comprobar(llegaron == len(peores), f'ley nueva: llega en {llegaron}/{len(peores)} casos '
          f'(la anterior frenaba en {anteriores}); se aleja a lo sumo {max(p[1] for p in peores) * 100:.0f} cm, '
          f'tarda a lo sumo {max(p[2] for p in peores):.0f} s')

# 4. Si MC girara al revés de lo que dice el SDK (o la orientación contara al revés), se detiene enseguida
llego, dijo, x2 = guiar(X2Falso(*RECEPCION, 105, signo_giro=-1.0), GIMNASIO)
movio = math.dist(x2.camino[0], x2.camino[-1])
comprobar(not llego and 'al revés' in dijo and movio < 0.1, f'giro al revés: se detiene en {x2.t:.1f} s, moviéndose {movio * 100:.0f} cm («{dijo}»)')

# 5. Si MC no gira en el sitio (como en la simulación), gira avanzando y llega igual
llego, dijo, x2 = guiar(X2Falso(*RECEPCION, 105, gira_quieto=False), GIMNASIO)
alejado = max(math.dist(p, GIMNASIO) for p in x2.camino) - d0
comprobar(llego, f'sin giro en el sitio: llega girando avanzando en {x2.t:.0f} s (se aleja {alejado * 100:.0f} cm)')

# 6. Orientación mal calculada (90° corrida, como con el ángulo de Euler del sensor del pecho): frena en menos de medio metro
llego, dijo, x2 = guiar(X2Falso(*RECEPCION, 105, desfase=90), GIMNASIO)
movio = max(math.dist(x2.camino[0], p) for p in x2.camino)
comprobar(not llego and 'mal calculada' in dijo and movio < 0.6, f'orientación corrida 90°: frena tras {movio * 100:.0f} cm («{dijo}»)')

# 7. La posición salta a mitad de camino: frena
llego, dijo, x2 = guiar(X2Falso(*RECEPCION, -66, salto_en=3.0), GIMNASIO)
comprobar(not llego and 'saltó' in dijo, f'salto de la odometría: frena («{dijo}»)')

# 8. La caminata grabada con el control remoto: la comprobación de dirección no se dispara en los tramos rectos
if len(sys.argv) > 1:
    filas = [(float(r['t']), float(r['x']), float(r['y']), math.radians(float(r['orientacion'])))
             for r in csv.DictReader(open(sys.argv[1], encoding='utf-8'))]
    desvios, inicio = [], filas[0]
    for fila in filas[1:]:
        if math.dist(inicio[1:3], fila[1:3]) >= GuiaReal.TRAMO:
            hacia = math.atan2(fila[2] - inicio[2], fila[1] - inicio[1])
            giro = abs(normalizar(fila[3] - inicio[3]))
            if giro < math.radians(10):  # tramo recto: así camina la guía (gira quieta, camina recto)
                desvios.append(abs(math.degrees(normalizar(hacia - fila[3]))))
            inicio = fila
    saltos = max(math.dist(a[1:3], b[1:3]) for a, b in zip(filas, filas[1:]))
    comprobar(desvios and max(desvios) < math.degrees(GuiaReal.DESVIO) and saltos < GuiaReal.SALTO,
              f'grabación real: {len(desvios)} tramos rectos, desvío máximo {max(desvios):.0f}° '
              f'(frena desde {math.degrees(GuiaReal.DESVIO):.0f}°); mayor paso entre lecturas {saltos * 100:.0f} cm')

print(f'{fallos} fallos' if fallos else 'todos correctos')
sys.exit(1 if fallos else 0)
