#!/usr/bin/env python3
"""Prueba del servicio sin tocar Supabase: registra a dos personas de la base pública ORL en una galería falsa
y comprueba que reconoce a cada una con otras fotos sin confundirlas, que no reconoce a desconocidos y que rechaza
lo que no es una foto.

    docker run --rm -v ../../../FaceRecognition_lite:/face:ro -v $PWD:/rostro x2-rostro python prueba_servicio.py
"""
import os

os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
for clave in ('SUPABASE_PUBLISHABLE_KEY', 'SUPABASE_AUTH_EMAIL', 'SUPABASE_AUTH_PASSWORD'):
    os.environ.setdefault(clave, 'prueba')

import servicio  # noqa: E402

ORL = 'datos/orl/images'
rec = servicio.Reconocedor()
plantillas, personas = [], []
for pid, sujeto, cat in (('p-a', 's1', 'member_vip'), ('p-b', 's2', 'staff')):
    r = rec.motor.enroll([f'{ORL}/{sujeto}/{i}.pgm' for i in (1, 2, 3)], pid, [f'{pid}-{i}' for i in range(3)])
    assert r['status'] == 'enrolled', r['status']
    plantillas += r['templates']
    personas.append({'person_id': pid, 'first_name': 'Persona', 'last_name': sujeto.upper(), 'category': cat, 'destination': 'Salón VIP'})
rec.supabase.leer = lambda version: (personas, plantillas)  # Supabase falso
rec.sincronizar()
assert rec.estado['listo'] and rec.estado['personas'] == 2, rec.estado

# Prioridad del componente: nunca confundir personas. Una foto conocida puede quedar "ambiguous" o "unknown"
# (el robot sigue con otra forma de identificar), pero nunca asignarse a otra persona; cada una se reconoce al menos una vez.
fallos = 0
for pid, sujeto in (('p-a', 's1'), ('p-b', 's2')):
    res = [rec.identificar(open(f'{ORL}/{sujeto}/{i}.pgm', 'rb').read()) for i in (7, 8, 9, 10)]
    quienes = [(r['person'] or {}).get('person_id') for r in res]
    ok = pid in quienes and all(q in (pid, None) for q in quienes)
    fallos += not ok
    print(f"{'OK   ' if ok else 'FALLA'} {sujeto}: {', '.join(r['status'] for r in res)}")
res = [rec.identificar(open(f'{ORL}/s{s}/1.pgm', 'rb').read()) for s in range(11, 21)]
ok = all(r['person'] is None for r in res)
fallos += not ok
print(f"{'OK   ' if ok else 'FALLA'} 10 desconocidos: ninguno reconocido como alguien registrado")
r = rec.identificar(b'esto no es una foto')
fallos += r['status'] != 'invalid_image'
print(f"{'OK   ' if r['status'] == 'invalid_image' else 'FALLA'} bytes que no son foto: {r['status']}")
# Una persona con registro incompleto no tumba la galería
rec.supabase.leer = lambda version: (personas, plantillas[:5])
rec.sincronizar()
ok = rec.estado['personas'] == 1 and rec.estado['incompletas'] == 1
fallos += not ok
print(f"{'OK   ' if ok else 'FALLA'} registro incompleto: {rec.estado['personas']} persona, {rec.estado['incompletas']} incompleta")
print('todos correctos' if not fallos else f'{fallos} fallos')
raise SystemExit(1 if fallos else 0)
