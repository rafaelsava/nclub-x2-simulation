# Reconocimiento facial del robot

Integra **FaceRecognition Lite**, el componente de Fermín (detección YuNet + embeddings SFace de OpenCV, https://github.com/FerminEscalona/FaceRecognition_lite), con las personas registradas en **Supabase** y con **PIBOT**.

```text
PIBOT, visitante "Persona frente a la cámara"
  → toma hasta 3 fotos con la cámara del portátil (en el X2 sería la de su cabeza)
  → servicio local (./x2 rostro, http://127.0.0.1:8096) → FaceRecognition Lite contra la galería de Supabase
  → identified: nombre, categoría y destino de la tabla persons → "Identificar visitante" sigue con esa categoría
  → unknown: se le pide su código (no es miembro) · ambiguous: duda · sin cara útil: como si no hubiera cámara
```

## Cómo usarlo

1. Clona el componente al lado de `x2_simulation/` (ya está en `FaceRecognition_lite/`):
   ```bash
   git clone https://github.com/FerminEscalona/FaceRecognition_lite.git
   ```
2. Copia `.env.example` como `.env` y complétalo con los datos de Supabase que da el equipo. El `.env` no se sube a git.
3. Arranca el servicio: `./x2 rostro`. La primera vez:
   - construye la imagen Docker (Python 3.11 con las mismas versiones fijadas que el componente);
   - descarga los modelos oficiales (unos 39 MB, verificados con SHA-256);
   - calibra con la base pública ORL.
4. En PIBOT, en "Quién llega", elige **Persona frente a la cámara**. El navegador pide permiso para la cámara; la etiqueta sobre el video dice cuántas personas hay registradas. Luego pulsa **Recibir al visitante**.

`./x2 rostro-down` lo detiene.

## Qué hace el servicio

- **Galería:** al arrancar y cada minuto inicia sesión en Supabase y baja `persons` y `face_templates`. Solo usa plantillas de su misma versión de modelo; hoy es `sface-fp32-f6ae35223478f49a5818`, la misma con que están guardadas.
- **Si una descarga falla,** sigue con la última galería buena.
- **Registros a medias:** quien no tiene exactamente tres plantillas se deja afuera, sin tumbar a los demás.
- **Fotos y registros:** no guarda fotos. Los registros no muestran nombres ni embeddings, solo el resultado, la similitud y el tiempo.
- **Quién puede consultarlo:** solo responde en `127.0.0.1`. Desde el navegador, solo a PIBOT (`localhost:8000`), para que otra página abierta no pueda averiguar quién está frente a la cámara.
- **Categorías:** las de Supabase (`member_vip`…) se traducen a las del club con `faceCategories` en `PIBOT/data/club.json`. Una categoría que no esté ahí llega tal cual, y "Identificar visitante" la manda a "Necesita ayuda".

| Ruta | Qué hace |
| --- | --- |
| `GET /estado` | Si está listo, cuántas personas hay, versión del modelo y calibración |
| `POST /identificar` | Cuerpo: la foto en JPEG o PNG. Responde `{status, person, similarity, gap, elapsed_ms}` |
| `POST /sincronizar` | Vuelve a bajar la galería de Supabase |

## Prueba

`prueba_servicio.py` registra a dos personas de ORL en una galería falsa, sin tocar Supabase, y comprueba cuatro cosas:
- reconoce a cada una sin confundirla nunca con la otra;
- no reconoce a 10 desconocidos;
- rechaza bytes que no son una foto;
- un registro incompleto no tumba la galería.

```bash
docker run --rm -v "$PWD/../../../FaceRecognition_lite:/face:ro" -v "$PWD:/rostro" x2-rostro python prueba_servicio.py
```

## Límites

- **La calibración es preliminar,** la de ORL: umbral 0.61 y margen 0.43. ORL son fotos pequeñas en escala de grises, no fotos de teléfono frente a la cámara del robot. Con la cámara real puede salir "unknown" o "ambiguous" más de lo deseable. Para calibrar de verdad hacen falta capturas propias, con el protocolo del componente (`docs/protocolo-datos.md` del repositorio de Fermín).
- **Margen entre personas:** con una sola persona registrada no se aplica, porque no hay con quién compararla. Con varias, una foto que se parezca a dos queda "ambiguous". El componente prefiere no reconocer antes que confundir.
- **Registro de personas:** este servicio no registra personas nuevas, solo las lee de Supabase.
