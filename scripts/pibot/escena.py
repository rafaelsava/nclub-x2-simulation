#!/usr/bin/env python3
"""Arma en MuJoCo el lobby del club a partir de destinos.json: arquitectura, luz, texturas y los muebles de cada lugar.

    python3 scripts/pibot/escena.py      (o ./x2 escena; luego reiniciar ./x2 sim para verlo)

Reescribe solo dos bloques de la escena del X2: "inicio/fin texturas" (cielo, luz de ambiente, texturas y
materiales) y "inicio/fin destinos" (todo lo que se ve). Las texturas las hace texturas.py en model_info/nclub.
Fuera de los bloques cambia una sola cosa: el material "groundplane" del piso infinito del simulador pasa a ser
pasto sin reflejo (cada superficie con reflejo vuelve a dibujar toda la escena y el lobby tiene ~750 piezas).

Cada lugar se ambienta según su "ambiente" en destinos.json (vip, social, terraza, restaurante, gimnasio, spa,
servicio, vestier); si no tiene o no se reconoce, se adivina por el nombre, y si tampoco, lleva un rincón genérico.
Los muebles se ponen *más allá* del punto del lugar, mirando desde recepción: el robot camina en línea recta y no
esquiva obstáculos. Antes de escribir se revisa que nada por debajo de su cabeza quede en sus caminos (ida, vuelta al
punto detrás del puesto y llegada al puesto); lo que estorbe se quita y se avisa. Todo es solo visual (sin colisión).
"""

import json
import math
import random
import re
import sys
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import texturas  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent.parent
ESCENA = RAIZ / 'sim_mujoco/configuration/robot/lx2501_3_t2d5/model_info/scene.xml'
CARPETA_TEX = 'nclub'  # junto a scene.xml
DESTINOS = Path(__file__).parent / 'destinos.json'
BLOQUE = re.compile(r'(    <!-- inicio destinos[^\n]*-->\n).*?(    <!-- fin destinos -->\n)', re.S)
BLOQUE_TEX = re.compile(r'(  <!-- inicio texturas[^\n]*-->\n).*?(  <!-- fin texturas -->\n)', re.S)
PISO_SIM = re.compile(r'<material name="groundplane"[^>]*/>')
PISO_PASTO = '<material name="groundplane" texture="cesped" texuniform="true" texrepeat="0.62 0.62" reflectance="0"/>'
MARCAS_TEX = ('  <!-- inicio texturas (generado por scripts/pibot/escena.py; no editar a mano) -->\n'
              '  <!-- fin texturas -->\n')

# El robot (robot.py): se detiene a 0.35 m del punto, vuelve a un punto 1.2 m detrás del puesto y de ahí al puesto
CABEZA, MEDIO_ANCHO, MARGEN, PARADA, ATRAS = 1.35, 0.3, 0.1, 0.35, 1.2
ALTO_PARED = 2.5

# nombre: (textura, metros que cubre una repetición o None = una vez por cara, rgba, specular, shininess,
#          reflectance, emission)
MATERIALES = {
    'marmol_piso': ('marmol', 1.2, (1, 1, 1, 1), 0.75, 0.8, 0, 0),
    'marmol_blanco': ('marmol', 0.8, (1, 1, 1, 1), 0.7, 0.8, 0, 0),
    'roble': ('madera', 0.7, (1, 0.96, 0.9, 1), 0.3, 0.3, 0, 0),
    'nogal': ('madera', 0.7, (0.6, 0.45, 0.36, 1), 0.35, 0.45, 0, 0),
    'wengue': ('madera', 0.7, (0.4, 0.31, 0.26, 1), 0.4, 0.5, 0, 0),
    'listones_nogal': ('listones', 0.6, (0.62, 0.47, 0.37, 1), 0.3, 0.4, 0, 0),
    'listones_roble': ('listones', 0.6, (1, 0.95, 0.88, 1), 0.2, 0.3, 0, 0),
    'teca': ('tablas', 2.0, (0.86, 0.68, 0.5, 1), 0.15, 0.2, 0, 0),
    'parquet': ('tablas', 1.6, (0.66, 0.48, 0.36, 1), 0.4, 0.5, 0, 0),
    'tela_vino': ('tela', 0.3, (0.56, 0.13, 0.17, 1), 0.15, 0.15, 0, 0),
    'tela_salvia': ('tela', 0.3, (0.58, 0.66, 0.57, 1), 0.1, 0.1, 0, 0),
    'tela_crema': ('tela', 0.3, (0.96, 0.93, 0.86, 1), 0.1, 0.1, 0, 0),
    'tela_gris': ('tela', 0.3, (0.48, 0.5, 0.53, 1), 0.1, 0.1, 0, 0),
    'tela_mostaza': ('tela', 0.3, (0.86, 0.64, 0.24, 1), 0.1, 0.1, 0, 0),
    'tela_terracota': ('tela', 0.3, (0.74, 0.38, 0.27, 1), 0.1, 0.1, 0, 0),
    'lona': ('tela', 0.5, (0.96, 0.94, 0.88, 1), 0.05, 0.05, 0, 0),
    'lona_lisa': (None, None, (0.95, 0.92, 0.84, 1), 0.1, 0.1, 0, 0),
    'cuero_cognac': ('cuero', 0.4, (0.66, 0.38, 0.2, 1), 0.45, 0.55, 0, 0),
    'cuero_crema': ('cuero', 0.4, (0.95, 0.91, 0.83, 1), 0.3, 0.4, 0, 0),
    'cuero_negro': ('cuero', 0.4, (0.15, 0.15, 0.16, 1), 0.45, 0.5, 0, 0),
    'alfombra_persa': ('alfombra_persa', None, (1, 1, 1, 1), 0, 0, 0, 0),
    'alfombra_moderna': ('alfombra_moderna', None, (1, 1, 1, 1), 0, 0, 0, 0),
    'tapete': ('tela', 0.4, (0.2, 0.21, 0.23, 1), 0, 0, 0, 0),
    'piedra_spa': ('piedra', 1.2, (0.88, 0.94, 0.93, 1), 0.3, 0.4, 0, 0),
    'piedra_gris': ('piedra', 1.2, (0.78, 0.79, 0.82, 1), 0.3, 0.4, 0, 0),
    'concreto': ('concreto', 1.5, (1, 1, 1, 1), 0.1, 0.1, 0, 0),
    'caucho': ('caucho', 1.0, (1, 1, 1, 1), 0.05, 0.05, 0, 0),
    'cesped': ('cesped', 1.6, (1, 1, 1, 1), 0, 0, 0, 0),
    'seto': ('seto', 0.9, (1, 1, 1, 1), 0.1, 0.2, 0, 0),
    'adoquin': ('adoquin', 1.2, (1, 1, 1, 1), 0.1, 0.1, 0, 0),
    'pared': ('pared', 1.0, (0.97, 0.95, 0.91, 1), 0.05, 0.05, 0, 0),
    'carton': ('carton', 0.5, (1, 1, 1, 1), 0, 0, 0, 0),
    'peligro': ('peligro', 0.5, (1, 1, 1, 1), 0.1, 0.1, 0, 0),
    'casillero': ('casillero', None, (0.8, 0.78, 0.94, 1), 0.7, 0.6, 0, 0),
    'logo': ('logo', None, (1, 1, 1, 1), 0.4, 0.5, 0, 0.12),
    'medallon': ('medallon', None, (1, 1, 1, 1), 0.6, 0.7, 0, 0),
    'puesto': ('puesto', None, (1, 1, 1, 1), 0.6, 0.7, 0, 0),
    'cuadro_atardecer': ('cuadro_atardecer', None, (1, 1, 1, 1), 0.1, 0.1, 0, 0.05),
    'cuadro_campos': ('cuadro_campos', None, (1, 1, 1, 1), 0.1, 0.1, 0, 0.05),
    'cuadro_geometrico': ('cuadro_geometrico', None, (1, 1, 1, 1), 0.1, 0.1, 0, 0.05),
    'laton': (None, None, (0.8, 0.63, 0.34, 1), 1, 0.8, 0, 0),
    'cromo': (None, None, (0.82, 0.84, 0.87, 1), 1, 1, 0, 0),
    'acero': (None, None, (0.56, 0.58, 0.61, 1), 0.8, 0.7, 0, 0),
    'acero_negro': (None, None, (0.13, 0.13, 0.14, 1), 0.6, 0.6, 0, 0),
    'fachada': (None, None, (0.17, 0.18, 0.19, 1), 0.6, 0.6, 0, 0),
    'blanco': (None, None, (0.95, 0.95, 0.93, 1), 0.3, 0.3, 0, 0),
    'porcelana': (None, None, (0.97, 0.97, 0.96, 1), 0.9, 0.9, 0, 0),
    'mantel': (None, None, (0.97, 0.96, 0.93, 1), 0.05, 0.05, 0, 0),
    'vidrio': (None, None, (0.72, 0.84, 0.88, 0.16), 1, 1, 0, 0),
    'vidrio_oscuro': (None, None, (0.12, 0.16, 0.2, 0.85), 1, 1, 0, 0),
    'copa': (None, None, (0.9, 0.95, 1, 0.35), 1, 1, 0, 0),
    'terracota': (None, None, (0.68, 0.38, 0.25, 1), 0.15, 0.2, 0, 0),
    'ceramica_blanca': (None, None, (0.93, 0.92, 0.89, 1), 0.7, 0.7, 0, 0),
    'ceramica_negra': (None, None, (0.16, 0.16, 0.17, 1), 0.7, 0.7, 0, 0),
    'ceramica_salvia': (None, None, (0.55, 0.64, 0.56, 1), 0.6, 0.6, 0, 0),
    'tierra': (None, None, (0.24, 0.17, 0.12, 1), 0, 0, 0, 0),
    'hoja_1': (None, None, (0.2, 0.43, 0.19, 1), 0.35, 0.5, 0, 0),
    'hoja_2': (None, None, (0.29, 0.53, 0.24, 1), 0.35, 0.5, 0, 0),
    'hoja_3': (None, None, (0.15, 0.34, 0.17, 1), 0.35, 0.5, 0, 0),
    'hoja_olivo': (None, None, (0.43, 0.52, 0.38, 1), 0.2, 0.3, 0, 0),
    'bambu': (None, None, (0.62, 0.68, 0.36, 1), 0.4, 0.5, 0, 0),
    'tronco': (None, None, (0.36, 0.27, 0.2, 1), 0.1, 0.1, 0, 0),
    'flor_blanca': (None, None, (0.98, 0.96, 0.96, 1), 0.3, 0.3, 0, 0),
    'flor_rosa': (None, None, (0.9, 0.52, 0.64, 1), 0.3, 0.3, 0, 0),
    'luz_calida': (None, None, (1, 0.88, 0.66, 1), 0, 0, 0, 1),
    'pantalla_lampara': (None, None, (0.98, 0.92, 0.8, 0.94), 0.1, 0.1, 0, 0.6),
    'vela': (None, None, (0.96, 0.93, 0.85, 1), 0.1, 0.1, 0, 0.25),
    'llama': (None, None, (1, 0.74, 0.32, 1), 0, 0, 0, 1),
    'pantalla': (None, None, (0.05, 0.07, 0.1, 1), 1, 1, 0, 0.08),
    'salida': (None, None, (0.15, 0.7, 0.35, 1), 0.2, 0.2, 0, 0.8),
    'banda': (None, None, (0.09, 0.09, 0.1, 1), 0.1, 0.1, 0, 0),
    'caucho_negro': (None, None, (0.1, 0.1, 0.11, 1), 0.3, 0.3, 0, 0),
    'pelota': (None, None, (0.24, 0.4, 0.74, 1), 0.6, 0.6, 0, 0),
    'toalla_blanca': (None, None, (0.97, 0.97, 0.95, 1), 0, 0, 0, 0),
    'toalla_teal': (None, None, (0.48, 0.72, 0.7, 1), 0, 0, 0, 0),
    'piedra_zen': (None, None, (0.32, 0.33, 0.34, 1), 0.6, 0.6, 0, 0),
    'piedra_clara': (None, None, (0.74, 0.72, 0.68, 1), 0.3, 0.3, 0, 0),
    'libro_1': (None, None, (0.52, 0.16, 0.18, 1), 0.2, 0.2, 0, 0),
    'libro_2': (None, None, (0.18, 0.3, 0.42, 1), 0.2, 0.2, 0, 0),
    'libro_3': (None, None, (0.85, 0.8, 0.68, 1), 0.2, 0.2, 0, 0),
}


# ---------- Piezas ----------

@dataclass
class Pieza:
    tipo: str            # box, cylinder, capsule, sphere, ellipsoid, mesh
    x: float
    y: float
    z: float
    size: tuple
    mat: str
    giro: float = 0.0    # rumbo (rad) de su eje x local; en un panel, hacia dónde mira su cara
    panel: bool = False  # caja vertical: su cara +z mira hacia `giro` y ahí va la textura (ancho, alto, grosor)
    incl: float = 0.0    # panel echado hacia atrás (rad)
    eje: tuple = None    # cilindro, cápsula o elipsoide con su eje z en esta dirección
    malla: tuple = None  # mesh: (forma, parámetros); size es (radio mayor, medio alto) para las huellas

    def colocar(self, x0, y0, ang, z0=0.0):
        c, s = math.cos(ang), math.sin(ang)
        eje = None if self.eje is None else (self.eje[0] * c - self.eje[1] * s, self.eje[0] * s + self.eje[1] * c,
                                             self.eje[2])
        return replace(self, x=x0 + self.x * c - self.y * s, y=y0 + self.x * s + self.y * c, z=self.z + z0,
                       giro=self.giro + ang, eje=eje)


def caja(x, y, z, sx, sy, sz, mat, giro=0.0):
    return Pieza('box', x, y, z, (sx, sy, sz), mat, giro)


def panel(x, y, z, ancho, alto, grueso, mat, mira=0.0, incl=0.0):
    return Pieza('box', x, y, z, (ancho, alto, grueso), mat, mira, True, incl)


def cil(x, y, z, r, h, mat):
    return Pieza('cylinder', x, y, z, (r, h), mat)


def barra(x, y, z, r, largo, mat, eje, tipo='capsule'):
    n = math.sqrt(sum(e * e for e in eje))
    return Pieza(tipo, x, y, z, (r, largo), mat, eje=tuple(e / n for e in eje))


def esfera(x, y, z, r, mat):
    return Pieza('sphere', x, y, z, (r,), mat)


def elip(x, y, z, a, b, c, mat, giro=0.0, eje=None):
    return Pieza('ellipsoid', x, y, z, (a, b, c), mat, giro, eje=eje)


def tronco(x, y, z, r_abajo, r_arriba, h, mat, lados=24):
    """Tronco de cono vertical (macetas, pantallas de lámpara), centrado en z."""
    return Pieza('mesh', x, y, z, (max(r_abajo, r_arriba), h), mat, malla=('tronco', (r_abajo, r_arriba, h, lados)))


def sombrilla(x, y, z, r, h, mat):
    """Pirámide octogonal baja: la lona de una sombrilla, con la base en z."""
    return Pieza('mesh', x, y, z + h / 2, (r, h / 2), mat, malla=('tronco', (r, 0.03, h / 2, 8)))


def entre(p, q, r, mat, tipo='capsule'):
    """Barra de p a q."""
    d = [b - a for a, b in zip(p, q)]
    largo = math.sqrt(sum(e * e for e in d)) / 2
    return barra(*((a + b) / 2 for a, b in zip(p, q)), r, largo, mat, d, tipo)


def junto(*grupos):
    """Une piezas de varios muebles; cada grupo es (piezas, x, y, ang) en el marco del conjunto."""
    return [p.colocar(x, y, a) for piezas, x, y, a in grupos for p in piezas]


@dataclass
class Objeto:
    nombre: str
    piezas: list
    opcional: bool = True  # la decoración del lobby se quita si estorba; las paredes y el piso no
    pared: bool = False    # va contra la pared que queda detrás del lugar (casilleros, puerta de servicio)


def obj(nombre, piezas, x=0.0, y=0.0, ang=0.0, z=0.0, opcional=True, pared=False):
    return Objeto(nombre, [p.colocar(x, y, ang, z) for p in piezas], opcional, pared)


def mover(objetos, x, y, ang):
    return [Objeto(o.nombre, [p.colocar(x, y, ang) for p in o.piezas], o.opcional, o.pared) for o in objetos]


# ---------- Muebles (en su marco: mira hacia +x, centrado en el origen) ----------

def silla(madera='roble', cojin='tela_crema'):
    p = [cil(sx * 0.19, sy * 0.19, 0.215, 0.018, 0.215, madera) for sx in (-1, 1) for sy in (-1, 1)]
    p += [caja(0, 0, 0.445, 0.22, 0.22, 0.02, madera), caja(0.01, 0, 0.485, 0.2, 0.2, 0.022, cojin)]
    p += [cil(-0.19, sy * 0.19, 0.67, 0.016, 0.22, madera) for sy in (-1, 1)]
    p.append(panel(-0.205, 0, 0.74, 0.2, 0.13, 0.016, madera, 0, 0.12))
    return p


def sillon(tela, patas='nogal', cojin=None):
    p = [cil(sx * 0.32, sy * 0.32, 0.06, 0.025, 0.06, patas) for sx in (-1, 1) for sy in (-1, 1)]
    p += [caja(0, 0, 0.24, 0.4, 0.4, 0.12, tela), caja(0.04, 0, 0.42, 0.33, 0.28, 0.06, tela),
          panel(-0.31, 0, 0.62, 0.4, 0.27, 0.09, tela, 0, 0.18)]
    for sy in (-1, 1):
        p += [caja(0, sy * 0.34, 0.47, 0.38, 0.06, 0.11, tela), barra(0, sy * 0.34, 0.58, 0.065, 0.33, tela, (1, 0, 0))]
    if cojin:
        p.append(panel(-0.19, 0, 0.62, 0.21, 0.15, 0.055, cojin, 0.15, 0.3))
    return p


def sofa(plazas, tela, cojin=None, patas='nogal'):
    w, d = 0.31 * plazas + 0.15, 0.45
    p = [cil(sx * (d - 0.07), sy * (w - 0.07), 0.06, 0.025, 0.06, patas) for sx in (-1, 1) for sy in (-1, 1)]
    p += [caja(0, 0, 0.25, d, w, 0.13, tela), caja(-0.38, 0, 0.6, 0.07, w, 0.26, tela)]
    for i in range(plazas):
        y = -(plazas - 1) * 0.31 + i * 0.62
        p += [caja(0.05, y, 0.44, d - 0.1, 0.3, 0.065, tela), panel(-0.27, y, 0.68, 0.29, 0.2, 0.08, tela, 0, 0.2)]
    for sy in (-1, 1):
        p += [caja(0, sy * (w - 0.08), 0.48, d, 0.08, 0.12, tela),
              barra(0, sy * (w - 0.08), 0.6, 0.08, d - 0.08, tela, (1, 0, 0))]
        if cojin:
            p.append(panel(-0.16, sy * (w - 0.38), 0.64, 0.19, 0.19, 0.055, cojin, -sy * 0.3, 0.35))
    return p


def mesa_redonda(r, alto, sup='marmol_blanco', base='laton'):
    return [cil(0, 0, 0.012, r * 0.55, 0.012, base), cil(0, 0, alto / 2, 0.035, alto / 2, base),
            cil(0, 0, alto - 0.015, r, 0.015, sup)]


def mesa_centro(sx, sy, alto=0.42, sup='nogal', patas='laton', semilla=0):
    r = random.Random(semilla)
    p = [caja(0, 0, alto - 0.025, sx, sy, 0.025, sup)]
    p += [cil(ex * (sx - 0.06), ey * (sy - 0.06), (alto - 0.05) / 2, 0.018, (alto - 0.05) / 2, patas)
          for ex in (-1, 1) for ey in (-1, 1)]
    z = alto
    for i, libro in enumerate(('libro_1', 'libro_2', 'libro_3')):  # libros apilados
        p.append(caja(-sx * 0.45, sy * 0.4, z + 0.018, 0.12 - 0.01 * i, 0.16 - 0.015 * i, 0.017, libro,
                      r.uniform(-0.3, 0.3)))
        z += 0.034
    p += [elip(sx * 0.35, -sy * 0.2, alto + 0.03, 0.13, 0.13, 0.035, 'ceramica_negra')]
    p += [esfera(sx * 0.35 + r.uniform(-0.04, 0.04), -sy * 0.2 + r.uniform(-0.04, 0.04), alto + 0.07, 0.035, m)
          for m in ('flor_blanca', 'hoja_2')]
    return p


def lampara_pie(alto=1.6):
    return [cil(0, 0, 0.012, 0.16, 0.012, 'acero_negro'), cil(0, 0, alto / 2, 0.012, alto / 2, 'laton'),
            tronco(0, 0, alto, 0.21, 0.15, 0.13, 'pantalla_lampara'), esfera(0, 0, alto - 0.06, 0.05, 'luz_calida')]


def lampara_mesa(z0):
    return [esfera(0, 0, z0 + 0.09, 0.09, 'ceramica_salvia'), cil(0, 0, z0 + 0.24, 0.01, 0.07, 'laton'),
            tronco(0, 0, z0 + 0.34, 0.15, 0.1, 0.09, 'pantalla_lampara')]


def planta(tipo='arbusto', alto=1.0, maceta='ceramica_blanca', semilla=0):
    r = random.Random(semilla)
    rm, hm = (0.2, 0.42) if tipo in ('alta', 'olivo') else (0.17, 0.36)
    p = [tronco(0, 0, hm / 2, rm * 0.72, rm, hm / 2, maceta), cil(0, 0, hm, rm + 0.012, 0.014, maceta),
         cil(0, 0, hm + 0.003, rm - 0.012, 0.01, 'tierra')]
    hojas = ('hoja_1', 'hoja_2', 'hoja_3')
    if tipo == 'arbusto':
        for k in range(7):
            a, d, rr = k * 2.4 + r.uniform(-0.3, 0.3), 0.06 + 0.05 * (k % 3), r.uniform(0.13, 0.19) * alto
            p.append(elip(d * math.cos(a), d * math.sin(a), hm + 0.1 + 0.3 * alto * r.random(), rr, rr * 0.9, rr * 0.8,
                          hojas[k % 3], a))
    elif tipo in ('alta', 'olivo'):
        p.append(barra(0, 0, hm + 0.42 * alto, 0.028, 0.42 * alto, 'tronco', (0, 0, 1)))
        verdes = ('hoja_olivo', 'hoja_2', 'hoja_olivo') if tipo == 'olivo' else hojas
        for k in range(10):
            a, d = k * 2.2, r.uniform(0.05, 0.24)
            rr = r.uniform(0.15, 0.23) * (0.8 + 0.4 * alto)
            p.append(elip(d * math.cos(a), d * math.sin(a), hm + alto * (0.78 + 0.5 * r.random()), rr, rr * 0.85,
                          rr * 0.7, verdes[k % 3], a))
    elif tipo == 'palmera':
        for k in range(11):
            a, incl = k * 2 * math.pi / 11 + r.uniform(-0.2, 0.2), r.uniform(0.3, 0.85)
            largo = r.uniform(0.36, 0.52) * alto
            e = (math.cos(a) * math.sin(incl), math.sin(a) * math.sin(incl), math.cos(incl))
            p.append(elip(e[0] * largo, e[1] * largo, hm + 0.04 + e[2] * largo, 0.018, 0.09, largo, hojas[k % 3],
                          eje=e))
    elif tipo == 'bambu':
        for k in range(7):
            a, d, h = k * 2.6, r.uniform(0.03, 0.12), r.uniform(0.55, 0.85) * alto
            x, y = d * math.cos(a), d * math.sin(a)
            p.append(barra(x, y, hm + h, 0.014, h, 'bambu', (0, 0, 1)))
            for j in range(3):
                b = r.uniform(0, 6.3)
                e = (math.cos(b) * 0.8, math.sin(b) * 0.8, 0.6)
                p.append(elip(x + e[0] * 0.1, y + e[1] * 0.1, hm + h * (1.2 + 0.35 * j) + 0.05, 0.012, 0.035, 0.12,
                              hojas[j], eje=e))
    return p


def letrero(material):
    """Tótem con el nombre del lugar; mira hacia +x."""
    return [cil(0, 0, 0.012, 0.17, 0.012, 'acero_negro'), cil(0, 0, 0.66, 0.018, 0.64, 'laton'),
            panel(0, 0, 1.42, 0.35, 0.23, 0.014, 'laton'), panel(0.016, 0, 1.42, 0.32, 0.2, 0.003, material),
            panel(-0.016, 0, 1.42, 0.32, 0.2, 0.003, material, math.pi)]


def poste(alto=0.95):
    return [cil(0, 0, 0.012, 0.15, 0.012, 'laton'), cil(0, 0, alto / 2, 0.025, alto / 2, 'laton'),
            esfera(0, 0, alto + 0.04, 0.045, 'laton')]


def cordon(p, q, z=0.88, caida=0.14):
    medio = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, z - caida)
    return [entre((p[0], p[1], z), medio, 0.017, 'tela_vino'), entre(medio, (q[0], q[1], z), 0.017, 'tela_vino')]


def mesa_mantel(asientos, semilla=0):
    """Mesa de restaurante con mantel, platos, copas y una vela; `asientos`: ángulos hacia donde hay sillas."""
    r = random.Random(semilla)
    p = [cil(0, 0, 0.012, 0.26, 0.012, 'acero_negro'), cil(0, 0, 0.25, 0.04, 0.24, 'acero_negro'),
         cil(0, 0, 0.615, 0.46, 0.15, 'mantel'), cil(0, 0, 0.765, 0.47, 0.006, 'mantel')]
    for a in asientos:
        c, s = math.cos(a), math.sin(a)
        p += [cil(0.29 * c, 0.29 * s, 0.774, 0.12, 0.003, 'porcelana'),
              cil(0.29 * c, 0.29 * s, 0.779, 0.075, 0.003, 'porcelana')]
        g = a + 0.55
        p += [cil(0.3 * math.cos(g), 0.3 * math.sin(g), 0.83, 0.028, 0.055, 'copa')]
    p += [cil(0, 0, 0.82, 0.035, 0.05, 'ceramica_blanca')]
    p += [esfera(r.uniform(-0.03, 0.03), r.uniform(-0.03, 0.03), 0.89 + 0.02 * k, 0.03, m)
          for k, m in enumerate(('flor_rosa', 'flor_blanca', 'hoja_2'))]
    p += [cil(0.12, -0.08, 0.8, 0.022, 0.03, 'vela'), esfera(0.12, -0.08, 0.84, 0.01, 'llama')]
    return p


def caminadora():
    p = [caja(0, 0, 0.1, 0.85, 0.38, 0.06, 'acero_negro'), caja(-0.05, 0, 0.165, 0.72, 0.25, 0.008, 'banda'),
         caja(0.76, 0, 0.21, 0.13, 0.37, 0.08, 'acero_negro')]
    p += [caja(-0.05, sy * 0.31, 0.172, 0.72, 0.06, 0.012, 'acero') for sy in (-1, 1)]
    p += [entre((0.8, sy * 0.33, 0.25), (0.66, sy * 0.33, 1.15), 0.03, 'acero') for sy in (-1, 1)]
    p += [panel(0.64, 0, 1.22, 0.34, 0.15, 0.03, 'acero_negro', math.pi, 0.5),
          panel(0.612, 0, 1.235, 0.19, 0.085, 0.004, 'pantalla', math.pi, 0.5),
          barra(0.56, 0, 1.05, 0.022, 0.33, 'acero', (0, 1, 0))]
    return p


def banco_pesas():
    p = [caja(0, 0, 0.45, 0.55, 0.15, 0.04, 'cuero_negro'), caja(0, 0, 0.36, 0.45, 0.04, 0.03, 'acero_negro')]
    p += [caja(sx * 0.42, 0, 0.2, 0.03, 0.2, 0.2, 'acero_negro') for sx in (-1, 1)]
    p += [caja(-0.62, sy * 0.38, 0.6, 0.03, 0.03, 0.6, 'acero') for sy in (-1, 1)]
    p += [barra(-0.6, 0, 1.05, 0.015, 0.78, 'cromo', (0, 1, 0))]
    p += [barra(-0.6, sy * yy, 1.05, rr, 0.022, 'caucho_negro', (0, 1, 0), 'cylinder')
          for sy in (-1, 1) for yy, rr in ((0.52, 0.22), (0.57, 0.17))]
    return p


def rack_mancuernas():
    p = [caja(0, sy * 0.56, 0.33, 0.2, 0.03, 0.33, 'acero_negro') for sy in (-1, 1)]
    p += [caja(0.04, 0, 0.3, 0.18, 0.56, 0.015, 'acero_negro'), caja(-0.06, 0, 0.6, 0.15, 0.56, 0.015, 'acero_negro')]
    for x, z, tam in ((0.04, 0.3, 0.07), (-0.06, 0.6, 0.055)):
        for i in range(3):
            y, r = -0.36 + 0.36 * i, tam + 0.008 * i
            p += [barra(x, y, z + r + 0.015, 0.014, 0.085, 'cromo', (1, 0, 0))]
            p += [barra(x + sx * 0.1, y, z + r + 0.015, r, 0.03, 'caucho_negro', (1, 0, 0), 'cylinder') for sx in (-1, 1)]
    return p


def camilla():
    p = [caja(0, 0, 0.72, 0.36, 0.92, 0.06, 'cuero_crema'), caja(0, 0, 0.635, 0.32, 0.86, 0.025, 'roble')]
    p += [cil(sx * 0.27, sy * 0.78, 0.3, 0.03, 0.3, 'roble') for sx in (-1, 1) for sy in (-1, 1)]
    p += [caja(0, 1.03, 0.71, 0.15, 0.1, 0.045, 'cuero_crema'), caja(0, -0.55, 0.792, 0.3, 0.22, 0.012, 'toalla_teal')]
    return p


def toallas():
    p = [caja(0, 0, 0.22, 0.24, 0.2, 0.02, 'roble')]
    p += [cil(sx * 0.2, sy * 0.16, 0.1, 0.02, 0.1, 'roble') for sx in (-1, 1) for sy in (-1, 1)]
    for y, z, m in ((-0.12, 0.3, 'toalla_blanca'), (0, 0.3, 'toalla_teal'), (0.12, 0.3, 'toalla_blanca'),
                    (-0.06, 0.4, 'toalla_teal'), (0.06, 0.4, 'toalla_blanca')):
        p.append(barra(0, y, z, 0.058, 0.17, m, (1, 0, 0), 'cylinder'))
    return p


def velas():
    p = [cil(0, 0, 0.012, 0.17, 0.012, 'piedra_zen')]
    for (x, y), h in zip(((0.05, 0.05), (-0.06, 0.03), (0.0, -0.07)), (0.07, 0.11, 0.05)):
        p += [cil(x, y, 0.024 + h, 0.036, h, 'vela'), esfera(x, y, 0.024 + 2 * h + 0.018, 0.012, 'llama')]
    return p


def piedras():
    p = [caja(0, 0, 0.15, 0.2, 0.2, 0.15, 'piedra_clara')]
    z = 0.3
    for a, b, c in ((0.14, 0.12, 0.05), (0.11, 0.09, 0.042), (0.08, 0.07, 0.036), (0.055, 0.048, 0.03)):
        p.append(elip(0, 0, z + c, a, b, c, 'piedra_zen', a * 9))
        z += 2 * c - 0.008
    return p


def biombo(material='listones_roble'):
    """Biombo de tres hojas en zigzag, mirando hacia +x."""
    p = []
    for y, a in ((-0.47, -0.32), (0, 0.32), (0.47, -0.32)):
        p += [panel(0, y, 0.92, 0.24, 0.84, 0.015, material, a), panel(0, y, 1.77, 0.25, 0.015, 0.02, 'nogal', a)]
    return p


def puerta_servicio():
    """Puerta metálica con barra antipánico, mirilla y aviso de salida; la pared queda en x = 0."""
    p = [caja(0.03, sy * 0.52, 1.1, 0.03, 0.04, 1.1, 'acero_negro') for sy in (-1, 1)]
    p += [caja(0.03, 0, 2.17, 0.03, 0.56, 0.05, 'acero_negro'),
          panel(0.02, 0, 1.06, 0.48, 1.04, 0.02, 'acero'),
          barra(0.075, 0, 1.0, 0.018, 0.38, 'cromo', (0, 1, 0)),
          panel(0.042, 0.18, 1.55, 0.08, 0.22, 0.002, 'vidrio_oscuro'),
          panel(0.042, 0, 0.14, 0.44, 0.1, 0.002, 'acero_negro'),
          panel(0.04, 0, 2.34, 0.2, 0.06, 0.02, 'salida')]
    return p


def cajas(semilla=0):
    r = random.Random(semilla)
    return [caja(0, 0, 0.2, 0.25, 0.2, 0.2, 'carton', r.uniform(-0.1, 0.1)),
            caja(0.02, 0.03, 0.55, 0.2, 0.17, 0.15, 'carton', r.uniform(0.1, 0.4)),
            caja(0.05, 0.47, 0.15, 0.18, 0.18, 0.15, 'carton', r.uniform(-0.4, 0))]


def carretilla():
    p = [barra(0, sy * 0.2, 0.1, 0.1, 0.02, 'caucho_negro', (0, 1, 0), 'cylinder') for sy in (-1, 1)]
    p += [entre((0.02, sy * 0.17, 0.12), (-0.12, sy * 0.17, 1.15), 0.016, 'acero') for sy in (-1, 1)]
    p += [caja(0.1, 0, 0.02, 0.1, 0.2, 0.01, 'acero'), barra(-0.12, 0, 1.15, 0.016, 0.17, 'acero_negro', (0, 1, 0))]
    return p


def casilleros(n=5):
    w = 0.2
    total = n * w
    p = [caja(0, 0, 0.04, 0.26, total, 0.04, 'acero_negro'), caja(0, 0, 1.91, 0.27, total + 0.01, 0.012, 'acero_negro')]
    for i in range(n):
        y = -total + w + 2 * w * i
        p += [caja(0, y, 0.98, 0.25, w - 0.004, 0.9, 'acero'), panel(0.252, y, 0.98, w - 0.02, 0.88, 0.003, 'casillero')]
    return p


def banca():
    p = [caja(sx * 0.12, 0, 0.44, 0.055, 0.8, 0.015, 'roble') for sx in (-1, 0, 1)]
    p += [caja(0, sy * 0.7, 0.215, 0.17, 0.022, 0.215, 'acero') for sy in (-1, 1)]
    return p


def arbol(semilla=0, alto=1.0):
    r = random.Random(semilla)
    p = [cil(0, 0, 1.1 * alto, 0.13, 1.1 * alto, 'tronco')]
    for k in range(6):
        a, d = k * 2.1, r.uniform(0.2, 0.7)
        rr = r.uniform(0.7, 1.0) * alto
        p.append(elip(d * math.cos(a), d * math.sin(a), (2.7 + r.uniform(0, 0.8)) * alto, rr, rr * 0.9, rr * 0.75,
                      ('hoja_1', 'hoja_2', 'hoja_3', 'hoja_olivo')[k % 4], a))
    return p


def farol():
    return [cil(0, 0, 0.02, 0.16, 0.02, 'acero_negro'), cil(0, 0, 1.6, 0.045, 1.6, 'acero_negro'),
            tronco(0, 0, 3.26, 0.1, 0.16, 0.1, 'pantalla_lampara'), cil(0, 0, 3.39, 0.2, 0.025, 'acero_negro')]


def banca_exterior():
    p = [caja(sx * 0.13, 0, 0.44, 0.06, 0.85, 0.02, 'teca') for sx in (-1, 0, 1)]
    p += [caja(-0.2, 0, 0.7, 0.02, 0.85, 0.12, 'teca')]
    p += [caja(0, sy * 0.72, 0.22, 0.2, 0.03, 0.22, 'acero_negro') for sy in (-1, 1)]
    return p


def cuadro(material, ancho=0.3, alto=0.38):
    """Cuadro con marco dorado y paspartú, centrado en z = 0; su cara mira hacia +x."""
    return [panel(0, 0, 0, ancho + 0.05, alto + 0.05, 0.02, 'laton'),
            panel(0.021, 0, 0, ancho + 0.02, alto + 0.02, 0.002, 'blanco'),
            panel(0.024, 0, 0, ancho, alto, 0.002, material)]


def aplique():
    """Lámpara de pared centrada en z = 0; mira hacia +x."""
    return [panel(0, 0, 0, 0.05, 0.09, 0.01, 'laton'), barra(0.07, 0, 0, 0.01, 0.06, 'laton', (1, 0, 0)),
            tronco(0.13, 0, 0.04, 0.08, 0.055, 0.09, 'pantalla_lampara')]


# ---------- Ambientes: lo que lleva cada lugar (u: alejándose de recepción, v: a su izquierda) ----------

def amb_vip(i):
    return [
        obj('alfombra', [caja(1.2, 0, 0.0065, 0.95, 0.8, 0.0025, 'alfombra_persa')]),
        obj('sillón', sillon('tela_vino', 'wengue', 'tela_mostaza'), 1.55, 0.56, math.pi + 0.2),
        obj('sillón', sillon('tela_vino', 'wengue', 'tela_mostaza'), 1.55, -0.56, math.pi - 0.2),
        obj('postes', junto((poste(), 0, 0, 0), (poste(), 0, 1.4, 0)) + cordon((0, 0), (0, 1.4)), 0.66, -0.7),
        obj('mesa', mesa_redonda(0.22, 0.56) + lampara_mesa(0.56), 2.05, 0),
        obj('lámpara', lampara_pie(1.55), 2.35, 0.75),
        obj('planta', planta('palmera', 0.9, 'ceramica_negra', i), 2.5, -0.85),
    ]


def amb_social(i):
    return [
        obj('alfombra', [caja(1.3, 0, 0.0065, 1.0, 1.15, 0.0025, 'alfombra_moderna')]),
        obj('sofá', sofa(3, 'tela_salvia', 'tela_mostaza'), 2.0, 0, math.pi),
        obj('mesa', mesa_centro(0.26, 0.48, semilla=i), 1.25, 0),
        obj('sillón', sillon('tela_crema', 'roble', 'tela_terracota'), 1.08, -0.98, math.pi / 2),
        obj('sillón', sillon('tela_crema', 'roble', 'tela_terracota'), 1.08, 0.98, -math.pi / 2),
        obj('planta', planta('alta', 1.0, 'terracota', i), 2.15, -1.35),
        obj('lámpara', lampara_pie(1.6), 2.2, 1.35),
    ]


def amb_terraza(i):
    mesa = mesa_redonda(0.42, 0.74, 'teca', 'acero_negro') + [
        cil(0, 0, 1.12, 0.022, 1.12, 'acero_negro'), sombrilla(0, 0, 2.12, 1.1, 0.32, 'lona_lisa'),
        cil(0, 0, 2.115, 1.1, 0.006, 'lona_lisa'), esfera(0, 0, 2.47, 0.035, 'acero_negro')]
    jardinera = [caja(0, 0, 0.28, 0.22, 0.55, 0.28, 'teca'), caja(0, 0, 0.62, 0.2, 0.52, 0.08, 'seto')]
    jardinera += [elip(0, y, 0.72, 0.18, 0.2, 0.16, 'hoja_2', y) for y in (-0.32, 0.05, 0.36)]
    return [
        obj('deck', [caja(1.35, 0, 0.012, 1.25, 1.2, 0.008, 'teca')]),
        obj('mesa', mesa, 1.5, 0),
        *[obj('silla', silla('roble', 'lona'), 1.5 + 0.7 * math.cos(a), 0.7 * math.sin(a), a + math.pi)
          for a in (0, 2.2, -2.2)],
        obj('jardinera', jardinera, 2.6, 0, math.pi),
        obj('olivo', planta('olivo', 1.15, 'terracota', i), 2.45, -1.0),
        obj('farol', [tronco(0, 0, 0.2, 0.1, 0.07, 0.2, 'acero_negro', 6), cil(0, 0, 0.29, 0.06, 0.08, 'pantalla_lampara'),
                      esfera(0, 0, 0.29, 0.03, 'luz_calida')], 2.5, 0.95),
    ]


def amb_restaurante(i):
    objetos = [obj('piso', [caja(1.35, 0, 0.0065, 1.25, 1.55, 0.0025, 'parquet')])]
    for k, v in enumerate((-0.68, 0.68)):
        objetos += [obj('mesa', mesa_mantel((0, math.pi), i * 10 + k), 1.42, v),
                    obj('silla', silla('nogal', 'cuero_cognac'), 0.7, v, 0),
                    obj('silla', silla('nogal', 'cuero_cognac'), 2.14, v, math.pi)]
    objetos += [obj('planta', planta('alta', 1.1, 'ceramica_negra', i), 2.45, 1.5),
                obj('planta', planta('alta', 1.1, 'ceramica_negra', i + 1), 2.45, -1.5)]
    return objetos


def amb_gimnasio(i):
    return [
        obj('piso', [caja(1.3, 0, 0.0075, 1.25, 1.4, 0.0035, 'caucho')]),
        obj('caminadora', caminadora(), 1.55, 0.55, 0),
        obj('banco', banco_pesas(), 1.6, -0.45, 0),
        obj('mancuernas', rack_mancuernas(), 2.55, -0.45, math.pi),
        obj('pelota', [esfera(0, 0, 0.3, 0.3, 'pelota')], 2.6, 0.75),
    ]


def amb_spa(i):
    return [
        obj('piso', [caja(1.25, 0, 0.0065, 1.25, 1.35, 0.0025, 'piedra_spa')]),
        obj('camilla', camilla(), 1.4, 0, 0),
        obj('biombo', biombo(), 2.35, 0, math.pi),
        obj('toallas', toallas(), 2.05, 1.1, -math.pi / 2),
        obj('piedras', piedras(), 2.0, -1.1),
        obj('velas', velas(), 2.6, -1.0),
        obj('bambú', planta('bambu', 1.1, 'ceramica_salvia', i), 2.65, 1.15),
    ]


def amb_servicio(i):
    return [
        obj('piso', [caja(1.3, 0, 0.0065, 1.3, 1.15, 0.0025, 'concreto'),
                     caja(0.68, 0, 0.0095, 0.06, 0.8, 0.0005, 'peligro')]),
        obj('puerta', puerta_servicio(), pared=True),
        obj('carretilla', carretilla(), 1.2, -0.75, math.pi * 0.8),
        obj('cajas', cajas(i), 1.35, 0.6, 0.3),
    ]


def amb_vestier(i):
    return [
        obj('piso', [caja(1.25, 0, 0.0065, 1.2, 1.25, 0.0025, 'piedra_gris')]),
        obj('casilleros', [p.colocar(0.27, 0, 0) for p in casilleros(4)], pared=True),
        obj('banca', banca(), 1.3, 0.1),
        obj('canasta', [tronco(0, 0, 0.24, 0.16, 0.2, 0.24, 'roble', 12), cil(0, 0, 0.47, 0.19, 0.012, 'nogal')]
            + [esfera(0.06 * math.cos(a), 0.06 * math.sin(a), 0.5, 0.09, m)
               for a, m in ((0, 'toalla_blanca'), (2.1, 'toalla_teal'), (4.2, 'toalla_blanca'))], 0.9, 1.15),
        obj('planta', planta('arbusto', 1.0, 'ceramica_negra', i), 1.85, 1.2),
    ]


def amb_generico(i):
    return [
        obj('alfombra', [cil(1.05, 0, 0.006, 1.0, 0.002, 'alfombra_moderna')]),
        obj('banca', banca(), 1.55, 0, math.pi),
        obj('planta', planta('alta', 1.0, 'terracota', i), 1.6, 1.1),
        obj('planta', planta('arbusto', 1.0, 'terracota', i + 1), 1.6, -1.1),
    ]


AMBIENTES = {'vip': amb_vip, 'social': amb_social, 'terraza': amb_terraza, 'restaurante': amb_restaurante,
             'gimnasio': amb_gimnasio, 'spa': amb_spa, 'servicio': amb_servicio, 'vestier': amb_vestier}
PALABRAS = {  # para reconocer el ambiente de un lugar nuevo por su nombre (o un ambiente que no está en la lista)
    'vip': r'vip|ejecutiv|premium', 'social': r'social|lounge|sala|espera|estar',
    'terraza': r'terraza|jardin|patio|bar|terrace|garden|exterior',
    'restaurante': r'restaurante|comedor|cafeteria|cafe|restaurant|dining|comida|food',
    'gimnasio': r'gimnasio|gym|fitness|entrena', 'spa': r'spa|sauna|masaje|wellness|massage|relaj',
    'servicio': r'servicio|proveedor|carga|bodega|service|staff|delivery|entrega',
    'vestier': r'vestier|casillero|locker|vestidor',
}


def _norm(texto):
    return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode().lower().strip()


def ambiente(destino):
    pedido = _norm(destino.get('ambiente') or '')
    if pedido in AMBIENTES:
        return pedido
    for texto in (pedido, _norm(destino['nombre'])):
        hallado = next((a for a, p in PALABRAS.items() if texto and re.search(p, texto)), None)
        if hallado:
            return hallado
    return None


# ---------- Huellas y caminos (para no estorbarle al robot) ----------

def huella(p):
    """Rectángulo en planta (cx, cy, medio largo, medio ancho, ángulo del largo) y alturas mínima y máxima."""
    if p.tipo == 'box':
        sx, sy, sz = p.size
        if p.panel:
            ci, si = abs(math.cos(p.incl)), abs(math.sin(p.incl))
            return (p.x, p.y, sz * ci + sy * si, sx, p.giro), p.z - (sy * ci + sz * si), p.z + (sy * ci + sz * si)
        return (p.x, p.y, sx, sy, p.giro), p.z - sz, p.z + sz
    if p.tipo in ('cylinder', 'capsule', 'mesh'):
        r, h = p.size
        tapa = r if p.tipo == 'capsule' else 0
        if p.eje is None:  # el cuadrado que lo contiene gira con el mueble, como se diseñó
            return (p.x, p.y, r, r, p.giro), p.z - h - tapa, p.z + h + tapa
        ex, ey, ez = p.eje
        vert = h * abs(ez) + r * math.hypot(ex, ey) + tapa
        return (p.x, p.y, h * math.hypot(ex, ey) + r * abs(ez) + tapa, r, math.atan2(ey, ex)), p.z - vert, p.z + vert
    if p.tipo == 'ellipsoid':
        a, b, c = p.size
        if p.eje is None:
            return (p.x, p.y, a, b, p.giro), p.z - c, p.z + c
        r, (ex, ey, ez) = max(a, b), p.eje  # como una cápsula a lo largo de su eje
        vert = c * abs(ez) + r * math.hypot(ex, ey)
        return (p.x, p.y, c * math.hypot(ex, ey) + r * abs(ez), r, math.atan2(ey, ex)), p.z - vert, p.z + vert
    m = max(p.size)
    return (p.x, p.y, m, m, p.giro), p.z - m, p.z + m


def se_tocan(a, b, margen=0.0):
    """Separación de ejes entre dos rectángulos girados."""
    for ang in (a[4], a[4] + math.pi / 2, b[4], b[4] + math.pi / 2):
        ux, uy = math.cos(ang), math.sin(ang)
        lim = []
        for r in (a, b):
            c = r[0] * ux + r[1] * uy
            ext = r[2] * abs(math.cos(r[4] - ang)) + r[3] * abs(math.sin(r[4] - ang))
            lim.append((c - ext, c + ext))
        if lim[0][1] + margen <= lim[1][0] or lim[1][1] + margen <= lim[0][0]:
            return False
    return True


def franja(p, q, ancho):
    """Rectángulo que barre el robot al ir de p a q."""
    largo = math.hypot(q[0] - p[0], q[1] - p[1])
    return ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, largo / 2 + ancho, ancho, math.atan2(q[1] - p[1], q[0] - p[0]))


def caminos(destinos, puesto):
    px, py = puesto['x'], puesto['y']
    atras = (px - ATRAS, py)
    tramos = [('el puesto', atras, (px, py))]
    for d in destinos:
        dx, dy = d['x'] - px, d['y'] - py
        largo = math.hypot(dx, dy)
        if largo < 0.5:
            continue
        parada = (d['x'] - dx / largo * PARADA, d['y'] - dy / largo * PARADA)
        tramos += [(d['nombre'], (px, py), parada), (d['nombre'], (d['x'], d['y']), atras)]
    return [(n, franja(p, q, MEDIO_ANCHO + MARGEN)) for n, p, q in tramos]


def solidas(objeto):
    """Huellas de lo que sobresale del piso (alfombras y pisos no cuentan)."""
    return [h for h in map(huella, objeto.piezas) if h[2] > 0.03]


def estorba(objeto, franjas):
    """El primer camino que el objeto invade por debajo de la cabeza del robot."""
    for rect, z0, _ in solidas(objeto):
        if z0 > CABEZA:
            continue
        for nombre, f in franjas:
            if se_tocan(rect, f):
                return nombre
    return None


def circulo(huellas):
    """Centro y radio de un círculo que contiene las huellas (para descartar rápido)."""
    if not huellas:
        return 0.0, 0.0, -1.0
    xs = [r[0] for r, _, _ in huellas]
    ys = [r[1] for r, _, _ in huellas]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    return cx, cy, max(math.hypot(r[0] - cx, r[1] - cy) + math.hypot(r[2], r[3]) for r, _, _ in huellas)


def choca(objeto, otros, margen=0.1):
    """El primer objeto de `otros` en el que se mete alguna pieza (en planta y en altura), o None."""
    mias = solidas(objeto)
    c = circulo(mias)
    for o in otros:
        suyas = solidas(o)
        d = circulo(suyas)
        if math.hypot(c[0] - d[0], c[1] - d[1]) > c[2] + d[2] + margen:
            continue
        for a, a0, a1 in mias:
            for b, b0, b1 in suyas:
                if a0 < b1 and b0 < a1 and se_tocan(a, b, margen):
                    return o
    return None


def cunas(destinos, px, py):
    """Para cada lugar, cuánto ángulo (visto desde el puesto) tiene a cada lado antes de llegar a la mitad del
    camino hacia el lugar vecino: sus muebles se quedan en esa cuña para no meterse en los del vecino."""
    angulos = {d['nombre']: math.atan2(d['y'] - py, d['x'] - px) for d in destinos
               if math.hypot(d['x'] - px, d['y'] - py) >= 0.5}
    res = {}
    for n, a in angulos.items():
        otros = [((b - a) % (2 * math.pi)) for m, b in angulos.items() if m != n]
        izq = min(otros, default=2 * math.pi)
        der = 2 * math.pi - max(otros, default=0.0)
        res[n] = (a, min(izq / 2, 1.1), min(der / 2, 1.1))
    return res


def en_su_cuna(objeto, px, py, cuna, margen=0.08):
    """0 si cabe; 1 si se sale por la izquierda; -1 si por la derecha (lo de arriba de 1.9 m no cuenta)."""
    a, izq, der = cuna
    for (cx, cy, hx, hy, ang), z0, _ in solidas(objeto):
        if z0 > 1.9:
            continue
        for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            x = cx + sx * hx * math.cos(ang) - sy * hy * math.sin(ang)
            y = cy + sx * hx * math.sin(ang) + sy * hy * math.cos(ang)
            r = math.hypot(x - px, y - py)
            d = (math.atan2(y - py, x - px) - a + math.pi) % (2 * math.pi) - math.pi
            m = margen / max(r, 0.5)
            if d > izq - m:
                return 1
            if d < -der + m:
                return -1
    return 0


# ---------- El lobby: piso, paredes, fachada, recepción y exterior ----------

def recepcion(px, py):
    """Mostrador al lado del robot (fuera de los caminos), con el logo hacia la entrada."""
    cx, cy = px + 0.55, py + 1.55
    p = [caja(cx, cy, 0.05, 0.27, 0.72, 0.05, 'acero_negro'),
         panel(cx + 0.29, cy, 0.56, 0.76, 0.46, 0.02, 'listones_nogal'),
         panel(cx, cy + 0.75, 0.56, 0.3, 0.46, 0.02, 'nogal', math.pi / 2),
         panel(cx, cy - 0.75, 0.56, 0.3, 0.46, 0.02, 'nogal', -math.pi / 2),
         panel(cx - 0.29, cy, 0.56, 0.76, 0.46, 0.01, 'nogal', math.pi),
         caja(cx + 0.01, cy, 1.05, 0.34, 0.8, 0.03, 'marmol_blanco'),
         panel(cx + 0.312, cy, 0.6, 0.46, 0.23, 0.003, 'logo'),
         caja(cx + 0.335, cy, 1.008, 0.006, 0.76, 0.006, 'luz_calida'),
         # monitor, timbre y orquídea
         cil(cx - 0.08, cy + 0.35, 1.09, 0.06, 0.01, 'acero_negro'),
         cil(cx - 0.08, cy + 0.35, 1.17, 0.012, 0.08, 'acero_negro'),
         panel(cx - 0.08, cy + 0.35, 1.32, 0.24, 0.15, 0.012, 'acero_negro', math.pi, 0.08),
         panel(cx - 0.093, cy + 0.35, 1.32, 0.225, 0.135, 0.002, 'pantalla', math.pi, 0.08),
         cil(cx + 0.18, cy + 0.05, 1.087, 0.04, 0.007, 'laton'), esfera(cx + 0.18, cy + 0.05, 1.1, 0.03, 'laton'),
         tronco(cx + 0.05, cy - 0.5, 1.14, 0.045, 0.06, 0.06, 'ceramica_blanca')]
    # Orquídea: vara que se arquea y flores a lo largo del arco
    vara = [(0, 0, 1.2), (0.01, 0, 1.36), (0.05, 0, 1.44), (0.12, 0, 1.45), (0.17, 0, 1.41)]
    p += [entre((cx + 0.05 + a[0], cy - 0.5, a[2]), (cx + 0.05 + b[0], cy - 0.5, b[2]), 0.004, 'hoja_3')
          for a, b in zip(vara, vara[1:])]
    p += [esfera(cx + 0.05 + x, cy - 0.5 + 0.012 * (-1) ** k, z - 0.02, 0.024, 'flor_blanca' if k % 2 else 'flor_rosa')
          for k, (x, _, z) in enumerate(vara[2:] + [(0.085, 0, 1.455)])]
    p += [elip(cx + 0.05 + sx * 0.07, cy - 0.5, 1.215, 0.08, 0.035, 0.008, 'hoja_1', sx * 0.4) for sx in (-1, 1)]
    return Objeto('recepción', p, False)


def lobby(x0, x1, y0, y1, px, py):
    """Lo fijo del lobby. Devuelve (estructura, decoración); la decoración se quita si estorba."""
    cx, cy, lx, ly = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    est, deco = [], []
    est.append(Objeto('piso', [caja(cx, cy, 0.002, lx, ly, 0.002, 'marmol_piso'),
                               cil(px, py, 0.0045, 0.55, 0.0005, 'puesto')], False))

    def muro(nombre, x, y, largo, mira, desde=0.0, hasta=ALTO_PARED, revestir=True):
        """Tramo de pared con la cara interior hacia `mira`: estuco, zócalo de listones y moldura de latón."""
        c, s = math.cos(mira), math.sin(mira)
        h = (hasta - desde) / 2
        p = [panel(x - c * 0.075, y - s * 0.075, desde + h, largo, h, 0.075, 'pared', mira)]
        if revestir and desde < 0.95:
            p += [panel(x + c * 0.012, y + s * 0.012, 0.475, largo, 0.475, 0.012, 'listones_nogal', mira),
                  panel(x + c * 0.03, y + s * 0.03, 0.96, largo, 0.012, 0.012, 'laton', mira)]
        if hasta >= ALTO_PARED:
            p.append(panel(x + c * 0.02, y + s * 0.02, ALTO_PARED - 0.04, largo, 0.04, 0.02, 'blanco', mira))
        est.append(Objeto(nombre, p, False))

    muro('pared izquierda', cx, y1, lx + 0.15, -math.pi / 2)
    muro('pared derecha', cx, y0, lx + 0.15, math.pi / 2)
    # Pared del fondo con un ventanal al jardín en el centro
    ancho_v = min(2.6, ly * 0.55)
    for lado in (-1, 1):
        largo = (ly + 0.15 - ancho_v) / 2
        muro('pared del fondo', x0, cy + lado * (ancho_v + largo), largo, 0)
    muro('bajo la ventana', x0, cy, ancho_v, 0, 0, 0.9)
    muro('sobre la ventana', x0, cy, ancho_v, 0, 2.2, ALTO_PARED, False)
    ventana = [panel(x0 - 0.075, cy, 1.55, ancho_v, 0.65, 0.008, 'vidrio'),
               caja(x0 + 0.04, cy, 0.92, 0.08, ancho_v + 0.04, 0.025, 'marmol_blanco')]
    n = max(2, round(ancho_v * 2 / 1.1))
    ventana += [caja(x0 - 0.075, cy - ancho_v + 2 * ancho_v * k / n, 1.55, 0.04, 0.025, 0.67, 'fachada')
                for k in range(n + 1)]
    ventana += [caja(x0 - 0.075, cy, z, 0.045, ancho_v, 0.025, 'fachada') for z in (0.91, 2.2)]
    est.append(Objeto('ventanal', ventana, False))

    # Fachada de vidrio con la entrada frente al robot
    e = 1.1
    fach = [panel(x1 + 0.04, cy, ALTO_PARED - 0.05, ly + 0.15, 0.06, 0.06, 'fachada', math.pi)]
    for a, b in ((y0 - 0.15, py - e), (py + e, y1 + 0.15)):
        m, h = (a + b) / 2, (b - a) / 2
        fach += [panel(x1 + 0.04, m, 0.06, h, 0.06, 0.04, 'fachada', math.pi),
                 panel(x1 + 0.04, m, 1.27, h, 1.18, 0.008, 'vidrio', math.pi)]
        k = max(1, round(2 * h / 1.2))
        fach += [caja(x1 + 0.04, a + 2 * h * j / k, 1.25, 0.045, 0.03, 1.25, 'fachada') for j in range(k + 1)]
    fach += [caja(x1 + 0.04, py + s * (e + 0.03), 1.25, 0.06, 0.06, 1.25, 'fachada') for s in (-1, 1)]
    fach += [caja(x1 + 0.04, py, 2.36, 0.06, e, 0.06, 'fachada')]
    for s in (-1, 1):  # puertas corredizas abiertas, guardadas detrás del vidrio fijo
        fach += [panel(x1 - 0.05, py + s * (e + 0.5), 1.18, 0.5, 1.14, 0.008, 'vidrio', math.pi),
                 caja(x1 - 0.05, py + s * (e + 0.02), 1.18, 0.02, 0.025, 1.14, 'cromo')]
    # Marquesina de vidrio y letrero del club sobre la entrada, por fuera
    fach += [caja(x1 + 0.95, py, 2.62, 0.85, e + 0.5, 0.012, 'vidrio'),
             caja(x1 + 1.8, py, 2.62, 0.02, e + 0.5, 0.03, 'fachada'),
             panel(x1 + 0.1, py, 2.71, 0.75, 0.2, 0.04, 'fachada'),
             panel(x1 + 0.142, py, 2.71, 0.36, 0.18, 0.003, 'logo')]
    est.append(Objeto('fachada', fach, False))
    est.append(recepcion(px, py))

    # Entrada: tapete, rosa de los vientos en el piso y plantas a los lados
    deco.append(Objeto('tapete', [caja(x1 - 0.45, py, 0.0065, 0.32, 0.85, 0.0025, 'tapete')]))
    deco.append(Objeto('rosa de los vientos', [cil(px + 1.75, py, 0.0047, 0.72, 0.0006, 'medallon')]))
    for s in (-1, 1):
        deco.append(obj('planta de la entrada', planta('alta', 1.15, 'ceramica_negra', 70 + s), x1 - 0.42, py + s * 1.55))
    # Sala de espera junto a la entrada
    espera = junto((sillon('cuero_cognac', 'wengue'), 0, 0, 0), (sillon('cuero_cognac', 'wengue'), 0, -1.1, 0),
                   (mesa_redonda(0.22, 0.52), 0.05, -0.55, 0), (lampara_mesa(0.52), 0.05, -0.55, 0))
    deco.append(obj('sala de espera', espera, x1 - 1.35, py + 3.6, math.pi))
    deco.append(obj('planta de la esquina', planta('palmera', 1.2, 'terracota', 81), x1 - 0.45, y1 - 0.45))
    for k, (x, y) in enumerate(((x0 + 0.45, y0 + 0.45), (x0 + 0.45, y1 - 0.45), (x1 - 0.45, y0 + 0.45))):
        deco.append(obj('planta de la esquina', planta('alta', 1.2, 'terracota', 90 + k), x, y))

    # Cuadros y apliques en las paredes laterales y a los lados del ventanal
    obras = ['cuadro_atardecer', 'cuadro_campos', 'cuadro_geometrico']
    k = 0
    for y_pared, mira in ((y1, -math.pi / 2), (y0, math.pi / 2)):
        s = math.sin(mira)
        x = x0 + 1.2
        while x < x1 - 1.0:
            deco.append(obj('cuadro', cuadro(obras[k % 3]), x, y_pared + s * 0.01, mira, 1.7))
            if x + 1.2 < x1 - 1.0:
                deco.append(obj('aplique', aplique(), x + 1.2, y_pared + s * 0.01, mira, 1.75))
            x += 2.4
            k += 1
    for lado in (-1, 1):
        y = cy + lado * (ancho_v + (ly - ancho_v) / 2)
        deco.append(obj('cuadro', cuadro(obras[k % 3], 0.38, 0.3), x0 + 0.01, y, 0, 1.7))
        k += 1
    return est, deco


def exterior(x0, x1, y0, y1, py):
    cx, cy, lx, ly = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    p = [caja(x1 + 2.7, py, 0.0025, 2.55, 3.8, 0.001, 'adoquin'),
         caja(x1 + 11, py, 0.0025, 5.8, 1.3, 0.001, 'adoquin')]
    # Setos junto a las paredes y jardineras a los lados de la entrada
    p += [caja(cx, y1 + 0.55, 0.4, lx + 0.2, 0.3, 0.4, 'seto'), caja(cx, y0 - 0.55, 0.4, lx + 0.2, 0.3, 0.4, 'seto'),
          caja(x0 - 0.55, cy, 0.3, 0.3, ly + 0.85, 0.3, 'seto')]
    for s in (-1, 1):
        largo = (ly - 1.6) / 2
        m = py + s * (1.75 + largo)
        p += [caja(x1 + 0.45, m, 0.22, 0.25, largo, 0.22, 'concreto'),
              caja(x1 + 0.45, m, 0.5, 0.21, largo - 0.04, 0.08, 'seto')]
    objetos = [Objeto('exterior', p, False)]
    for k, (x, y) in enumerate(((x1 + 3.9, py + 5.4), (x1 + 3.9, py - 5.4), (x0 - 2.2, y1 + 1.6), (x0 - 2.4, cy - 0.6),
                                (x0 - 1.8, y0 - 1.8), (cx, y1 + 2.4), (cx - 1, y0 - 2.6))):
        objetos.append(obj('árbol', arbol(200 + k, 1.0 + 0.1 * (k % 3)), x, y, opcional=False))
    for s in (-1, 1):
        objetos.append(obj('farol', farol(), x1 + 4.7, py + s * 2.3, opcional=False))
        objetos.append(obj('banca', banca_exterior(), x1 + 3.2, py + s * 3.3, math.pi, opcional=False))
    return objetos


# ---------- XML ----------

def _f(v):
    return f'{v:.4f}'.rstrip('0').rstrip('.') if abs(v) >= 1e-4 else '0'


def orientacion(p):
    if p.eje is not None:
        return ' zaxis="' + ' '.join(_f(e) for e in p.eje) + '"'
    c, s = math.cos(p.giro), math.sin(p.giro)
    if p.panel:
        ci, si = math.cos(p.incl), math.sin(p.incl)
        z = (c * ci, s * ci, si)
        x = (-s, c, 0.0)
        y = (z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0])
        return ' xyaxes="' + ' '.join(_f(e) for e in x + y) + '"'
    if p.tipo in ('box', 'ellipsoid') and abs(p.giro) > 1e-6:
        return f' xyaxes="{_f(c)} {_f(s)} 0 {_f(-s)} {_f(c)} 0"'
    return ''


class Materiales:
    """Declara cada material la primera vez que se usa; los que llevan textura repetida, uno por tamaño de cara."""

    def __init__(self, extra):
        self.tabla = dict(MATERIALES, **extra)
        self.usados = {}

    def usar(self, p):
        tex, metros, rgba, spec, brillo, refl, emis = self.tabla[p.mat]
        nombre, rep = p.mat, (1, 1)
        if tex and metros:
            a = 2 * p.size[0]
            b = 2 * (p.size[1] if p.tipo == 'box' else p.size[0])
            rep = (max(0.1, round(a / metros, 1)), max(0.1, round(b / metros, 1)))
            nombre = f'{p.mat}_{_f(rep[0])}x{_f(rep[1])}'.replace('.', '_')
        if nombre not in self.usados:
            attrs = f'name="{nombre}"' + (f' texture="{tex}" texrepeat="{_f(rep[0])} {_f(rep[1])}"' if tex else '')
            attrs += f' rgba="{" ".join(_f(c) for c in rgba)}" specular="{_f(spec)}" shininess="{_f(brillo)}"'
            attrs += (f' reflectance="{_f(refl)}"' if refl else '') + (f' emission="{_f(emis)}"' if emis else '')
            self.usados[nombre] = f'    <material {attrs}/>'
        return nombre


class Mallas:
    """Mallas convexas (troncos de cono) declaradas en línea en el <asset>, una por tamaño."""

    def __init__(self):
        self.usadas = {}

    def usar(self, p):
        forma, (r0, r1, h, lados) = p.malla
        nombre = f'nclub_{forma}_{lados}_' + '_'.join(f'{round(v * 1000)}' for v in (r0, r1, h))
        if nombre not in self.usadas:
            puntos = [(r * math.cos(2 * math.pi * k / lados), r * math.sin(2 * math.pi * k / lados), z)
                      for r, z in ((r0, -h), (r1, h)) for k in range(lados)]
            self.usadas[nombre] = (f'    <mesh name="{nombre}" vertex="'
                                   + ' '.join(_f(c) for q in puntos for c in q) + '"/>')
        return nombre


def geom(p, materiales, mallas):
    forma = f'mesh="{mallas.usar(p)}"' if p.tipo == 'mesh' else f'size="{" ".join(_f(s) for s in p.size)}"'
    ori = '' if p.tipo == 'mesh' else orientacion(p)
    return (f'    <geom type="{p.tipo}" {forma} pos="{_f(p.x)} {_f(p.y)} {_f(p.z)}"{ori} '
            f'material="{materiales.usar(p)}" contype="0" conaffinity="0"/>')


def contra_pared(objeto, x, y, fi, x0, x1, y0, y1, corrido=0.0):
    """Lleva un objeto (armado con la pared en x = 0, mirando a +x) a la pared que queda detrás del lugar."""
    ux, uy = math.cos(fi), math.sin(fi)
    cortes = [((x0 - x) / ux, 'x0') if ux < -1e-6 else None, ((x1 - x) / ux, 'x1') if ux > 1e-6 else None,
              ((y0 - y) / uy, 'y0') if uy < -1e-6 else None, ((y1 - y) / uy, 'y1') if uy > 1e-6 else None]
    t, pared = min(c for c in cortes if c)
    hx, hy = x + t * ux, y + t * uy
    medio = max(abs(r[1]) + abs(r[2] * math.sin(r[4])) + abs(r[3] * math.cos(r[4]))
                for r, _, _ in map(huella, objeto.piezas))

    def dentro(v, a, b):
        return min(max(v, a + medio + 0.2), b - medio - 0.2)
    sitio = {'x0': (x0, dentro(hy + corrido, y0, y1), 0.0), 'x1': (x1, dentro(hy + corrido, y0, y1), math.pi),
             'y0': (dentro(hx + corrido, x0, x1), y0, math.pi / 2),
             'y1': (dentro(hx + corrido, x0, x1), y1, -math.pi / 2)}[pared]
    return mover([objeto], *sitio)[0]


def camara(nombre, pos, mira):
    """Cámara fija en `pos` mirando a `mira` (en MuJoCo: Rendering → Camera)."""
    f = [m - p for m, p in zip(mira, pos)]
    n = math.sqrt(sum(v * v for v in f))
    f = [v / n for v in f]
    nx = math.hypot(f[0], f[1])
    x = (f[1] / nx, -f[0] / nx, 0.0)
    y = (x[1] * f[2] - x[2] * f[1], x[2] * f[0] - x[0] * f[2], x[0] * f[1] - x[1] * f[0])
    return (f'    <camera name="{nombre}" pos="{" ".join(_f(v) for v in pos)}" '
            f'xyaxes="{" ".join(_f(v) for v in x + y)}" fovy="50"/>')


def main():
    datos = json.loads(DESTINOS.read_text(encoding='utf-8'))
    puesto, destinos = datos['puesto'], datos['destinos']
    px, py = float(puesto['x']), float(puesto['y'])
    franjas = caminos(destinos, puesto)

    # 1. Los lugares, cada uno girado para que sus muebles queden más allá de su punto
    lugares, letreros, extra, quitados, tipos, de_pared, colas = [], [], {}, [], [], [], []
    for i, d in enumerate(destinos):
        x, y = float(d['x']), float(d['y'])
        if math.hypot(x - px, y - py) < 0.5:  # la recepción misma: ya están el mostrador y la marca del puesto
            continue
        fi = math.atan2(y - py, x - px)
        amb = ambiente(d)
        tipos.append(f'{d["nombre"]} ({amb or "genérico"})')
        locales = AMBIENTES.get(amb, amb_generico)(i)
        for o in locales:
            o.nombre = f'{o.nombre} de {d["nombre"]}'
        de_pared += [(o, x, y, fi, d['nombre']) for o in locales if o.pared]
        objetos = mover([o for o in locales if not o.pared], x, y, fi)
        for o in objetos:  # pisos y alfombras de lugares vecinos, a alturas distintas para que no titilen
            if not solidas(o):
                o.piezas = [replace(q, z=q.z + 0.0012 * (len(colas) % 6)) for q in o.piezas]
        mat = f'letrero_{i}'
        letreros.append((f'{mat}.png', d['nombre'], d.get('color', [0.45, 0.45, 0.45])))
        extra[mat] = (mat, None, (1, 1, 1, 1), 0.3, 0.3, 0, 0.18)
        carteles = []
        for v in (1.5, -1.5):  # el letrero a un lado, mirando hacia recepción (acomodar lo acerca si no cabe)
            sx, sy = x + 0.6 * math.cos(fi) - v * math.sin(fi), y + 0.6 * math.sin(fi) + v * math.cos(fi)
            carteles.append(obj(f'letrero de {d["nombre"]}', letrero(mat), sx, sy, math.atan2(py - sy, px - sx)))
        colas.append((d['nombre'], objetos, carteles))

    cuna = cunas(destinos, px, py)

    def acomodar(o, nombre, propios, correr=True):
        """Pone el objeto donde se diseñó o, si se sale de la cuña de su lugar o choca con lo del vecino, lo corre
        hacia el eje del lugar y hacia afuera. Si no hay dónde, se queda por fuera y se avisa."""
        a = cuna[nombre][0]
        ux, uy, vx, vy = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
        motivo = None
        for du in ((0.0, 0.15, 0.3, 0.45) if correr else (0.0,)):
            lado = 0  # hacia dónde estorba: 1 a la izquierda, -1 a la derecha; se corre al lado contrario
            for paso in range(25 if correr else 1):
                if paso and not lado:
                    break
                dv = -lado * 0.05 * paso
                q = Objeto(o.nombre, [replace(p, x=p.x + du * ux + dv * vx, y=p.y + du * uy + dv * vy)
                                      for p in o.piezas], o.opcional, o.pared)
                fuera = en_su_cuna(q, px, py, cuna[nombre]) if correr else 0
                if fuera:
                    lado = lado or fuera
                    if fuera != lado:
                        break
                    motivo = motivo or 'no cabe en su lado del lobby'
                    continue
                camino = estorba(q, franjas)
                if camino:
                    motivo = motivo or f'camino a {camino}'
                    continue
                vecino = choca(q, [x for x in lugares if x not in propios], 0.05)
                otro = vecino or choca(q, propios, 0.02)
                if otro:
                    motivo = motivo or f'choca con {otro.nombre}'
                    if vecino and not lado:
                        cx, cy, _ = circulo(solidas(vecino))
                        lado = 1 if (cx - px) * vx + (cy - py) * vy > ((q.piezas[0].x - px) * vx
                                                                         + (q.piezas[0].y - py) * vy) else -1
                    continue
                lugares.append(q)
                propios.append(q)
                return
        quitados.append(f'{o.nombre} ({motivo})')

    propios = {nombre: [] for nombre, _, _ in colas}
    for k in range(max((len(o) for _, o, _ in colas), default=0)):
        for nombre, objetos, carteles in colas:
            if k < len(objetos):
                acomodar(objetos[k], nombre, propios[nombre])

    # 2. El lobby envuelve lo de los lugares, con al menos el tamaño de siempre alrededor del puesto
    xs, ys = [px - 5.4, px + 3.4], [py - 4.8, py + 4.8]
    for o in lugares:
        for (cx_, cy_, hx, hy, a), _, _ in map(huella, o.piezas):
            ex = abs(hx * math.cos(a)) + abs(hy * math.sin(a))
            ey = abs(hx * math.sin(a)) + abs(hy * math.cos(a))
            xs += [cx_ - ex - 0.15, cx_ + ex + 0.15]
            ys += [cy_ - ey - 0.15, cy_ + ey + 0.15]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    for nombre, _, carteles in colas:  # el letrero al final, del lado con más espacio (o si no, del otro)
        _, izq, der = cuna[nombre]
        for k, c in enumerate(carteles if izq >= der else carteles[::-1]):
            antes = len(quitados)
            acomodar(c, nombre, propios[nombre])
            if len(quitados) == antes:
                break
            if k == 0:
                quitados.pop()
    for o, x, y, fi, nombre in de_pared:  # a lo largo de la pared, hasta encontrar un hueco
        for corrido in (0, 0.3, -0.3, 0.6, -0.6, 0.9, -0.9, 1.2, -1.2, 1.5, -1.5, 1.8, -1.8):
            q = contra_pared(o, x, y, fi, x0, x1, y0, y1, corrido)
            if not estorba(q, franjas) and not choca(q, lugares, 0.05):
                lugares.append(q)
                break
        else:
            quitados.append(f'{o.nombre} (no hay pared libre detrás)')
    estructura, deco = lobby(x0, x1, y0, y1, px, py)
    for o in estructura:
        camino = estorba(o, franjas) if o.nombre == 'recepción' else None
        if camino:
            quitados.append(f'(se dejó) el mostrador de recepción, en el camino a {camino}')
    lugares += [o for o in deco if not estorba(o, franjas) and not choca(o, lugares, 0.15)]
    todos = estructura + lugares + exterior(x0, x1, y0, y1, py)

    # 3. Texturas, materiales, luz y XML
    hechas = texturas.generar(ESCENA.parent / CARPETA_TEX, letreros)
    materiales, mallas = Materiales(extra), Mallas()
    geoms = [geom(p, materiales, mallas) for o in todos for p in o.piezas]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    vista = [
        f'    <light name="nclub_sol" pos="{_f(cx + 9)} {_f(cy + 7)} 15" dir="-9 -7 -15" cutoff="34" exponent="1" '
        'castshadow="true" diffuse="0.6 0.56 0.5" specular="0.3 0.3 0.28"/>',
        '    <light name="nclub_cielo" directional="true" castshadow="false" dir="0.3 -0.45 -1" '
        'diffuse="0.22 0.24 0.28" specular="0 0 0"/>',
        camara('nclub_lobby', (x1 + 5.5, py - 4.5, 6.2), (cx + 0.3, cy, 0.4)),
        camara('nclub_recepcion', (px + 2.6, py - 1.9, 1.75), (px - 0.4, py + 0.5, 0.85)),
    ]
    escena = ESCENA.read_text(encoding='utf-8')
    if not BLOQUE.search(escena):
        raise SystemExit(f'No encontré el bloque "inicio destinos" / "fin destinos" en {ESCENA}')
    if not BLOQUE_TEX.search(escena):  # la primera vez: antes del <asset> original, para que gane su cielo
        escena = escena.replace('  <asset>\n', MARCAS_TEX + '\n  <asset>\n', 1)
    tex = [f'    <texture name="{n}" type="2d" file="{CARPETA_TEX}/{n}.png"/>' for n in texturas.FIJAS]
    tex += [f'    <texture name="{a[:-4]}" type="2d" file="{CARPETA_TEX}/{a}"/>' for a, _, _ in letreros]
    bloque_tex = ['  <visual>',
                  '    <headlight diffuse="0.32 0.32 0.31" ambient="0.25 0.24 0.23" specular="0.15 0.15 0.15"/>',
                  '    <rgba haze="0.84 0.87 0.9 1"/>',
                  '  </visual>',
                  '  <asset>',
                  '    <texture type="skybox" builtin="gradient" rgb1="0.5 0.68 0.88" rgb2="0.9 0.91 0.9" '
                  'width="512" height="3072"/>',
                  *tex, *materiales.usados.values(), *mallas.usadas.values(),
                  '  </asset>']
    escena = BLOQUE_TEX.sub(lambda m: m.group(1) + '\n'.join(bloque_tex) + '\n' + m.group(2), escena)
    escena = BLOQUE.sub(lambda m: m.group(1) + '\n'.join(vista + geoms) + '\n' + m.group(2), escena)
    escena = PISO_SIM.sub(PISO_PASTO, escena, count=1)
    ESCENA.write_text(escena, encoding='utf-8')
    print(f'Lobby armado en {ESCENA.relative_to(RAIZ)}: {", ".join(tipos)}.')
    print(f'  {len(geoms)} piezas, {len(materiales.usados)} materiales'
          f'{f", {hechas} texturas nuevas" if hechas else ""}. Reinicia ./x2 sim para verlo.')
    for q in quitados:
        print(f'  Quité: {q}')


if __name__ == '__main__':
    main()
