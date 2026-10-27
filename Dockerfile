FROM python:3.12-slim
WORKDIR /app
COPY server.py ./
COPY static ./static
ENV MB_DB=/data/minibient.db MB_PORT=8080 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8080
CMD ["python", "server.py"]
