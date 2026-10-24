# Recepción N Club dentro del AgiBot X2

Todo corre en el **Orin** del robot (computador de desarrollo, `10.0.200.41` por el cable de SSH, `192.168.88.184` en su Wi-Fi), dentro de `~/nclub`. No se instala nada en el sistema del robot ni se toca lo de otros equipos.

| Pieza | Dónde corre | Qué hace |
| --- | --- | --- |
| Reconocimiento facial (`nclub-rostro`) | podman | FaceRecognition Lite con las caras de Supabase o de su copia local |
| Voz a texto (`nclub-voz`) | podman | Whisper `base`: unos 2 s por frase en la CPU del Orin |
| PIBOT (`PIBOT/runtime/robot-runtime.mjs`) | Node, en `~/nclub/node` | corre el flujo publicado cuando alguien llega; sirve la página en `http://<robot>:8000` |
| Puente (`pibot/puente.py --real`) | ROS del robot, con `entorno.sh` | habla, gestos y marcha con MC; cámara de la cabeza, micrófono y QR |

Los servicios de caras y de voz solo escuchan en el propio robot (`127.0.0.1`). PIBOT escucha en la red, para que se abra desde un celular en la Wi-Fi del robot.

## Por qué así y no como la guía al pie de la letra

La guía del SDK (4.4, *Develop in a Container*) pide correr todo en contenedores podman sobre `l4t-base`, bajando de repositorios en China. En este robot hubo que adaptar tres cosas:
- **Sin internet en el robot:** el Orin no tiene, y el portátil está en un hotspot lento. Las imágenes se construyen en el portátil para ARM y se cargan con `podman load` por el cable.
- **El puente corre directo en el Orin:** usa el ROS del robot y los mensajes del SDK ya compilados para ARM (`~/nclub/aimdk_msgs`, copiados del SDK del robot; coinciden 121 de 121 con los nuestros). La v1.1.0 lo permite (modo *Quick Start*), pero hay que pasarlo a contenedor antes de la v1.2.0.
- **Sin límite de CPU:** podman sin root no tiene el controlador de CPU en este Orin, así que Whisper se limita a 3 hilos.

## Instalar o actualizar (desde el portátil, por el cable)

```bash
docker buildx build --platform linux/arm64 -t nclub-rostro:arm64 --load scripts/rostro
docker buildx build --platform linux/arm64 -t nclub-voz:arm64 --load scripts/voz
docker save nclub-rostro:arm64 | gzip -1 | ssh agi@10.0.200.41 podman load
docker save nclub-voz:arm64 | gzip -1 | ssh agi@10.0.200.41 podman load
rsync -a scripts/pibot scripts/rostro scripts/voz robot/nclub.sh agi@10.0.200.41:nclub/   # sin .env ni datos/orl
rsync -a ../PIBOT/ agi@10.0.200.41:nclub/PIBOT/
rsync -a ../FaceRecognition_lite/src/ agi@10.0.200.41:nclub/face_lite/src/
```

Si el robot no tiene internet, las caras van en una copia local. Se baja en el portátil y se pasa al robot (son datos biométricos: el archivo queda con permisos 600):

```bash
docker run --rm --env-file scripts/rostro/.env -v ../FaceRecognition_lite:/face:ro -v $PWD/scripts/rostro:/rostro x2-rostro python servicio.py --exportar datos/galeria.json
rsync -a scripts/rostro/datos/galeria.json agi@10.0.200.41:nclub/rostro/datos/
```

## Encender (en el Orin)

```bash
cd ~/nclub
./nclub.sh servicios   # caras, voz y PIBOT: no mueven el robot
./nclub.sh puente      # pide confirmación: desde aquí un flujo puede hacer caminar al robot
./nclub.sh estado
./nclub.sh detener
```

Antes del puente, una sola vez, hay que hacer que el micrófono le llegue a PIBOT. Por defecto lo ocupa el asistente de voz de fábrica, así que se pasa a `only_voice` (sección 8.1 del SDK):
1. `ros2 service call /aimdk_5Fmsgs/srv/SetAgentPropertiesRequest ...` con el valor `'only_voice'`.
2. `aima em stop-app agent && aima em start-app agent`.
3. Decir la palabra de activación una vez.

Se revierte con el valor `'normal'`. Esto cambia la voz del robot para cualquiera que lo use.

## Usar

1. En un celular o portátil en la Wi-Fi del robot, abra `http://192.168.88.184:8000`. Arriba a la derecha aparece **Este robot**.
2. En **Diseñar**, arme o cambie el flujo y pulse **Publicar en el robot**.
3. En **En vivo** se ve lo que pasa:
   - cuando alguien se acerca a la cámara, el robot lo recibe solo;
   - las aprobaciones de ingreso se deciden ahí;
   - si el robot no entiende una respuesta, se puede tocar la opción o escribir el código por el visitante.
4. Los códigos se pueden dictar («fiesta siete K dos») o mostrar como QR a la cámara.

## Pendiente

- **Probar con el robot de pie:** el micrófono en `only_voice`, la voz `PlayTts` y la marcha. Hasta ahora todo se probó en la simulación, más la cámara y Whisper en el Orin.
- **Navegación:** la marcha es en línea recta y no esquiva obstáculos. El robot trae navegación con mapa (PNC sobre SLAM) que sí los esquiva; falta conectarla.
- **Odometría:** el puente usa la de las piernas (`/aima/mc/leg_odometry`) o la del SLAM. Los lugares se marcan en PIBOT con "Aquí está el robot".
- **LLM:** no está instalado todavía (la RAM es justa y el robot no tiene internet). Sin él, se entienden las respuestas que nombran la opción; con dudas, responde una persona desde PIBOT.
- **Supabase:** hoy solo una persona tiene sus tres plantillas visibles para la cuenta del robot.
