#!/usr/bin/env bash
# Recepción N Club en el AgiBot X2: corre en el Orin (computador de desarrollo), todo dentro de ~/nclub.
#   ./nclub.sh servicios   reconocimiento facial y voz a texto (podman) y PIBOT (http://<robot>:8000). No mueven el robot.
#   (Sin límite de CPU: en este Orin podman sin root no tiene el controlador de CPU; Whisper usa 3 hilos.)
#   ./nclub.sh puente      el puente con MC, la cámara y el micrófono: desde aquí un flujo puede hacer caminar al robot
#   ./nclub.sh estado      qué está corriendo
#   ./nclub.sh detener     apaga todo lo de N Club (nada de otros equipos)
set -uo pipefail
cd "$(dirname "$0")"
D=$PWD; mkdir -p "$D/run" "$D/logs"

vivo() { [[ -f "$D/run/$1.pid" ]] && kill -0 "$(cat "$D/run/$1.pid")" 2>/dev/null; }

servicios() {
  if ! podman container exists nclub-rostro || [[ "$(podman inspect -f '{{.State.Running}}' nclub-rostro)" != true ]]; then
    podman rm -f nclub-rostro >/dev/null 2>&1
    local env=(); [[ -f "$D/rostro/.env" ]] && env=(--env-file "$D/rostro/.env")
    # Calibración de demo (umbral 0.50, margen 0.10; ajuste manual sin validar) si existe; si no, la de ORL de Fermín
    [[ -f "$D/rostro/datos/calibracion-demo.json" ]] && env+=(-e FACE_CALIBRATION=datos/calibracion-demo.json)
    podman run -d --init --name nclub-rostro --network host -e HOST=127.0.0.1 -e PYTHONPATH=/face/src "${env[@]}" \
      -v "$D/face_lite:/face:ro" -v "$D/rostro:/rostro" nclub-rostro:arm64 python servicio.py >/dev/null && echo "reconocimiento facial: encendido"
  fi
  if podman image exists nclub-voz:arm64 && { ! podman container exists nclub-voz || [[ "$(podman inspect -f '{{.State.Running}}' nclub-voz)" != true ]]; }; then
    podman rm -f nclub-voz >/dev/null 2>&1
    podman run -d --init --name nclub-voz --network host -e HOST=127.0.0.1 -e VOZ_HILOS=3 -e VOZ_MODELO="${VOZ_MODELO:-base}" \
      -v "$D/voz:/voz" nclub-voz:arm64 python voz.py >/dev/null && echo "voz a texto: encendida"
  fi
  if ! vivo pibot; then
    PORT=8000 HOST=0.0.0.0 PIBOT_DATA="$D/datos_pibot" nohup "$D/node/bin/node" "$D/PIBOT/runtime/robot-runtime.mjs" \
      > "$D/logs/pibot.log" 2>&1 & echo $! > "$D/run/pibot.pid"
    echo "PIBOT: encendido en http://$(hostname -I | tr ' ' '\n' | grep -m1 '^192\.168\.'):8000 (red Wi-Fi del robot)"
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
  ( set +u; source "$D/entorno.sh" && cd "$D/pibot" && exec python3 puente.py --real --rostro http://127.0.0.1:8096 \
      --voz http://127.0.0.1:8097 "${llm[@]}" ) > "$D/logs/puente.log" 2>&1 & echo $! > "$D/run/puente.pid"
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

case "${1:-estado}" in
  servicios) servicios ;;
  puente) puente ;;
  estado) estado ;;
  detener) detener ;;
  *) sed -n 2,7p "$0" ;;
esac
