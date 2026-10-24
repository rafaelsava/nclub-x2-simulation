#!/usr/bin/env python3
"""Cámara y micrófono falsos del X2, para probar los sentidos del puente en la simulación (que no tiene ninguno).

    python3 sentidos_falsos.py --foto cara.jpg [--desde 3]          publica la foto como cámara de la cabeza
    python3 sentidos_falsos.py --frase hola.wav [--desde 2]         publica la frase como si alguien la dijera

Publica en los mismos tópicos y con el mismo formato que el robot real: la foto en JPEG a 10 Hz y la frase en
PCM de 16 kHz, en trozos de 30 ms marcados con el inicio, el medio y el fin de la detección de voz.
"""

import argparse
import array
import time
import wave

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import CompressedImage

from aimdk_msgs.msg import AudioVadStateType, ProcessedAudioOutput
from sentidos import CAMARA, MICROFONO


def leer_wav_16k(ruta):
    with wave.open(ruta) as w:
        frecuencia, canales = w.getframerate(), w.getnchannels()
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(np.float32)
    if canales > 1:
        audio = audio.reshape(-1, canales).mean(axis=1)
    if frecuencia != 16000:  # interpolación lineal: basta para una prueba
        n = int(len(audio) * 16000 / frecuencia)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
    return audio.astype('<i2').tobytes()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--foto', help='imagen que ve la cámara (sin --foto, no se publica cámara)')
    p.add_argument('--frase', help='WAV que oye el micrófono (sin --frase, no se publica audio)')
    p.add_argument('--desde', type=float, default=0.0, help='segundos antes de empezar')
    p.add_argument('--durante', type=float, default=30.0, help='segundos que se publica la foto')
    a = p.parse_args()

    rclpy.init()
    node = Node('nclub_sentidos_falsos')
    time.sleep(a.desde)
    if a.frase:
        pub = node.create_publisher(ProcessedAudioOutput, MICROFONO,
                                    QoSProfile(history=QoSHistoryPolicy.KEEP_LAST, depth=500,
                                               reliability=QoSReliabilityPolicy.BEST_EFFORT))
        time.sleep(1.0)  # que el puente descubra al publicador
        pcm, trozo = leer_wav_16k(a.frase), 960  # 30 ms
        partes = [pcm[i:i + trozo] for i in range(0, len(pcm), trozo)]
        for i, parte in enumerate(partes):
            m = ProcessedAudioOutput()
            m.stream_id = 0
            m.audio_vad_state.value = (AudioVadStateType.AUDIO_VAD_STATE_BEGIN if i == 0 else
                                       AudioVadStateType.AUDIO_VAD_STATE_END if i == len(partes) - 1 else
                                       AudioVadStateType.AUDIO_VAD_STATE_PROCESSING)
            m.audio_data = array.array('B', parte)
            pub.publish(m)
            time.sleep(0.03)
        print(f'frase publicada: {len(pcm) / 32000:.1f} s', flush=True)
    if a.foto:
        img = cv2.imread(a.foto)
        if img.shape[0] < 360:  # las fotos de prueba (ORL) son chicas: se agranda como si la persona estuviera cerca
            img = cv2.resize(img, None, fx=360 / img.shape[0], fy=360 / img.shape[0])
        lienzo = np.full((480, 640, 3), 120, np.uint8)
        y, x = (480 - img.shape[0]) // 2, (640 - img.shape[1]) // 2
        lienzo[y:y + img.shape[0], x:x + img.shape[1]] = img
        jpeg = cv2.imencode('.jpg', lienzo, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
        pub = node.create_publisher(CompressedImage, CAMARA, 1)
        fin = time.monotonic() + a.durante
        while time.monotonic() < fin:
            m = CompressedImage()
            m.format, m.data = 'jpeg', array.array('B', jpeg)
            pub.publish(m)
            time.sleep(0.1)
        print('cámara terminada', flush=True)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
