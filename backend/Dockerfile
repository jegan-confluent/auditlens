FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir -r /tmp/backend-requirements.txt

COPY --chown=1000:1000 backend /app/backend
COPY --chown=1000:1000 src /app/src

RUN mkdir -p /var/lib/auditlens && chown 1000:1000 /var/lib/auditlens

EXPOSE 8080

ENTRYPOINT ["python", "/app/backend/docker_entrypoint.py"]
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
