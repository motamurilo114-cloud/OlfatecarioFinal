FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py pipeline.py proposta.py gemini.py ./
COPY static ./static

# cache das análises de CNPJ num volume, para sobreviver a cada deploy
ENV OLFA_CACHE_DIR=/data/cache
VOLUME ["/data"]

EXPOSE 8765
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765", "--proxy-headers"]
