#!/usr/bin/env python3
"""Demo de movimiento básico del X2 Ultra: ponerse de pie, caminar, girar, detenerse.

Funciona igual en la simulación (MuJoCo + MC) y en el robot real, porque solo usa
las interfaces ROS 2 públicas del AimDK. Uso dentro del contenedor:

    python3 /workspace/scripts/demo_basico.py

Ctrl+C detiene el robot y lo deja de pie.
"""

import math
import signal
import threading
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from aimdk_msgs.msg import (CommonRequest, McActionCommand, McInputAction,
                            McLocomotionVelocity, MessageHeader, RequestHeader)
from aimdk_msgs.srv import GetMcAction, SetMcAction, SetMcInputSource
from nav_msgs.msg import Odometry

INPUT_SOURCE = 'node.nclub_demo'

# (nombre, avance m/s, lateral m/s, giro rad/s, duración s)
# MC solo arranca con avance/lateral 0 o entre 0.2 y 1.0, y giro 0 o entre 0.1 y 1.0.
# El giro en el sitio solo con velocidad angular no está garantizado, por eso se gira avanzando.
SECUENCIA = [
    ('avanzar', 0.3, 0.0, 0.0, 4.0),
    ('girar a la izquierda', 0.2, 0.0, 0.5, 4.0),
    ('detenerse', 0.0, 0.0, 0.0, 1.5),
]


class DemoBasico(Node):
    def __init__(self):
        super().__init__('nclub_demo_basico')
        self.set_action_client = self.create_client(SetMcAction, '/aimdk_5Fmsgs/srv/SetMcAction')
        self.get_action_client = self.create_client(GetMcAction, '/aimdk_5Fmsgs/srv/GetMcAction')
        self.input_source_client = self.create_client(SetMcInputSource, '/aimdk_5Fmsgs/srv/SetMcInputSource')
        self.velocity_pub = self.create_publisher(McLocomotionVelocity, '/aima/mc/locomotion/velocity', 10)
        # La odometría se publica como best effort; con la QoS por defecto (reliable) no llega ningún mensaje
        self.create_subscription(Odometry, '/aima/hal/odom/state', self._on_odom, qos_profile_sensor_data)

        self.velocity = (0.0, 0.0, 0.0)
        self.odom = None
        # MC espera comandos de velocidad continuos; si deja de recibirlos mientras camina, vuelve a estar de pie
        self.create_timer(0.02, self._publish_velocity)

    def _on_odom(self, msg):
        self.odom = msg.pose.pose

    def _publish_velocity(self):
        msg = McLocomotionVelocity()
        msg.header = MessageHeader()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.source = INPUT_SOURCE
        msg.forward_velocity, msg.lateral_velocity, msg.angular_velocity = self.velocity
        self.velocity_pub.publish(msg)

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

    def wait_for_services(self):
        for client in (self.set_action_client, self.get_action_client, self.input_source_client):
            while not client.wait_for_service(timeout_sec=2.0):
                self.get_logger().info(f'Esperando el servicio {client.srv_name}...')

    def set_input_source(self, action):
        req = SetMcInputSource.Request()
        req.action.value = action
        req.input_source.name = INPUT_SOURCE
        req.input_source.priority = 40
        req.input_source.timeout = 1000
        req.request.header.stamp = self.get_clock().now().to_msg()
        res = self._call(self.input_source_client, req)
        return res is not None and res.response.header.code == 0

    def register_input_source(self):
        if self.set_input_source(McInputAction.INPUTACTION_ADD):
            return True
        # Ya estaba registrada de una ejecución anterior
        return self.set_input_source(McInputAction.INPUTACTION_ENABLE)

    def get_mode(self):
        req = GetMcAction.Request()
        req.request = CommonRequest()
        res = self._call(self.get_action_client, req)
        return res.info.action_desc if res else None

    def set_mode(self, mode, timeout=15.0):
        req = SetMcAction.Request()
        req.header = RequestHeader()
        req.header.stamp = self.get_clock().now().to_msg()
        req.source = INPUT_SOURCE
        req.command = McActionCommand()
        req.command.action_desc = mode
        res = self._call(self.set_action_client, req)
        if res is None or res.response.header.code != 0:
            code = res.response.header.code if res else 'sin respuesta'
            self.get_logger().error(f'MC rechazó el cambio a {mode} (código {code})')
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.get_mode() == mode:
                return True
            time.sleep(0.2)
        self.get_logger().error(f'El robot no llegó a {mode} en {timeout:.0f} s')
        return False

    def position(self):
        if self.odom is None:
            return None
        p, q = self.odom.position, self.odom.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        return p.x, p.y, math.degrees(yaw)

    def log_position(self, label):
        pos = self.position()
        if pos:
            self.get_logger().info(f'{label}: x={pos[0]:.2f} m, y={pos[1]:.2f} m, orientación={pos[2]:.0f}°')


def main():
    rclpy.init()
    node = DemoBasico()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    def stop(*_):
        node.velocity = (0.0, 0.0, 0.0)
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        node.wait_for_services()
        if not node.register_input_source():
            node.get_logger().error('No se pudo registrar la fuente de control en MC')
            return

        node.get_logger().info(f'Modo actual: {node.get_mode()}')
        node.get_logger().info('Poniéndose de pie (STAND_DEFAULT)...')
        if not node.set_mode('STAND_DEFAULT'):
            return
        node.log_position('Inicio')

        # No hace falta pedir LOCOMOTION_DEFAULT: estando de pie, MC cambia solo a locomoción al recibir
        # velocidad distinta de cero, y vuelve a STAND_DEFAULT unos 2 s después de recibir solo ceros
        for name, forward, lateral, angular, duration in SECUENCIA:
            node.get_logger().info(f'{name}: avance {forward} m/s, lateral {lateral} m/s, giro {angular} rad/s, {duration} s')
            node.velocity = (forward, lateral, angular)
            time.sleep(duration)
            node.log_position(f'Después de {name} (modo {node.get_mode()})')
    except KeyboardInterrupt:
        node.get_logger().info('Interrumpido, deteniendo el robot')
    finally:
        node.velocity = (0.0, 0.0, 0.0)
        time.sleep(0.3)
        node.set_mode('STAND_DEFAULT')
        node.set_input_source(McInputAction.INPUTACTION_DISABLE)
        node.get_logger().info(f'Fin. Modo actual: {node.get_mode()}')
        executor.shutdown()
        spin_thread.join(timeout=2.0)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
