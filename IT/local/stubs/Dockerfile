FROM python:3.12-slim

# One dependency, pinned to the same floor as the bot's own aiohttp
RUN pip install --no-cache-dir "aiohttp>=3.9,<4"

WORKDIR /srv
COPY app.py .

# Both ports are above 1024 and the stub writes nothing, so it needs no root.
RUN useradd --system --no-create-home stub
USER stub

EXPOSE 8080 8081
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2)"]
CMD ["python", "app.py"]
