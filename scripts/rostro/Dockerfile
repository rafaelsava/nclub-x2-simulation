# Servicio de reconocimiento facial: el componente FaceRecognition Lite (YuNet + SFace de OpenCV) con las mismas
# versiones fijadas en su repositorio. Si cambia OpenCV cambia model_version y las plantillas de Supabase dejan de servir.
FROM python:3.11.14-slim
RUN pip install --no-cache-dir numpy==2.2.6 opencv-python-headless==4.12.0.88 pillow==11.3.0 psutil==7.0.0
ENV PYTHONPATH=/face/src PYTHONUNBUFFERED=1
WORKDIR /rostro
