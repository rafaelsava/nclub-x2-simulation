#!/usr/bin/env python3
"""La voz del robot: faster-whisper para entender lo que oye y Piper para hablar.

    ./x2 voz            (Docker, http://127.0.0.1:8097)

En el robot real, el puente junta cada frase que oye el X2 (su sistema de audio ya la separa con detección de voz y le
quita el ruido) y la manda aquí; el robot habla con su propia voz. En la simulación, PIBOT graba al visitante con el
micrófono del portátil y le pide aquí la voz del robot, porque el X2 de MuJoCo no tiene ni oído ni parlante. El audio
no se guarda.

    GET  /estado         ¿listo?, modelo, si sabe hablar
    POST /transcribir    cuerpo: PCM 16 bit, 16 kHz, mono (como /agent/process_audio_output) → {texto, ms}
                         ?contexto=...: lo que se espera oír (las opciones, los códigos del club), para que Whisper
                         lo escriba igual: "FIESTA-7K2" y no "fiesta 7 cados"
    POST /hablar         cuerpo: {"texto": "..."} → audio WAV con la voz del robot (si hay voz de Piper)
"""

import functools
import io
import json
import os
import threading
import time
import urllib.parse
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from faster_whisper import WhisperModel

MODELO = os.environ.get('VOZ_MODELO', 'small')
PUERTO = int(os.environ.get('PUERTO', '8097'))
HILOS = int(os.environ.get('VOZ_HILOS', '4'))
# Palabras de la recepción del club: Whisper las reconoce mejor si se las anuncian
CONTEXTO = os.environ.get('VOZ_CONTEXTO', 'Recepción del club: salón VIP, restaurante, gimnasio, spa, terraza, '
                                          'zona social, vestier, código de acceso, cédula.')
MAX_AUDIO = 16000 * 2 * 30  # 30 s
MAX_TEXTO = 1000
# Las páginas de PIBOT que pueden usar el servicio desde el navegador
ORIGENES = os.environ.get('PIBOT_ORIGENES', 'http://localhost:8000,http://127.0.0.1:8000').split(',')
PIPER = os.environ.get('VOZ_PIPER', 'modelos/piper/es_MX-claude-high.onnx')

# Si el modelo ya está bajado en modelos/faster-whisper-<nombre> (el robot no tiene internet), se usa esa carpeta
LOCAL = os.path.join('modelos', f'faster-whisper-{MODELO}')
print(f'cargando Whisper {MODELO}…', flush=True)
inicio = time.perf_counter()
modelo = WhisperModel(LOCAL if os.path.isfile(os.path.join(LOCAL, 'model.bin')) else MODELO, device='cpu',
                      compute_type='int8', cpu_threads=HILOS, download_root='modelos')
print(f'Whisper {MODELO} listo en {time.perf_counter() - inicio:.1f} s', flush=True)

# La voz para hablar es opcional: el robot real usa la suya y no necesita Piper
voz = None
if os.path.isfile(PIPER):
    try:
        from piper import PiperVoice
        voz = PiperVoice.load(PIPER)
        print(f'voz del robot: {os.path.basename(PIPER)}', flush=True)
    except ImportError:
        print('sin Piper instalado: el servicio solo escucha', flush=True)


# Una frase a la vez: dos en paralelo se reparten la CPU del Orin y las dos llegan tarde
_whisper = threading.Lock()


def transcribir(pcm, contexto=''):
    audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
    t0 = time.perf_counter()
    # temperature=0: sin los reintentos con más azar que Whisper hace cuando duda (en el Orin llegaron a tardar 42 s);
    # max_new_tokens: las respuestas del visitante son cortas, y así una frase confusa no se alarga
    with _whisper:
        partes, _ = modelo.transcribe(audio, language='es', beam_size=1, vad_filter=False, temperature=0.0,
                                      max_new_tokens=40, without_timestamps=True, condition_on_previous_text=False,
                                      initial_prompt=f'{CONTEXTO} {contexto}'.strip())
        texto = ' '.join(p.text.strip() for p in partes).strip()
    ms = round((time.perf_counter() - t0) * 1000)
    print(f'transcribir: {len(audio) / 16000:.1f} s de audio en {ms} ms', flush=True)  # sin el texto: es lo que dijo alguien
    return {'texto': texto, 'ms': ms, 'segundos': round(len(audio) / 16000, 2)}


@functools.lru_cache(maxsize=64)  # el robot repite mucho las mismas frases
def hablar(texto):
    t0 = time.perf_counter()
    salida = io.BytesIO()
    with wave.open(salida, 'wb') as wav:
        voz.synthesize(texto, wav)
    print(f'hablar: {len(texto)} letras en {round((time.perf_counter() - t0) * 1000)} ms', flush=True)
    return salida.getvalue()


class Manejador(BaseHTTPRequestHandler):
    def _enviar(self, codigo, datos, tipo):
        self.send_response(codigo)
        self.send_header('Content-Type', tipo)
        self.send_header('Content-Length', str(len(datos)))
        self._cors()
        self.end_headers()
        self.wfile.write(datos)

    def _responder(self, codigo, cuerpo):
        self._enviar(codigo, json.dumps(cuerpo, ensure_ascii=False).encode(), 'application/json; charset=utf-8')

    def _cors(self):
        origen = self.headers.get('Origin')
        if origen in ORIGENES:
            self.send_header('Access-Control-Allow-Origin', origen)
            self.send_header('Vary', 'Origin')

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Access-Control-Allow-Methods', 'GET, POST')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/estado':
            return self._responder(200, {'listo': True, 'modelo': MODELO, 'habla': voz is not None})
        self._responder(404, {'error': 'no existe'})

    def do_POST(self):
        largo = int(self.headers.get('Content-Length') or 0)
        ruta, _, consulta = self.path.partition('?')
        if ruta == '/transcribir':
            if not 0 < largo <= MAX_AUDIO or largo % 2:
                return self._responder(400, {'error': 'se espera PCM de 16 bit, hasta 30 s'})
            contexto = urllib.parse.parse_qs(consulta).get('contexto', [''])[0][:600]
            return self._responder(200, transcribir(self.rfile.read(largo), contexto))
        if ruta == '/hablar':
            if voz is None:
                return self._responder(503, {'error': 'este servicio no tiene voz para hablar (falta la voz de Piper)'})
            try:
                texto = str(json.loads(self.rfile.read(largo) if 0 < largo <= MAX_TEXTO * 4 else b'{}').get('texto', '')).strip()
            except (ValueError, AttributeError):
                texto = ''
            if not 0 < len(texto) <= MAX_TEXTO:
                return self._responder(400, {'error': f'se espera {{"texto": "..."}}, hasta {MAX_TEXTO} letras'})
            return self._enviar(200, hablar(texto), 'audio/wav')
        self._responder(404, {'error': 'no existe'})

    def log_message(self, *args):
        pass


print(f'Voz a texto lista en http://127.0.0.1:{PUERTO}', flush=True)
ThreadingHTTPServer((os.environ.get('HOST', '0.0.0.0'), PUERTO), Manejador).serve_forever()
