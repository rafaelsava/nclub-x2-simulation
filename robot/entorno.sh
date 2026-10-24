# Entorno para correr el puente en el Orin: el ROS y la configuración DDS del robot (como sus propios nodos)
# más los mensajes del SDK ya compilados para ARM, en aimdk_msgs/ junto a este archivo (copiados del SDK del robot).
source ~/.aima/env/bashrc
M="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/aimdk_msgs"
export AMENT_PREFIX_PATH="$M${AMENT_PREFIX_PATH:+:$AMENT_PREFIX_PATH}"
export LD_LIBRARY_PATH="$M/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$M/local/lib/python3.10/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
export RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}
