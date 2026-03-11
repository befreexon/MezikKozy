FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    gettext \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Překlady a statické soubory při buildu (bez potřeby DB nebo Redis).
# Všechny nastavení mají výchozí hodnoty, takže spuštění funguje i bez env proměnných.
RUN python manage.py compilemessages && \
    python manage.py collectstatic --no-input

# Neprivilegovaný uživatel pro runtime
RUN useradd -u 1000 -r django && \
    chmod +x entrypoint.sh

EXPOSE 8000

USER django

ENTRYPOINT ["./entrypoint.sh"]
