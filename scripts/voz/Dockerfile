# La voz del robot: faster-whisper (CTranslate2) para escuchar y Piper para hablar, en CPU. Las mismas ruedas existen
# para x86 y para el Orin (ARM).
FROM python:3.11.14-slim
RUN pip install --no-cache-dir --timeout 120 --retries 10 faster-whisper==1.1.1 numpy==2.2.6 requests==2.32.5 \
    piper-tts==1.2.0
ENV PYTHONUNBUFFERED=1 HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /voz
