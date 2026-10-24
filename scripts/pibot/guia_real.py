"""Cómo lleva el puente al X2 real hasta un lugar: primero gira en el sitio hacia el destino y después camina recto,
corrigiendo el rumbo. Solo decide a partir de la posición y la orientación (no sabe de ROS), así que se prueba sin el
robot: prueba_guia_real.py.

Por qué así (prueba del 2026-10-24): con la ley de la simulación, que gira siempre avanzando a 0.2 m/s, el robot daba
la media vuelta sobre un arco de 0.33 m de radio y se alejaba del destino antes de enfilar; el freno de 30 cm lo
detenía (registro: "se está alejando del destino (2.5 m)" con el destino a 2.2 m). Girando en el sitio no se aleja.

Además vigila lo que la odometría del robot real hizo mal ese día, y en vez de seguir se detiene con el motivo:
- gira al revés de lo pedido (signo del giro o de la orientación);
- no avanza hacia donde cree que mira (orientación mal calculada);
- la posición salta (la odometría de las piernas saltó ~50 m y ~10 m en minutos);
- se aleja del destino mientras camina.
"""

import math
from dataclasses import dataclass


def normalizar(angulo):
    return math.atan2(math.sin(angulo), math.cos(angulo))


@dataclass
class Orden:
    avance: float = 0.0
    giro: float = 0.0
    fin: str | None = None     # None mientras camina; 'llegó' o 'freno' al terminar
    motivo: str = ''


class GuiaReal:
    GIRO = 0.4          # rad/s al girar en el sitio (MC acepta hasta 1.0 en velocidad baja)
    GIRO_ARCO = 0.6     # rad/s si MC no gira en el sitio y hay que girar avanzando
    ALINEADO = math.radians(20)    # con menos error que esto, camina
    REALINEAR = math.radians(50)   # si caminando el error pasa de esto, se detiene a girar otra vez
    GIRO_CAMINANDO = 0.4           # corrección máxima mientras camina
    PRUEBA_GIRO = 2.5   # s girando antes de comprobar que gira hacia el lado pedido
    MAX_GIRO = 15.0     # s como máximo en un mismo giro
    ALEJARSE = 0.3      # m: caminando, más lejos que esto de lo más cerca que estuvo es un freno
    TRAMO = 0.4         # m caminados entre una comprobación de dirección y la siguiente
    DESVIO = math.radians(50)      # avanzar más desviado que esto de donde cree mirar es un freno
    SALTO = 0.5         # m entre dos lecturas seguidas (cada ~0.1 s) es un salto de la odometría

    def __init__(self, x, y, tolerancia=0.35, avance=0.2):
        self.x, self.y, self.tolerancia, self.avance = x, y, tolerancia, avance
        self.fase = 'girar'
        self.arco = False       # MC no giró en el sitio: se gira avanzando
        self._giro = None       # (t, yaw, sentido) al empezar a girar
        self._comprobado = False  # ya se comprobó que gira hacia el lado pedido
        self._d_giro = 0.0      # distancia al destino al empezar a girar
        self._antes = None      # última posición, para notar saltos
        self._tramo = None      # (x, y) donde empezó el tramo que se está caminando
        self._cerca = math.inf

    def _freno(self, motivo):
        return Orden(fin='freno', motivo=motivo)

    def paso(self, t, px, py, yaw):
        """La orden para este momento (se llama unas 10 veces por segundo)."""
        if self._antes and math.hypot(px - self._antes[0], py - self._antes[1]) > self.SALTO:
            salto = math.hypot(px - self._antes[0], py - self._antes[1])
            return self._freno(f'la posición del robot saltó {salto:.1f} m (odometría poco confiable)')
        self._antes = (px, py)
        d = math.hypot(self.x - px, self.y - py)
        if d < self.tolerancia:
            return Orden(fin='llegó')
        error = normalizar(math.atan2(self.y - py, self.x - px) - yaw)

        if self.fase == 'caminar':
            if abs(error) > self.REALINEAR:
                self.fase, self._giro = 'girar', None
            else:
                if d > self._cerca + self.ALEJARSE:
                    return self._freno(f'se está alejando del destino ({d:.1f} m)')
                self._cerca = min(self._cerca, d)
                # Lo que avanzó en el último tramo tiene que ir hacia donde cree mirar
                avanzado = math.hypot(px - self._tramo[0], py - self._tramo[1])
                if avanzado >= self.TRAMO:
                    hacia = math.atan2(py - self._tramo[1], px - self._tramo[0])
                    if abs(normalizar(hacia - yaw)) > self.DESVIO:
                        return self._freno(f'avanza hacia {math.degrees(hacia):.0f}° pero cree mirar a '
                                           f'{math.degrees(yaw):.0f}° (orientación mal calculada)')
                    self._tramo = (px, py)
                giro = max(-self.GIRO_CAMINANDO, min(self.GIRO_CAMINANDO, 1.0 * error))
                return Orden(self.avance, giro if abs(giro) >= 0.1 else 0.0)

        # Girar hacia el destino: en el sitio, o avanzando si MC no gira quieto
        if abs(error) < self.ALINEADO:
            self.fase, self._giro, self._tramo, self._cerca = 'caminar', None, (px, py), d
            return Orden(self.avance, 0.0)
        # El sentido se decide al empezar el giro y se mantiene: con el destino casi detrás, el error cambia de signo
        # con el ruido y el robot no debe dudar entre izquierda y derecha
        deseado = 1.0 if error > 0 else -1.0
        if self._giro is None or (deseado != self._giro[2] and abs(error) < math.radians(90)):
            self._giro, self._comprobado, self._d_giro = (t, yaw, deseado), False, d
        t0, yaw0, sentido = self._giro
        if not self._comprobado and t - t0 >= self.PRUEBA_GIRO:
            self._comprobado = True
            girado = normalizar(yaw - yaw0) * sentido
            if girado < -math.radians(10):
                return self._freno(f'gira al revés de lo pedido ({math.degrees(girado):.0f}° en {t - t0:.1f} s)')
            if girado < math.radians(5):
                if self.arco:
                    return self._freno('no logra girar')
                self.arco, self._giro = True, None  # MC no gira quieto: se intenta girando mientras avanza
                return Orden(self.avance, sentido * self.GIRO_ARCO)
        if t - t0 > self.MAX_GIRO:
            return self._freno('no termina de girar')
        if d > self._d_giro + (0.6 if self.arco else 0.3):
            return self._freno(f'se desplaza al girar ({d:.1f} m del destino)')
        return Orden(self.avance, sentido * self.GIRO_ARCO) if self.arco else Orden(0.0, sentido * self.GIRO)
