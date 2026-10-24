#!/usr/bin/env python3
"""Recepción de N Club con el X2 Ultra: reconocimiento facial (simulado o real) → confirmación → orientación.

Con la simulación (dentro del contenedor, con ./x2 sim, ./x2 mc y ./x2 pie corriendo):
    ./x2 recepcion
Sin robot ni ROS, solo para probar los flujos (en cualquier PC con Python 3):
    python3 scripts/recepcion/app.py --sin-robot

Luego abrir http://localhost:8090 en el navegador.
"""

import argparse
import json
import queue
import signal
from pathlib import Path

from flujos import Recepcion
from interfaz import Interfaz
from lenguaje import Interprete
from robot import crear_robot


def resolvedor_de_reconocimiento(club):
    """Convierte la salida del modelo facial (id de persona o desconocido) en miembro / no miembro.

    El modelo solo identifica a la persona; si es miembro o no lo dice la base de datos del club (club.json).
    La categoría exacta no se entrega aquí: la confirma el robot en flujos.py.
    """
    personas = {p['id']: p for p in club['personas']}

    def resolver(persona_id, confianza, fuente, incierto=False):
        if incierto:
            return {'estado': 'incierto', 'persona_id': None, 'confianza': confianza, 'fuente': fuente}
        persona = personas.get(persona_id)
        if persona is None:
            return {'estado': 'no_miembro', 'persona_id': None, 'confianza': confianza, 'fuente': fuente}
        estado = 'miembro' if persona['categoria'] in ('vip', 'regular') else 'no_miembro'
        return {'estado': estado, 'persona_id': persona['id'], 'confianza': confianza, 'fuente': fuente}

    return resolver


def simulador_de_reconocimiento(club, resolver):
    """Imita al modelo facial desde el panel: el visitante elegido 'aparece' frente a la cámara."""
    visitantes = {v['id']: v for v in club['visitantes_simulados']}

    def reconocer(visitante_id, dudoso):
        visitante = visitantes.get(visitante_id)
        if visitante is None:
            return None
        if dudoso:
            return resolver(None, 0.41, 'simulado', incierto=True)
        confianza = 0.93 if visitante['persona_id'] else 0.88
        return resolver(visitante['persona_id'], confianza, 'simulado')

    return reconocer


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--sin-robot', action='store_true', help='no usar ROS ni MC: el robot solo se imita')
    parser.add_argument('--host', default='127.0.0.1', help='usar 0.0.0.0 para abrir el panel desde otro equipo')
    parser.add_argument('--puerto', type=int, default=8090)
    parser.add_argument('--club', type=Path, default=Path(__file__).parent / 'club.json')
    parser.add_argument('--llm', metavar='URL',
                        help='API compatible con OpenAI para entender lenguaje natural, p. ej. http://127.0.0.1:8095/v1 '
                             '(./x2 llm). Para la nube, además LLM_API_KEY en el entorno')
    parser.add_argument('--llm-modelo', default='local', help='nombre del modelo que se pide al servidor')
    args = parser.parse_args()

    interprete = None
    if args.llm:
        interprete = Interprete(args.llm, args.llm_modelo)
        if not interprete.disponible():
            parser.error(f'el LLM no responde en {args.llm} (¿está corriendo ./x2 llm?)')
        # La primera consulta tarda varios segundos más (el modelo se "calienta"); mejor ahora que con un visitante
        interprete.elegir_opcion('¿Prefiere café o té?', ['Café', 'Té'], 'un tinto, por favor')
        print(f'Lenguaje natural activado con {args.llm}', flush=True)

    club = json.loads(args.club.read_text(encoding='utf-8'))
    robot = crear_robot(args.sin_robot)
    robot.iniciar()
    ui = Interfaz(interprete)
    recepcion = Recepcion(ui, robot, club)
    datos_panel = {'visitantes': [{'id': v['id'], 'etiqueta': v['etiqueta']} for v in club['visitantes_simulados']],
                   'zonas': club['zonas']}
    resolver = resolvedor_de_reconocimiento(club)
    servidor = ui.servir(args.host, args.puerto, simulador_de_reconocimiento(club, resolver), resolver,
                         robot.estado, datos_panel)
    print(f'Recepción N Club lista: abre http://localhost:{args.puerto} (Ctrl+C para salir)', flush=True)

    def salir(*_):
        raise KeyboardInterrupt

    # Se instalan explícitamente: en segundo plano el shell deja SIGINT ignorado, y docker/pkill mandan SIGTERM
    signal.signal(signal.SIGINT, salir)
    signal.signal(signal.SIGTERM, salir)
    try:
        while True:
            # Un visitante a la vez; los que llegan mientras tanto esperan en la cola
            try:
                recepcion.atender(ui.llegadas.get(timeout=0.5))
            except queue.Empty:
                pass
    except KeyboardInterrupt:
        pass
    finally:
        servidor.shutdown()
        robot.cerrar()


if __name__ == '__main__':
    main()
