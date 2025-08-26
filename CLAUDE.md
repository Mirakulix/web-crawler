# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a web crawler and video downloader service built with FastAPI that provides REST API endpoints for crawling websites and downloading videos. The system includes PostgreSQL database storage, Google Drive integration, email notifications, and supports Docker deployment.

## Key Commands

### Development Setup
- `make install` - Install Python dependencies in virtual environment
- `make install-dev` - Install development dependencies including linting tools
- `source venv/bin/activate` - Activate virtual environment for local development

### Docker Operations
- `make build` - Build Docker images
- `make up` - Start all services (API, PostgreSQL, Redis)
- `make down` - Stop all services
- `make logs` - View container logs
- `make shell` - Open shell in API container

### Local Development
- `make run-local` - Run API locally (requires virtual environment activation)
- `./venv/bin/python main.py` - Direct local execution

### Testing and Quality
- `make test` - Run tests locally
- `make lint` - Run code quality checks (black, isort, flake8)
- `make format` - Auto-format code
- Linting commands: `./venv/bin/black .`, `./venv/bin/isort .`, `./venv/bin/flake8 .`

### Database Operations
- `make db-init` - Initialize database
- `make db-reset` - Reset database (destroys data)
- `make shell-db` - Open PostgreSQL shell
- `make backup` - Create database backup
- `make restore BACKUP_FILE=path/to/backup.sql` - Restore from backup

### Monitoring
- `make status` - Check service status and API health
- `make monitor` - View resource usage
- API available at: http://localhost:8000
- API docs at: http://localhost:8000/docs

## Architecture Overview

### Core Components
- **main.py**: FastAPI application with REST endpoints
- **website_crawler.py**: Website crawling engine with PDF generation
- **video_downloader.py**: Video download service using yt-dlp and Selenium
- **services/**: Modular services for database, email, and Google Drive integration

### Database Schema
The PostgreSQL database (`sql/init.sql`) includes:
- Jobs tracking with status management
- Crawled pages with full-text search
- Downloaded videos/images metadata
- Email logs and Google Drive file tracking
- Performance indices and search functions

### FastAPI Endpoints
- `POST /crawl` - Start website crawling job
- `POST /download-video` - Start video download job  
- `GET /status/{job_id}` - Check job status
- `GET /result/{job_id}` - Download result ZIP
- `GET /jobs` - List all jobs
- `GET /health` - Health check

### Service Integration
- **Database**: PostgreSQL with SQLAlchemy ORM for job tracking and metadata
- **Google Drive**: Automatic upload of generated PDFs and videos
- **Email**: SMTP integration for result notifications
- **Background Processing**: ThreadPoolExecutor for async job execution

### Configuration
Environment variables managed through `.env` file (see `.env.example`):
- PostgreSQL connection settings
- SMTP email configuration
- Google Drive API credentials path
- Application logging levels

### Crawling Features
- Multiple crawl scopes: hierarchical, domain-only, all URLs
- PDF generation from web pages using WeasyPrint
- Image extraction and processing
- Single PDF compilation option
- Robots.txt compliance

### Video Download Features
- yt-dlp integration for video platforms
- Selenium browser automation for complex sites
- Screen recording capabilities (when display available)
- Multiple format support and quality selection

## Development Notes

- Code is primarily in German with some English comments
- Uses comprehensive error handling and logging
- Supports graceful fallbacks when optional dependencies unavailable
- Implements job queuing system for background processing
- Includes Docker health checks and proper container shutdown
- Database includes full-text search capabilities with German language support