#!/usr/bin/env python3
"""Prueba de la caminata en el X2 real, sin PIBOT. Usa el mismo control que el puente (robot.py en modo real, con
guia_real.py) para ir a un punto relativo a donde está el robot ahora.

    python3 caminar_real.py donde            # dice dónde está y hacia dónde mira (no se mueve)
    python3 caminar_real.py adelante 1.0     # 1 m al frente
    python3 caminar_real.py izquierda 1.0    # 1 m a su izquierda: gira 90° en el sitio y camina
    python3 caminar_real.py atras 2.0        # 2 m detrás: media vuelta en el sitio
    python3 caminar_real.py volver           # vuelve al punto donde empezó la primera prueba

Antes de correrlo:
- el robot de pie en modo caminar, puesto con el control;
- el camino libre;
- una persona con el control en la mano y otra cerca para sostenerlo.

Ctrl+C lo detiene. Cada prueba deja su trayectoria (posición cada 0.2 s) en logs/caminata-<hora>.csv. No corre si
el puente de PIBOT está encendido: los dos mandarían el mismo cuerpo.
"""

import argparse
import csv
import json
import math
import os
import signal
import threading
import time

from robot import crear_robot

AQUI = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(AQUI, '..', 'logs')
INICIO = os.path.join(LOGS, 'caminata-inicio.json')  # el punto de partida, para "volver"
GIROS = {'adelante': 0.0, 'izquierda': math.pi / 2, 'derecha': -math.pi / 2, 'atras': math.pi}


def puente_encendido():
    for pid in filter(str.isdigit, os.listdir('/proc')):
        try:
            if b'puente.py' in open(f'/proc/{pid}/cmdline', 'rb').read():
                return True
        except OSError:
            pass
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('accion', choices=['donde', 'volver', *GIROS])
    p.add_argument('distancia', nargs='?', type=float, default=1.0, help='metros (de 0.3 a 3)')
    p.add_argument('--velocidad', type=float, default=0.2, help='m/s en recta (MC acepta desde 0.2)')
    a = p.parse_args()
    if not 0.3 <= a.distancia <= 3.0:
        p.error('la distancia va de 0.3 a 3 m: para la prueba, cerca y con el camino libre')
    os.makedirs(LOGS, exist_ok=True)
    if a.accion != 'donde' and puente_encendido():
        p.error('el puente de PIBOT está encendido (./nclub.sh detener): los dos mandarían el mismo cuerpo')

    robot = crear_robot(False, velocidad=a.velocidad, nombre='nclub_caminata', real=True)
    robot.iniciar()
    # Para frenarlo desde otra terminal: kill -INT $(cat logs/caminata.pid)
    signal.signal(signal.SIGINT, lambda *_: robot.detener())
    signal.signal(signal.SIGTERM, lambda *_: robot.detener())
    pid = os.path.join(LOGS, 'caminata.pid')
    open(pid, 'w').write(str(os.getpid()))
    try:
        for _ in range(50):  # hasta 5 s para que llegue la odometría
            if robot._pose is not None and robot.odometria:
                break
            time.sleep(0.1)
        if robot._pose is None:
            print('No llega la posición del robot (odometría). No camino.')
            return
        x, y, _, yaw = robot._pose
        print(f'odometría: {robot.odometria} · modo de MC: {robot._leer_modo()}')
        print(f'está en x {x:.2f} m, y {y:.2f} m, mirando a {math.degrees(yaw):.0f}°')
        if a.accion == 'donde':
            return
        if a.accion == 'volver':
            if not os.path.exists(INICIO):
                print('No hay punto de partida guardado: todavía no se ha hecho ninguna prueba.')
                return
            inicio = json.load(open(INICIO))
            if inicio['odometria'] != robot.odometria:
                print(f'El punto de partida es de otra odometría ({inicio["odometria"]}): no lo uso.')
                return
            tx, ty = inicio['x'], inicio['y']
        else:
            if not os.path.exists(INICIO):
                json.dump({'x': x, 'y': y, 'odometria': robot.odometria}, open(INICIO, 'w'))
            rumbo = yaw + GIROS[a.accion]
            tx, ty = x + a.distancia * math.cos(rumbo), y + a.distancia * math.sin(rumbo)
        print(f'voy a x {tx:.2f} m, y {ty:.2f} m ({math.hypot(tx - x, ty - y):.2f} m)')

        # La trayectoria, para revisar después qué hizo
        ruta = os.path.join(LOGS, f'caminata-{time.strftime("%H%M%S")}.csv')
        listo = threading.Event()

        def grabar():
            with open(ruta, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(['t', 'x', 'y', 'orientacion', 'avance', 'giro'])
                t0 = time.monotonic()
                while not listo.is_set():
                    if robot._pose:
                        px, py, _, pyaw = robot._pose
                        w.writerow([round(time.monotonic() - t0, 2), round(px, 3), round(py, 3), round(math.degrees(pyaw), 1),
                                    round(robot._velocidad[0], 2), round(robot._velocidad[2], 2)])
                    time.sleep(0.2)
        hilo = threading.Thread(target=grabar, daemon=True)
        hilo.start()
        t0 = time.monotonic()
        llego = robot.ir_a(tx, ty, tolerancia=0.15)  # más justa que en PIBOT (0.35): en la prueba se mide la precisión
        listo.set()
        hilo.join(timeout=1)

        fx, fy, _, fyaw = robot._pose
        falta = math.hypot(tx - fx, ty - fy)
        print(f'{"llegó" if llego else "se detuvo"} en {time.monotonic() - t0:.0f} s: quedó a {falta:.2f} m del punto, '
              f'en x {fx:.2f}, y {fy:.2f}, mirando a {math.degrees(fyaw):.0f}°')
        print(f'trayectoria: {os.path.relpath(ruta, os.path.join(AQUI, ".."))}')
    finally:
        robot.cerrar()
        os.remove(pid)


if __name__ == '__main__':
    main()
