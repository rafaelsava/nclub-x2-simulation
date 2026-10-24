# Probar con el AgiBot X2 real

El mismo puente de PIBOT mueve al robot real en vez del de MuJoCo. El PC (con el contenedor `x2-sim`) se conecta por cable al robot y habla con su control de movimiento (MC) por ROS 2.

En modo real, el puente cambia cuatro cosas:
- **Voz:** el robot dice las frases por su parlante (`PlayTts`).
- **Velocidad:** camina a 0.2 m/s, la mínima de MC.
- **Levantarse:** nunca se levanta solo, y PIBOT no muestra el botón "Levantar robot".
- **Lugares:** usa `scripts/pibot/destinos_real.json`, no los del lobby de MuJoCo.

> Esto no se ha probado todavía en el robot: solo en la simulación. Hagan la primera prueba despacio y con el control remoto en la mano.

## Antes de ir al robot

- **Modelo:** tiene que ser un **X2 Ultra**. El X2 EDU no tiene voz, pantalla ni cámaras.
- **Versión del SDK:** debe coincidir con el firmware del robot. Este proyecto usa AimDK **v1.1.0**. Revisen la versión del firmware en la app; si no es 1.1.x, hay que usar el SDK de esa versión.
- **Acceso SSH** al módulo de desarrollo (Orin, `10.0.1.41`): las credenciales las da el soporte de AgiBot o los organizadores. Se necesita para leer el `ROS_DOMAIN_ID`.
- **No correr nada en `10.0.1.40`,** el computador del control de movimiento: el manual lo prohíbe.

## 1. Conectar el PC

1. Conecten un cable de red entre el PC y el **puerto de desarrollo** de la espalda del robot. Wi-Fi no sirve para ROS: el manual lo deja solo para depurar.
2. Pongan una IP fija en esa interfaz. Busquen el nombre con `ip link`.
   ```bash
   sudo ip addr add 10.0.1.2/24 dev <interfaz>      # temporal, hasta reiniciar
   # o, con NetworkManager:
   # nmcli con add type ethernet ifname <interfaz> con-name x2 ipv4.method manual ipv4.addresses 10.0.1.2/24 && nmcli con up x2
   ```
3. Lean el dominio ROS del robot y guárdenlo en `real/robot.env` (copien `robot.env.example`):
   ```bash
   ssh agi@10.0.1.41 'grep ROS_DOMAIN_ID ~/.aima/env/bashrc'
   ```
4. Cierren la simulación con Ctrl+C en las terminales de `./x2 sim` y `./x2 mc`. El contenedor sigue arriba. Con el MC simulado corriendo, los dos MC publicarían los mismos tópicos; los comandos del robot real se niegan a arrancar si lo detectan.
5. Revisen la conexión:
   ```bash
   ./x2 real-check
   ```
   Debe responder el modo actual de MC. Esto no mueve al robot.

   Si no responde: copien la configuración DDS del robot a `real/` y repitan.
   ```bash
   scp agi@10.0.1.41:/home/agi/.aima/env/ros_dds_configuration.xml real/
   ```

## 2. Preparar el robot (al menos dos personas)

- **Encender y poner de pie:** prendan el robot y pónganlo de pie con el control remoto o la app, como dice el manual.
- **Espacio:** despejen unos 3 m alrededor y el camino hacia cada lugar. El robot va en línea recta y **no esquiva obstáculos**.
- **Control remoto:** una persona lo tiene en la mano. Si mueve las palancas, el control tiene prioridad y el robot ignora a PIBOT. Al soltarlas, pasa un momento antes de que PIBOT vuelva a mandar.
- **Parada de emergencia** (según el manual): modo de torque cero, **L1 + R1 + Create**. El robot se desploma: otra persona debe sostenerlo del asa de la espalda. Para echarlo con calma, primero amortiguado (**L2 + R2 + Create**) y luego torque cero.

## 3. Primera prueba

1. Arranquen el puente, en lugar de `./x2 pibot`. Si quieren lenguaje natural, corran `./x2 llm` antes; si quieren reconocimiento facial, `./x2 rostro`.
   ```bash
   ./x2 pibot-real
   ```
   Si dice que no llega la odometría, revisen el paso 1.
2. En PIBOT, arriba a la derecha, elijan "AgiBot X2 en MuJoCo". Al conectarse cambia a **AgiBot X2 real**, y el mapa en vivo muestra la posición real.
3. **Lugares del robot real:** la odometría empieza en (0, 0), donde se prendió el robot, y ahí queda **Recepción**: el puesto al que vuelve.
   - Con el control, lleven el robot hasta cada sitio.
   - En "Lugares", creen el lugar y pulsen **Aquí está el robot**.
   - Al final, **Guardar en el robot**. Se guarda en `destinos_real.json`; los de MuJoCo no se tocan.
   - En PIBOT los lugares son unos solos: para volver a la simulación, use "Restablecer lugares de ejemplo".
4. **Prueben por partes:**
   - un flujo que solo hable, por ejemplo con el asistente y "Solo lo saluda";
   - después, que guíe a un lugar a 2 o 3 m, con el camino libre.

   El robot vuelve solo a Recepción unos segundos después de terminar.

## Lo que falta probar en el robot

- **Voz:** si `PlayTts` responde pero no se oye, puede que haya que desactivar el sistema de interacción de fábrica (sección 8.1 de la documentación del SDK).
- **Gestos:** son los movimientos predefinidos de MC, que la simulación no ejecuta.
- **Odometría:** se desvía con el tiempo. Si los lugares dejan de coincidir, lleven el robot a Recepción, reinícienlo y vuelvan a marcar los lugares.
- **Cámara:** el reconocimiento facial sigue usando la cámara del portátil. Usar la de la cabeza del robot es un paso aparte.
