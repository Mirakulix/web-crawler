#!/usr/bin/env python3
"""
Email Service für PDF-Versand
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import List, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        self.smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', 587))
        self.smtp_username = os.getenv('SMTP_USERNAME')
        self.smtp_password = os.getenv('SMTP_PASSWORD')
        self.email_from = os.getenv('EMAIL_FROM', 'flo.code.dev@gmail.com')
        self.email_to = os.getenv('EMAIL_TO', 'flo.code.dev@gmail.com')
        
        if not all([self.smtp_username, self.smtp_password]):
            logger.warning("SMTP credentials not configured. Email service will not work.")
    
    def send_pdf_email(
        self, 
        pdf_files: List[Path], 
        job_id: str, 
        job_type: str = "crawl",
        additional_info: Optional[str] = None
    ) -> bool:
        """
        Sendet PDFs per E-Mail
        
        Args:
            pdf_files: Liste der PDF-Dateien zum Versenden
            job_id: ID des Jobs
            job_type: Art des Jobs (crawl oder video_download)
            additional_info: Zusätzliche Informationen für die E-Mail
            
        Returns:
            True wenn erfolgreich versendet, False sonst
        """
        try:
            if not all([self.smtp_username, self.smtp_password]):
                logger.error("SMTP credentials not configured")
                return False
            
            # E-Mail zusammenstellen
            msg = MIMEMultipart()
            msg['From'] = self.email_from
            msg['To'] = self.email_to
            msg['Subject'] = self._generate_subject(job_type, job_id, len(pdf_files))
            
            # E-Mail-Inhalt
            body = self._generate_email_body(job_id, job_type, pdf_files, additional_info)
            msg.attach(MIMEText(body, 'html'))
            
            # PDFs anhängen
            for pdf_file in pdf_files:
                if pdf_file.exists() and pdf_file.suffix.lower() == '.pdf':
                    self._attach_pdf(msg, pdf_file)
            
            # E-Mail versenden
            return self._send_email(msg)
            
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False
    
    def send_completion_notification(
        self, 
        job_id: str, 
        job_type: str, 
        statistics: dict,
        result_files: Optional[List[Path]] = None
    ) -> bool:
        """
        Sendet Benachrichtigung über Job-Abschluss
        
        Args:
            job_id: ID des Jobs
            job_type: Art des Jobs
            statistics: Statistiken des Jobs
            result_files: Optionale Ergebnis-Dateien
            
        Returns:
            True wenn erfolgreich versendet, False sonst
        """
        try:
            if not all([self.smtp_username, self.smtp_password]):
                logger.error("SMTP credentials not configured")
                return False
            
            msg = MIMEMultipart()
            msg['From'] = self.email_from
            msg['To'] = self.email_to
            msg['Subject'] = f"Web Crawler Job {job_id[:8]} abgeschlossen - {job_type}"
            
            # E-Mail-Inhalt
            body = self._generate_completion_email_body(job_id, job_type, statistics)
            msg.attach(MIMEText(body, 'html'))
            
            # Kleine Dateien (< 10MB) als Anhang
            if result_files:
                for file_path in result_files:
                    if file_path.exists() and file_path.stat().st_size < 10 * 1024 * 1024:  # 10MB Limit
                        self._attach_file(msg, file_path)
            
            return self._send_email(msg)
            
        except Exception as e:
            logger.error(f"Error sending completion notification: {e}")
            return False
    
    def _generate_subject(self, job_type: str, job_id: str, pdf_count: int) -> str:
        """Generiert E-Mail-Betreff"""
        job_type_map = {
            'crawl': 'Website-Crawling',
            'video_download': 'Video-Download'
        }
        type_name = job_type_map.get(job_type, job_type)
        
        return f"Web Crawler Ergebnisse - {type_name} ({pdf_count} PDFs) - Job {job_id[:8]}"
    
    def _generate_email_body(
        self, 
        job_id: str, 
        job_type: str, 
        pdf_files: List[Path],
        additional_info: Optional[str] = None
    ) -> str:
        """Generiert HTML E-Mail-Inhalt"""
        
        job_type_map = {
            'crawl': 'Website-Crawling',
            'video_download': 'Video-Download'
        }
        type_name = job_type_map.get(job_type, job_type)
        
        html = f"""
        <html>
        <head></head>
        <body>
            <h2>🔍 Web Crawler Ergebnisse</h2>
            
            <div style="background-color: #f0f0f0; padding: 10px; margin: 10px 0;">
                <strong>Job Details:</strong><br>
                <strong>Job ID:</strong> {job_id}<br>
                <strong>Typ:</strong> {type_name}<br>
                <strong>Zeitstempel:</strong> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}<br>
                <strong>Anzahl PDFs:</strong> {len(pdf_files)}
            </div>
            
            <h3>📄 Angehängte PDFs:</h3>
            <ul>
        """
        
        for pdf_file in pdf_files:
            file_size = pdf_file.stat().st_size / 1024 / 1024 if pdf_file.exists() else 0
            html += f"<li><strong>{pdf_file.name}</strong> ({file_size:.1f} MB)</li>"
        
        html += "</ul>"
        
        if additional_info:
            html += f"""
            <h3>ℹ️ Zusätzliche Informationen:</h3>
            <div style="background-color: #e8f4f8; padding: 10px; margin: 10px 0;">
                {additional_info}
            </div>
            """
        
        html += """
            <hr>
            <p style="color: #666; font-size: 12px;">
                Diese E-Mail wurde automatisch von dem Web Crawler Service generiert.<br>
                Alle Dateien wurden auch in Google Drive im Ordner 'web-crawler' gespeichert.
            </p>
        </body>
        </html>
        """
        
        return html
    
    def _generate_completion_email_body(self, job_id: str, job_type: str, statistics: dict) -> str:
        """Generiert HTML für Job-Abschluss-Benachrichtigung"""
        
        job_type_map = {
            'crawl': 'Website-Crawling',
            'video_download': 'Video-Download'
        }
        type_name = job_type_map.get(job_type, job_type)
        
        html = f"""
        <html>
        <head></head>
        <body>
            <h2>✅ Job abgeschlossen</h2>
            
            <div style="background-color: #d4edda; padding: 10px; margin: 10px 0; border-left: 4px solid #28a745;">
                <strong>Job Details:</strong><br>
                <strong>Job ID:</strong> {job_id}<br>
                <strong>Typ:</strong> {type_name}<br>
                <strong>Abgeschlossen:</strong> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
            </div>
            
            <h3>📊 Statistiken:</h3>
            <ul>
        """
        
        # Statistiken hinzufügen
        for key, value in statistics.items():
            html += f"<li><strong>{key}:</strong> {value}</li>"
        
        html += """
            </ul>
            
            <p>Die Ergebnisse sind verfügbar über:</p>
            <ul>
                <li>📁 Google Drive (Ordner: web-crawler)</li>
                <li>🗄️ PostgreSQL Datenbank</li>
                <li>🌐 API Download-Endpunkt</li>
            </ul>
            
            <hr>
            <p style="color: #666; font-size: 12px;">
                Diese E-Mail wurde automatisch generiert.
            </p>
        </body>
        </html>
        """
        
        return html
    
    def _attach_pdf(self, msg: MIMEMultipart, pdf_file: Path) -> None:
        """Hängt PDF-Datei an E-Mail an"""
        try:
            with open(pdf_file, "rb") as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
            
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= {pdf_file.name}'
            )
            
            msg.attach(part)
            logger.info(f"PDF attached: {pdf_file.name}")
            
        except Exception as e:
            logger.error(f"Error attaching PDF {pdf_file}: {e}")
    
    def _attach_file(self, msg: MIMEMultipart, file_path: Path) -> None:
        """Hängt beliebige Datei an E-Mail an"""
        try:
            with open(file_path, "rb") as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
            
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= {file_path.name}'
            )
            
            msg.attach(part)
            logger.info(f"File attached: {file_path.name}")
            
        except Exception as e:
            logger.error(f"Error attaching file {file_path}: {e}")
    
    def _send_email(self, msg: MIMEMultipart) -> bool:
        """Sendet die E-Mail"""
        try:
            # SMTP-Verbindung aufbauen
            server = smtplib.SMTP(self.smtp_host, self.smtp_port)
            server.starttls()
            server.login(self.smtp_username, self.smtp_password)
            
            # E-Mail senden
            text = msg.as_string()
            server.sendmail(self.email_from, self.email_to, text)
            server.quit()
            
            logger.info(f"Email sent successfully to {self.email_to}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return False