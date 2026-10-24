#!/usr/bin/env python3
"""Diagnóstico de gestos predefinidos de MC: pide uno y muestra la respuesta, el estado y el brazo derecho."""

import sys
import threading
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from aimdk_msgs.msg import CommonRequest, JointStateArray, McControlArea, McInputAction, McPresetMotion, RequestHeader
from aimdk_msgs.srv import GetMcPresetMotionState, SetMcInputSource, SetMcPresetMotion

FUENTE = 'node.nclub_prueba_gesto'


def esperar(future, timeout):
    fin = time.monotonic() + timeout
    while not future.done() and time.monotonic() < fin:
        time.sleep(0.01)
    return future.result() if future.done() else None


def main():
    motion = int(sys.argv[1]) if len(sys.argv) > 1 else 1002
    area = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    rclpy.init()
    node = Node('nclub_prueba_gesto')
    brazo = {}

    def on_arm(msg):
        for j in msg.joints:
            if j.name in ('right_shoulder_pitch_joint', 'right_shoulder_roll_joint', 'right_elbow_joint'):
                brazo[j.name] = j.position

    node.create_subscription(JointStateArray, '/aima/hal/joint/arm/state', on_arm, qos_profile_sensor_data)
    set_preset = node.create_client(SetMcPresetMotion, '/aimdk_5Fmsgs/srv/SetMcPresetMotion')
    get_preset = node.create_client(GetMcPresetMotionState, '/aimdk_5Fmsgs/srv/GetMcPresetMotionState')
    fuente = node.create_client(SetMcInputSource, '/aimdk_5Fmsgs/srv/SetMcInputSource')
    ex = SingleThreadedExecutor()
    ex.add_node(node)
    threading.Thread(target=ex.spin, daemon=True).start()
    for c in (set_preset, get_preset, fuente):
        print(c.srv_name, 'disponible' if c.wait_for_service(timeout_sec=5) else 'NO DISPONIBLE', flush=True)

    req = SetMcInputSource.Request()
    req.action.value = McInputAction.INPUTACTION_ADD
    req.input_source.name, req.input_source.priority, req.input_source.timeout = FUENTE, 40, 1000
    r = esperar(fuente.call_async(req), 3)
    print('registrar fuente (ADD):', r.response.header.code if r else 'sin respuesta', flush=True)

    r = esperar(get_preset.call_async(GetMcPresetMotionState.Request()), 5)
    print('estado del gesto antes:', r if r else 'sin respuesta', flush=True)

    time.sleep(0.5)
    antes = dict(brazo)
    req = SetMcPresetMotion.Request()
    req.header = RequestHeader()
    req.header.stamp = node.get_clock().now().to_msg()
    req.input_source.name, req.input_source.priority, req.input_source.timeout = FUENTE, 40, 1000
    req.motion = McPresetMotion(value=motion)
    req.area = McControlArea(value=area)
    req.interrupt = True
    t0 = time.monotonic()
    future = set_preset.call_async(req)
    maximo = 0.0
    while time.monotonic() - t0 < 12:
        if brazo and antes:
            maximo = max(maximo, max(abs(brazo[k] - antes.get(k, brazo[k])) for k in brazo))
        if future.done() and time.monotonic() - t0 > 6:
            break
        time.sleep(0.05)
    r = future.result() if future.done() else None
    print(f'respuesta SetMcPresetMotion ({time.monotonic() - t0:.1f} s):', r if r else 'SIN RESPUESTA', flush=True)
    print(f'movimiento máximo del brazo derecho: {maximo:.2f} rad', flush=True)
    r = esperar(get_preset.call_async(GetMcPresetMotionState.Request()), 5)
    print('estado del gesto después:', r if r else 'sin respuesta', flush=True)
    ex.shutdown()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
