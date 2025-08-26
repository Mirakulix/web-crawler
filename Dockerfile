FROM python:3.11-slim

# System-Abhängigkeiten installieren
RUN apt-get update && apt-get install -y \
    # Basis-Tools
    curl \
    wget \
    git \
    # Browser-Abhängigkeiten für Selenium
    chromium \
    chromium-driver \
    # WeasyPrint-Abhängigkeiten
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    # Video-Processing-Abhängigkeiten
    ffmpeg \
    # Bildverarbeitung
    libjpeg-dev \
    libpng-dev \
    # Cleanup
    && rm -rf /var/lib/apt/lists/*

# Arbeitsverzeichnis setzen
WORKDIR /app

# Python-Abhängigkeiten kopieren und installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chrome/Chromium für Selenium konfigurieren
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV DISPLAY=:99

# App-Code kopieren
COPY . .

# Downloads-Verzeichnis erstellen
RUN mkdir -p /app/downloads /app/temp

# Benutzer für Sicherheit erstellen
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /app/downloads /app/temp
USER appuser

# Port freigeben
EXPOSE 8000

# Health Check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Startbefehl
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]