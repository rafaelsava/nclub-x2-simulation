# Recepción N Club dentro del AgiBot X2

Todo corre en el **Orin** del robot (computador de desarrollo, `10.0.200.41` por el cable de SSH, `192.168.88.184` en su Wi-Fi), dentro de `~/pibot_nclub`.

> **El robot es compartido.** `~/nclub` es de otro equipo, que tiene su propio agente en este Orin: no instalar ahí ni tocar sus archivos. Y no encender el puente (`./nclub.sh puente`) mientras otro equipo esté usando el robot, porque los dos sistemas mandarían el mismo cuerpo, la cámara y el micrófono.

Para entrar sin contraseña, en `~/.ssh/config` del portátil:

```
Host x2
    HostName 10.0.200.41
    User agi
    IdentityFile ~/.ssh/id_ed25519
```

Después, una sola vez: `ssh-copy-id -i ~/.ssh/id_ed25519.pub x2`, que pide la clave del robot. No se instala nada en el sistema del robot ni se toca lo de otros equipos.

| Pieza | Dónde corre | Qué hace |
| --- | --- | --- |
| Reconocimiento facial (`nclub-rostro`) | podman | FaceRecognition Lite con las caras de Supabase o de su copia local |
| Voz a texto (`nclub-voz`) | podman | Whisper `base` en la CPU del Orin: unos 2 s por frase con el Orin libre, 17–21 s con los procesos del robot corriendo (2026-10-24) |
| PIBOT (`PIBOT/runtime/robot-runtime.mjs`) | Node, en `~/pibot_nclub/node` | corre el flujo publicado cuando alguien llega; sirve la página en `http://<robot>:8000` |
| Puente (`pibot/puente.py --real`) | ROS del robot, con `entorno.sh` | habla, gestos y marcha con MC; cámara de la cabeza y micrófono |

Los servicios de caras y de voz solo escuchan en el propio robot (`127.0.0.1`). PIBOT escucha en la red, para que se abra desde un celular en la Wi-Fi del robot.

## Por qué así y no como la guía al pie de la letra

La guía del SDK (4.4, *Develop in a Container*) pide correr todo en contenedores podman sobre `l4t-base`, bajando de repositorios en China. En este robot hubo que adaptar tres cosas:
- **Sin internet en el robot:** el Orin no tiene, y el portátil está en un hotspot lento. Las imágenes se construyen en el portátil para ARM y se cargan con `podman load` por el cable.
- **El puente corre directo en el Orin:** usa el ROS del robot y los mensajes del SDK ya compilados para ARM (`~/pibot_nclub/aimdk_msgs`, copiados del SDK del robot; coinciden 121 de 121 con los nuestros). La v1.1.0 lo permite (modo *Quick Start*), pero hay que pasarlo a contenedor antes de la v1.2.0.
- **Sin límite de CPU:** podman sin root no tiene el controlador de CPU en este Orin, así que Whisper se limita a 3 hilos.

## Instalar, encender y limpiar

**Desde el portátil**, con el cable al puerto de desarrollo y el alias `x2` de arriba:

```bash
./x2 robot-instalar   # imágenes, código, SDK, modelos y Node en ~/pibot_nclub (sin credenciales ni caras)
./x2 robot-caras      # las caras: se bajan de Supabase aquí y al robot va solo esa copia (permisos 600)
./x2 robot-llm        # opcional: le presta al robot el LLM de este portátil (déjelo abierto en otra terminal)
```

- **`robot-instalar`** se puede repetir para actualizar: solo copia lo que cambió.
- **Imágenes:** las de ARM se construyen la primera vez (`docker buildx`).
- **Node:** lo baja el robot si tiene internet; si no, lo baja el portátil y se lo pasa.
- **Requisitos:** el SDK descomprimido en `aimdk/` y los modelos (corran antes `./x2 voz base` y `./x2 rostro`).
- **Robot compartido:** si encuentra corriendo el agente de otro equipo, `robot-instalar` avisa y no lo toca.

**En el robot** (`ssh x2`, `cd ~/pibot_nclub`):

```bash
./nclub.sh demo                 # todo para la demostración (abajo)
NCLUB_LLM=http://127.0.0.1:8095/v1 ./nclub.sh demo   # lo mismo, con el LLM del túnel
./nclub.sh estado
./nclub.sh detener
```

`demo` hace, en orden:
1. **`servicios`:** caras, voz y PIBOT. No mueven el robot.
2. **`asistente propio`:** pasa el asistente de fábrica (Lumi) a `only_voice`, según la sección 8.1 del SDK. Después hay que decir **«Hello, lumi» una vez** frente al robot. Si no, Lumi contesta por su cuenta y se queda con el micrófono, y a PIBOT no le llega nada.
3. **`puente`:** sin caminar. Al guiar, el robot lo dice pero no se mueve; con `NCLUB_CAMINAR=1` camina.
4. **`publicar`:** publica en PIBOT la demostración (`PIBOT/flows/demostracion.json`) y los datos del club.
5. **`llegadas si`:** el robot recibe solo a quien se acerque a su cámara.

Cada paso también se puede correr suelto, por ejemplo `./nclub.sh publicar recepcion-conversacional.json` o `./nclub.sh llegadas no`.

**Al terminar** (robot compartido), desde el portátil:

```bash
./x2 robot-limpiar
```

Guarda los registros del robot en `logs/robot-<fecha>` (fuera de git: tienen nombres de visitantes). En el robot corre `./nclub.sh limpiar`, que:
- apaga todo;
- devuelve el asistente a `normal`;
- borra nuestras fuentes de control en MC y nuestras imágenes.

Después borra `~/pibot_nclub`. No toca nada de otros equipos.

**Las caras y las categorías:**
- **Quién es lo dice la cara** (las personas de Supabase).
- **La categoría la decide la lista de miembros del club** (`PIBOT/data/club.json`, «Membresías»), no la de Supabase. Allí hoy Adriana figura como invitada y Fermín como VIP.
- **Quien no está en Membresías** sigue con su segunda señal: carné, o código del evento u obra. El robot ya sabe su nombre.
- **Si hay varias personas delante,** atiende a la cara más grande.
- **`PIBOT/test/robot-caras.test.mjs`** recorre la demostración con las cinco personas de la demo.

## Usar

1. Abra PIBOT del robot: `./nclub.sh servicios` muestra sus direcciones, por la Wi-Fi y por el cable (por ejemplo `http://10.0.200.41:8000`). Arriba a la derecha aparece **Este robot**.
2. En **Diseñar**, arme o cambie el flujo y pulse **Publicar en el robot**.
3. En **En vivo** se ve lo que pasa:
   - cuando alguien se acerca a la cámara, el robot lo recibe solo;
   - las aprobaciones de ingreso se deciden ahí;
   - si el robot no entiende una respuesta, se puede tocar la opción o escribir el código por el visitante.
4. Como en la simulación, el visitante responde hablando: los códigos se dictan («fiesta veintisiete»). Si el robot no entiende, alguien toca la opción o escribe el código en la página.

## Estado (2026-10-24)

El 24 de octubre, al terminar las pruebas, se borró del Orin todo lo de este proyecto (el respaldo quedó en el portátil). Para volver a probar hay que instalar de nuevo, con los pasos de arriba.

**Probado en el robot real:**
- Voz con `PlayTts`: necesita internet; sin él responde `offline_cache_miss`.
- Reconocimiento facial con la cámara de la cabeza: reconoció a las 3 personas de Supabase, con la calibración de demo (umbral bajado a mano, sin validar).
- Saludar con la mano.
- Escuchar en modo `only_voice` con Whisper: entiende, pero tarda de 17 a 21 s por frase porque la CPU del Orin está ocupada con los procesos del robot. Además, el micrófono captó pocas frases.

**Probado el 24 en la tarde, en otro robot compartido** (se borró todo al terminar):
- **Instalación:** en `~/pibot_nclub`, con `entorno.sh`, `aimdk_msgs` del SDK, Node 22 y las dos imágenes. Funcionó tal como está arriba.
- **Caras:** la copia de Supabase, bajada en el portátil (6 personas), sin la contraseña en el robot. La categoría la decide la lista de miembros del club, no la de Supabase. Con varias personas delante, atiende a la cara más grande.
- **Micrófono:** sin `only_voice`, Lumi contesta y se queda con el audio, y a PIBOT no le llega nada. Con `only_voice` y «Hello, lumi» una sola vez, llegan las frases.
- **Whisper:** sin los reintentos con temperatura, y con las pistas de opciones y códigos, tarda unos 2.3 s por frase (antes, a veces 42 s).
- **Lenguaje natural:** el LLM del portátil por un túnel (`ssh -N -R 127.0.0.1:8095:127.0.0.1:8095 x2`, con `NCLUB_LLM=http://127.0.0.1:8095/v1`).
- **Caminar** (`pibot/caminar_real.py`, sin el puente encendido):
  - recto, a 0.2 m/s, va bien;
  - el giro en el sitio no lo hace: MC no se mueve;
  - girando a 0.1 m/s arranca y se detiene;
  - a 0.2 m/s gira en un arco de unos 0.33 m, pero si el punto está más cerca que eso, da vueltas a su alrededor sin llegar.

  Por eso el puente queda por defecto sin caminar.

**Pendiente:**
- **Guiar caminando.** Con lo de arriba: al girar avanzando, dejar de girar (o dar el lugar por alcanzado) cuando el punto quede dentro del arco. La primera versión se alejaba al girar. `guia_real.py` gira en el sitio y frena si algo va mal, pero todavía no se probó en el robot. Plan de prueba en `real/README.md`.
- **Lugares.** La odometría de las piernas salta: hay que marcar los lugares en cada sesión. La solución es hacer un mapa, relocalizar al robot y usar `/slam/lidar_odom`; después, conectar la navegación del robot (PNC), que esquiva obstáculos.
- **Oír más rápido y mejor:**
  - Whisper en la GPU;
  - que el puente le pase a Whisper las pistas de códigos y opciones, como hace la página en la simulación;
  - elegir bien el micrófono.
- **Lenguaje natural.** El LLM no está en el robot, así que entiende las opciones y las frases del club, pero no lenguaje libre. Hay dos caminos: el modelo 1.5b en el Orin, o el del portátil por la Wi-Fi (el puente acepta cualquier URL con `--llm`).
- **Voz sin internet.** `nclub-voz` ya trae Piper (`/hablar`; las ruedas para ARM existen). Falta que el puente reproduzca esa voz por el parlante del robot cuando `PlayTts` falle.
- **Varias caras.** Si hay varias personas, no decide. Habría que atender a la cara más grande.
