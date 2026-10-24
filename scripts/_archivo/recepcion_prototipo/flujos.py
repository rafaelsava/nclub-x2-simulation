"""Cómo el robot pasa de "miembro / no miembro" a la categoría exacta, y qué hace con cada una.

Este es el archivo para personalizar: textos, gestos, a qué zona se acompaña y cuándo se llama a recepción.

Confirmación de la categoría (por capas):
  1. Reconocimiento facial: identifica a la persona (id o desconocida). Con la base de datos del club
     (club.json) ese id se traduce en miembro / no miembro (app.py).
  2. Base de datos del club: con el id se sabe la categoría (VIP, regular, personal).
  3. Confirmación ligera con la persona ("¿Es usted Ana?").
  Sin coincidencia: el robot pregunta el motivo de la visita; invitados y trabajadores externos no están
  registrados y se confirman con su código (invitación u orden de servicio). Lo que no se puede confirmar
  va a recepción.
"""

import threading
import time

MOTIVOS = {
    'miembro': 'Tengo membresía del club',
    'invitado': 'Vengo por invitación',
    'personal': 'Soy parte del personal de N Club',
    'servicio': 'Vengo de una empresa a hacer un trabajo o una entrega',
    'persona': 'Prefiero hablar con una persona',
}

# Para que el LLM entienda respuestas con palabras propias (lenguaje.py): {opción: (etiqueta, qué cubre)}.
# Los ejemplos son a propósito distintos de las frases de evaluar_lenguaje.py, para que la medición sea honesta.
PISTAS = {
    MOTIVOS['miembro']: ('MIEMBRO', 'es socio o tiene membresía del club, regular o VIP '
                                    '(p. ej. "soy socia", "tengo mi carné de membresía")'),
    MOTIVOS['invitado']: ('INVITADO', 'lo invitó alguien del club o viene a ver a un socio '
                                      '(p. ej. "un socio me está esperando", "vengo al cumpleaños de Carlos")'),
    MOTIVOS['personal']: ('EMPLEADO_DEL_CLUB', 'trabaja para N Club como empleado y viene a su turno '
                                               '(p. ej. "soy de seguridad del club", "hago parte del equipo de recepción")'),
    MOTIVOS['servicio']: ('EMPRESA_EXTERNA', 'viene de una empresa de afuera a hacer un trabajo, una reparación o una '
                                             'entrega (p. ej. "soy el electricista", "vengo a entregar un paquete")'),
    MOTIVOS['persona']: ('HABLAR_CON_PERSONA', 'quiere que le atienda una persona: recepción, un encargado o alguien '
                                               'del club (p. ej. "busco a alguien que me ayude", "¿está el administrador?")'),
    'Sí': ('SI', 'confirma que es esa persona (p. ej. "esa soy yo", "correcto")'),
    'No': ('NO', 'dice que no es esa persona (p. ej. "no, me llamo distinto", "se equivocó")'),
    'No, gracias': ('NADA_MAS', 'no necesita nada más (p. ej. "estoy bien así", "nada más")'),
    'Quiero hablar con recepción': ('HABLAR_CON_RECEPCION', 'quiere que le atienda una persona '
                                                            '(p. ej. "llame a alguien", "prefiero hablar con un humano")'),
}


def _buscar_por_codigo(tabla, texto):
    # Acepta el código con o sin prefijo y con cualquier separador: "OS-1077", "os 1077" o "1077"
    digitos = ''.join(c for c in texto if c.isdigit())
    for codigo, item in tabla.items():
        if texto.strip().upper() == codigo or (digitos and digitos == ''.join(c for c in codigo if c.isdigit())):
            return item
    return None


class Recepcion:
    def __init__(self, ui, robot, club):
        self.ui = ui
        self.robot = robot
        self.zonas = club['zonas']
        self.personas = {p['id']: p for p in club['personas']}
        self.invitaciones = {i['codigo'].upper(): i for i in club['invitaciones']}
        self.ordenes = {o['codigo'].upper(): o for o in club['ordenes_servicio']}

    def atender(self, reconocimiento):
        inicio = time.monotonic()
        self.ui.mostrar_reconocimiento(reconocimiento)
        self.ui.paso('Nuevo visitante')
        resultado = self._confirmar_y_orientar(reconocimiento)
        self.ui.registrar({
            'reconocimiento': reconocimiento['estado'],
            'categoria': resultado['categoria'],
            'confirmacion': resultado['confirmacion'],
            'resultado': resultado['resultado'],
            'duracion_s': round(time.monotonic() - inicio),
        })
        self.ui.en_reposo()

    # --- Confirmación de la categoría ---

    def _confirmar_y_orientar(self, rec):
        persona = self.personas.get(rec.get('persona_id'))
        if rec['estado'] == 'incierto':
            self.ui.paso('Reconocimiento dudoso: se confirma hablando con la persona')
            return self._sin_coincidencia(rec)
        if persona is None:
            self.ui.paso('Persona no registrada: se pregunta el motivo de la visita')
            return self._sin_coincidencia(rec)

        nombre = persona['nombre'].split()[0]
        self.ui.paso(f'Base de datos: {persona["nombre"]} ({persona["categoria"]}). Confirmación ligera')
        respuesta = self.ui.preguntar(f'¡Hola! ¿Es usted {nombre}?', ['Sí', 'No'], timeout=20, pistas=PISTAS)
        if respuesta is None:
            return self._escalar(f'Se reconoció a {persona["nombre"]}, pero no respondió', categoria='sin confirmar')
        if respuesta == 'No':
            self.ui.paso('La persona dice no ser quien reconoció el sistema')
            return self._sin_coincidencia(rec, aviso=f'Posible error del reconocimiento: no era {persona["nombre"]}')

        flujo = {'vip': self._vip, 'regular': self._regular, 'personal': self._personal}[persona['categoria']]
        return flujo(persona)

    def _sin_coincidencia(self, rec, aviso=None):
        if aviso:
            self.ui.alertar(aviso)
        self.ui.cara('neutral')
        respuesta = self.ui.preguntar('¡Hola! Le doy la bienvenida a N Club. ¿Cuál es el motivo de su visita?',
                                      list(MOTIVOS.values()), pistas=PISTAS)
        if respuesta is None:
            return self._escalar('Visitante sin identificar que no respondió', categoria='sin confirmar')
        motivo = next(k for k, v in MOTIVOS.items() if v == respuesta)
        if motivo == 'persona':
            return self._escalar('Pidió hablar con una persona', categoria='sin confirmar')
        if motivo == 'invitado':
            return self._confirmar_invitacion()
        if motivo == 'servicio':
            return self._confirmar_orden_servicio()
        # Dice ser miembro o del personal, pero el reconocimiento no lo respalda: lo decide una persona
        return self._escalar(f'Dice "{respuesta}", pero no se pudo confirmar con el reconocimiento facial',
                             categoria=f'{motivo} (sin confirmar)')

    def _confirmar_invitacion(self):
        for _ in range(2):
            codigo = self.ui.pedir_codigo('Por favor, escriba el código de su invitación.')
            if codigo is None:
                break
            invitacion = _buscar_por_codigo(self.invitaciones, codigo)
            if invitacion:
                return self._invitado(invitacion)
            self.ui.decir('No encuentro esa invitación.', cara='confundido')
        return self._escalar('Invitación no válida o sin código', categoria='invitado (sin confirmar)')

    def _confirmar_orden_servicio(self):
        for _ in range(2):
            codigo = self.ui.pedir_codigo('Por favor, escriba el código de su orden de servicio.')
            if codigo is None:
                break
            orden = _buscar_por_codigo(self.ordenes, codigo)
            if orden:
                return self._externo(orden)
            self.ui.decir('No encuentro esa orden de servicio.', cara='confundido')
        return self._escalar('Orden de servicio no válida o sin código', categoria='externo (sin confirmar)')

    # --- Los cinco flujos de orientación ---

    def _vip(self, persona):
        # VIP: trato personalizado y acompañamiento hasta el salón
        self.ui.paso('Flujo VIP')
        nombre = persona['nombre'].split()[0]
        self._gesto('saludar')
        self.ui.decir(f'¡{nombre}, qué gusto tenerle de vuelta! Su Salón VIP está listo.', cara='feliz')
        if persona.get('preferencias'):
            self.ui.decir(persona['preferencias'])
        self.ui.decir('Acompáñeme, por favor.')
        llego = self._acompanar('vip')
        if llego:
            self.ui.decir('Llegamos al Salón VIP. Que disfrute su visita.', cara='feliz')
        self._volver()
        return self._resultado('VIP', 'rostro + confirmación', 'acompañado al Salón VIP' if llego else 'no llegó')

    def _regular(self, persona):
        # Regular: conoce el club; saludo y orientación rápida, sin acompañar
        self.ui.paso('Flujo miembro regular')
        self._gesto('saludar')
        self.ui.decir(f'¡Hola, {persona["nombre"].split()[0]}! Qué bueno verle.', cara='feliz')
        self.ui.decir(self.zonas['socios']['indicaciones'])
        respuesta = self.ui.preguntar('¿Le puedo ayudar en algo más?', ['No, gracias', 'Quiero hablar con recepción'],
                                      timeout=15, pistas=PISTAS)
        if respuesta == 'Quiero hablar con recepción':
            self.ui.alertar('Un miembro regular pidió hablar con recepción')
            self.ui.decir('Claro, ya le avisé a recepción.')
        else:
            self.ui.decir('¡Que disfrute su visita!')
        return self._resultado('regular', 'rostro + confirmación', 'indicaciones a la zona de socios')

    def _personal(self, persona):
        # Personal: viene a trabajar; lo más rápido posible, sin preguntas extra
        self.ui.paso('Flujo personal del club')
        self._gesto('levantar')
        area = f' Hoy le esperan en {persona["area"]}.' if persona.get('area') else ''
        self.ui.decir(f'Buen turno, {persona["nombre"].split()[0]}.{area}', cara='feliz')
        self.ui.decir(self.zonas['personal']['indicaciones'])
        return self._resultado('personal', 'rostro + confirmación', 'indicaciones a la entrada de personal')

    def _invitado(self, invitacion):
        # Invitado: primera visita; se avisa al anfitrión y se le acompaña a la zona social a esperarle
        self.ui.paso('Flujo invitado')
        anfitrion = self.personas.get(invitacion['anfitrion'], {}).get('nombre', 'su anfitrión')
        self._gesto('dar_la_mano')
        self.ui.decir(f'Le doy la bienvenida, {invitacion["invitado"].split()[0]}. {anfitrion} ya sabe que llegó.',
                      cara='feliz')
        self.ui.alertar(f'Para {anfitrion}: llegó {invitacion["invitado"]} (invitación {invitacion["codigo"]})')
        self.ui.decir('Le acompaño a la zona social, donde puede esperar.')
        llego = self._acompanar('invitados')
        if llego:
            self.ui.decir(f'Aquí puede esperar a {anfitrion}. ¡Disfrute N Club!', cara='feliz')
        self._volver()
        return self._resultado('invitado', 'código de invitación', 'acompañado a la zona social' if llego else 'no llegó')

    def _externo(self, orden):
        # Externo: se valida el trabajo, se dan las reglas y se le acompaña (no debe circular solo por el club)
        self.ui.paso('Flujo trabajador externo')
        self.ui.decir(f'Gracias, {orden["trabajador"].split()[0]}. Tengo registrado: {orden["trabajo"]} '
                      f'para {orden["empresa"]}.', cara='neutral')
        self.ui.decir(f'Por seguridad le acompaño al acceso de servicio. Allí le recibe {orden["responsable"]}.')
        self.ui.alertar(f'Para {orden["responsable"]}: llegó {orden["trabajador"]} ({orden["empresa"]}, '
                        f'orden {orden["codigo"]})')
        llego = self._acompanar('servicio')
        if llego:
            self.ui.decir('Llegamos al acceso de servicio. Recuerde registrar sus herramientas al salir.')
        self._volver()
        return self._resultado('externo', 'orden de servicio', 'acompañado al acceso de servicio' if llego else 'no llegó')

    def _escalar(self, motivo, categoria):
        self.ui.paso('Se llama a recepción')
        self.ui.decir('Un momento, por favor. Ya viene una persona de recepción a ayudarle.', cara='pensando')
        self.ui.alertar(motivo, urgente=True)
        return self._resultado(categoria, 'no confirmada', 'derivado a recepción')

    # --- Ayudas ---

    def _resultado(self, categoria, confirmacion, resultado):
        return {'categoria': categoria, 'confirmacion': confirmacion, 'resultado': resultado}

    def _gesto(self, nombre):
        # El gesto va en paralelo con lo que dice el robot. Se pide siempre a MC (funciona en el robot real) y
        # además se muestra en la pantalla, porque el MC de la simulación (mc-x86 v1.0.0) no ejecuta gestos.
        self.ui.mostrar_gesto(nombre)

        def hacer():
            if not self.robot.gesto(nombre):
                self.ui.evento(f'(gesto "{nombre}" solo en pantalla: MC no lo ejecutó)')
        threading.Thread(target=hacer, daemon=True).start()

    def _acompanar(self, zona_id):
        zona = self.zonas[zona_id]
        self.ui.paso(f'Acompañando a {zona["nombre"]}')
        self.ui.cara('caminando')
        llego = self.robot.ir_a(zona['x'], zona['y'])
        if not llego:
            self.ui.alertar(f'El robot no pudo llegar a {zona["nombre"]}', urgente=True)
        return llego

    def _volver(self):
        self.ui.paso('Volviendo al puesto')
        self.ui.cara('caminando')
        if not self.robot.volver_al_puesto(self.zonas['puesto']):
            self.ui.alertar('El robot no pudo volver a su puesto', urgente=True)
