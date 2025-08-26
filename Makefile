.PHONY: help install build up down logs shell test clean backup restore deploy

# Konfiguration
DOCKER_COMPOSE_FILE = docker-compose.yml
PROJECT_NAME = web-crawler
PYTHON_VERSION = 3.11
VENV_NAME = venv

# Standard-Ziel
help: ## Zeigt diese Hilfe an
	@echo "Web Crawler & Video Downloader API"
	@echo "=================================="
	@echo ""
	@echo "Verfügbare Befehle:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# Entwicklung
install: ## Installiert alle Abhängigkeiten (virtuelle Umgebung)
	@echo "🔧 Installiere Abhängigkeiten..."
	python$(PYTHON_VERSION) -m venv $(VENV_NAME)
	./$(VENV_NAME)/bin/pip install --upgrade pip
	./$(VENV_NAME)/bin/pip install -r requirements.txt
	@echo "✅ Installation abgeschlossen!"
	@echo "Aktiviere virtuelle Umgebung mit: source $(VENV_NAME)/bin/activate"

install-dev: install ## Installiert Entwicklungs-Abhängigkeiten
	@echo "🔧 Installiere Entwicklungs-Tools..."
	./$(VENV_NAME)/bin/pip install pytest pytest-asyncio pytest-cov black isort flake8
	@echo "✅ Entwicklungs-Installation abgeschlossen!"

run-local: ## Startet die API lokal (virtuelle Umgebung erforderlich)
	@echo "🚀 Starte API lokal..."
	./$(VENV_NAME)/bin/python main.py

# Docker
build: ## Erstellt Docker Images
	@echo "🏗️ Erstelle Docker Images..."
	docker-compose -f $(DOCKER_COMPOSE_FILE) build --no-cache

up: ## Startet alle Services mit Docker Compose
	@echo "🚀 Starte Services..."
	docker-compose -f $(DOCKER_COMPOSE_FILE) up -d
	@echo "✅ Services gestartet!"
	@echo "API: http://localhost:8000"
	@echo "API Docs: http://localhost:8000/docs"
	@echo "Database: localhost:5432"

up-build: ## Erstellt Images neu und startet Services
	@echo "🏗️🚀 Erstelle Images und starte Services..."
	docker-compose -f $(DOCKER_COMPOSE_FILE) up -d --build

down: ## Stoppt alle Services
	@echo "🛑 Stoppe Services..."
	docker-compose -f $(DOCKER_COMPOSE_FILE) down

down-volumes: ## Stoppt Services und entfernt Volumes (⚠️ Daten gehen verloren!)
	@echo "⚠️ Stoppe Services und entferne Volumes..."
	docker-compose -f $(DOCKER_COMPOSE_FILE) down -v

restart: down up ## Neustart aller Services

logs: ## Zeigt Container-Logs an
	docker-compose -f $(DOCKER_COMPOSE_FILE) logs -f

logs-api: ## Zeigt API-Logs an
	docker-compose -f $(DOCKER_COMPOSE_FILE) logs -f web_crawler

logs-db: ## Zeigt Datenbank-Logs an
	docker-compose -f $(DOCKER_COMPOSE_FILE) logs -f postgres

# Development Tools
shell: ## Öffnet Shell im API-Container
	docker-compose -f $(DOCKER_COMPOSE_FILE) exec web_crawler /bin/bash

shell-db: ## Öffnet PostgreSQL Shell
	docker-compose -f $(DOCKER_COMPOSE_FILE) exec postgres psql -U crawler_user -d web_crawler

test: ## Führt Tests aus (lokal)
	@echo "🧪 Führe Tests aus..."
	./$(VENV_NAME)/bin/python -m pytest tests/ -v

test-docker: ## Führt Tests im Docker-Container aus
	docker-compose -f $(DOCKER_COMPOSE_FILE) exec web_crawler python -m pytest tests/ -v

lint: ## Code-Qualitätsprüfung
	@echo "🔍 Prüfe Code-Qualität..."
	./$(VENV_NAME)/bin/black --check .
	./$(VENV_NAME)/bin/isort --check-only .
	./$(VENV_NAME)/bin/flake8 .

format: ## Formatiert Code automatisch
	@echo "✨ Formatiere Code..."
	./$(VENV_NAME)/bin/black .
	./$(VENV_NAME)/bin/isort .

# Datenbank
db-init: ## Initialisiert die Datenbank
	@echo "🗄️ Initialisiere Datenbank..."
	docker-compose -f $(DOCKER_COMPOSE_FILE) exec postgres psql -U crawler_user -d web_crawler -f /docker-entrypoint-initdb.d/init.sql

db-reset: ## Setzt Datenbank zurück (⚠️ alle Daten gehen verloren!)
	@echo "⚠️ Setze Datenbank zurück..."
	docker-compose -f $(DOCKER_COMPOSE_FILE) down
	docker volume rm web-crawler_postgres_data 2>/dev/null || true
	docker-compose -f $(DOCKER_COMPOSE_FILE) up -d postgres
	sleep 5
	make db-init

backup: ## Erstellt Datenbank-Backup
	@echo "💾 Erstelle Datenbank-Backup..."
	mkdir -p backups
	docker-compose -f $(DOCKER_COMPOSE_FILE) exec postgres pg_dump -U crawler_user -d web_crawler > backups/backup_$(shell date +%Y%m%d_%H%M%S).sql
	@echo "✅ Backup erstellt in backups/"

restore: ## Stellt Datenbank aus Backup wieder her (BACKUP_FILE=pfad/zum/backup.sql)
	@if [ -z "$(BACKUP_FILE)" ]; then echo "❌ BACKUP_FILE Parameter erforderlich: make restore BACKUP_FILE=backup.sql"; exit 1; fi
	@echo "🔄 Stelle Datenbank wieder her..."
	docker-compose -f $(DOCKER_COMPOSE_FILE) exec -T postgres psql -U crawler_user -d web_crawler < $(BACKUP_FILE)
	@echo "✅ Wiederherstellung abgeschlossen!"

# Überwachung
status: ## Zeigt Status aller Services an
	@echo "📊 Service Status:"
	docker-compose -f $(DOCKER_COMPOSE_FILE) ps
	@echo ""
	@echo "📊 API Health Check:"
	@curl -s http://localhost:8000/health 2>/dev/null | python3 -m json.tool || echo "API nicht erreichbar"

monitor: ## Zeigt Ressourcenverbrauch an
	docker stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"

# Aufräumen
clean: ## Räumt temporäre Dateien auf
	@echo "🧹 Räume auf..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	rm -rf downloads/* temp/* logs/* 2>/dev/null || true
	@echo "✅ Aufräumen abgeschlossen!"

clean-docker: ## Entfernt nicht verwendete Docker-Ressourcen
	@echo "🧹 Docker aufräumen..."
	docker system prune -f
	docker volume prune -f
	docker network prune -f

# Deployment
deploy: ## Deployment auf Produktionsserver
	@echo "🚀 Deployment wird vorbereitet..."
	@echo "Stelle sicher, dass folgende Dateien vorhanden sind:"
	@echo "  - credentials/google_drive_credentials.json"
	@echo "  - .env (mit Passwörtern und API-Keys)"
	@echo ""
	@echo "Führe folgende Befehle aus:"
	@echo "  1. make build"
	@echo "  2. make up"
	@echo "  3. make status"
	@echo "  4. Konfiguriere Reverse Proxy (nginx/Apache)"
	@echo "  5. SSL-Zertifikat einrichten"

check-credentials: ## Überprüft ob alle Credentials vorhanden sind
	@echo "🔐 Überprüfe Credentials..."
	@test -f credentials/google_drive_credentials.json || (echo "❌ Google Drive Credentials fehlen" && exit 1)
	@test -f .env || (echo "⚠️ .env Datei fehlt - erstelle sie aus .env.example" && exit 1)
	@echo "✅ Grundlegende Credentials vorhanden!"

# Setup
setup: ## Komplettes Setup (Installation + Docker Build)
	@echo "🎯 Vollständiges Setup..."
	make install-dev
	make build
	@echo "✅ Setup abgeschlossen!"
	@echo ""
	@echo "Nächste Schritte:"
	@echo "  1. Credentials einrichten: make check-credentials"
	@echo "  2. Services starten: make up"
	@echo "  3. Status prüfen: make status"

# Hilfsfunktionen
env-example: ## Erstellt .env.example Datei
	@echo "# PostgreSQL Konfiguration" > .env.example
	@echo "POSTGRES_PASSWORD=your_secure_password_here" >> .env.example
	@echo "" >> .env.example
	@echo "# SMTP/Email Konfiguration" >> .env.example
	@echo "SMTP_HOST=smtp.gmail.com" >> .env.example
	@echo "SMTP_PORT=587" >> .env.example
	@echo "SMTP_USERNAME=your_email@gmail.com" >> .env.example
	@echo "SMTP_PASSWORD=your_app_password" >> .env.example
	@echo "EMAIL_FROM=flo.code.dev@gmail.com" >> .env.example
	@echo "EMAIL_TO=flo.code.dev@gmail.com" >> .env.example
	@echo "" >> .env.example
	@echo "# Google Drive Konfiguration" >> .env.example
	@echo "GOOGLE_DRIVE_CREDENTIALS_PATH=/app/credentials/google_drive_credentials.json" >> .env.example
	@echo "GOOGLE_DRIVE_FOLDER_NAME=web-crawler" >> .env.example
	@echo "✅ .env.example erstellt!"

version: ## Zeigt Version und System-Informationen an
	@echo "🔍 System Information:"
	@echo "Docker Version: $(shell docker --version 2>/dev/null || echo 'Docker nicht installiert')"
	@echo "Docker Compose Version: $(shell docker-compose --version 2>/dev/null || echo 'Docker Compose nicht installiert')"
	@echo "Python Version: $(shell python3 --version 2>/dev/null || echo 'Python3 nicht installiert')"
	@echo "Make Version: $(shell make --version 2>/dev/null | head -1 || echo 'Make nicht installiert')"
	@echo ""
	@echo "🐳 Docker Status:"
	@docker info --format '{{.ServerVersion}}' 2>/dev/null || echo "Docker Daemon nicht erreichbar"