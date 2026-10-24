#!/usr/bin/env bash
# Recepción N Club en el AgiBot X2: corre en el Orin (computador de desarrollo), todo dentro de ~/pibot_nclub
# (no en ~/nclub: es de otro equipo).
#   ./nclub.sh servicios   reconocimiento facial y voz a texto (podman) y PIBOT (http://<robot>:8000). No mueven el robot.
#   (Sin límite de CPU: en este Orin podman sin root no tiene el controlador de CPU; Whisper usa 3 hilos.)
#   Whisper escucha como en la madrugada del 2026-10-24, sin pistas de opciones ni códigos; VOZ_PISTAS=1 las activa.
#   ./nclub.sh puente      el puente con MC, la cámara y el micrófono. Por defecto no camina (al guiar, solo lo dice);
#                          con NCLUB_CAMINAR=1 un flujo puede hacer caminar al robot
#   ./nclub.sh asistente propio|normal   el asistente de voz de fábrica (Lumi): «propio» lo calla (only_voice) para que
#                          el micrófono le llegue a PIBOT; después hay que decir «Hello, lumi» una vez. «normal» lo devuelve
#   ./nclub.sh publicar [flujo.json]     publica en PIBOT un flujo de PIBOT/flows (demostracion.json por defecto) y
#                          los datos del club (PIBOT/data/club.json)
#   ./nclub.sh llegadas si|no            el robot recibe solo a quien se acerque a la cámara, o no
#   ./nclub.sh demo        todo lo anterior para la demostración: servicios, asistente propio, puente, flujo y llegadas
#   ./nclub.sh estado      qué está corriendo
#   ./nclub.sh detener     apaga todo lo de N Club (nada de otros equipos)
#   ./nclub.sh limpiar     detener, asistente normal, borrar nuestras fuentes de control en MC y nuestras imágenes
set -uo pipefail
cd "$(dirname "$0")"
D=$PWD; mkdir -p "$D/run" "$D/logs"

vivo() { [[ -f "$D/run/$1.pid" ]] && kill -0 "$(cat "$D/run/$1.pid")" 2>/dev/null; }

servicios() {
  if ! podman container exists nclub-rostro || [[ "$(podman inspect -f '{{.State.Running}}' nclub-rostro)" != true ]]; then
    podman rm -f nclub-rostro >/dev/null 2>&1
    local env=(); [[ -f "$D/rostro/.env" ]] && env=(--env-file "$D/rostro/.env")
    # Calibración de demo (umbral 0.50, margen 0.10; ajuste manual sin validar) si existe; si no, la de ORL de Fermín
    if [[ -f "$D/rostro/calibracion-demo.json" ]]; then env+=(-e FACE_CALIBRATION=calibracion-demo.json)
    elif [[ -f "$D/rostro/datos/calibracion-demo.json" ]]; then env+=(-e FACE_CALIBRATION=datos/calibracion-demo.json); fi
    podman run -d --init --name nclub-rostro --network host -e HOST=127.0.0.1 -e PYTHONPATH=/face/src "${env[@]}" \
      -v "$D/face_lite:/face:ro" -v "$D/rostro:/rostro" nclub-rostro:arm64 python servicio.py >/dev/null && echo "reconocimiento facial: encendido"
  fi
  if podman image exists nclub-voz:arm64 && { ! podman container exists nclub-voz || [[ "$(podman inspect -f '{{.State.Running}}' nclub-voz)" != true ]]; }; then
    podman rm -f nclub-voz >/dev/null 2>&1
    podman run -d --init --name nclub-voz --network host -e HOST=127.0.0.1 -e VOZ_HILOS=3 -e VOZ_MODELO="${VOZ_MODELO:-base}" -e VOZ_PISTAS="${VOZ_PISTAS:-0}" \
      -v "$D/voz:/voz" nclub-voz:arm64 python voz.py >/dev/null && echo "voz a texto: encendida"
  fi
  if ! vivo pibot; then
    PORT=8000 HOST=0.0.0.0 PIBOT_DATA="$D/datos_pibot" nohup "$D/node/bin/node" "$D/PIBOT/runtime/robot-runtime.mjs" \
      > "$D/logs/pibot.log" 2>&1 & echo $! > "$D/run/pibot.pid"
    # Las direcciones a las que se puede entrar: la Wi-Fi y el cable de desarrollo (no las redes internas del robot)
    echo "PIBOT: encendido en $(hostname -I | tr ' ' '\n' | grep -v -E '^(10\.0\.1\.|10\.11\.|127\.)' | grep . | sed 's#.*#http://&:8000#' | tr '\n' ' ')"
  fi
}

puente() {
  vivo puente && { echo "El puente ya está corriendo."; return; }
  cat <<'AVISO'
Desde que arranca el puente, un flujo de PIBOT puede hacer hablar, gesticular y CAMINAR al robot.
Antes: el robot de pie (con el control), 3 m libres, una persona con el control en la mano y otra cerca para sostenerlo.
Parada de emergencia según el manual: torque cero (L1 + R1 + Create); el robot se desploma, hay que sostenerlo del asa.
AVISO
  read -r -p "¿Está todo listo? Escribe si para arrancar: " r
  [[ "$r" == "si" || "$r" == "sí" ]] || { echo "No se arrancó."; return; }
  # El LLM solo si se indica (NCLUB_LLM=http://127.0.0.1:<puerto>/v1): en el robot puede haber servidores de otros equipos
  local llm=(); [[ -n "${NCLUB_LLM:-}" ]] && llm=(--llm "$NCLUB_LLM")
  # Caminar solo si se pide: en el X2 real el giro todavía no es confiable (2026-10-24)
  local caminar=(--sin-caminar); [[ "${NCLUB_CAMINAR:-0}" == 1 ]] && caminar=()
  ( set +u; source "$D/entorno.sh" && cd "$D/pibot" && exec python3 puente.py --real --rostro http://127.0.0.1:8096 \
      --voz http://127.0.0.1:8097 "${llm[@]}" "${caminar[@]}" ) > "$D/logs/puente.log" 2>&1 & echo $! > "$D/run/puente.pid"
  sleep 4; tail -5 "$D/logs/puente.log"
}

estado() {
  for c in nclub-rostro nclub-voz; do
    printf '%-22s %s\n' "$c" "$(podman inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo 'apagado')"
  done
  for p in pibot puente; do printf '%-22s %s\n' "$p" "$(vivo "$p" && echo corriendo || echo apagado)"; done
  curl -s -m 2 http://127.0.0.1:8096/estado 2>/dev/null | python3 -c 'import json,sys; e=json.load(sys.stdin); print("caras:", e.get("personas"), "personas,", e.get("origen") or e.get("error"))' 2>/dev/null
}

detener() {
  for p in puente pibot; do vivo "$p" && kill "$(cat "$D/run/$p.pid")" && echo "$p: detenido"; rm -f "$D/run/$p.pid"; done
  podman rm -f nclub-rostro nclub-voz >/dev/null 2>&1 && echo "reconocimiento facial y voz: detenidos"
}

# El asistente de fábrica (sección 8.1 del SDK). Cambia la voz del robot para cualquiera que lo use: al terminar, «normal»
asistente() {
  local modo
  case "${1:-}" in propio) modo=only_voice ;; normal) modo=normal ;; *) echo "Uso: ./nclub.sh asistente propio|normal"; return 1 ;; esac
  ( set +u; source "$D/entorno.sh"
    ros2 service call /aimdk_5Fmsgs/srv/SetAgentPropertiesRequest aimdk_msgs/srv/SetAgentPropertiesRequest \
      "{contents: {properties: [{key: {value: 2}, value: '$modo'}]}}" 2>&1 | grep -q "code=0" ) \
    || { echo "El asistente no aceptó el modo $modo"; return 1; }
  timeout 60 aima em stop-app agent >/dev/null 2>&1; sleep 3; timeout 60 aima em start-app agent >/dev/null 2>&1
  echo "asistente de voz: $modo"
  [[ "$modo" == only_voice ]] && echo "Digan «Hello, lumi» una vez frente al robot: desde ahí el micrófono le llega a PIBOT."
}

api() { curl -s -m 10 -X POST -H 'Content-Type: application/json' "$@"; }

publicar() {
  local flujo="$D/PIBOT/flows/${1:-demostracion.json}"
  [[ -f "$flujo" ]] || { echo "No existe $flujo"; return 1; }
  python3 -c 'import json, sys; print(json.dumps({"flow": json.load(open(sys.argv[1])), "workspace": json.load(open(sys.argv[2]))}))' \
    "$flujo" "$D/PIBOT/data/club.json" | api --data-binary @- http://127.0.0.1:8000/api/publish | grep -q '"ok":true' \
    && echo "publicado en PIBOT: $(basename "$flujo")" || echo "PIBOT no aceptó el flujo (¿está encendido? ./nclub.sh servicios)"
}

llegadas() {
  local pausa
  case "${1:-}" in si) pausa=false ;; no) pausa=true ;; *) echo "Uso: ./nclub.sh llegadas si|no"; return 1 ;; esac
  api -d "{\"paused\": $pausa}" http://127.0.0.1:8000/api/pause >/dev/null && echo "llegadas: ${1}"
}

demo() {
  servicios
  asistente propio
  echo si | puente >/dev/null
  for _ in $(seq 1 30); do curl -s -m 2 http://127.0.0.1:8000/api/robot | grep -q '"connected":true' && break; sleep 1; done
  publicar "${1:-demostracion.json}"
  llegadas si
  estado
}

# Al irse de un robot compartido: no queda nada nuestro corriendo ni configurado (la carpeta la borra ./x2 robot-limpiar)
limpiar() {
  detener
  asistente normal
  ( set +u; source "$D/entorno.sh" && cd "$D/pibot" && timeout 40 python3 quitar_fuentes.py )
  podman rmi nclub-rostro:arm64 nclub-voz:arm64 >/dev/null 2>&1 && echo "imágenes nclub-*: borradas"
}

case "${1:-estado}" in
  servicios) servicios ;;
  puente) puente ;;
  estado) estado ;;
  detener) detener ;;
  asistente) asistente "${2:-}" ;;
  publicar) publicar "${2:-}" ;;
  llegadas) llegadas "${2:-}" ;;
  demo) demo "${2:-}" ;;
  limpiar) limpiar ;;
  *) sed -n 2,17p "$D/nclub.sh" ;;
esac
