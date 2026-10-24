# Basado en la guía oficial "X2 Sim + MC Deployment" (AimDK v1.1.0, opción Docker)
FROM osrf/ros:humble-desktop-full

ENV DEBIAN_FRONTEND=noninteractive
ENV RMW_IMPLEMENTATION=rmw_fastrtps_cpp

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      cmake \
      curl \
      libcurl4-openssl-dev \
      libeigen3-dev \
      libgflags-dev \
      libgl1 \
      libgl1-mesa-dri \
      libglx-mesa0 \
      libncurses-dev \
      liboctomap1.9 \
      libopencv-dev \
      libscrypt0 \
      libyaml-cpp-dev \
      mesa-utils \
      pkg-config \
      python3-colcon-common-extensions \
      python3-pip \
      ros-humble-cv-bridge \
      ros-humble-grid-map-msgs \
      ros-humble-grid-map-ros \
      ros-humble-joy \
      ros-humble-rmw-fastrtps-cpp \
      x11-xserver-utils \
    && rm -rf /var/lib/apt/lists/*

# Entorno común: lo cargan tanto las shells interactivas como los scripts de ./x2
RUN printf '%s\n' \
      'source /opt/ros/humble/setup.bash' \
      'export RMW_IMPLEMENTATION=rmw_fastrtps_cpp' \
      'if [ -f /workspace/aimdk/install/local_setup.bash ]; then source /workspace/aimdk/install/local_setup.bash; fi' \
      > /etc/x2_env.sh \
    && echo 'source /etc/x2_env.sh' >> /root/.bashrc

WORKDIR /workspace
CMD ["sleep", "infinity"]
