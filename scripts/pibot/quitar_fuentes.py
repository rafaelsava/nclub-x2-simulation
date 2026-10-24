#!/usr/bin/env python3
"""Borra del control de movimiento (MC) las fuentes de control que registran nuestros programas.

    python3 quitar_fuentes.py

Cada programa que mueve el robot registra su fuente (robot.py, nombre "node.<nombre>"): al terminar, cerrar() solo
la desactiva. En un robot compartido conviene borrarlas al irse. No toca las de otros.
"""

import rclpy
from rclpy.node import Node

from aimdk_msgs.msg import McInputAction
from aimdk_msgs.srv import SetMcInputSource

NUESTRAS = ('node.nclub_pibot', 'node.nclub_caminata', 'node.nclub_diagnostico', 'node.nclub_x2')


def main():
    rclpy.init()
    nodo = Node('nclub_limpieza')
    cliente = nodo.create_client(SetMcInputSource, '/aimdk_5Fmsgs/srv/SetMcInputSource')
    if not cliente.wait_for_service(timeout_sec=10.0):
        print('MC no responde: no se borró ninguna fuente')
        return
    for nombre in NUESTRAS:
        req = SetMcInputSource.Request()
        req.action.value = McInputAction.INPUTACTION_DELETE
        req.input_source.name = nombre
        futuro = cliente.call_async(req)
        rclpy.spin_until_future_complete(nodo, futuro, timeout_sec=5.0)
        r = futuro.result()
        codigo = r.response.header.code if r else None
        print(f'{nombre}: {"borrada" if codigo == 0 else "no estaba" if r else "sin respuesta"}')
    nodo.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
