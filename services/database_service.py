#!/usr/bin/env python3
"""
Database Service für PostgreSQL Integration
"""

import os
import uuid
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import logging
import json

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False

logger = logging.getLogger(__name__)

class DatabaseService:
    """Service für PostgreSQL Datenbank-Operationen"""
    
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL', 'postgresql://crawler_user:crawler_password@localhost:5432/web_crawler')
        self.engine = None
        self.Session = None
        self.database_available = DATABASE_AVAILABLE
        
        if not DATABASE_AVAILABLE:
            logger.warning("Database libraries not available. Install psycopg2-binary and sqlalchemy")
            return
        
        self._init_database()
    
    def _init_database(self) -> bool:
        """Initialisiert Datenbankverbindung"""
        try:
            self.engine = create_engine(self.database_url)
            self.Session = sessionmaker(bind=self.engine)
            
            # Verbindung testen
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            logger.info("Database connection established")
            return True
            
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return False
    
    def create_job(self, job_type: str, request_data: dict) -> str:
        """
        Erstellt neuen Job in der Datenbank
        
        Args:
            job_type: Art des Jobs (crawl/video_download)
            request_data: Request-Daten als Dict
            
        Returns:
            Job UUID als String
        """
        try:
            if not self.engine:
                return None
            
            job_id = str(uuid.uuid4())
            
            with self.engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO jobs (id, job_type, status, request_data, created_at)
                    VALUES (:id, :job_type, 'pending', :request_data, :created_at)
                """), {
                    'id': job_id,
                    'job_type': job_type,
                    'request_data': json.dumps(request_data),
                    'created_at': datetime.now()
                })
                conn.commit()
            
            logger.info(f"Job created in database: {job_id}")
            return job_id
            
        except Exception as e:
            logger.error(f"Error creating job in database: {e}")
            return None
    
    def update_job_status(
        self, 
        job_id: str, 
        status: str, 
        error_message: Optional[str] = None,
        result_path: Optional[str] = None,
        statistics: Optional[dict] = None
    ) -> bool:
        """
        Aktualisiert Job-Status
        
        Args:
            job_id: Job ID
            status: Neuer Status (pending/running/completed/error)
            error_message: Fehlermeldung falls status=error
            result_path: Pfad zu Ergebnis-Dateien
            statistics: Job-Statistiken
            
        Returns:
            True wenn erfolgreich
        """
        try:
            if not self.engine:
                return False
            
            update_fields = {'status': status}
            
            if status == 'running':
                update_fields['started_at'] = datetime.now()
            elif status in ['completed', 'error']:
                update_fields['completed_at'] = datetime.now()
            
            if error_message:
                update_fields['error_message'] = error_message
            
            if result_path:
                update_fields['result_path'] = result_path
            
            if statistics:
                update_fields['statistics'] = json.dumps(statistics)
            
            # SQL-Statement dynamisch erstellen
            set_clause = ', '.join([f"{k} = :{k}" for k in update_fields.keys()])
            
            with self.engine.connect() as conn:
                conn.execute(text(f"""
                    UPDATE jobs SET {set_clause}
                    WHERE id = :job_id
                """), {**update_fields, 'job_id': job_id})
                conn.commit()
            
            logger.info(f"Job status updated: {job_id} -> {status}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating job status: {e}")
            return False
    
    def save_crawled_page(
        self, 
        job_id: str, 
        url: str, 
        title: Optional[str] = None,
        content_text: Optional[str] = None,
        html_content: Optional[str] = None,
        pdf_path: Optional[str] = None,
        word_count: Optional[int] = None,
        page_size_kb: Optional[float] = None,
        response_time_ms: Optional[int] = None
    ) -> Optional[str]:
        """
        Speichert gecrawlte Seite in Datenbank
        
        Returns:
            Page ID oder None bei Fehler
        """
        try:
            if not self.engine:
                return None
            
            page_id = str(uuid.uuid4())
            
            with self.engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO crawled_pages (
                        id, job_id, url, title, content_text, html_content, 
                        pdf_path, word_count, page_size_kb, response_time_ms, extracted_at
                    ) VALUES (
                        :id, :job_id, :url, :title, :content_text, :html_content,
                        :pdf_path, :word_count, :page_size_kb, :response_time_ms, :extracted_at
                    )
                """), {
                    'id': page_id,
                    'job_id': job_id,
                    'url': url,
                    'title': title,
                    'content_text': content_text,
                    'html_content': html_content,
                    'pdf_path': pdf_path,
                    'word_count': word_count,
                    'page_size_kb': page_size_kb,
                    'response_time_ms': response_time_ms,
                    'extracted_at': datetime.now()
                })
                conn.commit()
            
            logger.debug(f"Crawled page saved: {url}")
            return page_id
            
        except Exception as e:
            logger.error(f"Error saving crawled page: {e}")
            return None
    
    def store_crawled_page(self, job_id: str, url: str, title: str, content_text: str, html_content: str, pdf_path: str, word_count: int, page_size_kb: float) -> Optional[str]:
        """Alias for save_crawled_page for compatibility"""
        return self.save_crawled_page(
            job_id=job_id,
            url=url, 
            title=title,
            content_text=content_text,
            html_content=html_content,
            pdf_path=pdf_path,
            word_count=word_count,
            page_size_kb=page_size_kb
        )
    
    def save_downloaded_video(
        self,
        job_id: str,
        source_url: str,
        file_path: str,
        video_title: Optional[str] = None,
        file_size_mb: Optional[float] = None,
        duration_seconds: Optional[int] = None,
        format: Optional[str] = None,
        resolution: Optional[str] = None,
        download_method: Optional[str] = None,
        google_drive_file_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Optional[str]:
        """
        Speichert heruntergeladenes Video in Datenbank
        
        Returns:
            Video ID oder None bei Fehler
        """
        try:
            if not self.engine:
                return None
            
            video_id = str(uuid.uuid4())
            
            with self.engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO downloaded_videos (
                        id, job_id, source_url, video_title, file_path, file_size_mb,
                        duration_seconds, format, resolution, download_method,
                        google_drive_file_id, metadata, downloaded_at
                    ) VALUES (
                        :id, :job_id, :source_url, :video_title, :file_path, :file_size_mb,
                        :duration_seconds, :format, :resolution, :download_method,
                        :google_drive_file_id, :metadata, :downloaded_at
                    )
                """), {
                    'id': video_id,
                    'job_id': job_id,
                    'source_url': source_url,
                    'video_title': video_title,
                    'file_path': file_path,
                    'file_size_mb': file_size_mb,
                    'duration_seconds': duration_seconds,
                    'format': format,
                    'resolution': resolution,
                    'download_method': download_method,
                    'google_drive_file_id': google_drive_file_id,
                    'metadata': json.dumps(metadata) if metadata else None,
                    'downloaded_at': datetime.now()
                })
                conn.commit()
            
            logger.debug(f"Downloaded video saved: {video_title or source_url}")
            return video_id
            
        except Exception as e:
            logger.error(f"Error saving downloaded video: {e}")
            return None
    
    def save_downloaded_image(
        self,
        job_id: str,
        source_url: str,
        file_path: str,
        page_id: Optional[str] = None,
        image_alt_text: Optional[str] = None,
        file_size_kb: Optional[float] = None,
        width_px: Optional[int] = None,
        height_px: Optional[int] = None,
        format: Optional[str] = None,
        google_drive_file_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Optional[str]:
        """
        Speichert heruntergeladenes Bild in Datenbank
        
        Returns:
            Image ID oder None bei Fehler
        """
        try:
            if not self.engine:
                return None
            
            image_id = str(uuid.uuid4())
            
            # Bild-Hash für Duplikatserkennung
            image_hash = None
            is_duplicate = False
            
            try:
                if Path(file_path).exists():
                    with open(file_path, 'rb') as f:
                        image_hash = hashlib.md5(f.read()).hexdigest()
                    
                    # Prüfen ob bereits vorhanden
                    with self.engine.connect() as conn:
                        result = conn.execute(text("""
                            SELECT id FROM downloaded_images WHERE image_hash = :hash
                        """), {'hash': image_hash}).fetchone()
                        
                        if result:
                            is_duplicate = True
            except Exception as e:
                logger.warning(f"Error calculating image hash: {e}")
            
            with self.engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO downloaded_images (
                        id, job_id, page_id, source_url, image_alt_text, file_path,
                        file_size_kb, width_px, height_px, format, google_drive_file_id,
                        image_hash, is_duplicate, metadata, downloaded_at
                    ) VALUES (
                        :id, :job_id, :page_id, :source_url, :image_alt_text, :file_path,
                        :file_size_kb, :width_px, :height_px, :format, :google_drive_file_id,
                        :image_hash, :is_duplicate, :metadata, :downloaded_at
                    )
                """), {
                    'id': image_id,
                    'job_id': job_id,
                    'page_id': page_id,
                    'source_url': source_url,
                    'image_alt_text': image_alt_text,
                    'file_path': file_path,
                    'file_size_kb': file_size_kb,
                    'width_px': width_px,
                    'height_px': height_px,
                    'format': format,
                    'google_drive_file_id': google_drive_file_id,
                    'image_hash': image_hash,
                    'is_duplicate': is_duplicate,
                    'metadata': json.dumps(metadata) if metadata else None,
                    'downloaded_at': datetime.now()
                })
                conn.commit()
            
            logger.debug(f"Downloaded image saved: {source_url} (duplicate: {is_duplicate})")
            return image_id
            
        except Exception as e:
            logger.error(f"Error saving downloaded image: {e}")
            return None
    
    def log_email_sent(
        self,
        job_id: str,
        recipient_email: str,
        subject: str,
        status: str = 'sent',
        error_message: Optional[str] = None,
        attachment_count: int = 0
    ) -> bool:
        """
        Protokolliert versendete E-Mails
        
        Returns:
            True wenn erfolgreich
        """
        try:
            if not self.engine:
                return False
            
            with self.engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO email_logs (
                        job_id, recipient_email, subject, sent_at, status, 
                        error_message, attachment_count
                    ) VALUES (
                        :job_id, :recipient_email, :subject, :sent_at, :status,
                        :error_message, :attachment_count
                    )
                """), {
                    'job_id': job_id,
                    'recipient_email': recipient_email,
                    'subject': subject,
                    'sent_at': datetime.now(),
                    'status': status,
                    'error_message': error_message,
                    'attachment_count': attachment_count
                })
                conn.commit()
            
            logger.info(f"Email log saved: {recipient_email} ({status})")
            return True
            
        except Exception as e:
            logger.error(f"Error logging email: {e}")
            return False
    
    def save_google_drive_file(
        self,
        job_id: str,
        local_file_path: str,
        google_drive_file_id: str,
        google_drive_file_name: str,
        file_type: str,
        file_size_mb: Optional[float] = None,
        drive_folder_id: Optional[str] = None,
        share_url: Optional[str] = None
    ) -> bool:
        """
        Speichert Google Drive Datei-Info
        
        Returns:
            True wenn erfolgreich
        """
        try:
            if not self.engine:
                return False
            
            with self.engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO google_drive_files (
                        job_id, local_file_path, google_drive_file_id, google_drive_file_name,
                        file_type, file_size_mb, drive_folder_id, share_url, uploaded_at
                    ) VALUES (
                        :job_id, :local_file_path, :google_drive_file_id, :google_drive_file_name,
                        :file_type, :file_size_mb, :drive_folder_id, :share_url, :uploaded_at
                    )
                """), {
                    'job_id': job_id,
                    'local_file_path': local_file_path,
                    'google_drive_file_id': google_drive_file_id,
                    'google_drive_file_name': google_drive_file_name,
                    'file_type': file_type,
                    'file_size_mb': file_size_mb,
                    'drive_folder_id': drive_folder_id,
                    'share_url': share_url,
                    'uploaded_at': datetime.now()
                })
                conn.commit()
            
            logger.info(f"Google Drive file logged: {google_drive_file_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving Google Drive file info: {e}")
            return False
    
    def get_job_statistics(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Holt Job-Statistiken aus der Datenbank
        
        Returns:
            Dict mit Statistiken oder None
        """
        try:
            if not self.engine:
                return None
            
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT * FROM job_statistics WHERE id = :job_id
                """), {'job_id': job_id}).fetchone()
                
                if result:
                    return dict(result._mapping)
                
            return None
            
        except Exception as e:
            logger.error(f"Error getting job statistics: {e}")
            return None
    
    def search_content(self, search_query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Full-Text-Suche in gecrawlten Inhalten
        
        Args:
            search_query: Suchbegriff
            limit: Maximale Anzahl Ergebnisse
            
        Returns:
            Liste mit Suchergebnissen
        """
        try:
            if not self.engine:
                return []
            
            with self.engine.connect() as conn:
                results = conn.execute(text("""
                    SELECT * FROM search_content(:search_query)
                    LIMIT :limit
                """), {
                    'search_query': search_query,
                    'limit': limit
                }).fetchall()
                
                return [dict(row._mapping) for row in results]
                
        except Exception as e:
            logger.error(f"Error searching content: {e}")
            return []
    
    def cleanup_old_jobs(self, days_old: int = 30) -> int:
        """
        Räumt alte Jobs auf
        
        Args:
            days_old: Alter in Tagen ab dem Jobs gelöscht werden
            
        Returns:
            Anzahl gelöschter Jobs
        """
        try:
            if not self.engine:
                return 0
            
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT cleanup_old_jobs(:days_old)
                """), {'days_old': days_old}).fetchone()
                conn.commit()
                
                if result:
                    return result[0]
                
            return 0
            
        except Exception as e:
            logger.error(f"Error cleaning up old jobs: {e}")
            return 0