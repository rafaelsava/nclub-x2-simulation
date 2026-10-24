"""Pantalla del robot y panel de control: estado compartido con los flujos y servidor web que los muestra.

En la simulación, la "pantalla de la cara" del X2 y la voz se muestran en el navegador (web/index.html).
Los flujos solo usan decir / preguntar / pedir_codigo / alertar, así que en el robot real basta con
cambiar esta clase por una que use la voz y la pantalla del AimDK.
"""

import json
import queue
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB_DIR = Path(__file__).parent / 'web'

CARAS = {'neutral', 'feliz', 'pensando', 'confundido', 'caminando'}


class Interfaz:
    def __init__(self, interprete=None):
        # interprete (lenguaje.Interprete) permite responder con palabras propias; sin él, solo valen los botones
        self.interprete = interprete
        self._lock = threading.Lock()
        self._respuestas = queue.Queue()
        self.llegadas = queue.Queue()
        self._estado = {
            'pantalla': {'cara': 'neutral', 'texto': '', 'opciones': [], 'pide_codigo': False, 'id_mensaje': 0,
                         'gesto': None, 'id_gesto': 0},
            'reconocimiento': None,
            'paso': 'Esperando visitantes',
            'alertas': [],
            'registro': [],
            'eventos': [],
        }

    # --- Lo que usan los flujos ---

    def decir(self, texto, cara=None):
        with self._lock:
            pantalla = self._estado['pantalla']
            pantalla.update(texto=texto, opciones=[], pide_codigo=False, id_mensaje=pantalla['id_mensaje'] + 1)
            if cara:
                pantalla['cara'] = cara
        self.evento(f'Robot: {texto}')
        # Tiempo aproximado para que la voz del navegador termine la frase antes de seguir
        time.sleep(max(1.5, len(texto) / 14))

    def cara(self, cara):
        assert cara in CARAS, cara
        with self._lock:
            self._estado['pantalla']['cara'] = cara

    def mostrar_gesto(self, nombre):
        # La simulación no ejecuta los gestos de MC, así que la pantalla muestra cuál haría el robot
        with self._lock:
            pantalla = self._estado['pantalla']
            pantalla.update(gesto=nombre, id_gesto=pantalla['id_gesto'] + 1)

    def preguntar(self, texto, opciones, timeout=40.0, pistas=None):
        """Muestra la pregunta con botones. Devuelve la opción elegida, o None si nadie respondió.

        Con un intérprete, el visitante también puede responder con sus palabras y el LLM elige la opción
        (pistas: {opción: qué cubre}, ayuda al LLM a entender respuestas indirectas).
        """
        self._vaciar_respuestas()
        self.decir(texto)
        limite = time.monotonic() + timeout
        no_entendidas = 0
        try:
            while True:
                with self._lock:
                    self._estado['pantalla']['opciones'] = list(opciones)
                respuesta = self._respuestas.get(timeout=max(0.1, limite - time.monotonic()))
                if respuesta in opciones:
                    self.evento(f'Visitante: {respuesta}')
                    return respuesta
                if not self.interprete or not respuesta:
                    continue
                opcion = self._interpretar(
                    lambda: self.interprete.elegir_opcion(texto, opciones, respuesta, pistas), respuesta, 'LLM')
                if opcion:
                    return opcion
                no_entendidas += 1
                if no_entendidas == 1:
                    self.decir('Disculpe, no le entendí. ¿Me lo puede decir de otra forma?', cara='confundido')
                else:
                    self.decir('Puede tocar una de las opciones en mi pantalla.', cara='neutral')
        except queue.Empty:
            self.evento('Visitante: (sin respuesta)')
            return None
        finally:
            with self._lock:
                self._estado['pantalla']['opciones'] = []

    def pedir_codigo(self, texto, timeout=60.0):
        """Muestra un campo para escribir un código. Devuelve el texto, o None si nadie respondió.

        Con un intérprete, el visitante puede decirlo con palabras ("mil setenta y siete") y se devuelven las cifras.
        """
        self._vaciar_respuestas()
        self.decir(texto)
        with self._lock:
            self._estado['pantalla']['pide_codigo'] = True
        try:
            respuesta = self._respuestas.get(timeout=timeout)
        except queue.Empty:
            self.evento('Visitante: (sin respuesta)')
            return None
        finally:
            with self._lock:
                self._estado['pantalla']['pide_codigo'] = False
        if not self.interprete:
            self.evento(f'Visitante escribe: {respuesta}')
            return respuesta
        # Las cifras dichas en palabras se convierten con reglas (lenguaje.cifras_dichas), no con el LLM
        codigo = self._interpretar(lambda: self.interprete.extraer_codigo(texto, respuesta), respuesta, 'código')
        return codigo or respuesta

    def _interpretar(self, consulta, dicho, quien):
        with self._lock:
            pantalla = self._estado['pantalla']
            cara_antes = pantalla['cara']
            pantalla['cara'] = 'pensando'
        resultado = consulta()
        with self._lock:
            self._estado['pantalla']['cara'] = cara_antes
        if resultado.error:
            self.evento(f'Visitante: "{dicho}" → el {quien} no respondió ({resultado.error})')
        elif quien == 'LLM':
            self.evento(f'Visitante: "{dicho}" → LLM: {resultado.valor or "no entendió"} ({resultado.segundos:.1f} s)')
        else:
            self.evento(f'Visitante: "{dicho}" → {quien}: {resultado.valor or "no reconocido"}')
        return resultado.valor

    def paso(self, texto):
        with self._lock:
            self._estado['paso'] = texto
        self.evento(f'— {texto}')

    def alertar(self, texto, urgente=False):
        """Aviso para el personal de recepción (o para un anfitrión o responsable de área)."""
        with self._lock:
            alertas = self._estado['alertas']
            alertas.append({'id': len(alertas) + 1, 'hora': _hora(), 'texto': texto,
                            'urgente': urgente, 'atendida': False})
        self.evento(f'Aviso a recepción: {texto}')

    def mostrar_reconocimiento(self, reconocimiento):
        with self._lock:
            self._estado['reconocimiento'] = dict(reconocimiento, hora=_hora())

    def registrar(self, entrada):
        with self._lock:
            self._estado['registro'].append(dict(entrada, hora=_hora()))

    def evento(self, texto):
        with self._lock:
            eventos = self._estado['eventos']
            eventos.append(f'{_hora()}  {texto}')
            del eventos[:-200]

    def en_reposo(self):
        with self._lock:
            self._estado['paso'] = 'Esperando visitantes'
            self._estado['pantalla'].update(cara='neutral', texto='', opciones=[], pide_codigo=False)

    # --- Lo que usa el servidor web ---

    def _vaciar_respuestas(self):
        while not self._respuestas.empty():
            self._respuestas.get_nowait()

    def responder(self, valor):
        self._respuestas.put(str(valor).strip())

    def atender_alerta(self, alerta_id):
        with self._lock:
            for alerta in self._estado['alertas']:
                if alerta['id'] == alerta_id:
                    alerta['atendida'] = True

    def foto(self):
        with self._lock:
            return json.loads(json.dumps(self._estado))

    def servir(self, host, puerto, al_simular_llegada, resolver_reconocimiento, estado_robot, datos_panel):
        interfaz = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, data, status=200):
                body = json.dumps(data, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self):
                largo = int(self.headers.get('Content-Length') or 0)
                return json.loads(self.rfile.read(largo) or b'{}')

            def do_GET(self):
                if self.path in ('/', '/index.html'):
                    body = (WEB_DIR / 'index.html').read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == '/api/estado':
                    self._json(dict(interfaz.foto(), robot=estado_robot(),
                                    llegadas_en_espera=interfaz.llegadas.qsize(),
                                    lenguaje_natural=interfaz.interprete is not None))
                elif self.path == '/api/panel':
                    self._json(datos_panel)
                else:
                    self._json({'error': 'no encontrado'}, 404)

            def do_POST(self):
                try:
                    body = self._body()
                except ValueError:
                    return self._json({'error': 'JSON inválido'}, 400)
                if self.path == '/api/llegada':
                    # Panel: simula que una persona llega y el reconocimiento facial del club la ve
                    reconocimiento = al_simular_llegada(body.get('visitante'), bool(body.get('dudoso')))
                    if reconocimiento is None:
                        return self._json({'error': 'visitante desconocido'}, 400)
                    interfaz.llegadas.put(reconocimiento)
                    self._json({'ok': True, 'reconocimiento': reconocimiento})
                elif self.path == '/api/reconocimiento':
                    # Resultado del modelo facial real: id de la persona (o null si es desconocida) y confianza
                    reconocimiento = resolver_reconocimiento(body.get('persona_id'), body.get('confianza'),
                                                             body.get('fuente', 'modelo'), bool(body.get('incierto')))
                    interfaz.llegadas.put(reconocimiento)
                    self._json({'ok': True, 'reconocimiento': reconocimiento})
                elif self.path == '/api/respuesta':
                    interfaz.responder(body.get('valor', ''))
                    self._json({'ok': True})
                elif self.path == '/api/alerta':
                    interfaz.atender_alerta(int(body.get('id', 0)))
                    self._json({'ok': True})
                else:
                    self._json({'error': 'no encontrado'}, 404)

        servidor = ThreadingHTTPServer((host, puerto), Handler)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        return servidor


def _hora():
    return datetime.now().strftime('%H:%M:%S')
