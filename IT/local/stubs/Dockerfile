FROM python:3.12-slim

# One dependency, pinned to the same floor as the bot's own aiohttp
RUN pip install --no-cache-dir "aiohttp>=3.9,<4"

WORKDIR /srv
COPY app.py .

EXPOSE 8080 8081
CMD ["python", "app.py"]
