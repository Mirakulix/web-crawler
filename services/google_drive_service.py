#!/usr/bin/env python3
"""
Google Drive Service für Datei-Upload
"""

import os
import io
from pathlib import Path
from typing import Optional, List, Dict, Any
import logging
from datetime import datetime

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    GOOGLE_DRIVE_AVAILABLE = True
except ImportError:
    GOOGLE_DRIVE_AVAILABLE = False

logger = logging.getLogger(__name__)

class GoogleDriveService:
    """Service für Google Drive Upload und Management"""
    
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    
    def __init__(self):
        self.service = None
        self.credentials_path = os.getenv('GOOGLE_DRIVE_CREDENTIALS_PATH', 'credentials/google_drive_credentials.json')
        self.folder_name = os.getenv('GOOGLE_DRIVE_FOLDER_NAME', 'web-crawler')
        self.main_folder_id = None
        
        if not GOOGLE_DRIVE_AVAILABLE:
            logger.warning("Google Drive API libraries not available. Install google-api-python-client")
            return
        
        self._authenticate()
    
    def _authenticate(self) -> bool:
        """Authentifizierung mit Google Drive API"""
        try:
            creds = None
            token_path = Path(self.credentials_path).parent / 'token.json'
            
            # Vorhandenes Token laden
            if token_path.exists():
                creds = Credentials.from_authorized_user_file(str(token_path), self.SCOPES)
            
            # Token aktualisieren oder neue Authentifizierung
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    if not Path(self.credentials_path).exists():
                        logger.error(f"Google Drive credentials file not found: {self.credentials_path}")
                        return False
                    
                    flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, self.SCOPES)
                    creds = flow.run_local_server(port=0)
                
                # Token speichern
                token_path.parent.mkdir(exist_ok=True)
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())
            
            # Drive Service initialisieren
            self.service = build('drive', 'v3', credentials=creds)
            logger.info("Google Drive authentication successful")
            
            # Hauptordner erstellen/finden
            self._ensure_main_folder()
            return True
            
        except Exception as e:
            logger.error(f"Google Drive authentication failed: {e}")
            return False
    
    def _ensure_main_folder(self) -> Optional[str]:
        """Stellt sicher, dass der Hauptordner existiert"""
        try:
            if not self.service:
                return None
            
            # Nach existierendem Ordner suchen
            results = self.service.files().list(
                q=f"name='{self.folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="files(id, name)"
            ).execute()
            
            folders = results.get('files', [])
            
            if folders:
                self.main_folder_id = folders[0]['id']
                logger.info(f"Found existing folder '{self.folder_name}': {self.main_folder_id}")
            else:
                # Neuen Ordner erstellen
                folder_metadata = {
                    'name': self.folder_name,
                    'mimeType': 'application/vnd.google-apps.folder'
                }
                
                folder = self.service.files().create(body=folder_metadata, fields='id').execute()
                self.main_folder_id = folder.get('id')
                logger.info(f"Created new folder '{self.folder_name}': {self.main_folder_id}")
            
            return self.main_folder_id
            
        except Exception as e:
            logger.error(f"Error ensuring main folder: {e}")
            return None
    
    def create_job_folder(self, job_id: str, job_type: str) -> Optional[str]:
        """
        Erstellt Unterordner für spezifischen Job
        
        Args:
            job_id: ID des Jobs
            job_type: Art des Jobs (crawl/video_download)
            
        Returns:
            Google Drive Folder ID oder None
        """
        try:
            if not self.service or not self.main_folder_id:
                logger.error("Google Drive service not available")
                return None
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            folder_name = f"{job_type}_{job_id[:8]}_{timestamp}"
            
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [self.main_folder_id]
            }
            
            folder = self.service.files().create(body=folder_metadata, fields='id').execute()
            folder_id = folder.get('id')
            
            logger.info(f"Created job folder: {folder_name} ({folder_id})")
            return folder_id
            
        except Exception as e:
            logger.error(f"Error creating job folder: {e}")
            return None
    
    def upload_file(
        self, 
        file_path: Path, 
        folder_id: Optional[str] = None,
        custom_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Lädt Datei zu Google Drive hoch
        
        Args:
            file_path: Pfad zur lokalen Datei
            folder_id: ID des Zielordners (Standard: Hauptordner)
            custom_name: Benutzerdefinierter Dateiname
            
        Returns:
            Dict mit file_id, name, und share_url oder None
        """
        try:
            if not self.service:
                logger.error("Google Drive service not available")
                return None
            
            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                return None
            
            target_folder_id = folder_id or self.main_folder_id
            if not target_folder_id:
                logger.error("No target folder available")
                return None
            
            file_name = custom_name or file_path.name
            
            # MIME-Type bestimmen
            mime_type = self._get_mime_type(file_path)
            
            # Datei-Metadaten
            file_metadata = {
                'name': file_name,
                'parents': [target_folder_id]
            }
            
            # Datei hochladen
            media = MediaFileUpload(str(file_path), mimetype=mime_type)
            file = self.service.files().create(
                body=file_metadata, 
                media_body=media, 
                fields='id,name,webViewLink'
            ).execute()
            
            file_id = file.get('id')
            share_url = file.get('webViewLink')
            
            # Datei öffentlich teilbar machen
            self._make_file_shareable(file_id)
            
            logger.info(f"Uploaded file: {file_name} ({file_id})")
            
            return {
                'file_id': file_id,
                'name': file_name,
                'share_url': share_url,
                'size_mb': file_path.stat().st_size / 1024 / 1024
            }
            
        except Exception as e:
            logger.error(f"Error uploading file {file_path}: {e}")
            return None
    
    def upload_directory(
        self, 
        directory: Path, 
        folder_id: Optional[str] = None,
        file_extensions: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Lädt alle Dateien eines Verzeichnisses hoch
        
        Args:
            directory: Verzeichnis zum Hochladen
            folder_id: Zielordner-ID
            file_extensions: Liste erlaubter Dateierweiterungen (z.B. ['.pdf', '.mp4'])
            
        Returns:
            Liste der hochgeladenen Dateien
        """
        uploaded_files = []
        
        try:
            if not directory.exists() or not directory.is_dir():
                logger.error(f"Directory not found: {directory}")
                return uploaded_files
            
            # Job-Unterordner erstellen falls noch nicht vorhanden
            if not folder_id:
                job_folder_name = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                folder_id = self._create_subfolder(job_folder_name, self.main_folder_id)
            
            # Dateien durchgehen
            for file_path in directory.rglob('*'):
                if not file_path.is_file():
                    continue
                
                # Dateierweiterung prüfen
                if file_extensions and file_path.suffix.lower() not in file_extensions:
                    continue
                
                result = self.upload_file(file_path, folder_id)
                if result:
                    result['local_path'] = str(file_path)
                    uploaded_files.append(result)
            
            logger.info(f"Uploaded {len(uploaded_files)} files from {directory}")
            
        except Exception as e:
            logger.error(f"Error uploading directory {directory}: {e}")
        
        return uploaded_files
    
    def _create_subfolder(self, folder_name: str, parent_folder_id: str) -> Optional[str]:
        """Erstellt Unterordner"""
        try:
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder_id]
            }
            
            folder = self.service.files().create(body=folder_metadata, fields='id').execute()
            return folder.get('id')
            
        except Exception as e:
            logger.error(f"Error creating subfolder {folder_name}: {e}")
            return None
    
    def _make_file_shareable(self, file_id: str) -> bool:
        """Macht Datei öffentlich teilbar"""
        try:
            permission = {
                'role': 'reader',
                'type': 'anyone'
            }
            
            self.service.permissions().create(
                fileId=file_id,
                body=permission
            ).execute()
            
            return True
            
        except Exception as e:
            logger.error(f"Error making file shareable {file_id}: {e}")
            return False
    
    def _get_mime_type(self, file_path: Path) -> str:
        """Bestimmt MIME-Type basierend auf Dateierweiterung"""
        extension = file_path.suffix.lower()
        
        mime_types = {
            '.pdf': 'application/pdf',
            '.mp4': 'video/mp4',
            '.avi': 'video/avi',
            '.mov': 'video/quicktime',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.txt': 'text/plain',
            '.json': 'application/json',
            '.zip': 'application/zip',
            '.html': 'text/html'
        }
        
        return mime_types.get(extension, 'application/octet-stream')
    
    def delete_file(self, file_id: str) -> bool:
        """Löscht Datei von Google Drive"""
        try:
            if not self.service:
                return False
            
            self.service.files().delete(fileId=file_id).execute()
            logger.info(f"Deleted file from Google Drive: {file_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting file {file_id}: {e}")
            return False
    
    def get_file_info(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Holt Datei-Informationen"""
        try:
            if not self.service:
                return None
            
            file_info = self.service.files().get(
                fileId=file_id,
                fields='id,name,size,mimeType,createdTime,webViewLink'
            ).execute()
            
            return file_info
            
        except Exception as e:
            logger.error(f"Error getting file info {file_id}: {e}")
            return None
    
    def list_folder_contents(self, folder_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Listet Ordnerinhalte auf"""
        try:
            if not self.service:
                return []
            
            target_folder_id = folder_id or self.main_folder_id
            
            results = self.service.files().list(
                q=f"'{target_folder_id}' in parents and trashed=false",
                fields="files(id,name,mimeType,size,createdTime,webViewLink)"
            ).execute()
            
            return results.get('files', [])
            
        except Exception as e:
            logger.error(f"Error listing folder contents: {e}")
            return []