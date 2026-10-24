#!/usr/bin/env python3
"""Puente PIBOT → X2: el lado "MuJoCo" del protocolo de PIBOT (PIBOT/src/robot/mujoco-bridge.js).

PIBOT, el editor sin código, decide qué hace el robot; este puente hace que el X2 lo haga, en MuJoCo o en el
robot real, a través del control de movimiento oficial (MC). Protocolo: JSON por WebSocket.
  PIBOT → puente: {"id": 1, "cmd": "speak", "text": "Hola"}
                  {"id": 2, "cmd": "navigate", "destination": "Salón VIP, piso 3"}
                  {"id": 3, "cmd": "gesture", "name": "saludar"}          (saludar | asentir | señalar)
                  {"id": 4, "cmd": "show", "title": "...", "text": "..."}
                  {"id": 5, "cmd": "hello"} | places [{name, x, y}] | interpret question, options, text | pose
  puente → PIBOT: {"id": 1, "ok": true} al terminar la acción, o {"id": 2, "ok": false, "error": "..."}
  (detalle de todas las órdenes al inicio de PIBOT/src/robot/mujoco-bridge.js)

Uso dentro del contenedor (./x2 pibot):  python3 /workspace/scripts/pibot/puente.py
Sin simulador, solo para probar flujos:  python3 scripts/pibot/puente.py --sin-robot
"""

import argparse
import base64
import hashlib
import json
import re
import signal
import socketserver
import struct
import threading
import time
import unicodedata
from pathlib import Path

from lenguaje import Interprete
from robot import crear_robot

DESTINOS = Path(__file__).parent / 'destinos.json'

# Órdenes que mueven o "ocupan" al robot frente al visitante: solo estas cuentan para volver al puesto
ACCIONES = {'speak', 'show', 'gesture', 'navigate'}

# Gestos de PIBOT → gestos de MC. "asentir" no tiene equivalente entre los gestos predefinidos del X2.
GESTOS = {'saludar': 'saludar', 'señalar': 'levantar', 'asentir': None}

# Tras guiar a alguien, el robot espera esto sin recibir órdenes antes de volver a su puesto
# (así puede seguir hablando en el destino si el flujo lo pide)
VOLVER_TRAS_S = 5.0


PALETA = [[0.83, 0.63, 0.09], [0.09, 0.64, 0.29], [0.05, 0.58, 0.53], [0.86, 0.15, 0.15], [0.15, 0.39, 0.92],
          [0.86, 0.15, 0.47], [0.92, 0.35, 0.05], [0.49, 0.23, 0.93], [0.4, 0.65, 0.12], [0.02, 0.52, 0.78]]


def _normalizar(texto):
    sin_tildes = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode()
    return ' '.join(sin_tildes.lower().replace(',', ' ').split())


def _destinos_legibles(datos):
    # Un destino por línea, como lo escribiría una persona, en vez de un número por línea
    otros = {k: v for k, v in datos.items() if k != 'destinos'}
    cuerpo = json.dumps(otros, ensure_ascii=False, indent=2)[:-2]
    lineas = ',\n'.join(f'    {json.dumps(d, ensure_ascii=False)}' for d in datos['destinos'])
    return f'{cuerpo},\n\n  "destinos": [\n{lineas}\n  ]\n}}\n'


class Puente:
    def __init__(self, robot, destinos, interprete=None, levantar_solo=False, real=False, sentidos=None):
        self.robot = robot
        self.sentidos = sentidos  # cámara de la cabeza y micrófono del robot real (None en la simulación)
        self._ultima_llegada, self._visto, self._se_fue = 0.0, 0.0, True
        self.real = real  # el X2 de verdad: con voz, sin levantarse solo
        self.interprete = interprete
        self.puesto = destinos['puesto']
        self.destinos = destinos['destinos']
        self._cuerpo = threading.Lock()   # una sola acción física a la vez
        self._volver = None
        self._volviendo = False
        self._fuera_del_puesto = False
        self.levantando = False
        self._sin_levantar_solo = False  # tras fallar, deja de intentarlo solo hasta que alguien lo levante
        if levantar_solo:
            threading.Thread(target=self._vigilar_caidas, daemon=True).start()

    def ruta(self, texto):
        """'Acceso de servicio → Spa, piso 2' → [destino, destino]. El piso y lo demás tras la coma se ignoran."""
        tramos = [t for t in texto.replace('->', '→').split('→') if t.strip()]
        ruta = []
        for tramo in tramos:
            t = _normalizar(tramo)
            candidatos = []
            for d in self.destinos:
                for nombre in [d['nombre'], *d.get('alias', [])]:
                    n = _normalizar(nombre)
                    if t == n or t.startswith(n + ' '):
                        candidatos.append((len(n), d))
            if not candidatos:
                raise LookupError(f'sin ruta a "{tramo.strip()}" (no está en destinos.json)')
            ruta.append(max(candidatos, key=lambda c: c[0])[1])
        return ruta

    def atender(self, msg):
        cmd = msg.get('cmd')
        respuesta = {'id': msg.get('id'), 'ok': True}
        if cmd in ACCIONES and self._volver:
            self._volver.cancel()  # llegó otra orden: el robot sigue con el visitante
        try:
            if cmd == 'hello':
                # En el robot real no se ofrece levantarlo desde PIBOT: se levanta con el control y con gente al lado
                capacidades = ['interpret', 'places', 'pose'] + ([] if self.real else ['stand_up'])
                if self.sentidos and self.sentidos.rostro_url:
                    capacidades += ['identify', 'arrivals', 'scan_code']
                if self.sentidos and self.sentidos.voz_url:
                    capacidades.append('listen')
                respuesta.update(capabilities=capacidades, llm=self.interprete is not None, real=self.real)
            elif cmd == 'places':
                self._recibir_lugares(msg.get('places'), bool(msg.get('save')))
            elif cmd == 'interpret':
                respuesta['option'] = self._interpretar(msg)
            elif cmd == 'pose':
                estado = self.robot.estado()
                respuesta.update(x=estado.get('x'), y=estado.get('y'), heading=estado.get('orientacion'),
                                 height=estado.get('altura'), recovering=self.levantando)
            elif cmd == 'stand_up':
                if self.real:
                    raise RuntimeError('en el robot real se levanta con el control remoto, con personas al lado')
                if not self._levantar():
                    raise RuntimeError('el robot no logró levantarse; en la simulación, ./x2 pie lo pone de pie')
            elif cmd == 'speak':
                texto = msg.get('text', '')
                print(f'habla: {texto}', flush=True)
                # En el robot real lo dice su parlante; la simulación no tiene voz. Se espera lo que tarda en decirlo.
                dura = self.robot.hablar(texto) if self.real else None
                time.sleep(dura if dura and dura < 60 else max(1.0, len(texto) / 14))
                if self.sentidos:  # lo que el micrófono oiga antes de esto es la voz del propio robot
                    self.sentidos.callado_desde = time.monotonic()
            elif cmd == 'identify':
                respuesta.update(self._sentido('identificar'))
            elif cmd == 'listen':
                respuesta['text'] = self._sentido('escuchar', timeout=float(msg.get('timeout', 8)))
            elif cmd == 'scan_code':
                respuesta['text'] = self._sentido('leer_qr', timeout=float(msg.get('timeout', 10)))
            elif cmd == 'stop_listening':
                self._sentido('dejar')
            elif cmd == 'wait_arrival':
                respuesta['arrived'] = self._esperar_llegada(float(msg.get('timeout', 15)))
            elif cmd == 'show':
                print(f'pantalla: {msg.get("title", "")} / {msg.get("text", "")}', flush=True)
            elif cmd == 'gesture':
                self._gesto(msg.get('name', ''))
            elif cmd == 'navigate':
                self._guiar(msg.get('destination', ''))
            else:
                raise ValueError(f'comando desconocido: {cmd}')
            return respuesta
        except (LookupError, ValueError, RuntimeError) as e:
            print(f'error en {cmd}: {e}', flush=True)
            return {'id': msg.get('id'), 'ok': False, 'error': str(e)}
        finally:
            if cmd in ACCIONES and self._fuera_del_puesto:
                self._programar_vuelta()

    def _sentido(self, que, **kw):
        if not self.sentidos:
            raise RuntimeError('este puente no tiene cámara ni micrófono (solo en el robot real: ./x2 pibot-real)')
        return getattr(self.sentidos, que)(**kw)

    def _esperar_llegada(self, timeout):
        """Espera a que alguien se acerque al robot: una cara cerca en dos fotos seguidas.

        Después de avisar una llegada, la siguiente cuenta solo cuando pasaron 10 s y esa persona se fue (3 s sin ver
        a nadie), o pasó un minuto, para no recibir dos veces a quien sigue parado frente al robot.
        """
        if not self.sentidos or not self.sentidos.rostro_url:
            raise RuntimeError('este puente no tiene cámara')
        fin, seguidas = time.monotonic() + timeout, 0
        while time.monotonic() < fin:
            cerca, ahora = self.sentidos.alguien_cerca(), time.monotonic()
            if cerca:
                self._visto = ahora
            elif ahora - self._visto > 3:
                self._se_fue = True
            seguidas = seguidas + 1 if cerca else 0
            if seguidas >= 2 and ((self._se_fue and ahora - self._ultima_llegada > 10) or ahora - self._ultima_llegada > 60):
                self._ultima_llegada, self._se_fue = ahora, False
                print('llegó alguien', flush=True)
                return True
            time.sleep(0.5)
        return False

    def _recibir_lugares(self, lugares, guardar):
        """Lugares del club definidos en PIBOT (pantalla "Lugares"): reemplazan a los de destinos.json."""
        if not isinstance(lugares, list):
            raise ValueError('places debe ser una lista')
        colores = {_normalizar(d['nombre']): d for d in self.destinos}
        nuevos = []
        for lugar in lugares:
            try:
                nombre, x, y = str(lugar['name']).strip(), float(lugar['x']), float(lugar['y'])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f'lugar inválido: {lugar}')
            if not nombre:
                raise ValueError('hay un lugar sin nombre')
            anterior = colores.get(_normalizar(nombre), {})
            nuevo = {'nombre': nombre, 'x': round(x, 2), 'y': round(y, 2)}
            for clave in ('color', 'alias', 'ambiente'):  # lo que PIBOT no manda se conserva
                if clave in anterior:
                    nuevo[clave] = anterior[clave]
            # Color ("#rrggbb") y tipo de lugar elegidos en PIBOT: los mismos en su mapa y en MuJoCo
            color = str(lugar.get('color') or '')
            if re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                nuevo['color'] = [round(int(color[i:i + 2], 16) / 255, 2) for i in (1, 3, 5)]
            if lugar.get('kind'):
                nuevo['ambiente'] = str(lugar['kind'])
            nuevos.append(nuevo)
        # Los lugares nuevos reciben un color libre para verse distintos en MuJoCo
        usados = {tuple(d['color']) for d in nuevos if 'color' in d}
        libres = [c for c in PALETA if tuple(c) not in usados]
        for d in nuevos:
            if 'color' not in d:
                d['color'] = libres.pop(0) if libres else [0.5, 0.5, 0.5]
        self.destinos = nuevos
        # El puesto (a donde vuelve el robot) es el lugar de PIBOT con el mismo nombre, p. ej. Recepción marcada con
        # "Aquí está el robot": en el robot real la odometría no empieza donde está su puesto
        puesto = next((d for d in nuevos if _normalizar(d['nombre']) == _normalizar(self.puesto['nombre'])), None)
        if puesto:
            self.puesto = {'nombre': puesto['nombre'], 'x': puesto['x'], 'y': puesto['y']}
        print(f'lugares de PIBOT: {", ".join(d["nombre"] for d in nuevos)}', flush=True)
        if guardar:
            datos = json.loads(DESTINOS.read_text(encoding='utf-8'))
            datos['destinos'] = nuevos
            DESTINOS.write_text(_destinos_legibles(datos), encoding='utf-8')
            print(f'  guardados en {DESTINOS.name}; ./x2 escena los dibuja en MuJoCo', flush=True)

    def _interpretar(self, msg):
        """Qué opción quiso decir el visitante. El LLM solo puede devolver una de las opciones (o ninguna)."""
        if not self.interprete:
            raise RuntimeError('el puente no tiene LLM (./x2 llm y reiniciar ./x2 pibot)')
        opciones = [str(o) for o in msg.get('options') or []]
        pistas = msg.get('hints') if isinstance(msg.get('hints'), dict) else None  # "Cómo reconocer cada opción"
        r = self.interprete.elegir_opcion(str(msg.get('question', '')), opciones, str(msg.get('text', '')),
                                          ejemplos=pistas)
        print(f'interpreta: "{msg.get("text")}" → {r.valor or "no entendió"} ({r.segundos:.1f} s)', flush=True)
        return r.valor

    def _gesto(self, nombre):
        gesto = GESTOS.get(nombre)
        print(f'gesto: {nombre}', flush=True)
        if gesto:
            # En segundo plano: el MC de la simulación (mc-x86 v1.0.0) no responde a los gestos y no debe
            # frenar el flujo. En el robot real (firmware v1.1.0) sí se ejecutan.
            def hacer():
                if not self.robot.gesto(gesto):
                    print(f'  (gesto "{nombre}" no ejecutado por MC)', flush=True)
            threading.Thread(target=hacer, daemon=True).start()
        time.sleep(1.5)

    def _en_el_suelo(self):
        altura = self.robot.estado().get('altura')
        return altura is not None and altura < 0.4

    def _levantar(self):
        """Levanta al robot si está en el suelo y luego lo lleva de vuelta a su puesto."""
        if self._volver:
            self._volver.cancel()
        if self._volviendo:
            self.robot.detener()
        with self._cuerpo:
            if not self._en_el_suelo():
                return True
            print('el robot está en el suelo: levantándose', flush=True)
            self.levantando = True
            try:
                ok = self.robot.levantarse()
            finally:
                self.levantando = False
            print('  de pie' if ok else '  no logró levantarse; espera a que lo levanten desde PIBOT o con ./x2 pie', flush=True)
        if ok:
            self._fuera_del_puesto = True  # quedó donde cayó: vuelve a recepción como después de guiar
            self._programar_vuelta()
        return ok

    def _vigilar_caidas(self):
        # Solo en la simulación (--levantar-solo): si queda 3 s en el suelo sin atender a nadie, se levanta solo.
        # En el robot real se levanta con el botón de PIBOT, porque el manual pide 0.5 m libres alrededor.
        en_el_suelo_desde = None
        while True:
            time.sleep(1.0)
            if not self._en_el_suelo():
                en_el_suelo_desde, self._sin_levantar_solo = None, False
                continue
            if self.levantando or self._sin_levantar_solo:
                en_el_suelo_desde = None
                continue
            en_el_suelo_desde = en_el_suelo_desde or time.monotonic()
            if time.monotonic() - en_el_suelo_desde >= 3.0 and not self._cuerpo.locked():
                self._sin_levantar_solo = not self._levantar()
                en_el_suelo_desde = None

    def _guiar(self, destino):
        ruta = self.ruta(destino)
        if self._en_el_suelo():
            raise RuntimeError('el robot está en el suelo y no puede guiar (en la simulación: ./x2 pie lo levanta)')
        if self._volviendo:
            # Llegó otro visitante mientras volvía al puesto: se corta la vuelta y va directo al nuevo destino,
            # para no pasarse de los 20 s que PIBOT espera por cada acción
            self.robot.detener()
        with self._cuerpo:
            inicio = time.monotonic()
            for d in ruta:
                print(f'guía a: {d["nombre"]} ({d["x"]}, {d["y"]})', flush=True)
                self._fuera_del_puesto = (d['x'], d['y']) != (self.puesto['x'], self.puesto['y'])
                if not self.robot.ir_a(d['x'], d['y']):
                    motivo = 'se cayó en el camino' if self._en_el_suelo() else 'no pudo llegar'
                    raise RuntimeError(f'el robot {motivo} a {d["nombre"]}')
            print(f'  llegó en {time.monotonic() - inicio:.1f} s', flush=True)

    def _programar_vuelta(self):
        self._volver = threading.Timer(VOLVER_TRAS_S, self._volver_al_puesto)
        self._volver.daemon = True
        self._volver.start()

    def _volver_al_puesto(self):
        with self._cuerpo:
            print('vuelve al puesto', flush=True)
            self._volviendo = True
            try:
                llego = self.robot.volver_al_puesto(self.puesto)
            finally:
                self._volviendo = False
            if llego:
                self._fuera_del_puesto = False
            elif self._en_el_suelo():
                print('  ¡el robot se cayó volviendo al puesto! En la simulación: ./x2 pie', flush=True)
            else:
                print('  vuelta interrumpida (llegó otro visitante)', flush=True)


class WebSocket(socketserver.StreamRequestHandler):
    """WebSocket mínimo (RFC 6455) con la biblioteca estándar: mensajes de texto cortos, sin extensiones."""

    GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
    puente = None

    def handle(self):
        headers = {}
        linea = self.rfile.readline()
        while True:
            h = self.rfile.readline().decode('latin-1').strip()
            if not h:
                break
            k, _, v = h.partition(':')
            headers[k.strip().lower()] = v.strip()
        clave = headers.get('sec-websocket-key')
        if not linea.startswith(b'GET') or not clave:
            self.wfile.write(b'HTTP/1.1 400 Bad Request\r\n\r\n')
            return
        aceptar = base64.b64encode(hashlib.sha1((clave + self.GUID).encode()).digest()).decode()
        self.wfile.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                          f'Sec-WebSocket-Accept: {aceptar}\r\n\r\n').encode())
        print(f'PIBOT conectado desde {self.client_address[0]}', flush=True)
        try:
            while True:
                opcode, datos = self._leer()
                if opcode == 0x8:  # cerrar
                    self._enviar(b'', 0x8)
                    break
                if opcode == 0x9:  # ping
                    self._enviar(datos, 0xA)
                    continue
                if opcode != 0x1:
                    continue
                try:
                    msg = json.loads(datos.decode())
                except ValueError:
                    continue
                self._enviar(json.dumps(self.puente.atender(msg)).encode())
        except (ConnectionError, struct.error, EOFError):
            pass
        print('PIBOT desconectado', flush=True)

    def _leer(self):
        mensaje, opcode = b'', None
        while True:
            b1, b2 = self._exacto(2)
            largo = b2 & 0x7F
            if largo == 126:
                largo = struct.unpack('>H', self._exacto(2))[0]
            elif largo == 127:
                largo = struct.unpack('>Q', self._exacto(8))[0]
            mascara = self._exacto(4) if b2 & 0x80 else b'\0\0\0\0'
            datos = bytes(b ^ mascara[i % 4] for i, b in enumerate(self._exacto(largo)))
            if b1 & 0x0F:
                opcode = b1 & 0x0F
            mensaje += datos
            if b1 & 0x80:  # último fragmento
                return opcode, mensaje

    def _exacto(self, n):
        datos = self.rfile.read(n)
        if len(datos) < n:
            raise EOFError
        return datos

    def _enviar(self, datos, opcode=0x1):
        largo = len(datos)
        if largo < 126:
            cabecera = struct.pack('>BB', 0x80 | opcode, largo)
        elif largo < 65536:
            cabecera = struct.pack('>BBH', 0x80 | opcode, 126, largo)
        else:
            cabecera = struct.pack('>BBQ', 0x80 | opcode, 127, largo)
        self.wfile.write(cabecera + datos)


class Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--sin-robot', action='store_true', help='no usar ROS ni MC: el robot solo se imita')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--puerto', type=int, default=8765)
    # 0.3 m/s es lo probado: a 0.5 m/s el robot se cayó en un giro en la simulación (2026-10-23)
    parser.add_argument('--velocidad', type=float,
                        help='avance al guiar en m/s (MC acepta 0.2 a 1.0); 0.3 en la simulación, 0.2 en el robot real')
    parser.add_argument('--llm', metavar='URL', help='LLM para entender lenguaje natural, p. ej. http://127.0.0.1:8095/v1')
    parser.add_argument('--levantar-solo', action='store_true',
                        help='si el robot se cae y nadie lo está usando, se levanta solo (para la simulación)')
    parser.add_argument('--rostro', metavar='URL', help='reconocimiento facial con la cámara de la cabeza, p. ej. http://127.0.0.1:8096')
    parser.add_argument('--voz', metavar='URL', help='voz a texto con el micrófono del robot, p. ej. http://127.0.0.1:8097')
    parser.add_argument('--camara', default=None, help='tópico de la cámara (CompressedImage)')
    parser.add_argument('--microfono', default=None, help='tópico del micrófono (ProcessedAudioOutput)')
    parser.add_argument('--real', action='store_true',
                        help='el X2 de verdad: habla por su parlante, camina a 0.2 m/s, no se levanta solo y usa destinos_real.json')
    args = parser.parse_args()
    if args.real and args.levantar_solo:
        parser.error('en el robot real no se usa --levantar-solo: se levanta con el control remoto y con gente al lado')
    velocidad = args.velocidad or (0.2 if args.real else 0.3)
    global DESTINOS
    if args.real:
        # Los lugares del robot real son otros que los del lobby de MuJoCo: la odometría empieza donde se prendió el robot
        DESTINOS = DESTINOS.with_name('destinos_real.json')
        if not DESTINOS.exists():
            DESTINOS.write_text(_destinos_legibles({
                '_nota': 'Lugares del robot real (odometría desde donde arrancó). Se definen en PIBOT, Lugares: '
                         'lleve el robot con el control hasta cada sitio, pulse "Aquí está el robot" y luego "Guardar en el robot".',
                'puesto': {'nombre': 'Recepción', 'x': 0.0, 'y': 0.0},
                'destinos': [{'nombre': 'Recepción', 'x': 0.0, 'y': 0.0, 'color': [0.42, 0.46, 0.44]}]}), encoding='utf-8')

    interprete = None
    if args.llm:
        interprete = Interprete(args.llm)
        if not interprete.disponible():
            parser.error(f'el LLM no responde en {args.llm} (¿está corriendo ./x2 llm?)')
        interprete.elegir_opcion('¿Prefiere café o té?', ['Café', 'Té'], 'un tinto, por favor')  # calentar el modelo
        print(f'Lenguaje natural activado con {args.llm}', flush=True)

    robot = crear_robot(args.sin_robot, velocidad, nombre='nclub_pibot', real=args.real)
    robot.iniciar()
    sentidos = None
    if (args.rostro or args.voz) and not args.sin_robot:
        from sentidos import CAMARA, MICROFONO, Sentidos
        sentidos = Sentidos(robot._node, args.rostro, args.voz, args.camara or CAMARA, args.microfono or MICROFONO)
        print('Sentidos: ' + ', '.join(s for s, on in (('cámara de la cabeza', args.rostro), ('micrófono', args.voz)) if on),
              flush=True)
    if not args.sin_robot:  # sin odometría no hay robot: mejor decirlo ahora que cuando PIBOT lo mande a caminar
        for _ in range(80):
            if robot.estado().get('x') is not None:  # en el real no hay altura: basta con que llegue la posición
                break
            time.sleep(0.1)
        else:
            print('No llega la odometría del robot. ' + (
                'Revisa el cable al puerto de desarrollo, la IP 10.0.1.2 y ROS_DOMAIN_ID (ver README).' if args.real
                else '¿Están corriendo ./x2 sim y ./x2 mc?'), flush=True)
    WebSocket.puente = Puente(robot, json.loads(DESTINOS.read_text(encoding='utf-8')), interprete, args.levantar_solo,
                              args.real, sentidos)
    if args.real:
        print(f'ROBOT REAL: camina a {velocidad} m/s en línea recta y no esquiva obstáculos. Ten el control remoto en la mano: '
              'si lo mueves, manda el control y se ignora a PIBOT; para detenerlo de inmediato, el manual indica '
              'torque cero (L1 + R1 + Create), y el robot se desploma: alguien debe sostenerlo del asa.', flush=True)
    servidor = Servidor((args.host, args.puerto), WebSocket)
    print(f'Puente PIBOT listo en ws://{args.host}:{args.puerto} (en PIBOT, arriba a la derecha: "AgiBot X2 en MuJoCo";'
          f'{" con este puente aparece como AgiBot X2 real" if args.real else ""})',
          flush=True)

    def salir(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, salir)
    signal.signal(signal.SIGTERM, salir)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
        robot.cerrar()


if __name__ == '__main__':
    main()
