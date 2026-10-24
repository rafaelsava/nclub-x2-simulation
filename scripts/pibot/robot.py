"""Movimiento del X2 para el puente de PIBOT: a través del control de movimiento oficial (MC), o imitado sin ROS.

RobotMC usa solo interfaces ROS 2 públicas del AimDK, así que funciona igual con MuJoCo y con el robot real.
RobotSinRos no mueve nada: imita los tiempos para poder probar los flujos sin Docker ni simulador.
"""

import math
import threading
import time

from guia_real import GuiaReal

try:
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.signals import SignalHandlerOptions

    from aimdk_msgs.msg import (CommonRequest, McActionCommand, McControlArea, McInputAction,
                                McLocomotionVelocity, McPresetMotion, MessageHeader, RequestHeader, TtsPriorityLevel)
    from aimdk_msgs.srv import GetMcAction, PlayTts, SetMcAction, SetMcInputSource, SetMcPresetMotion
    from nav_msgs.msg import Odometry
except ImportError:  # sin ROS 2 solo se puede usar RobotSinRos
    rclpy = None


GESTOS = {'levantar': 1001, 'saludar': 1002, 'dar_la_mano': 1003, 'beso': 1004}
BRAZO_DERECHO = 2


def _normalizar(angulo):
    return math.atan2(math.sin(angulo), math.cos(angulo))


# Odometría: la simulación la publica en /aima/hal/odom/state. En el X2 real, en orden de preferencia:
# - /slam/lidar_odom: el robot en el mapa del SLAM (marco 'map', torso_link). Solo publica después de relocalizar el
#   robot en un mapa (SDK 5.5.2); sus coordenadas no cambian al reiniciar, así que los lugares marcados duran.
# - /aima/mc/leg_odometry: la de las piernas de MC. Siempre publica, pero arranca donde se prendió el robot y el
#   2026-10-24 saltó ~50 m y ~10 m en pocos minutos: los lugares hay que marcarlos de nuevo en cada sesión.
ODOMETRIA_SIM = ['/aima/hal/odom/state']
ODOMETRIA_REAL = ['/slam/lidar_odom', '/aima/mc/leg_odometry']
ESPERA_ODOMETRIA = 3.0  # s al arrancar para ver qué odometrías publican y quedarse con la mejor
SALTO_ODOMETRIA = 0.5   # m entre dos mensajes seguidos: un salto, no un paso
MAX_DISTANCIA_REAL = 6.0  # m: más lejos que esto, el robot real no camina (lugar mal marcado o salto de odometría)


def crear_robot(sin_ros, velocidad=0.3, nombre='nclub_x2', real=False):
    """velocidad: avance en m/s al caminar en recta (MC acepta 0.2 a 1.0).

    nombre: nodo ROS y fuente de control en MC; cada programa que mueve el robot usa el suyo.
    real: el X2 de verdad: nunca cambia solo el modo de MC (eso se hace con el control) y la altura no sirve para
    saber si se cayó (su odometría no mide la pelvis sobre el piso).
    """
    if sin_ros:
        return RobotSinRos(velocidad)
    if rclpy is None:
        raise RuntimeError('ROS 2 no está disponible: corre dentro del contenedor (./x2 pibot) o usa --sin-robot')
    return RobotMC(velocidad, nombre, real)


class RobotMC:
    def __init__(self, velocidad=0.3, nombre='nclub_x2', real=False):
        self.velocidad_avance = velocidad
        self.nombre = nombre
        self.real = real
        self.odometria = None  # el tópico del que llegan las posiciones (no se mezclan marcos de referencia)
        self._vistas = set()   # odometrías que han publicado mientras se elige
        self._desde = None     # cuándo empezó a escuchar las odometrías
        self.fuente = f'node.{nombre}'
        self._velocidad = (0.0, 0.0, 0.0)
        self._moviendo = False
        self._parar = threading.Event()
        self._inclinacion = 0.0
        self._pose = None
        self._modo = None
        self.voz_propia = None  # VozPropia: hablar con Piper en vez de la voz de fábrica (solo el robot real)

    def iniciar(self):
        # Ctrl+C y SIGTERM los maneja app.py; si rclpy los toma, apaga ROS pero el programa sigue vivo
        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
        node = Node(self.nombre)
        self._node = node
        self._set_action = node.create_client(SetMcAction, '/aimdk_5Fmsgs/srv/SetMcAction')
        self._get_action = node.create_client(GetMcAction, '/aimdk_5Fmsgs/srv/GetMcAction')
        self._input_source = node.create_client(SetMcInputSource, '/aimdk_5Fmsgs/srv/SetMcInputSource')
        self._preset = node.create_client(SetMcPresetMotion, '/aimdk_5Fmsgs/srv/SetMcPresetMotion')
        self._tts = node.create_client(PlayTts, '/aimdk_5Fmsgs/srv/PlayTts')  # voz del robot (no existe en la simulación)
        self._velocity_pub = node.create_publisher(McLocomotionVelocity, '/aima/mc/locomotion/velocity', 10)
        # La odometría se publica como best effort; con la QoS por defecto (reliable) no llega nada
        self._desde = time.monotonic()
        for topico in (ODOMETRIA_REAL if self.real else ODOMETRIA_SIM):
            node.create_subscription(Odometry, topico, lambda m, t=topico: self._on_odom(m, t), qos_profile_sensor_data)
        node.create_timer(0.02, self._publicar_velocidad)

        self._executor = SingleThreadedExecutor()
        self._executor.add_node(node)
        self._spin_thread = threading.Thread(target=self._executor.spin, daemon=True)
        self._spin_thread.start()

        for client in (self._set_action, self._get_action, self._input_source, self._preset):
            if not client.wait_for_service(timeout_sec=10.0):
                raise RuntimeError(f'MC no responde ({client.srv_name}). ¿Están corriendo ./x2 sim y ./x2 mc?')
        if not self._registrar_fuente():
            raise RuntimeError('No se pudo registrar la fuente de control en MC')
        threading.Thread(target=self._vigilar_modo, daemon=True).start()

    def cerrar(self):
        self._velocidad = (0.0, 0.0, 0.0)
        self._moviendo = False
        self._set_fuente(McInputAction.INPUTACTION_DISABLE)
        self._executor.shutdown()
        self._spin_thread.join(timeout=2.0)
        self._node.destroy_node()
        rclpy.shutdown()

    # --- Comunicación con MC ---

    def _call(self, client, req, timeout=2.0, retries=4):
        # Igual que en los ejemplos oficiales: los servicios ROS entre equipos a veces se pierden, así que se reintenta
        for _ in range(retries):
            future = client.call_async(req)
            deadline = time.monotonic() + timeout
            while not future.done() and time.monotonic() < deadline:
                time.sleep(0.01)
            if future.done():
                return future.result()
        return None

    def _set_fuente(self, action):
        req = SetMcInputSource.Request()
        req.action.value = action
        req.input_source.name = self.fuente
        req.input_source.priority = 40
        req.input_source.timeout = 1000
        res = self._call(self._input_source, req)
        return res is not None and res.response.header.code == 0

    def _registrar_fuente(self):
        if self._set_fuente(McInputAction.INPUTACTION_ADD):
            return True
        # Ya estaba registrada de una ejecución anterior
        return self._set_fuente(McInputAction.INPUTACTION_ENABLE)

    def _on_odom(self, msg, topico):
        if self.odometria is None:
            # En la simulación hay una sola. En el real se espera unos segundos y gana la preferida de las que
            # publican; después no se cambia, para no mezclar marcos de referencia (los lugares quedarían mal)
            self._vistas.add(topico)
            lista = ODOMETRIA_REAL if self.real else ODOMETRIA_SIM
            if topico == lista[0] or time.monotonic() - self._desde >= ESPERA_ODOMETRIA:
                self.odometria = min(self._vistas, key=lista.index)
                print(f'odometría: {self.odometria}', flush=True)
        if topico != self.odometria:
            return
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        if self._pose and math.hypot(p.x - self._pose[0], p.y - self._pose[1]) > SALTO_ODOMETRIA:
            print(f'la odometría saltó {math.hypot(p.x - self._pose[0], p.y - self._pose[1]):.1f} m: '
                  'los lugares marcados antes pueden haber quedado corridos', flush=True)
        if self.real and topico == '/aima/mc/leg_odometry':
            # Esta odometría es la del sensor del pecho (lidar_imu_chest_front), montado con su eje x hacia arriba
            # (cabeceo de -88°): ahí el ángulo de Euler no sirve. Adelante es su eje z al revés (medido con el
            # control, 2026-10-24): la orientación es la de -z proyectado en el piso.
            zx, zy = 2 * (q.x * q.z + q.y * q.w), 2 * (q.y * q.z - q.x * q.w)
            yaw = math.atan2(-zy, -zx)
        else:
            yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        self._pose = (p.x, p.y, p.z, yaw)
        # Inclinación hacia adelante: positiva = boca abajo, negativa = boca arriba (sirve para saber cómo levantarse)
        self._inclinacion = math.asin(max(-1.0, min(1.0, 2 * (q.w * q.y - q.z * q.x))))

    def _publicar_velocidad(self):
        # Solo se publica mientras el robot se mueve, para no pisar a otras herramientas (teclado, ejemplos)
        if not self._moviendo:
            return
        msg = McLocomotionVelocity()
        msg.header = MessageHeader()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.source = self.fuente
        msg.forward_velocity, msg.lateral_velocity, msg.angular_velocity = self._velocidad
        self._velocity_pub.publish(msg)

    def _leer_modo(self):
        req = GetMcAction.Request()
        req.request = CommonRequest()
        res = self._call(self._get_action, req, timeout=1.0, retries=2)
        return res.info.action_desc if res else None

    def _vigilar_modo(self):
        while rclpy.ok():
            try:
                self._modo = self._leer_modo()
            except Exception:  # al cerrar, ROS se apaga a mitad de una consulta: no es un error
                if not rclpy.ok():
                    return
                raise
            time.sleep(1.0)

    def _pedir_modo(self, modo):
        req = SetMcAction.Request()
        req.header = RequestHeader()
        req.source = self.fuente
        req.command = McActionCommand()
        req.command.action_desc = modo
        res = self._call(self._set_action, req)
        return res is not None and res.response.header.code == 0

    def _set_modo(self, modo, timeout=15.0):
        if not self._pedir_modo(modo):
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._leer_modo() == modo:
                return True
            time.sleep(0.2)
        return False

    # --- Acciones que usan los flujos ---

    def estado(self):
        if self._pose is None:
            return {'modo': self._modo}
        x, y, z, yaw = self._pose
        return {'modo': self._modo, 'x': round(x, 2), 'y': round(y, 2), 'altura': None if self.real else round(z, 2),
                'orientacion': round(math.degrees(yaw))}

    def de_pie(self):
        """Deja al robot en equilibrio de pie. Devuelve False si no lo logra (por ejemplo, si se cayó)."""
        if self.real:  # en el robot real no se le cambia el modo: si no está de pie, se pone de pie con el control
            return self._leer_modo() in ('STAND_DEFAULT', 'LOCOMOTION_DEFAULT')
        if self._pose is not None and self._pose[2] < 0.4:
            return False  # pelvis casi en el suelo: el robot está caído
        # Justo después de caminar MC sigue en locomoción unos 2 s antes de volver solo a STAND_DEFAULT
        if self._leer_modo() in ('STAND_DEFAULT', 'LOCOMOTION_DEFAULT'):
            return True
        return self._set_modo('STAND_DEFAULT')

    def levantarse(self, intentos=3):
        """Si está en el suelo, se levanta solo con las rutinas de MC, igual que el X2 real. Devuelve True si quedó de pie.

        Secuencia (probada en MuJoCo, 2026-10-23): modo pasivo, que siempre se permite y quita el bloqueo de seguridad
        que MC pone tras una caída; unos segundos para que el cuerpo se asiente; y LIE_UP_DEFAULT, que acomoda el
        cuerpo boca arriba (si cayó boca abajo o de lado, primero lo da vuelta). MC sigue solo con el movimiento de
        levantarse (GROUNDUP) y queda en STAND_DEFAULT. Pedir directamente el movimiento, sin dejar que acomode,
        falla; y la rutina de boca abajo (GET_UP_DEFAULT → PRONE_UP_DEFAULT) falló en todas las pruebas.
        El manual pide 0.5 m libres alrededor del robot para hacerlo.
        """
        if self.real:
            return False  # en el real se levanta con el control remoto y con personas al lado
        for _ in range(intentos):
            if self._pose and self._pose[2] > 0.55:
                return True
            self._pedir_modo('PASSIVE_DEFAULT')
            time.sleep(3.0)
            self._pedir_modo('LIE_UP_DEFAULT')
            fin = time.monotonic() + 25.0
            while time.monotonic() < fin:
                time.sleep(1.0)
                if self._pose and self._pose[2] > 0.6 and self._leer_modo() == 'STAND_DEFAULT':
                    time.sleep(2.0)  # que se estabilice antes de dar por bueno
                    if self._pose[2] > 0.6:
                        return True
                if self._pose and self._pose[2] < 0.2 and self._leer_modo() == 'STAND_DEFAULT':
                    break  # el intento terminó en el suelo (a veces cae del otro lado): se reintenta desde ahí
        return bool(self._pose and self._pose[2] > 0.55)

    def usar_voz_propia(self, voz_url):
        """Desde ahora habla con la voz en español de Piper (la de la simulación) por el parlante del robot."""
        from voz_propia import VozPropia
        self.voz_propia = VozPropia(self._node, voz_url, self._call)

    def hablar(self, texto):
        """Dice el texto por el parlante del robot: con la voz de Piper si se pidió (usar_voz_propia) y, si no se
        puede, con la de fábrica (PlayTts, como en el ejemplo oficial).

        Devuelve cuántos segundos estima el robot que tarda en decirlo, o None si no hay voz (en la simulación).
        """
        if self.voz_propia:
            try:
                if self.voz_propia.decir(texto):
                    return 0.05  # ya terminó de sonar
                print('voz propia: el robot no dio el foco de audio; hablo con la voz de fábrica', flush=True)
            except Exception as e:  # sin servicio de voz, sin Piper o sin el tópico de audio
                print(f'voz propia: {e}; hablo con la voz de fábrica', flush=True)
        if not self._tts.wait_for_service(timeout_sec=1.0):
            return None
        req = PlayTts.Request()
        req.header = CommonRequest()
        req.tts_req.text = texto
        req.tts_req.domain = 'nclub_recepcion'  # quién llama
        req.tts_req.trace_id = f'pibot-{time.monotonic_ns()}'
        req.tts_req.is_interrupted = True  # una frase nueva corta la anterior
        req.tts_req.priority_weight = 0
        req.tts_req.priority_level = TtsPriorityLevel()
        req.tts_req.priority_level.value = TtsPriorityLevel.INTERACTION_L6
        res = self._call(self._tts, req, timeout=10.0, retries=1)
        if res is None or not res.tts_resp.is_success:
            return None
        d = res.tts_resp.estimated_duration  # sin unidad documentada: si es grande, son milisegundos
        return d / 1000 if d > 100 else float(d)

    def gesto(self, nombre):
        """Gesto predefinido de MC con el brazo derecho: levantar, saludar, dar_la_mano o beso."""
        if not self.de_pie():
            return False
        req = SetMcPresetMotion.Request()
        req.header = RequestHeader()
        req.input_source.name = self.fuente
        req.input_source.priority = 40
        req.input_source.timeout = 1000
        req.motion = McPresetMotion()
        req.motion.value = GESTOS[nombre]
        req.area = McControlArea()
        req.area.value = BRAZO_DERECHO
        req.interrupt = False
        res = self._call(self._preset, req, timeout=5.0, retries=1)
        return res is not None and res.response.header.code == 0

    def ir_a(self, x, y, tolerancia=0.35, timeout=90.0):
        """Camina hasta (x, y) en el marco de la odometría. Devuelve True si llegó."""
        self._parar.clear()
        return self._ir(x, y, tolerancia, timeout)

    def volver_al_puesto(self, puesto):
        # Primero a un punto 1.2 m detrás del puesto y luego por la recta hasta él,
        # para quedar mirando hacia la entrada (+x) y no torcido
        self._parar.clear()
        if self.real:  # en el robot real no se sabe qué hay "detrás" del puesto: va derecho a él
            return self.ir_a(puesto['x'], puesto['y'])
        if not self._ir(puesto['x'] - 1.2, puesto['y'], 0.35, 90.0):
            return False

        def sobre_la_recta(px, py, yaw):
            if px >= puesto['x'] - 0.05:
                return None
            if px >= puesto['x'] - 0.4:
                return yaw  # los últimos 40 cm, recto: frenar girando lo tumbó dos veces al llegar
            return math.atan2(-1.5 * (py - puesto['y']), 1.0)
        # El tramo final va a la velocidad mínima: ahí se cayó una vez el robot (2026-10-23) y no hay prisa
        return self._conducir(sobre_la_recta, timeout=30.0, velocidad=0.2)

    def detener(self):
        """Interrumpe la caminata en curso (ir_a / volver_al_puesto devuelven False)."""
        self._parar.set()

    def _ir(self, x, y, tolerancia, timeout):
        if self.real:
            return self._ir_real(x, y, tolerancia, timeout)

        def guia(px, py, yaw):
            if math.hypot(x - px, y - py) < tolerancia:
                return None
            return math.atan2(y - py, x - px)
        return self._conducir(guia, timeout)

    def _ir_real(self, x, y, tolerancia, timeout):
        """En el robot real: gira en el sitio hacia el destino y camina recto, con los frenos de GuiaReal."""
        if self._pose is None:
            print('  no llega la posición del robot: no camino', flush=True)
            return False
        if not self.de_pie():
            return False
        distancia = math.hypot(x - self._pose[0], y - self._pose[1])
        # Un lugar muy lejos casi siempre es un lugar mal marcado (la odometría del robot real a veces salta)
        if distancia > MAX_DISTANCIA_REAL:
            print(f'  el lugar queda a {distancia:.0f} m: no camino; márquelo de nuevo en PIBOT', flush=True)
            return False
        # No más de lo que tardaría a 0.2 m/s, con holgura, más una media vuelta
        timeout = min(timeout, 25.0 + 3 * distancia / 0.2)
        guia = GuiaReal(x, y, tolerancia, self.velocidad_avance)
        inicio = time.monotonic()
        self._moviendo = True
        try:
            while time.monotonic() - inicio < timeout:
                if self._parar.is_set():
                    return False
                px, py, _, yaw = self._pose
                orden = guia.paso(time.monotonic() - inicio, px, py, yaw)
                if orden.fin:
                    if orden.motivo:
                        print(f'  {orden.motivo}: me detengo', flush=True)
                    return orden.fin == 'llegó'
                self._velocidad = (orden.avance, 0.0, orden.giro)
                time.sleep(0.1)
            print('  se acabó el tiempo para llegar: me detengo', flush=True)
            return False
        finally:
            self._velocidad = (0.0, 0.0, 0.0)
            time.sleep(0.3)  # unos comandos en cero para que MC frene antes de soltar el control
            self._moviendo = False

    def _conducir(self, rumbo_deseado, timeout, velocidad=None):
        """Camina corrigiendo el rumbo. rumbo_deseado(x, y, yaw) da el ángulo a seguir, o None al llegar."""
        if not self.de_pie():
            return False
        inicio = time.monotonic()
        avance = 0.2
        self._moviendo = True
        try:
            while time.monotonic() - inicio < timeout:
                if self._parar.is_set():
                    return False
                if self._pose is None:
                    time.sleep(0.1)
                    continue
                px, py, pz, yaw = self._pose
                if pz < 0.4 and not self.real:  # en el real la altura es la del sensor del pecho, no sirve
                    print('El robot se cayó. En la simulación: ./x2 pie lo vuelve a poner de pie.', flush=True)
                    return False
                rumbo = rumbo_deseado(px, py, yaw)
                if rumbo is None:
                    return True
                if rumbo is False:  # el que guía pidió detenerse
                    return False
                error = _normalizar(rumbo - yaw)
                # MC solo arranca con avance 0 o >= 0.2 m/s y giro 0 o >= 0.1 rad/s,
                # y no garantiza girar en el sitio: se gira siempre avanzando un poco
                giro = max(-0.6, min(0.6, 1.2 * error))
                if abs(giro) < 0.1:
                    giro = 0.0
                objetivo = (velocidad or self.velocidad_avance) if abs(error) < 0.8 else 0.2
                # Aceleración gradual: saltar de 0.2 a 0.5 m/s mientras aún gira tumbó al robot en la simulación
                avance = max(0.2, min(objetivo, avance + 0.05)) if objetivo > avance else objetivo
                self._velocidad = (avance, 0.0, giro)
                time.sleep(0.1)
            return False
        finally:
            self._velocidad = (0.0, 0.0, 0.0)
            time.sleep(0.3)  # unos comandos en cero para que MC frene antes de soltar el control
            self._moviendo = False


class RobotSinRos:
    """Imita al robot sin ROS: mismos métodos, tiempos parecidos, sin moverse de verdad."""

    def __init__(self, velocidad=0.3):
        self.velocidad_avance = velocidad
        self._x, self._y, self._yaw = 0.0, 0.0, 0.0
        self._parar = threading.Event()

    def iniciar(self):
        pass

    def cerrar(self):
        pass

    def estado(self):
        return {'modo': 'SIN ROBOT', 'x': round(self._x, 2), 'y': round(self._y, 2), 'altura': None,
                'orientacion': round(math.degrees(self._yaw))}

    def de_pie(self):
        return True

    def levantarse(self, intentos=3):
        return True

    def hablar(self, texto):
        return None

    def gesto(self, nombre):
        time.sleep(2.0)
        return True

    def ir_a(self, x, y, tolerancia=0.35, timeout=90.0):
        self._parar.clear()
        distancia = math.hypot(x - self._x, y - self._y)
        self._yaw = math.atan2(y - self._y, x - self._x)
        pasos = max(1, int(distancia / self.velocidad_avance / 0.2))
        x0, y0 = self._x, self._y
        for i in range(1, pasos + 1):
            if self._parar.is_set():
                return False
            self._x = x0 + (x - x0) * i / pasos
            self._y = y0 + (y - y0) * i / pasos
            time.sleep(0.2)
        return True

    def volver_al_puesto(self, puesto):
        ok = self.ir_a(puesto['x'], puesto['y'])
        if ok:
            self._yaw = 0.0
        return ok

    def detener(self):
        self._parar.set()
