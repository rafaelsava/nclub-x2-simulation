#!/usr/bin/env python3
"""Servicio de voz a texto del robot: faster-whisper sobre lo que oye el micrófono del X2.

    ./x2 voz            (Docker, http://127.0.0.1:8097)

El puente junta cada frase que el robot oye (el sistema de audio del X2 ya la separa con detección de voz y le quita
el ruido) y la manda aquí. El audio no se guarda.

    GET  /estado         ¿listo?, modelo
    POST /transcribir    cuerpo: PCM 16 bit, 16 kHz, mono (como /agent/process_audio_output) → {texto, ms}
"""

import json
import os
import time
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

# Si el modelo ya está bajado en modelos/faster-whisper-<nombre> (el robot no tiene internet), se usa esa carpeta
LOCAL = os.path.join('modelos', f'faster-whisper-{MODELO}')
print(f'cargando Whisper {MODELO}…', flush=True)
inicio = time.perf_counter()
modelo = WhisperModel(LOCAL if os.path.isfile(os.path.join(LOCAL, 'model.bin')) else MODELO, device='cpu',
                      compute_type='int8', cpu_threads=HILOS, download_root='modelos')
print(f'Whisper {MODELO} listo en {time.perf_counter() - inicio:.1f} s', flush=True)


def transcribir(pcm):
    audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
    t0 = time.perf_counter()
    partes, _ = modelo.transcribe(audio, language='es', beam_size=1, vad_filter=False,
                                  condition_on_previous_text=False, initial_prompt=CONTEXTO)
    texto = ' '.join(p.text.strip() for p in partes).strip()
    ms = round((time.perf_counter() - t0) * 1000)
    print(f'transcribir: {len(audio) / 16000:.1f} s de audio en {ms} ms', flush=True)  # sin el texto: es lo que dijo alguien
    return {'texto': texto, 'ms': ms, 'segundos': round(len(audio) / 16000, 2)}


class Manejador(BaseHTTPRequestHandler):
    def _responder(self, codigo, cuerpo):
        datos = json.dumps(cuerpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        if self.path == '/estado':
            return self._responder(200, {'listo': True, 'modelo': MODELO})
        self._responder(404, {'error': 'no existe'})

    def do_POST(self):
        if self.path != '/transcribir':
            return self._responder(404, {'error': 'no existe'})
        largo = int(self.headers.get('Content-Length') or 0)
        if not 0 < largo <= MAX_AUDIO or largo % 2:
            return self._responder(400, {'error': 'se espera PCM de 16 bit, hasta 30 s'})
        self._responder(200, transcribir(self.rfile.read(largo)))

    def log_message(self, *args):
        pass


print(f'Voz a texto lista en http://127.0.0.1:{PUERTO}', flush=True)
ThreadingHTTPServer((os.environ.get('HOST', '0.0.0.0'), PUERTO), Manejador).serve_forever()
