# Simulación del AgiBot X2 Ultra (MuJoCo)

Esta es la **capa del robot** del proyecto. La plataforma que usa el club es [PIBOT](https://github.com/santiagoguti17/PIBOT), el editor de flujos sin código; aquí está lo que hace que esos flujos muevan al X2: la simulación, el control de movimiento, el puente con PIBOT y el LLM local. No tiene interfaz propia.

Sigue la guía oficial "X2 Sim + MC Deployment" del AimDK v1.1.0 (opción Docker), adaptada para correr sin `sudo` y en cualquier distro con Docker.

Tiene tres partes:

- **`sim_mujoco/`**: MuJoCo con el robot `lx2501_3_t2d5` (X2 Ultra). Es el cuerpo del robot.
- **`mc/`**: el control de movimiento oficial, el mismo del robot real. Pararse, caminar y girar ya vienen resueltos.
- **`aimdk/`**: el SDK (ROS 2 Humble) con los ejemplos en Python (`py_examples`) y C++ (`examples`).

```
nuestro código ──comandos de alto nivel──▶ MC ──comandos de articulación──▶ MuJoCo
     ▲                                                                       │
     └──────────────── estado de articulaciones, IMU, odometría ─────────────┘
```

## Qué no está en el repositorio

`sim_mujoco/`, `mc/` y `aimdk/` son paquetes de AgiBot y no se suben: se descomprimen aquí desde los zip de la carpeta `X2/SDK-y-recursos-online` del Drive de la hackathon (`sim_mujoco-x86-v1.0.0`, `mc-x86-v1.0.0` y `aimdk-sdk-v1_1_0`). Del simulador, el repositorio sí trae la escena con el lobby del club (`sim_mujoco/.../model_info/scene.xml` y `nclub/`). Tampoco se suben los modelos (`modelos/`, los de `scripts/voz` y `scripts/rostro`, que se bajan con `./x2 llm`, `./x2 voz` y `./x2 rostro`) ni las credenciales de Supabase (`scripts/rostro/.env`, a partir de `.env.example`).

## Requisitos

- PC x86_64 con escritorio gráfico y Docker. Se recomiendan 16 GB de RAM.
- No hace falta GPU NVIDIA.

## Primera vez

```bash
./x2 build   # imagen Docker con ROS 2 Humble y dependencias (~5.5 GB)
./x2 up      # arranca el contenedor
./x2 sdk     # compila el SDK (~1.5 min)
```

## Cada vez que se use

Cada comando va en su propia terminal y en este orden:

```bash
./x2 up      # solo si el contenedor no está corriendo
./x2 sim     # terminal 1: abre MuJoCo
./x2 mc      # terminal 2: control de movimiento
./x2 pie     # terminal 3: deja al robot de pie
./x2 llm     # opcional: LLM local para lenguaje natural
./x2 pibot   # terminal 3: puente para PIBOT (en PIBOT/: python3 -m http.server 8000)
./x2 rostro  # opcional: reconocimiento facial real (cámara del portátil + personas de Supabase)
./x2 down    # al terminar
```

Con `./x2 llm` corriendo antes de `./x2 pibot`, PIBOT entiende respuestas con palabras propias. Los modelos quedan en `modelos/` (2–3 GB, no subirlos a git). Más detalles en `scripts/pibot/README.md`.

Para probar solo el movimiento, sin PIBOT: `./x2 demo` camina, gira y se detiene.

`./x2 help` muestra todos los comandos. `./x2 ex <ejemplo>` corre cualquier ejemplo de `aimdk/src/py_examples` (por ejemplo, `./x2 ex keyboard` para manejarlo con el teclado).

## Nuestro código

Va en `scripts/`, que se monta en el contenedor como `/workspace/scripts`:

- **`robot/`**: la recepción corriendo dentro del X2 (Orin): `nclub.sh` y cómo instalar, encender y usar; ver su `README.md`.
- **`scripts/voz/`**: voz a texto (Whisper) para lo que oye el micrófono del robot (`./x2 voz`).
- **`real/`**: cómo probar con el X2 real (cable, IP fija 10.0.1.2, `./x2 real-check` y `./x2 pibot-real`); ver su `README.md`.
- **`scripts/rostro/`**: el reconocimiento facial real: FaceRecognition Lite (de Fermín, en `../FaceRecognition_lite`) con las personas registradas en Supabase, como servicio local para PIBOT. Se corre con `./x2 rostro`; ver su `README.md`.
- **`scripts/pibot/`**: el puente que permite que los flujos de PIBOT muevan al X2 en MuJoCo, junto con el control del robot (`robot.py`) y el lenguaje natural (`lenguaje.py`, `evaluar_lenguaje.py`). Se corre con `./x2 pibot`; ver su `README.md`.
- **`scripts/demo_basico.py`**: plantilla mínima. Registra una fuente de control en MC, pone al robot de pie, publica velocidades y lee la odometría.
- **`scripts/prueba_gesto.py`**: diagnóstico de gestos de MC, para comprobarlos en el robot real.
- **`scripts/_archivo/recepcion_prototipo/`**: el primer prototipo de la recepción (flujos en código y página propia). Archivado: la plataforma es PIBOT.

Todos usan solo interfaces ROS 2 públicas del AimDK, así que el mismo código debería funcionar en el robot real.

## Cosas que no dice la documentación (comprobadas en la simulación)

- **El robot cae al arrancar.** El simulador empieza con la física corriendo y, mientras MC no lo controla, el robot se desploma. Por eso existe `./x2 pie`: pone MC en `STAND_DEFAULT` y reinicia MuJoCo (Backspace), con lo que el robot reaparece de pie y MC lo mantiene en equilibrio. Con `./x2 pibot` corriendo ya no hace falta: si el robot está en el suelo, se levanta solo con las rutinas de MC (ver `scripts/pibot/README.md`). Si MC ya estaba de pie cuando se reinicia MuJoCo, el robot aparece de pie y no se cae.
- **En MuJoCo**, Espacio pausa o reanuda y Backspace reinicia al robot a la pose inicial. Si la ventana dice `PAUSE`, nada se mueve.
- **No hace falta pedir `LOCOMOTION_DEFAULT`.** Estando de pie, MC pasa solo a locomoción cuando recibe velocidad distinta de cero, y vuelve a `STAND_DEFAULT` unos 2 s después de recibir solo ceros.
- **Velocidades válidas:** avance y lateral 0 o entre 0.2 y 1.0 m/s; giro 0 o entre 0.1 y 1.0 rad/s. El giro en el sitio no está garantizado; hay que girar avanzando un poco.
- **`mc_locomotion_velocity` no termina solo.** Después de los 5 s sigue publicando ceros hasta recibir Ctrl+C. Si queda vivo, los ceros se mezclan con los comandos de otro programa y el robot no camina. Para revisar y limpiar: `docker exec x2-sim pkill -f py_examples`.
- **La odometría** (`/aima/hal/odom/state`) se publica como *best effort*. Un suscriptor con la QoS por defecto (*reliable*) no recibe nada; hay que usar `qos_profile_sensor_data`.
- **Los archivos que crea el contenedor quedan a nombre de root** (`aimdk/build`, `aimdk/install`, `mc/bin/log`, `agibot_data/`...). Para borrarlos se necesita `sudo` o hacerlo desde el contenedor.
- **Pantalla:** la ventana de MuJoCo necesita que root del contenedor tenga acceso a la pantalla X. `./x2 up` lo da con `xhost`; si el host no lo tiene instalado, usa el `xhost` del contenedor.

## Qué no se puede probar aquí

La simulación cubre el cuerpo y el movimiento: articulaciones, IMU, odometría, caminar y girar. Los gestos de MC (saludar, dar la mano) no se ejecutan: este MC (mc-x86 v1.0.0) no responde a `SetMcPresetMotion` y no tiene el modo de control del tren superior. No publica cámaras ni LiDAR, y no tiene la unidad de interacción del robot real (voz/TTS, micrófono, pantalla de la cara, luces, LinkSoul). Eso hay que probarlo en el robot o simularlo aparte.
