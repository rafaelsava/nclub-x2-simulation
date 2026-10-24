#!/usr/bin/env python3
"""Servicio de reconocimiento facial del robot: FaceRecognition Lite + las personas registradas en Supabase.

    ./x2 rostro          (corre en Docker, en http://127.0.0.1:8096)

La cámara (en la demo, la del portátil desde PIBOT; en el X2, la de su cabeza) manda una foto y el servicio responde
quién es, con su nombre, categoría y destino de la tabla persons. Las plantillas (tres embeddings por persona) se bajan
de Supabase al arrancar y cada minuto; las fotos no se guardan y en los registros no salen nombres ni embeddings.

    GET  /estado        ¿listo?, cuántas personas, versión del modelo y de la calibración
    POST /identificar   cuerpo: la foto (JPEG o PNG) → {status, person, similarity, gap, elapsed_ms}
    POST /sincronizar   vuelve a bajar personas y plantillas de Supabase
    POST /detectar      cuerpo: la foto → {cerca}: si hay una cara lo bastante grande (alguien llegó al robot)

Sin internet (el robot en el club), usa la copia de la galería en datos/galeria.json: la baja el portátil con
`python servicio.py --exportar datos/galeria.json` (o `./x2 rostro-copiar`, que además se la pasa al robot).

Solo `status == "identified"` trae persona. Los demás (unknown, ambiguous, no_face, multiple_faces,
insufficient_quality, invalid_image) no: PIBOT sigue con las otras formas de identificar.
"""

import argparse
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
from face_lite import Calibration, FaceEngine, Gallery

MODELOS = Path(os.environ.get('FACE_MODELS', 'modelos'))
CALIBRACION = Path(os.environ.get('FACE_CALIBRATION', 'datos/orl-fp32/calibration.json'))
PUERTO = int(os.environ.get('PUERTO', '8096'))
CADA = int(os.environ.get('SINCRONIZAR_CADA', '60'))
# Solo PIBOT puede preguntar desde el navegador (otra página abierta no puede averiguar quién está frente a la cámara)
ORIGENES = os.environ.get('PIBOT_ORIGENES', 'http://localhost:8000,http://127.0.0.1:8000').split(',')
MAX_FOTO = 20_000_000
GALERIA = Path(os.environ.get('FACE_GALERIA', 'datos/galeria.json'))  # copia local, para cuando no hay internet
CLAVES = ('SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY', 'SUPABASE_AUTH_EMAIL', 'SUPABASE_AUTH_PASSWORD')


class Supabase:
    """Lectura con la sesión del usuario del robot (las tablas no se ven sin iniciar sesión)."""

    def __init__(self):
        self.url = os.environ['SUPABASE_URL'].rstrip('/')
        self.clave = os.environ['SUPABASE_PUBLISHABLE_KEY']
        self.correo, self.contrasena = os.environ['SUPABASE_AUTH_EMAIL'], os.environ['SUPABASE_AUTH_PASSWORD']

    def _pedir(self, metodo, ruta, cuerpo=None, token=None):
        cabeceras = {'apikey': self.clave, 'Content-Type': 'application/json'}
        if token:
            cabeceras['Authorization'] = f'Bearer {token}'
        req = urllib.request.Request(self.url + ruta, method=metodo, headers=cabeceras,
                                     data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read() or 'null')
        except urllib.error.HTTPError as e:
            raise RuntimeError(f'Supabase respondió {e.code} en {ruta.split("?")[0]}') from None
        except urllib.error.URLError as e:
            raise RuntimeError(f'sin conexión con Supabase ({e.reason})') from None

    def leer(self, model_version):
        token = self._pedir('POST', '/auth/v1/token?grant_type=password',
                            {'email': self.correo, 'password': self.contrasena})['access_token']
        personas = self._pedir('GET', '/rest/v1/persons?select=person_id,first_name,last_name,category,destination', token=token)
        filas = self._pedir('GET', '/rest/v1/face_templates?select=template_id,person_id,embedding,model_version'
                                   f'&model_version=eq.{model_version}', token=token)
        return personas, filas


class Reconocedor:
    def __init__(self):
        self.motor = FaceEngine(MODELOS)
        self.politica = Calibration(**json.loads(CALIBRACION.read_text()))
        self.supabase = Supabase() if all(os.environ.get(k) for k in CLAVES) else None
        self.galeria, self.personas = None, {}
        self.estado = {'listo': False, 'error': 'todavía no se ha sincronizado'}
        self._cambio = threading.Lock()

    def sincronizar(self):
        """Baja la galería y la cambia de una vez; si algo falla se queda con la última buena."""
        try:
            personas, filas, origen = self._leer()
            por_persona = {}
            for f in filas:
                if isinstance(f.get('embedding'), str):  # según el tipo de columna llega como texto JSON
                    f['embedding'] = json.loads(f['embedding'])
                f = {k: str(v) if k in ('template_id', 'person_id') else v for k, v in f.items()}
                por_persona.setdefault(f['person_id'], []).append(f)
            # Quien no tiene exactamente tres plantillas no entra (el registro quedó a medias), pero no tumba a los demás
            completas = [f for fs in por_persona.values() if len(fs) == 3 for f in fs]
            incompletas = sum(1 for fs in por_persona.values() if len(fs) != 3)
            galeria = Gallery(completas, self.motor.model_version, self.motor.dimension)
            galeria.check_consistency(self.politica.enrollment_min_similarity)
            datos = {str(p['person_id']): p for p in personas}
            sin_datos = sum(1 for p in galeria.person_ids if p not in datos)
            with self._cambio:
                self.galeria, self.personas = galeria, datos
                self.estado = {'listo': True, 'origen': origen, 'personas': len(galeria.person_ids), 'incompletas': incompletas,
                               'sin_datos': sin_datos, 'sincronizado': time.time(), 'error': None}
            print(f'galería ({origen}): {len(galeria.person_ids)} personas'
                  + (f', {incompletas} con registro incompleto' if incompletas else '')
                  + (f', {sin_datos} sin fila en persons' if sin_datos else ''), flush=True)
        except (RuntimeError, ValueError, KeyError, TypeError) as e:
            self.estado = {**self.estado, 'error': str(e)}
            print(f'no se pudo sincronizar: {e}', flush=True)

    def _leer(self):
        """Personas y plantillas: de Supabase si se puede; si no, de la copia local."""
        if self.supabase:
            try:
                return (*self.supabase.leer(self.motor.model_version), 'Supabase')
            except RuntimeError as e:
                if not GALERIA.exists():
                    raise
                print(f'{e}: se usa la copia local', flush=True)
        if not GALERIA.exists():
            raise RuntimeError(f'sin Supabase (.env) ni copia local de la galería ({GALERIA})')
        copia = json.loads(GALERIA.read_text())
        filas = [f for f in copia['plantillas'] if f['model_version'] == self.motor.model_version]
        return copia['personas'], filas, f'copia local del {copia.get("fecha", "?")}'

    def identificar(self, foto):
        with self._cambio:
            galeria, personas = self.galeria, self.personas
        if galeria is None:
            return {'status': 'not_ready', 'person': None, 'reason': self.estado.get('error')}
        r = self.motor.identify(foto, galeria, self.politica)
        if r['status'] == 'multiple_faces':  # varias personas frente al robot: se atiende a la más cercana
            cara = self._cara_mas_cercana(foto)
            if cara is not None:
                r = self.motor.identify(cara, galeria, self.politica)
        p = personas.get(r.get('person_id')) if r['status'] == 'identified' else None
        persona = p and {'person_id': r['person_id'], 'first_name': p.get('first_name'), 'last_name': p.get('last_name'),
                         'name': ' '.join(x for x in (p.get('first_name'), p.get('last_name')) if x),
                         'category': p.get('category'), 'destination': p.get('destination')}
        print(f'identificar: {r["status"]}' + (f' ({r["similarity"]:.2f})' if r.get('similarity') is not None else '')
              + f' {r.get("elapsed_ms", 0):.0f} ms', flush=True)
        return {'status': r['status'], 'reason': r.get('reason'), 'person': persona, 'similarity': r.get('similarity'),
                'gap': r.get('gap'), 'threshold': self.politica.threshold, 'elapsed_ms': round(r.get('elapsed_ms', 0))}

    def detectar(self, foto):
        """Solo mira si hay alguien cerca (una cara de tamaño útil); no compara con nadie ni guarda nada."""
        r = self.motor.extract(foto)
        if r['status'] == 'multiple_faces':
            cara = self._cara_mas_cercana(foto)
            r = self.motor.extract(cara) if cara is not None else r
        return {'cerca': r['status'] == 'ok', 'status': r['status']}

    def _cara_mas_cercana(self, foto):
        """Con varias caras en la foto, la más grande (la persona más cercana al robot), recortada con margen.

        FaceRecognition Lite rechaza una foto con varias caras; aquí se elige una antes de dársela. Usa el mismo
        detector (YuNet) del motor y devuelve la imagen BGR recortada, o None si no se puede.
        """
        try:
            bgr = self.motor._load(foto)
        except Exception:
            return None
        h, w = bgr.shape[:2]
        escala = min(1.0, self.motor.config.detector_max_side / max(h, w))
        chica = cv2.resize(bgr, (max(1, round(w * escala)), max(1, round(h * escala))))
        with self.motor._lock:
            self.motor._detector.setInputSize((chica.shape[1], chica.shape[0]))
            _, caras = self.motor._detector.detect(chica)
        if caras is None or len(caras) < 2:
            return None
        x, y, cw, ch = caras[int(np.argmax(caras[:, 2] * caras[:, 3]))][:4] / escala
        m = 0.5  # margen alrededor de la cara, para que el detector la vuelva a encontrar sola
        x0, y0, x1, y1 = int(max(0, x - m * cw)), int(max(0, y - m * ch)), int(min(w, x + cw * (1 + m))), int(min(h, y + ch * (1 + m)))
        return bgr[y0:y1, x0:x1].copy()

    def resumen(self):
        hace = round(time.time() - self.estado['sincronizado']) if self.estado.get('sincronizado') else None
        return {**{k: v for k, v in self.estado.items() if k != 'sincronizado'}, 'sincronizado_hace_s': hace,
                'model_version': self.motor.model_version,
                'calibration': {'id': self.politica.calibration_id, 'scope': self.politica.scope,
                                'threshold': self.politica.threshold, 'margin': self.politica.margin}}


def servidor(rec):
    class Manejador(BaseHTTPRequestHandler):
        def _responder(self, codigo, cuerpo):
            datos = json.dumps(cuerpo, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(datos)))
            self._cors()
            self.end_headers()
            self.wfile.write(datos)

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
                return self._responder(200, rec.resumen())
            self._responder(404, {'error': 'no existe'})

        def do_POST(self):
            if self.path == '/sincronizar':
                rec.sincronizar()
                return self._responder(200, rec.resumen())
            if self.path not in ('/identificar', '/detectar'):
                return self._responder(404, {'error': 'no existe'})
            largo = int(self.headers.get('Content-Length') or 0)
            if not 0 < largo <= MAX_FOTO:
                return self._responder(413 if largo else 400, {'status': 'invalid_image', 'person': None})
            foto = self.rfile.read(largo)
            self._responder(200, rec.identificar(foto) if self.path == '/identificar' else rec.detectar(foto))

        def log_message(self, *args):  # sin registro por petición: las respuestas traen datos personales
            pass

    # En Docker escucha en todas las interfaces (el puerto lo publica Docker solo en 127.0.0.1); en el robot, HOST=127.0.0.1
    return ThreadingHTTPServer((os.environ.get('HOST', '0.0.0.0'), PUERTO), Manejador)


def exportar(destino):
    """Baja de Supabase la galería (personas y plantillas) a un archivo, para el robot sin internet."""
    personas, filas = Supabase().leer(FaceEngine(MODELOS).model_version)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.touch(mode=0o600, exist_ok=True)
    destino.chmod(0o600)  # datos biométricos: solo para el usuario del robot
    destino.write_text(json.dumps({'fecha': time.strftime('%Y-%m-%d %H:%M'), 'personas': personas, 'plantillas': filas}))
    print(f'galería exportada a {destino}: {len(personas)} personas, {len(filas)} plantillas', flush=True)


def main():
    p = argparse.ArgumentParser(description='Servicio de reconocimiento facial del robot')
    p.add_argument('--exportar', metavar='ARCHIVO', help='baja la galería de Supabase a ARCHIVO y termina')
    args = p.parse_args()
    if args.exportar:
        return exportar(args.exportar)
    rec = Reconocedor()
    print(f'modelo {rec.motor.model_version}, calibración {rec.politica.calibration_id} ({rec.politica.scope}), '
          f'arranque {rec.motor.cold_start_ms:.0f} ms', flush=True)
    rec.sincronizar()

    def cada_tanto():
        while True:
            time.sleep(CADA)
            rec.sincronizar()
    threading.Thread(target=cada_tanto, daemon=True).start()
    print(f'Reconocimiento facial listo en http://127.0.0.1:{PUERTO} (en PIBOT: "Persona frente a la cámara")', flush=True)
    servidor(rec).serve_forever()


if __name__ == '__main__':
    main()
