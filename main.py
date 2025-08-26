#!/usr/bin/env python3
"""
FastAPI Web Crawler Service
Bietet Video-Download und Website-Crawling als REST API
"""

import os
import asyncio
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import uuid
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, BackgroundTasks, File, UploadFile, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl, Field
import uvicorn

# Import unserer Module
from video_downloader import VideoDownloader, integrate_with_crawler
from website_crawler import WebsiteCrawler, CrawlScope

# FastAPI App initialisieren
app = FastAPI(
    title="Web Crawler & Video Downloader API",
    description="REST API für Website-Crawling und Video-Downloads",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Middleware hinzufügen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Globaler Thread Pool
executor = ThreadPoolExecutor(max_workers=4)

# Globale Dictionaries für Job-Tracking
jobs: Dict[str, Dict[str, Any]] = {}
job_results: Dict[str, Dict[str, Any]] = {}

# Pydantic Models
class CrawlRequest(BaseModel):
    base_url: HttpUrl
    url_title: Optional[str] = None
    max_urls: int = Field(default=100, ge=1, le=10000)
    single_pdf: bool = False
    delete_individual_pdfs: bool = False
    crawl_scope: str = Field(default="hierarchical", regex="^(hierarchical|domain_only|all_urls)$")

class VideoDownloadRequest(BaseModel):
    url: HttpUrl
    output_dir: Optional[str] = None

class JobStatus(BaseModel):
    job_id: str
    status: str  # pending, running, completed, error
    progress: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    error_message: Optional[str] = None
    result_path: Optional[str] = None

class CrawlResponse(BaseModel):
    job_id: str
    status: str
    message: str

# Hilfsfunktionen
def create_job_id() -> str:
    return str(uuid.uuid4())

def get_output_directory(job_id: str, prefix: str = "job") -> Path:
    """Erstellt temporäres Ausgabeverzeichnis für Job"""
    temp_dir = Path(tempfile.gettempdir()) / f"{prefix}_{job_id}"
    temp_dir.mkdir(exist_ok=True)
    return temp_dir

def create_zip_from_directory(directory: Path, zip_path: Path) -> None:
    """Erstellt ZIP-Archiv aus Verzeichnis"""
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in directory.rglob('*'):
            if file_path.is_file():
                arcname = file_path.relative_to(directory)
                zipf.write(file_path, arcname)

async def run_in_executor(func, *args):
    """Führt Funktion im Thread-Pool aus"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)

def crawl_website_sync(job_id: str, request: CrawlRequest) -> None:
    """Synchrone Website-Crawling-Funktion"""
    try:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["start_time"] = datetime.now().isoformat()
        
        # Scope konvertieren
        scope_map = {
            "hierarchical": CrawlScope.HIERARCHICAL,
            "domain_only": CrawlScope.DOMAIN_ONLY,
            "all_urls": CrawlScope.ALL_URLS
        }
        crawl_scope = scope_map[request.crawl_scope]
        
        # Output-Directory
        output_dir = get_output_directory(job_id, "crawl")
        
        # URL-Titel generieren wenn nicht angegeben
        url_title = request.url_title
        if not url_title:
            url_title = str(request.base_url).replace('https://', '').replace('http://', '').replace('www.','').rstrip('/')
            url_title = url_title.replace('/', '-').replace('.', '_').strip("-")
        
        # Crawler initialisieren und starten
        crawler = WebsiteCrawler(
            base_url=str(request.base_url),
            url_title=str(output_dir / url_title),
            max_urls=request.max_urls,
            single_pdf=request.single_pdf,
            delete_individual_pdfs=request.delete_individual_pdfs,
            crawl_scope=crawl_scope
        )
        
        # Crawling starten
        crawler.crawl()
        
        # Ergebnis-ZIP erstellen
        zip_path = output_dir.parent / f"crawl_result_{job_id}.zip"
        create_zip_from_directory(crawler.output_dir, zip_path)
        
        # Job als abgeschlossen markieren
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["end_time"] = datetime.now().isoformat()
        jobs[job_id]["result_path"] = str(zip_path)
        
        # Ergebnis-Statistiken speichern
        job_results[job_id] = {
            "type": "crawl",
            "statistics": crawler.stats,
            "output_directory": str(crawler.output_dir),
            "zip_path": str(zip_path),
            "pages_processed": len(crawler.pages)
        }
        
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error_message"] = str(e)
        jobs[job_id]["end_time"] = datetime.now().isoformat()

def download_video_sync(job_id: str, request: VideoDownloadRequest) -> None:
    """Synchrone Video-Download-Funktion"""
    try:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["start_time"] = datetime.now().isoformat()
        
        # Output-Directory
        output_dir = get_output_directory(job_id, "video")
        
        # Video-Downloader initialisieren
        downloader = VideoDownloader(
            base_url=str(request.url),
            output_dir=str(output_dir)
        )
        
        # Video herunterladen
        videos = downloader.process_url(str(request.url))
        
        # Zusammenfassung erstellen
        downloader.create_video_summary()
        
        # Ergebnis-ZIP erstellen
        zip_path = output_dir.parent / f"video_result_{job_id}.zip"
        create_zip_from_directory(output_dir, zip_path)
        
        # Job als abgeschlossen markieren
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["end_time"] = datetime.now().isoformat()
        jobs[job_id]["result_path"] = str(zip_path)
        
        # Ergebnis-Statistiken speichern
        job_results[job_id] = {
            "type": "video_download",
            "statistics": downloader.stats,
            "output_directory": str(output_dir),
            "zip_path": str(zip_path),
            "videos_downloaded": len(videos)
        }
        
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error_message"] = str(e)
        jobs[job_id]["end_time"] = datetime.now().isoformat()

# API Endpunkte

@app.get("/", response_model=dict)
async def root():
    """API Info"""
    return {
        "service": "Web Crawler & Video Downloader API",
        "version": "1.0.0",
        "endpoints": {
            "crawl": "POST /crawl - Website crawlen",
            "download_video": "POST /download-video - Video herunterladen", 
            "status": "GET /status/{job_id} - Job-Status abfragen",
            "result": "GET /result/{job_id} - Ergebnis herunterladen",
            "jobs": "GET /jobs - Alle Jobs auflisten",
            "docs": "GET /docs - API-Dokumentation"
        }
    }

@app.post("/crawl", response_model=CrawlResponse)
async def crawl_website(request: CrawlRequest, background_tasks: BackgroundTasks):
    """Website crawlen"""
    job_id = create_job_id()
    
    # Job registrieren
    jobs[job_id] = {
        "type": "crawl",
        "status": "pending",
        "request": request.dict(),
        "created_time": datetime.now().isoformat()
    }
    
    # Background-Task starten
    background_tasks.add_task(crawl_website_sync, job_id, request)
    
    return CrawlResponse(
        job_id=job_id,
        status="pending",
        message=f"Website-Crawling gestartet für {request.base_url}"
    )

@app.post("/download-video", response_model=CrawlResponse)
async def download_video(request: VideoDownloadRequest, background_tasks: BackgroundTasks):
    """Video herunterladen"""
    job_id = create_job_id()
    
    # Job registrieren
    jobs[job_id] = {
        "type": "video_download",
        "status": "pending", 
        "request": request.dict(),
        "created_time": datetime.now().isoformat()
    }
    
    # Background-Task starten
    background_tasks.add_task(download_video_sync, job_id, request)
    
    return CrawlResponse(
        job_id=job_id,
        status="pending",
        message=f"Video-Download gestartet für {request.url}"
    )

@app.get("/status/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Job-Status abfragen"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    
    job = jobs[job_id]
    return JobStatus(
        job_id=job_id,
        status=job["status"],
        progress=job.get("progress"),
        start_time=job.get("start_time"),
        end_time=job.get("end_time"),
        error_message=job.get("error_message"),
        result_path=job.get("result_path")
    )

@app.get("/result/{job_id}")
async def download_result(job_id: str):
    """Ergebnis-ZIP herunterladen"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    
    job = jobs[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job noch nicht abgeschlossen")
    
    result_path = job.get("result_path")
    if not result_path or not os.path.exists(result_path):
        raise HTTPException(status_code=404, detail="Ergebnis-Datei nicht gefunden")
    
    # Dateiname für Download
    job_type = job["type"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{job_type}_result_{timestamp}.zip"
    
    return FileResponse(
        path=result_path,
        filename=filename,
        media_type="application/zip"
    )

@app.get("/jobs", response_model=List[dict])
async def list_jobs():
    """Alle Jobs auflisten"""
    job_list = []
    for job_id, job_info in jobs.items():
        job_summary = {
            "job_id": job_id,
            "type": job_info["type"],
            "status": job_info["status"],
            "created_time": job_info["created_time"],
            "start_time": job_info.get("start_time"),
            "end_time": job_info.get("end_time")
        }
        
        # Zusätzliche Info je nach Job-Typ
        if job_id in job_results:
            result = job_results[job_id]
            if result["type"] == "crawl":
                job_summary["pages_processed"] = result.get("pages_processed", 0)
            elif result["type"] == "video_download":
                job_summary["videos_downloaded"] = result.get("videos_downloaded", 0)
        
        job_list.append(job_summary)
    
    return job_list

@app.get("/job/{job_id}/details")
async def get_job_details(job_id: str):
    """Detaillierte Job-Informationen"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    
    job_info = jobs[job_id]
    response = {
        "job_id": job_id,
        "job_info": job_info
    }
    
    # Ergebnis-Details hinzufügen falls verfügbar
    if job_id in job_results:
        response["results"] = job_results[job_id]
    
    return response

@app.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """Job und Ergebnisse löschen"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    
    # Ergebnis-Dateien löschen
    job = jobs[job_id]
    result_path = job.get("result_path")
    if result_path and os.path.exists(result_path):
        try:
            os.remove(result_path)
        except Exception as e:
            pass  # Ignorieren falls bereits gelöscht
    
    # Job aus Dictionaries entfernen
    del jobs[job_id]
    if job_id in job_results:
        del job_results[job_id]
    
    return {"message": f"Job {job_id} wurde gelöscht"}

@app.get("/health")
async def health_check():
    """Health Check Endpunkt"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_jobs": len([j for j in jobs.values() if j["status"] in ["pending", "running"]]),
        "total_jobs": len(jobs)
    }

# Cleanup-Funktion für alte Jobs
@app.on_event("startup")
async def startup_event():
    """Startup-Logik"""
    print("🚀 Web Crawler & Video Downloader API gestartet")
    print("📚 Dokumentation: http://localhost:8000/docs")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup beim Shutdown"""
    print("🛑 API wird heruntergefahren...")
    executor.shutdown(wait=True)
    
    # Temporäre Dateien aufräumen
    temp_dir = Path(tempfile.gettempdir())
    for job_dir in temp_dir.glob("*_*-*-*-*-*"):
        try:
            if job_dir.is_dir():
                shutil.rmtree(job_dir)
        except Exception:
            pass  # Ignorieren falls Zugriffsfehler

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )