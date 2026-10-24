"""Texturas del lobby de MuJoCo, hechas con Python puro (sin descargas ni librerías): mármol, maderas, telas, alfombras,
cuadros, el logo del club y los letreros de cada lugar.

escena.py llama a generar(); los PNG quedan en la carpeta del modelo (model_info/nclub) y solo se rehacen si falta
alguno o cambia VERSION. Los letreros se rehacen siempre, porque dependen de los nombres y colores de destinos.json.
"""

import math
import random
import struct
import zlib

VERSION = '1'  # súbelo al cambiar un generador para que se rehagan las texturas guardadas


# ---------- PNG, ruido y lienzo ----------

def guardar_png(ruta, ancho, alto, pix):
    """pix: RGB de 8 bits, fila de arriba primero."""
    paso = ancho * 3
    crudo = b''.join(b'\x00' + bytes(pix[y * paso:(y + 1) * paso]) for y in range(alto))

    def trozo(tipo, datos):
        return struct.pack('>I', len(datos)) + tipo + datos + struct.pack('>I', zlib.crc32(tipo + datos) & 0xffffffff)
    ruta.write_bytes(b'\x89PNG\r\n\x1a\n' + trozo(b'IHDR', struct.pack('>IIBBBBB', ancho, alto, 8, 2, 0, 0, 0))
                     + trozo(b'IDAT', zlib.compress(crudo, 6)) + trozo(b'IEND', b''))


def _bytes(valores):
    return bytes(0 if v < 0 else 255 if v > 255 else int(v) for v in valores)


def ruido(ancho, alto, cx, cy, semilla):
    """Ruido de valor en [0, 1] con cx × cy celdas; es periódico, así que la textura se repite sin costuras."""
    cx, cy = min(cx, ancho), min(cy, alto)
    rnd = random.Random(semilla)
    red = [[rnd.random() for _ in range(cx)] for _ in range(cy)]
    cols = []
    for x in range(ancho):
        f = x * cx / ancho
        i = int(f)
        t = f - i
        cols.append((i % cx, (i + 1) % cx, t * t * (3 - 2 * t)))
    out = []
    for y in range(alto):
        f = y * cy / alto
        j = int(f)
        t = f - j
        t = t * t * (3 - 2 * t)
        fila = [a + (b - a) * t for a, b in zip(red[j % cy], red[(j + 1) % cy])]
        out.extend([fila[i0] + (fila[i1] - fila[i0]) * tx for i0, i1, tx in cols])
    return out


def fbm(ancho, alto, cx, cy, octavas, semilla):
    """Suma de octavas de ruido (cada una el doble de fina y la mitad de fuerte), normalizada a [0, 1]."""
    total, amp, suma = [0.0] * (ancho * alto), 1.0, 0.0
    for o in range(octavas):
        total = [a + b * amp for a, b in zip(total, ruido(ancho, alto, cx << o, cy << o, semilla + 31 * o))]
        suma += amp
        amp *= 0.5
    return [a / suma for a in total]


class Lienzo:
    def __init__(self, ancho, alto, color):
        self.w, self.h = ancho, alto
        self.pix = bytearray(bytes(color) * (ancho * alto))

    def mezclar(self, x, y, color, a):
        if 0 <= x < self.w and 0 <= y < self.h and a > 0:
            k = (y * self.w + x) * 3
            for c in range(3):
                self.pix[k + c] = int(self.pix[k + c] * (1 - a) + color[c] * a)

    def rect(self, x0, y0, x1, y1, color, a=1.0):
        x0, x1 = max(0, int(x0)), min(self.w, int(x1))
        for y in range(max(0, int(y0)), min(self.h, int(y1))):
            if a >= 1:
                self.pix[(y * self.w + x0) * 3:(y * self.w + x1) * 3] = bytes(color) * (x1 - x0)
            else:
                for x in range(x0, x1):
                    self.mezclar(x, y, color, a)

    def disco(self, cx, cy, r, color, r_hueco=0.0):
        """Círculo (o anillo, si r_hueco > 0) con borde suavizado."""
        for y in range(max(0, int(cy - r - 1)), min(self.h, int(cy + r + 2))):
            for x in range(max(0, int(cx - r - 1)), min(self.w, int(cx + r + 2))):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                a = min(1.0, max(0.0, r - d + 0.5))
                if r_hueco:
                    a = min(a, max(0.0, min(1.0, d - r_hueco + 0.5)))
                self.mezclar(x, y, color, a)

    def guardar(self, ruta):
        guardar_png(ruta, self.w, self.h, self.pix)


# ---------- Letra de bloques (5 × 7) para letreros y logo ----------

LETRAS = {
    'A': '01110 10001 10001 11111 10001 10001 10001', 'B': '11110 10001 10001 11110 10001 10001 11110',
    'C': '01110 10001 10000 10000 10000 10001 01110', 'D': '11110 10001 10001 10001 10001 10001 11110',
    'E': '11111 10000 10000 11110 10000 10000 11111', 'F': '11111 10000 10000 11110 10000 10000 10000',
    'G': '01110 10001 10000 10111 10001 10001 01111', 'H': '10001 10001 10001 11111 10001 10001 10001',
    'I': '01110 00100 00100 00100 00100 00100 01110', 'J': '00111 00010 00010 00010 00010 10010 01100',
    'K': '10001 10010 10100 11000 10100 10010 10001', 'L': '10000 10000 10000 10000 10000 10000 11111',
    'M': '10001 11011 10101 10101 10001 10001 10001', 'N': '10001 10001 11001 10101 10011 10001 10001',
    'O': '01110 10001 10001 10001 10001 10001 01110', 'P': '11110 10001 10001 11110 10000 10000 10000',
    'Q': '01110 10001 10001 10001 10101 10010 01101', 'R': '11110 10001 10001 11110 10100 10010 10001',
    'S': '01111 10000 10000 01110 00001 00001 11110', 'T': '11111 00100 00100 00100 00100 00100 00100',
    'U': '10001 10001 10001 10001 10001 10001 01110', 'V': '10001 10001 10001 10001 10001 01010 00100',
    'W': '10001 10001 10001 10101 10101 10101 01010', 'X': '10001 10001 01010 00100 01010 10001 10001',
    'Y': '10001 10001 01010 00100 00100 00100 00100', 'Z': '11111 00001 00010 00100 01000 10000 11111',
    '0': '01110 10001 10011 10101 11001 10001 01110', '1': '00100 01100 00100 00100 00100 00100 01110',
    '2': '01110 10001 00001 00010 00100 01000 11111', '3': '11111 00010 00100 00010 00001 10001 01110',
    '4': '00010 00110 01010 10010 11111 00010 00010', '5': '11111 10000 11110 00001 00001 10001 01110',
    '6': '00110 01000 10000 11110 10001 10001 01110', '7': '11111 00001 00010 00100 01000 01000 01000',
    '8': '01110 10001 10001 01110 10001 10001 01110', '9': '01110 10001 10001 01111 00001 00010 01100',
    '-': '00000 00000 00000 11111 00000 00000 00000', '.': '00000 00000 00000 00000 00000 01100 01100',
    '&': '01100 10010 10100 01000 10101 10010 01101', ' ': '00000 00000 00000 00000 00000 00000 00000',
}
ACENTOS = {'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U', 'Ü': 'U', 'Ñ': 'N'}


def _filas(letra):
    """Las 9 filas de una letra: 2 para el acento o la virgulilla y 7 para la letra."""
    base = LETRAS.get(ACENTOS.get(letra, letra), LETRAS[' ']).split()
    if letra == 'Ñ':
        arriba = ['01101', '10110']
    elif letra in ACENTOS:
        arriba = ['00011', '00110']
    else:
        arriba = ['00000', '00000']
    return arriba + base


def escribir(lienzo, texto, cx, cy, escala, color, sombra=None, espacio=1):
    """Escribe texto centrado en (cx, cy) con celdas de `escala` píxeles; `sombra` dibuja antes un relieve oscuro."""
    texto = texto.upper()
    ancho = (len(texto) * (5 + espacio) - espacio) * escala
    x0, y0 = int(cx - ancho / 2), int(cy - 9 * escala / 2)
    if sombra:
        d = max(1, escala // 3)
        _escribir(lienzo, texto, x0 + d, y0 + d, escala, sombra, espacio)
    _escribir(lienzo, texto, x0, y0, escala, color, espacio)


def _escribir(lienzo, texto, x0, y0, escala, color, espacio):
    for n, letra in enumerate(texto):
        filas = _filas(letra)

        def lleno(f, c):
            return 0 <= f < 9 and 0 <= c < 5 and filas[f][c] == '1'
        for fila in range(9):
            for col in range(5):
                x = x0 + (n * (5 + espacio) + col) * escala
                y = y0 + fila * escala
                if lleno(fila, col):
                    lienzo.rect(x, y, x + escala, y + escala, color)
                    continue
                # Suaviza las diagonales: rellena medio cuadro en la esquina entre dos vecinos llenos
                for df, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
                    if lleno(fila + df, col) and lleno(fila, col + dc) and not lleno(fila + df, col + dc):
                        for py in range(escala):
                            for px in range(escala):
                                a = (px if dc < 0 else escala - 1 - px) + (py if df < 0 else escala - 1 - py)
                                if a < escala - 1:
                                    lienzo.mezclar(x + px, y + py, color, 1.0)


def partir(nombre, max_lineas=2):
    """Parte el nombre en líneas lo más parejas posible (por palabras)."""
    palabras = nombre.upper().split()
    if len(palabras) < 2 or max_lineas < 2:
        return [nombre.upper()]
    mejor = None
    for corte in range(1, len(palabras)):
        lineas = [' '.join(palabras[:corte]), ' '.join(palabras[corte:])]
        largo = max(map(len, lineas))
        if mejor is None or largo < mejor[0]:
            mejor = (largo, lineas)
    return mejor[1] if mejor[0] < len(nombre) - 2 else [nombre.upper()]


# ---------- Superficies ----------

def marmol(n=512):
    """Cuatro baldosas de mármol crema con vetas (la textura cubre 2 × 2 baldosas)."""
    turb, nube = fbm(n, n, 3, 3, 5, 11), fbm(n, n, 6, 6, 3, 12)
    rnd = random.Random(5)
    fases = [rnd.uniform(0, 6.3) for _ in range(4)]
    medio, k, out = n // 2, 2 * math.pi / n, []
    for y in range(n):
        for x in range(n):
            if x % medio < 2 or y % medio < 2:
                out += (196, 188, 176)
                continue
            i, f = y * n + x, fases[(y >= medio) * 2 + (x >= medio)]
            t = turb[i]
            v1 = 1 - abs(math.sin((x * 0.8 + y * 0.45) * k * 1.4 + t * 9 + f))
            v2 = 1 - abs(math.sin((x * 0.35 - y * 0.9) * k * 2.3 + t * 7 + f * 1.7))
            vena = v1 ** 14 * 0.5 + v2 ** 26 * 0.35
            b = 1 - 0.07 * nube[i] - (0.025 if x % medio < 4 or y % medio < 4 else 0)
            out += (243 * b - 100 * vena, 236 * b - 98 * vena, 224 * b - 96 * vena)
    return n, n, _bytes(out)


def madera(n=256, vertical=False):
    """Veta de madera clara (se tiñe con el color del material). La veta corre a lo largo de x, o de y si vertical."""
    vet = fbm(n, n, *((6, 2) if vertical else (2, 6)), 4, 21)
    fino = ruido(n, n, *((64, 4) if vertical else (4, 64)), 22)
    out = []
    for y in range(n):
        for x in range(n):
            i = y * n + x
            anillo = ((x if vertical else y) / n * 16 + vet[i] * 2.0) % 1.0
            banda = (0.5 + 0.5 * math.sin(2 * math.pi * anillo)) ** 3
            f = fino[i]
            out += (224 - 72 * banda - 34 * f, 182 - 64 * banda - 28 * f, 134 - 50 * banda - 22 * f)
    return n, n, _bytes(out)


def listones(n=256):
    """Listones verticales de madera con ranuras oscuras (frente de la recepción, biombo)."""
    w, h, pix = madera(n, vertical=True)
    out = bytearray(pix)
    for y in range(n):
        for x in range(n):
            if x % 32 < 3:
                k = (y * n + x) * 3
                out[k:k + 3] = bytes((46, 34, 26))
            elif x % 32 == 3 or x % 32 == 31:
                k = (y * n + x) * 3
                out[k:k + 3] = bytes(int(c * 0.82) for c in out[k:k + 3])
    return n, n, bytes(out)


def tablas(n=512, filas=12, semilla=31):
    """Tablas de madera con juntas y tonos distintos (deck de la terraza, piso del restaurante)."""
    rnd = random.Random(semilla)
    vet, fino = fbm(n, n, 2, 24, 3, 32), ruido(n, n, 4, 96, 33)
    alto_f = n / filas
    out = []
    for y in range(n):
        f = int(y / alto_f)
        if y - f * alto_f < 2:
            out += (52, 40, 30) * n
            continue
        r = random.Random(semilla * 100 + f)
        x0 = r.randrange(n)
        cortes = sorted({x0, (x0 + n // 2 + r.randrange(-70, 70)) % n})
        tintes = [r.uniform(0.86, 1.08) for _ in cortes]
        for x in range(n):
            if any(abs(x - c) < 2 for c in cortes):
                out += (52, 40, 30)
                continue
            seg = sum(1 for c in cortes if c <= x) % len(cortes)
            i = y * n + x
            anillo = (y / alto_f * 1.7 + vet[i] * 2.5 + f * 0.37) % 1.0
            banda = (0.5 + 0.5 * math.sin(2 * math.pi * anillo)) ** 3
            t = tintes[seg] * (1 - 0.05 * rnd.random())
            out += ((222 - 70 * banda - 32 * fino[i]) * t, (180 - 62 * banda - 26 * fino[i]) * t,
                    (132 - 48 * banda - 20 * fino[i]) * t)
    return n, n, _bytes(out)


def tela(n=256):
    """Tejido claro tipo sarga (se tiñe con el color del material)."""
    fino, medio = ruido(n, n, 64, 64, 41), fbm(n, n, 8, 8, 2, 42)
    out = []
    for y in range(n):
        for x in range(n):
            i = y * n + x
            v = 0.84 + 0.045 * (((x + y) % 6) < 3) - 0.035 * ((x % 2) ^ (y % 2)) + 0.07 * (fino[i] - 0.5) \
                + 0.05 * (medio[i] - 0.5)
            out += (250 * v, 248 * v, 244 * v)
    return n, n, _bytes(out)


def cuero(n=256):
    """Cuero con manchas suaves, poros y pliegues."""
    m, poros, pliegue = fbm(n, n, 6, 6, 4, 51), ruido(n, n, 128, 128, 52), fbm(n, n, 5, 5, 3, 53)
    out = []
    for i in range(n * n):
        v = 0.8 + 0.14 * m[i] - (0.07 if poros[i] > 0.9 else 0) - (0.06 if abs(pliegue[i] - 0.5) < 0.008 else 0)
        out += (250 * v, 246 * v, 240 * v)
    return n, n, _bytes(out)


def piedra(n=512, por_lado=4, semilla=61):
    """Baldosas de piedra con nubes y juntas claras (spa, vestier)."""
    nube, fino = fbm(n, n, 6, 6, 4, semilla), ruido(n, n, 128, 128, semilla + 1)
    rnd = random.Random(semilla)
    lado = n // por_lado
    tonos = [rnd.uniform(0.9, 1.05) for _ in range(por_lado * por_lado)]
    out = []
    for y in range(n):
        for x in range(n):
            if x % lado < 3 or y % lado < 3:
                out += (226, 224, 218)
                continue
            i = y * n + x
            t = tonos[(y // lado) * por_lado + x // lado] * (0.88 + 0.16 * nube[i] + 0.05 * (fino[i] - 0.5))
            out += (226 * t, 228 * t, 226 * t)
    return n, n, _bytes(out)


def concreto(n=256):
    nube, grano = fbm(n, n, 4, 4, 5, 71), ruido(n, n, 256, 256, 72)
    out = []
    for i in range(n * n):
        v = 150 + 38 * nube[i] + 16 * (grano[i] - 0.5) - (30 if grano[i] > 0.97 else 0)
        out += (v, v * 0.99, v * 0.97)
    return n, n, _bytes(out)


def caucho(n=256):
    """Piso de caucho de gimnasio: negro con motas de colores y juntas cada media textura."""
    motas, nube = ruido(n, n, 256, 256, 81), fbm(n, n, 4, 4, 3, 82)
    rnd = random.Random(83)
    colores = [(70, 95, 150), (120, 120, 125), (90, 90, 95)]
    out = []
    for y in range(n):
        for x in range(n):
            if x % (n // 2) < 2 or y % (n // 2) < 2:
                out += (22, 22, 24)
                continue
            i = y * n + x
            if motas[i] > 0.93:
                out += colores[int(motas[i] * 1000) % 3]
            else:
                v = 38 + 10 * nube[i] + rnd.uniform(-4, 4)
                out += (v, v, v * 1.04)
    return n, n, _bytes(out)


def cesped(n=256):
    nube, fino = fbm(n, n, 6, 6, 4, 91), ruido(n, n, 256, 256, 92)
    out = []
    for i in range(n * n):
        v = 0.75 + 0.35 * nube[i] + 0.3 * (fino[i] - 0.5)
        out += (72 * v, 122 * v, 52 * v)
    return n, n, _bytes(out)


def seto(n=256):
    """Follaje denso para setos: verdes oscuros con hojas iluminadas."""
    nube, fino = fbm(n, n, 8, 8, 4, 95), ruido(n, n, 96, 96, 96)
    out = []
    for i in range(n * n):
        v = 0.55 + 0.45 * nube[i] + (0.35 if fino[i] > 0.8 else 0) - (0.25 if fino[i] < 0.15 else 0)
        out += (46 * v, 92 * v, 44 * v)
    return n, n, _bytes(out)


def adoquin(n=256):
    """Adoquines en hilera trabada (la textura cubre 4 hileras de 2 adoquines)."""
    nube = fbm(n, n, 8, 8, 3, 101)
    rnd = random.Random(102)
    alto, largo = n // 4, n // 2
    tonos = {}
    out = []
    for y in range(n):
        fila = y // alto
        desp = (largo // 2) * (fila % 2)
        for x in range(n):
            xx = (x + desp) % n
            if y % alto < 3 or xx % largo < 3:
                out += (118, 112, 104)
                continue
            clave = (fila, xx // largo)
            if clave not in tonos:
                tonos[clave] = rnd.uniform(0.85, 1.08)
            t = tonos[clave] * (0.9 + 0.14 * nube[y * n + x])
            out += (184 * t, 176 * t, 162 * t)
    return n, n, _bytes(out)


def pared(n=256):
    """Estuco claro, casi liso."""
    nube = fbm(n, n, 8, 8, 4, 111)
    out = []
    for i in range(n * n):
        v = 0.95 + 0.05 * nube[i]
        out += (250 * v, 246 * v, 238 * v)
    return n, n, _bytes(out)


def carton(n=256):
    """Cartón corrugado con una cinta al centro (se ve en la tapa de las cajas)."""
    nube = fbm(n, n, 6, 6, 3, 121)
    out = []
    for y in range(n):
        for x in range(n):
            v = 0.9 + 0.12 * nube[y * n + x] + 0.03 * math.sin(x * 0.8)
            if abs(y - n / 2) < n * 0.09:
                out += (214 * v, 190 * v, 140 * v)
            else:
                out += (188 * v, 146 * v, 98 * v)
    return n, n, _bytes(out)


def peligro(n=128):
    """Franjas diagonales amarillas y negras (piso frente al acceso de servicio)."""
    out = []
    for y in range(n):
        for x in range(n):
            out += (232, 186, 40) if ((x + y) // (n // 4)) % 2 == 0 else (32, 32, 34)
    return n, n, bytes(out)


def casillero(n=256):
    """Puerta de casillero metálico: marco, rejilla de ventilación, manija y placa."""
    rayado = ruido(n, n, 4, 128, 131)
    out = []
    for y in range(n):
        for x in range(n):
            v = 0.92 + 0.08 * rayado[y * n + x]
            c = (200 * v, 206 * v, 214 * v)
            if x < 8 or x > n - 9 or y < 8 or y > n - 9:
                c = (120, 126, 136)
            elif 70 <= x <= 186 and 30 <= y <= 120 and (y - 30) % 15 < 7:
                c = (70, 76, 86)
            elif 206 <= x <= 220 and 112 <= y <= 168:
                c = (236, 238, 242) if x < 213 else (160, 164, 172)
            elif 104 <= x <= 152 and 190 <= y <= 214:
                c = (196, 164, 96)
            out += c
    return n, n, _bytes(out)


# ---------- Alfombras ----------

def alfombra_persa(n=512):
    """Alfombra persa: guardas azul y oro, campo vino con celosía y medallón central."""
    lana = fbm(n, n, 64, 64, 2, 141)
    out = []
    for y in range(n):
        for x in range(n):
            u, v = (x + 0.5) / (n / 2) - 1, (y + 0.5) / (n / 2) - 1
            b = max(abs(u), abs(v))
            if b > 0.94:
                c = (30, 34, 62)
            elif b > 0.92 or 0.78 < b <= 0.80:
                c = (200, 160, 90)
            elif b > 0.80:
                s = (u if abs(v) > abs(u) else v) * 9
                motivo = abs((s % 1.0) - 0.5) * 2 + abs((b - 0.86) / 0.06)
                c = (206, 170, 102) if motivo < 0.75 else (150, 32, 42) if motivo < 1.05 else (40, 42, 74)
            else:
                e = (u / 0.52) ** 2 + (v / 0.36) ** 2
                ang = math.atan2(v, u)
                petalo = 0.78 + 0.16 * math.cos(8 * ang)
                esquina = math.hypot(abs(u) - 0.78, abs(v) - 0.78)
                if e < 0.12:
                    c = (34, 40, 76) if e < 0.04 else (210, 172, 100)
                elif e < 0.42:
                    c = (232, 216, 178) if abs(math.cos(6 * ang)) > 0.85 else (36, 42, 80)
                elif e < 0.5:
                    c = (206, 166, 96)
                elif e < petalo:
                    c = (178, 46, 52) if math.cos(16 * ang) > 0 else (156, 34, 44)
                elif esquina < 0.3:
                    c = (36, 42, 80) if esquina < 0.26 else (206, 166, 96)
                else:
                    red = min(abs(((u + v) * 4) % 1.0 - 0.5), abs(((u - v) * 4) % 1.0 - 0.5))
                    nodo = math.hypot(((u * 4) % 1.0) - 0.5, ((v * 4) % 1.0) - 0.5)
                    c = (224, 196, 140) if nodo < 0.1 else (100, 20, 30) if red < 0.035 else (128, 28, 38)
            w = 0.88 + 0.16 * lana[y * n + x]
            out += (c[0] * w, c[1] * w, c[2] * w)
    return n, n, _bytes(out)


def alfombra_moderna(n=512):
    """Alfombra tipo bereber: lana crema con rombos irregulares en gris carbón y una guarda salvia."""
    lana, temblor = fbm(n, n, 64, 64, 2, 151), fbm(n, n, 4, 4, 3, 152)
    out = []
    for y in range(n):
        for x in range(n):
            u, v = (x + 0.5) / (n / 2) - 1, (y + 0.5) / (n / 2) - 1
            i = y * n + x
            w = 0.9 + 0.14 * lana[i]
            if max(abs(u), abs(v)) > 0.93:
                c = (128, 150, 128)
            else:
                t = (temblor[i] - 0.5) * 0.12
                d1 = abs(((u + v) * 2.2 + t) % 1.0 - 0.5)
                d2 = abs(((u - v) * 2.2 - t) % 1.0 - 0.5)
                c = (62, 62, 64) if max(d1, d2) > 0.465 else (236, 230, 216)
            out += (c[0] * w, c[1] * w, c[2] * w)
    return n, n, _bytes(out)


# ---------- Logo, medallones y cuadros ----------

DORADO, AZUL_NOCHE = (214, 178, 106), (22, 32, 54)


def logo(ancho=512, alto=256):
    lz = Lienzo(ancho, alto, AZUL_NOCHE)
    lz.rect(0, 0, ancho, 10, (14, 20, 36))
    lz.rect(0, alto - 10, ancho, alto, (14, 20, 36))
    lz.disco(104, alto / 2, 76, DORADO, r_hueco=69)
    escribir(lz, 'N', 104, alto / 2 - 9, 9, DORADO)
    escribir(lz, 'CLUB', 340, alto / 2 - 30, 11, DORADO)
    lz.rect(214, alto / 2 + 36, 466, alto / 2 + 39, DORADO)
    escribir(lz, 'BIENVENIDOS', 340, alto / 2 + 58, 3, (236, 226, 200))
    return ancho, alto, lz.pix


def medallon(n=512):
    """Rosa de los vientos de mármol para el piso de la entrada (se ve dentro del círculo)."""
    out = []
    for y in range(n):
        for x in range(n):
            u, v = (x + 0.5) / (n / 2) - 1, (y + 0.5) / (n / 2) - 1
            r, ang = math.hypot(u, v), math.atan2(v, u)
            f = (ang / (2 * math.pi) * 8) % 1.0
            punta = 0.22 + 0.68 * (1 - abs(f - 0.5) * 2)
            f2 = ((ang / (2 * math.pi) * 8) + 0.5) % 1.0
            punta2 = 0.22 + 0.4 * (1 - abs(f2 - 0.5) * 2)
            if r > 0.96:
                c = (40, 46, 52)
            elif r > 0.92:
                c = DORADO
            elif r < 0.1:
                c = DORADO
            elif r < punta:
                c = (44, 52, 60) if f < 0.5 else (232, 224, 210)
            elif r < punta2:
                c = (196, 160, 96) if f2 < 0.5 else (150, 118, 66)
            elif 0.66 < r < 0.68:
                c = (44, 52, 60)
            else:
                c = (222, 212, 194)
            out += c
    return n, n, bytes(out)


def puesto(n=256):
    """Marca del puesto del robot: piso oscuro con un anillo de bronce."""
    lz = Lienzo(n, n, (196, 188, 176))
    lz.disco(n / 2, n / 2, n / 2 - 2, (48, 52, 58))
    lz.disco(n / 2, n / 2, n / 2 - 10, DORADO, r_hueco=n / 2 - 16)
    lz.disco(n / 2, n / 2, n / 2 - 30, (64, 70, 78), r_hueco=n / 2 - 32)
    return n, n, lz.pix


def cuadro_atardecer(ancho=256, alto=320):
    out = []
    capas = [(0.62, 16, 0.031, (122, 78, 116)), (0.7, 22, 0.022, (84, 60, 104)), (0.8, 14, 0.04, (46, 40, 76))]
    for y in range(alto):
        for x in range(ancho):
            t = y / alto
            c = (250 - 30 * t, 196 - 120 * t, 120 - 20 * t)
            if math.hypot(x - ancho * 0.62, y - alto * 0.48) < ancho * 0.11:
                c = (255, 232, 180)
            for base, amp, frec, color in capas:
                cresta = alto * base + amp * math.sin(x * frec + base * 10) + amp * 0.5 * math.sin(x * frec * 2.7)
                if y > cresta:
                    c = color
            out += c
    return ancho, alto, _bytes(out)


def cuadro_campos(ancho=256, alto=320):
    """Campos de color al estilo Rothko."""
    borde = fbm(ancho, alto, 8, 8, 3, 161)
    out = []
    for y in range(alto):
        for x in range(ancho):
            b = (borde[y * ancho + x] - 0.5) * 10
            c = (128, 34, 40)
            if 22 + b < x < ancho - 22 - b and alto * 0.08 + b < y < alto * 0.46 - b:
                c = (226, 128, 62)
            elif 22 + b < x < ancho - 22 - b and alto * 0.54 + b < y < alto * 0.92 - b:
                c = (78, 20, 34)
            w = 0.94 + 0.08 * borde[y * ancho + x]
            out += (c[0] * w, c[1] * w, c[2] * w)
    return ancho, alto, _bytes(out)


def cuadro_geometrico(ancho=256, alto=320):
    """Composición de mediados de siglo: círculos y arcos sobre crema."""
    lz = Lienzo(ancho, alto, (236, 226, 204))
    lz.disco(ancho * 0.38, alto * 0.34, 74, (200, 98, 66))
    lz.disco(ancho * 0.66, alto * 0.7, 88, (128, 158, 128), r_hueco=60)
    lz.disco(ancho * 0.3, alto * 0.78, 40, (222, 172, 64))
    lz.rect(ancho * 0.12, alto * 0.55, ancho * 0.9, alto * 0.55 + 4, (34, 44, 70))
    lz.disco(ancho * 0.78, alto * 0.22, 18, (34, 44, 70))
    return ancho, alto, lz.pix


def letrero(nombre, color, ancho=512, alto=320):
    """Letrero de un lugar: su nombre en blanco sobre su color (el mismo del mapa de PIBOT)."""
    c = [int(255 * v) for v in color[:3]]
    lz = Lienzo(ancho, alto, c)
    for y in range(alto):  # degradado suave: más claro arriba
        k = 1.12 - 0.22 * y / alto
        lz.rect(0, y, ancho, y + 1, [min(255, int(v * k)) for v in c])
    claro = [min(255, int(v + (255 - v) * 0.55)) for v in c]
    for x0, y0, x1, y1 in [(18, 18, ancho - 18, 22), (18, alto - 22, ancho - 18, alto - 18),
                           (18, 18, 22, alto - 18), (ancho - 22, 18, ancho - 18, alto - 18)]:
        lz.rect(x0, y0, x1, y1, claro)
    lineas = partir(nombre)
    cols = max(len(l) for l in lineas) * 6 - 1
    filas = len(lineas) * 9 + (len(lineas) - 1) * 3
    escala = max(2, int(min((ancho - 80) / cols, (alto - 90) / filas)))
    sombra = [int(v * 0.6) for v in c]
    alto_linea = 12 * escala
    y = alto / 2 - (len(lineas) - 1) * alto_linea / 2
    for linea in lineas:
        escribir(lz, linea, ancho / 2, y, escala, (252, 250, 244), sombra=sombra)
        y += alto_linea
    return ancho, alto, lz.pix


FIJAS = {
    'marmol': marmol, 'madera': madera, 'listones': listones, 'tablas': tablas, 'tela': tela, 'cuero': cuero,
    'piedra': piedra, 'concreto': concreto, 'caucho': caucho, 'cesped': cesped, 'seto': seto,
    'adoquin': adoquin, 'pared': pared, 'carton': carton, 'peligro': peligro, 'casillero': casillero,
    'alfombra_persa': alfombra_persa, 'alfombra_moderna': alfombra_moderna, 'logo': logo, 'medallon': medallon,
    'puesto': puesto, 'cuadro_atardecer': cuadro_atardecer, 'cuadro_campos': cuadro_campos,
    'cuadro_geometrico': cuadro_geometrico,
}


def generar(carpeta, letreros):
    """Escribe las texturas en `carpeta`. letreros: [(archivo, nombre, color)]. Devuelve cuántas fijas rehízo."""
    carpeta.mkdir(parents=True, exist_ok=True)
    marca = carpeta / 'VERSION'
    vigente = marca.exists() and marca.read_text().strip() == VERSION
    hechas = 0
    for nombre, fn in FIJAS.items():
        ruta = carpeta / f'{nombre}.png'
        if vigente and ruta.exists():
            continue
        guardar_png(ruta, *fn())
        hechas += 1
    marca.write_text(VERSION + '\n')
    usados = set()
    for archivo, nombre, color in letreros:
        guardar_png(carpeta / archivo, *letrero(nombre, color))
        usados.add(archivo)
    for viejo in carpeta.glob('letrero_*.png'):
        if viejo.name not in usados:
            viejo.unlink()
    return hechas
