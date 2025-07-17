#!/usr/bin/env python3
"""
Video Downloader & Recorder
Lädt Videos von Websites herunter oder zeichnet sie auf
Mit Integration für Website Crawler
"""

import os
import re
import json
import time
import subprocess
import requests
from urllib.parse import urljoin, urlparse
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# Standard library imports
import os
import re
import json
import time
import subprocess
import requests
from urllib.parse import urljoin, urlparse
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# Early Display-Check um pyautogui-Import zu vermeiden
DISPLAY_AVAILABLE = False
if os.name == 'nt':  # Windows
    DISPLAY_AVAILABLE = True
elif 'DISPLAY' in os.environ:  # Linux mit X11
    try:
        # Test ob Display wirklich erreichbar ist
        import subprocess
        result = subprocess.run(['xset', 'q'], capture_output=True, timeout=2)
        DISPLAY_AVAILABLE = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        DISPLAY_AVAILABLE = False
elif 'WAYLAND_DISPLAY' in os.environ:  # Linux mit Wayland
    DISPLAY_AVAILABLE = True

# Third-party imports with graceful fallbacks
GUI_AVAILABLE = False
SELENIUM_AVAILABLE = True
VIDEO_PROCESSING_AVAILABLE = True

try:
    import yt_dlp
except ImportError:
    print("Warnung: yt-dlp nicht installiert. YouTube/Vimeo Downloads nicht verfügbar.")
    yt_dlp = None

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import WebDriverException, TimeoutException
except ImportError:
    print("Warnung: Selenium nicht installiert. Browser-Automation nicht verfügbar.")
    SELENIUM_AVAILABLE = False
    webdriver = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Fehler: BeautifulSoup4 ist erforderlich!")
    exit(1)

try:
    import cv2
    import numpy as np
    from PIL import Image
except ImportError:
    print("Warnung: OpenCV/PIL nicht installiert. Video-Processing nicht verfügbar.")
    VIDEO_PROCESSING_AVAILABLE = False
    cv2 = None

# GUI-abhängige Imports nur wenn Display verfügbar
ImageGrab = None
pyautogui = None

if DISPLAY_AVAILABLE:
    try:
        from PIL import ImageGrab
        # pyautogui erst importieren wenn wir sicher sind dass Display funktioniert
        import pyautogui
        # Test ob GUI wirklich funktioniert
        pyautogui.size()
        GUI_AVAILABLE = True
        print("✅ GUI-Features verfügbar")
    except Exception as e:
        print(f"Warnung: GUI-Features nicht verfügbar: {e}")
        GUI_AVAILABLE = False
        ImageGrab = None
        pyautogui = None
else:
    print("ℹ️  Kein Display erkannt - GUI-Features deaktiviert")

try:
    import psutil
except ImportError:
    print("Warnung: psutil nicht installiert. Prozess-Monitoring eingeschränkt.")
    psutil = None

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('video_downloader.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class VideoInfo:
    """Datenklasse für Video-Informationen"""
    url: str
    title: str
    duration: Optional[float]
    format: str
    file_path: str
    file_size: Optional[int]
    download_method: str
    timestamp: str

class VideoDownloader:
    """Haupt-Video-Downloader-Klasse mit Fallback-Strategien"""
    
    def __init__(self, base_url: str, output_dir: str):
        self.base_url = base_url
        self.output_dir = Path(output_dir)
        
        # Sicherstellen dass alle benötigten Ordner existieren
        self._ensure_directories()
        
        # Session für HTTP-Requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
        # Browser-Setup nur wenn Selenium verfügbar
        self.driver = None
        if SELENIUM_AVAILABLE:
            self._setup_selenium()
        
        # yt-dlp Konfiguration
        self.ydl_opts = {
            'format': 'best[height<=1080][ext=mp4]/best[height<=1080][ext=mkv]/best[ext=mp4]/best',
            'outtmpl': str(self.videos_dir / '%(title)s.%(ext)s'),
            'noplaylist': True,
            'extractaudio': False,
            'audioformat': 'mp3',
            'ignoreerrors': True,
            'no_warnings': False,
        } if yt_dlp else {}
        
        # Capabilities basierend auf verfügbaren Bibliotheken
        self.capabilities = {
            'direct_download': True,  # Immer verfügbar
            'yt_dlp_download': yt_dlp is not None,
            'browser_automation': SELENIUM_AVAILABLE,
            'screen_recording': GUI_AVAILABLE and VIDEO_PROCESSING_AVAILABLE,
            'video_processing': VIDEO_PROCESSING_AVAILABLE
        }
        
        # Statistiken
        self.stats = {
            'total_found': 0,
            'direct_downloads': 0,
            'yt_dlp_downloads': 0,
            'screen_recordings': 0,
            'failures': 0,
            'total_size_mb': 0
        }
        
        # Video-Sammlung
        self.downloaded_videos: List[VideoInfo] = []
        
        # Log verfügbare Features
        self._log_capabilities()
    
    def _ensure_directories(self) -> None:
        """Erstellt alle benötigten Ordner mit rekursiver Parent-Erstellung"""
        try:
            # Hauptausgabe-Ordner erstellen (parents=True für rekursive Erstellung)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            
            # Video-Unterordner erstellen
            self.videos_dir = self.output_dir / "videos"
            self.videos_dir.mkdir(parents=True, exist_ok=True)
            
            # Logs-Ordner für detaillierte Video-Logs
            self.logs_dir = self.output_dir / "logs"
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            
            # Temp-Ordner für temporäre Downloads
            self.temp_dir = self.output_dir / "temp"
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"✅ Ordnerstruktur erstellt: {self.output_dir}")
            logger.debug(f"   📁 Videos: {self.videos_dir}")
            logger.debug(f"   📁 Logs: {self.logs_dir}")
            logger.debug(f"   📁 Temp: {self.temp_dir}")
            
        except PermissionError as e:
            logger.error(f"❌ Keine Berechtigung zum Erstellen von Ordnern: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Fehler beim Erstellen der Ordnerstruktur: {e}")
            raise
    
    def _ensure_file_directory(self, file_path: Path) -> None:
        """Stellt sicher, dass das Verzeichnis für eine Datei existiert"""
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Verzeichnisses für {file_path}: {e}")
            raise
    
    def _setup_selenium(self) -> None:
        """Selenium-Setup mit Fehlerbehandlung"""
        try:
            self.chrome_options = Options()
            self.chrome_options.add_argument('--no-sandbox')
            self.chrome_options.add_argument('--disable-dev-shm-usage')
            self.chrome_options.add_argument('--disable-gpu')
            self.chrome_options.add_argument('--window-size=1920,1080')
            
            # In headless Umgebungen oder wenn kein GUI verfügbar
            if not GUI_AVAILABLE:
                self.chrome_options.add_argument('--headless')
                logger.info("Selenium wird im Headless-Modus verwendet")
            
            # Test ChromeDriver
            test_driver = webdriver.Chrome(options=self.chrome_options)
            test_driver.quit()
            logger.info("✅ ChromeDriver erfolgreich getestet")
            
        except Exception as e:
            logger.warning(f"Selenium-Setup fehlgeschlagen: {e}")
            global SELENIUM_AVAILABLE
            SELENIUM_AVAILABLE = False
    
    def _log_capabilities(self) -> None:
        """Logge verfügbare Funktionen"""
        logger.info("🔧 Verfügbare Video-Download-Methoden:")
        for capability, available in self.capabilities.items():
            status = "✅" if available else "❌"
            logger.info(f"   {status} {capability}")
        
        if not any(self.capabilities.values()):
            logger.warning("⚠️  Keine erweiterten Features verfügbar - nur grundlegende Downloads möglich")
        
    def find_videos_on_page(self, url: str) -> List[Dict[str, str]]:
        """Findet alle Video-URLs auf einer Webseite"""
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            videos = []
            
            # 1. Video-Tags finden
            for video_tag in soup.find_all('video'):
                sources = []
                
                # Direkte src-Attribute
                if video_tag.get('src'):
                    sources.append(video_tag['src'])
                
                # Source-Tags innerhalb des Video-Tags
                for source in video_tag.find_all('source'):
                    if source.get('src'):
                        sources.append(source['src'])
                
                for src in sources:
                    absolute_url = urljoin(url, src)
                    videos.append({
                        'url': absolute_url,
                        'type': 'direct',
                        'title': video_tag.get('title', 'Untitled Video'),
                        'poster': video_tag.get('poster', '')
                    })
            
            # 2. YouTube/Vimeo Embeds
            iframe_patterns = [
                (r'youtube\.com/embed/([^/?&]+)', 'https://www.youtube.com/watch?v={}'),
                (r'youtu\.be/([^/?&]+)', 'https://www.youtube.com/watch?v={}'),
                (r'vimeo\.com/video/(\d+)', 'https://vimeo.com/{}'),
                (r'player\.vimeo\.com/video/(\d+)', 'https://vimeo.com/{}'),
            ]
            
            for iframe in soup.find_all('iframe'):
                iframe_src = iframe.get('src', '')
                if iframe_src:
                    iframe_src = urljoin(url, iframe_src)
                    
                    for pattern, url_template in iframe_patterns:
                        match = re.search(pattern, iframe_src)
                        if match:
                            video_id = match.group(1)
                            video_url = url_template.format(video_id)
                            videos.append({
                                'url': video_url,
                                'type': 'embedded',
                                'title': iframe.get('title', f'Embedded Video {video_id}'),
                                'iframe_src': iframe_src
                            })
            
            # 3. JavaScript-basierte Videos (grundlegende Erkennung)
            scripts = soup.find_all('script')
            for script in scripts:
                script_content = script.get_text() if script.string else ''
                
                # Suche nach Video-URLs in JavaScript
                video_url_patterns = [
                    r'"(https?://[^"]*\.(?:mp4|mkv|webm|mov|avi))"',
                    r"'(https?://[^']*\.(?:mp4|mkv|webm|mov|avi))'",
                    r'videoUrl["\s]*:["\s]*"([^"]+)"',
                    r'src["\s]*:["\s]*"([^"]+\.(?:mp4|mkv|webm))"'
                ]
                
                for pattern in video_url_patterns:
                    matches = re.finditer(pattern, script_content, re.IGNORECASE)
                    for match in matches:
                        video_url = match.group(1)
                        absolute_url = urljoin(url, video_url)
                        videos.append({
                            'url': absolute_url,
                            'type': 'javascript',
                            'title': 'JavaScript Video',
                            'source': 'script_extraction'
                        })
            
            logger.info(f"Gefunden: {len(videos)} Videos auf {url}")
            self.stats['total_found'] += len(videos)
            
            return videos
            
        except Exception as e:
            logger.error(f"Fehler beim Scannen der Seite {url}: {e}")
            return []
    
    def download_direct_video(self, video_url: str, title: str) -> Optional[VideoInfo]:
        """Lädt Video direkt über HTTP herunter"""
        try:
            logger.info(f"Direkter Download: {video_url}")
            
            # HEAD-Request für Metadaten
            head_response = self.session.head(video_url, timeout=10)
            content_length = head_response.headers.get('content-length')
            content_type = head_response.headers.get('content-type', '')
            
            if 'video' not in content_type.lower():
                logger.warning(f"Content-Type ist nicht video: {content_type}")
                return None
            
            # Dateiname und Pfad erstellen
            parsed_url = urlparse(video_url)
            file_extension = Path(parsed_url.path).suffix or '.mp4'
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)
            filename = f"{safe_title}{file_extension}"
            file_path = self.videos_dir / filename
            
            # Sicherstellen dass das Verzeichnis existiert
            self._ensure_file_directory(file_path)
            
            # Download mit Progress
            response = self.session.get(video_url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(content_length) if content_length else 0
            downloaded = 0
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            print(f"\rDownload: {progress:.1f}%", end="", flush=True)
            
            print()  # Neue Zeile nach Progress
            
            file_size = file_path.stat().st_size
            self.stats['direct_downloads'] += 1
            self.stats['total_size_mb'] += file_size / (1024 * 1024)
            
            video_info = VideoInfo(
                url=video_url,
                title=title,
                duration=None,
                format=file_extension[1:],
                file_path=str(file_path),
                file_size=file_size,
                download_method='direct_http',
                timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
            )
            
            logger.info(f"✅ Direkter Download erfolgreich: {filename}")
            return video_info
            
        except Exception as e:
            logger.error(f"Direkter Download fehlgeschlagen für {video_url}: {e}")
            return None
    
    def download_with_yt_dlp(self, video_url: str) -> Optional[VideoInfo]:
        """Lädt Video mit yt-dlp herunter"""
        if not self.capabilities['yt_dlp_download']:
            logger.warning("yt-dlp nicht verfügbar")
            return None
            
        try:
            logger.info(f"yt-dlp Download: {video_url}")
            
            # Sicherstellen dass Videos-Ordner existiert
            self._ensure_file_directory(self.videos_dir / "dummy")
            
            # yt-dlp Output-Template mit absoluten Pfaden aktualisieren
            safe_output_template = str(self.videos_dir / '%(title)s.%(ext)s')
            current_ydl_opts = {
                **self.ydl_opts,
                'outtmpl': safe_output_template
            }
            
            with yt_dlp.YoutubeDL(current_ydl_opts) as ydl:
                # Video-Informationen extrahieren
                info = ydl.extract_info(video_url, download=False)
                
                if not info:
                    logger.warning(f"Keine Video-Informationen verfügbar für: {video_url}")
                    return None
                
                title = info.get('title', 'Unknown')
                duration = info.get('duration')
                
                # Download durchführen
                ydl.download([video_url])
                
                # Heruntergeladene Datei finden
                safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)
                possible_extensions = ['.mp4', '.mkv', '.webm', '.mov']
                
                downloaded_file = None
                for ext in possible_extensions:
                    potential_file = self.videos_dir / f"{safe_title}{ext}"
                    if potential_file.exists():
                        downloaded_file = potential_file
                        break
                
                if not downloaded_file:
                    # Fallback: Suche nach neuester Datei im Videos-Ordner
                    try:
                        video_files = [f for f in self.videos_dir.iterdir() 
                                     if f.is_file() and f.suffix in possible_extensions]
                        if video_files:
                            downloaded_file = max(video_files, key=lambda f: f.stat().st_mtime)
                    except Exception as e:
                        logger.error(f"Fehler beim Suchen der heruntergeladenen Datei: {e}")
                
                if downloaded_file and downloaded_file.exists():
                    file_size = downloaded_file.stat().st_size
                    self.stats['yt_dlp_downloads'] += 1
                    self.stats['total_size_mb'] += file_size / (1024 * 1024)
                    
                    video_info = VideoInfo(
                        url=video_url,
                        title=title,
                        duration=duration,
                        format=downloaded_file.suffix[1:],
                        file_path=str(downloaded_file),
                        file_size=file_size,
                        download_method='yt_dlp',
                        timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
                    )
                    
                    logger.info(f"✅ yt-dlp Download erfolgreich: {downloaded_file.name}")
                    return video_info
                else:
                    logger.error(f"Heruntergeladene Datei nicht gefunden für: {video_url}")
                    return None
                    
        except Exception as e:
            logger.error(f"yt-dlp Download fehlgeschlagen für {video_url}: {e}")
            return None
    
    def record_video_with_browser(self, video_url: str, title: str, duration: int = 30) -> Optional[VideoInfo]:
        """Zeichnet Video über Browser-Automation auf (nur wenn GUI verfügbar)"""
        if not self.capabilities['screen_recording']:
            logger.warning("Screen-Recording nicht verfügbar (GUI oder Video-Processing fehlt)")
            return None
            
        if not self.capabilities['browser_automation']:
            logger.warning("Browser-Automation nicht verfügbar")
            return None
            
        driver = None
        try:
            logger.info(f"Browser-Recording: {video_url} für {duration}s")
            
            # Browser starten
            driver = webdriver.Chrome(options=self.chrome_options)
            driver.get(video_url)
            
            # Warten bis Seite geladen ist
            time.sleep(3)
            
            # Versuche Video zu starten
            self._start_video_playback(driver)
            
            # Video-Element für Recording finden
            recording_area = self._get_recording_area(driver)
            
            # Dateiname erstellen
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{safe_title}_{timestamp}.mp4"
            file_path = self.videos_dir / filename
            
            # Screen-Recording durchführen
            success = self._record_screen_area(recording_area, file_path, duration)
            
            if success and file_path.exists():
                file_size = file_path.stat().st_size
                self.stats['screen_recordings'] += 1
                self.stats['total_size_mb'] += file_size / (1024 * 1024)
                
                video_info = VideoInfo(
                    url=video_url,
                    title=title,
                    duration=duration,
                    format='mp4',
                    file_path=str(file_path),
                    file_size=file_size,
                    download_method='screen_recording',
                    timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
                )
                
                logger.info(f"✅ Screen-Recording erfolgreich: {filename}")
                return video_info
            else:
                logger.error("Recording-Datei wurde nicht erstellt")
                return None
                
        except Exception as e:
            logger.error(f"Browser-Recording fehlgeschlagen für {video_url}: {e}")
            return None
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
    
    def _start_video_playback(self, driver) -> None:
        """Startet Video-Wiedergabe im Browser"""
        try:
            # Verschiedene Play-Button Selektoren
            play_selectors = [
                'button[aria-label*="play" i]',
                'button[aria-label*="Play" i]',
                '.play-button',
                '.video-play-button',
                '[role="button"][aria-label*="play" i]',
                'video'  # Fallback: direkt auf Video klicken
            ]
            
            video_started = False
            for selector in play_selectors:
                try:
                    play_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    play_button.click()
                    video_started = True
                    logger.info(f"Video gestartet mit Selektor: {selector}")
                    break
                except (TimeoutException, WebDriverException):
                    continue
            
            if not video_started and pyautogui:
                # Fallback: Leertaste drücken (universeller Play/Pause)
                try:
                    driver.find_element(By.TAG_NAME, 'body').click()
                    pyautogui.press('space')
                    time.sleep(1)
                    logger.info("Video gestartet mit Leertaste")
                except:
                    logger.warning("Konnte Video nicht automatisch starten")
            
        except Exception as e:
            logger.warning(f"Video-Start fehlgeschlagen: {e}")
    
    def _get_recording_area(self, driver) -> Dict[str, int]:
        """Bestimmt den Aufnahmebereich für Screen-Recording"""
        try:
            video_element = driver.find_element(By.TAG_NAME, 'video')
            location = video_element.location
            size = video_element.size
            
            return {
                'x': location['x'],
                'y': location['y'], 
                'width': size['width'],
                'height': size['height']
            }
            
        except:
            # Fallback: Standard-Bereich
            logger.warning("Video-Element nicht gefunden, verwende Standard-Bereich")
            return {
                'x': 0,
                'y': 100,  # Höher um Browser-UI zu vermeiden
                'width': 1280,
                'height': 720
            }
    
    def _record_screen_area(self, area: Dict[str, int], file_path: Path, duration: int) -> bool:
        """Führt Screen-Recording durch mit robuster Ordner-Erstellung"""
        if not VIDEO_PROCESSING_AVAILABLE or not ImageGrab:
            logger.error("Video-Processing oder ImageGrab nicht verfügbar")
            return False
            
        try:
            # Sicherstellen dass das Zielverzeichnis existiert
            self._ensure_file_directory(file_path)
            
            # OpenCV VideoWriter setup
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            fps = 30.0
            out = cv2.VideoWriter(
                str(file_path), 
                fourcc, 
                fps, 
                (area['width'], area['height'])
            )
            
            start_time = time.time()
            frames_recorded = 0
            
            logger.info(f"Starte Recording für {duration}s...")
            
            while time.time() - start_time < duration:
                # Screenshot aufnehmen
                bbox = (
                    area['x'], 
                    area['y'], 
                    area['x'] + area['width'], 
                    area['y'] + area['height']
                )
                screenshot = ImageGrab.grab(bbox=bbox)
                frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
                
                # Frame in Video schreiben
                out.write(frame)
                frames_recorded += 1
                
                # Progress anzeigen
                elapsed = time.time() - start_time
                progress = (elapsed / duration) * 100
                print(f"\rRecording: {progress:.1f}% ({frames_recorded} frames)", 
                      end="", flush=True)
                
                # FPS regulieren
                time.sleep(1/fps)
            
            print()  # Neue Zeile nach Progress
            
            # Recording beenden
            out.release()
            return True
            
        except Exception as e:
            logger.error(f"Screen-Recording fehlgeschlagen: {e}")
            return False
    
    def create_video_summary(self) -> None:
        """Erstellt eine JSON-Zusammenfassung aller Videos mit robuster Ordner-Erstellung"""
        try:
            summary_data = {
                'base_url': self.base_url,
                'download_timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
                'statistics': self.stats,
                'videos': []
            }
            
            for video in self.downloaded_videos:
                video_data = {
                    'url': video.url,
                    'title': video.title,
                    'duration': video.duration,
                    'format': video.format,
                    'file_path': video.file_path,
                    'file_size_mb': round(video.file_size / (1024 * 1024), 2) if video.file_size else None,
                    'download_method': video.download_method,
                    'timestamp': video.timestamp
                }
                summary_data['videos'].append(video_data)
            
            # JSON-Datei speichern
            summary_path = self.output_dir / "videos_summary.json"
            self._ensure_file_directory(summary_path)
            
            with open(summary_path, 'w', encoding='utf-8') as f:
                json.dump(summary_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"📊 Video-Zusammenfassung erstellt: {summary_path}")
            
            # Zusätzliche detaillierte Log-Datei erstellen
            log_path = self.logs_dir / f"video_download_{time.strftime('%Y%m%d_%H%M%S')}.log"
            self._ensure_file_directory(log_path)
            
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write("=== Video Download Log ===\n")
                f.write(f"Datum: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Basis-URL: {self.base_url}\n")
                f.write(f"Gefundene Videos: {self.stats['total_found']}\n")
                f.write(f"Erfolgreiche Downloads: {self.stats['direct_downloads'] + self.stats['yt_dlp_downloads'] + self.stats['screen_recordings']}\n")
                f.write(f"Fehlgeschlagen: {self.stats['failures']}\n\n")
                
                for video in self.downloaded_videos:
                    f.write(f"Video: {video.title}\n")
                    f.write(f"  URL: {video.url}\n")
                    f.write(f"  Datei: {video.file_path}\n")
                    f.write(f"  Methode: {video.download_method}\n")
                    f.write(f"  Größe: {video.file_size / (1024*1024):.1f} MB\n" if video.file_size else "  Größe: Unknown\n")
                    f.write("\n")
            
            logger.info(f"📝 Detailliertes Log erstellt: {log_path}")
            
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der Video-Zusammenfassung: {e}")
            # Fallback: Minimale Zusammenfassung erstellen
            try:
                fallback_path = self.output_dir / "videos_summary_minimal.txt"
                self._ensure_file_directory(fallback_path)
                
                with open(fallback_path, 'w', encoding='utf-8') as f:
                    f.write(f"Video Download Summary - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Base URL: {self.base_url}\n")
                    f.write(f"Videos downloaded: {len(self.downloaded_videos)}\n")
                    for video in self.downloaded_videos:
                        f.write(f"- {video.title}: {video.file_path}\n")
                
                logger.info(f"Fallback-Zusammenfassung erstellt: {fallback_path}")
            except Exception as fallback_error:
                logger.error(f"Auch Fallback-Zusammenfassung fehlgeschlagen: {fallback_error}")
    
    def download_video(self, video_info: Dict[str, str]) -> Optional[VideoInfo]:
        """Lädt ein Video mit verfügbaren Methoden herunter"""
        video_url = video_info['url']
        title = video_info.get('title', 'Unknown Video')
        video_type = video_info.get('type', 'unknown')
        
        logger.info(f"Verarbeite Video: {title} ({video_type})")
        
        # Methode 1: Direkter Download für direkte Video-URLs
        if video_type == 'direct' or video_url.lower().endswith(('.mp4', '.mkv', '.webm', '.mov', '.avi')):
            result = self.download_direct_video(video_url, title)
            if result:
                return result
        
        # Methode 2: yt-dlp für YouTube, Vimeo und andere Plattformen
        if self.capabilities['yt_dlp_download']:
            try:
                result = self.download_with_yt_dlp(video_url)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"yt-dlp fehlgeschlagen: {e}")
        else:
            logger.info("yt-dlp nicht verfügbar, überspringe")
        
        # Methode 3: Browser-basiertes Screen-Recording (nur wenn GUI verfügbar)
        if self.capabilities['screen_recording']:
            logger.info(f"Fallback zu Screen-Recording für: {video_url}")
            
            # Recording-Dauer intelligent bestimmen
            recording_duration = 60  # Standard: 1 Minute
            
            # Frage User nach Recording-Dauer für dieses Video (nur wenn interaktiv)
            try:
                if os.isatty(0):  # Prüfe ob stdout ein TTY ist (interaktive Session)
                    user_duration = input(f"\n🎬 Screen-Recording für '{title}'\n"
                                         f"URL: {video_url}\n"
                                         f"Wie lange soll aufgezeichnet werden? (Sekunden, Standard: 60): ").strip()
                    if user_duration and user_duration.isdigit():
                        recording_duration = int(user_duration)
            except (EOFError, KeyboardInterrupt):
                logger.info("User-Input übersprungen, verwende Standard-Dauer")
            
            result = self.record_video_with_browser(video_url, title, recording_duration)
            if result:
                return result
        else:
            logger.info("Screen-Recording nicht verfügbar (GUI/Video-Processing fehlt)")
        
        # Alle Methoden fehlgeschlagen
        logger.error(f"❌ Alle verfügbaren Download-Methoden fehlgeschlagen für: {video_url}")
        self.stats['failures'] += 1
        return None
    
    def check_system_requirements(self) -> Dict[str, bool]:
        """Prüft Systemvoraussetzungen und gibt Status zurück"""
        requirements = {
            'ffmpeg': False,
            'chromedriver': False,
            'python_packages': False,
            'gui_available': GUI_AVAILABLE,
            'display_available': 'DISPLAY' in os.environ or os.name == 'nt'
        }
        
        # FFmpeg prüfen
        try:
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, check=True, timeout=5)
            requirements['ffmpeg'] = True
            logger.debug("✅ FFmpeg gefunden")
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning("❌ FFmpeg nicht gefunden")
        
        # ChromeDriver prüfen (nur wenn Selenium verfügbar)
        if SELENIUM_AVAILABLE:
            try:
                options = Options()
                options.add_argument('--headless')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                
                driver = webdriver.Chrome(options=options)
                driver.quit()
                requirements['chromedriver'] = True
                logger.debug("✅ ChromeDriver gefunden")
            except Exception as e:
                logger.warning(f"❌ ChromeDriver Problem: {e}")
        
        # Python-Pakete prüfen (KORRIGIERT)
        required_packages = [
            ('requests', 'requests'),
            ('beautifulsoup4', 'bs4'),  # Import-Name ist 'bs4', nicht 'beautifulsoup4'
        ]
        
        optional_packages = [
            ('yt-dlp', 'yt_dlp'),
            ('selenium', 'selenium'),
            ('opencv-python', 'cv2'),
            ('pillow', 'PIL'),
            ('pyautogui', 'pyautogui'),
            ('psutil', 'psutil')
        ]
        
        missing_required = []
        missing_optional = []
        
        # Erforderliche Pakete testen
        for package_name, import_name in required_packages:
            try:
                __import__(import_name)
                logger.debug(f"✅ {package_name} verfügbar")
            except ImportError:
                missing_required.append(package_name)
                logger.error(f"❌ {package_name} fehlt")
        
        # Optionale Pakete testen
        for package_name, import_name in optional_packages:
            try:
                __import__(import_name)
                logger.debug(f"✅ {package_name} verfügbar")
            except ImportError:
                missing_optional.append(package_name)
                logger.debug(f"⚠️  {package_name} fehlt (optional)")
        
        requirements['python_packages'] = len(missing_required) == 0
        
        if missing_required:
            logger.error(f"❌ Erforderliche Pakete fehlen: {', '.join(missing_required)}")
        if missing_optional:
            logger.warning(f"⚠️  Optionale Pakete fehlen: {', '.join(missing_optional)}")
        
        return requirements
    
    def process_url(self, url: str) -> List[VideoInfo]:
        """Verarbeitet eine URL und lädt alle gefundenen Videos herunter"""
        logger.info(f"🔍 Scanne URL nach Videos: {url}")
        
        # Videos auf der Seite finden
        found_videos = self.find_videos_on_page(url)
        
        if not found_videos:
            logger.info(f"Keine Videos gefunden auf: {url}")
            return []
        
        logger.info(f"📹 Gefunden: {len(found_videos)} Videos")
        
        downloaded_videos = []
        
        # Videos parallel herunterladen (begrenzt auf 2 gleichzeitige Downloads)
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_video = {
                executor.submit(self.download_video, video_info): video_info 
                for video_info in found_videos
            }
            
            for future in as_completed(future_to_video):
                video_info = future_to_video[future]
                try:
                    result = future.result()
                    if result:
                        downloaded_videos.append(result)
                        self.downloaded_videos.append(result)
                except Exception as e:
                    logger.error(f"Fehler beim Herunterladen: {e}")
                    self.stats['failures'] += 1
        
        return downloaded_videos
    
    def create_video_summary(self) -> None:
        """Erstellt eine JSON-Zusammenfassung aller Videos"""
        summary_data = {
            'base_url': self.base_url,
            'download_timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'statistics': self.stats,
            'videos': []
        }
        
        for video in self.downloaded_videos:
            video_data = {
                'url': video.url,
                'title': video.title,
                'duration': video.duration,
                'format': video.format,
                'file_path': video.file_path,
                'file_size_mb': round(video.file_size / (1024 * 1024), 2) if video.file_size else None,
                'download_method': video.download_method,
                'timestamp': video.timestamp
            }
            summary_data['videos'].append(video_data)
        
        summary_path = self.output_dir / "videos_summary.json"
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📊 Video-Zusammenfassung erstellt: {summary_path}")
    
    def print_summary(self) -> None:
        """Gibt eine Zusammenfassung der Downloads aus"""
        print("\n" + "="*60)
        print("🎬 VIDEO DOWNLOAD ZUSAMMENFASSUNG")
        print("="*60)
        print(f"📊 Gefundene Videos: {self.stats['total_found']}")
        print(f"📥 Direkte Downloads: {self.stats['direct_downloads']}")
        print(f"🎯 yt-dlp Downloads: {self.stats['yt_dlp_downloads']}")
        print(f"📹 Screen Recordings: {self.stats['screen_recordings']}")
        print(f"❌ Fehlgeschlagen: {self.stats['failures']}")
        print(f"💾 Gesamtgröße: {self.stats['total_size_mb']:.1f} MB")
        print(f"📁 Speicherort: {self.videos_dir}")
        print("="*60)
        
        if self.downloaded_videos:
            print("\n📋 Heruntergeladene Videos:")
            for video in self.downloaded_videos:
                size_mb = round(video.file_size / (1024 * 1024), 1) if video.file_size else "?"
                print(f"  • {video.title}")
                print(f"    └─ {video.format.upper()} | {size_mb}MB | {video.download_method}")

def integrate_with_crawler(crawler_output_dir: str, urls: List[str]) -> None:
    """Integration mit dem Website-Crawler mit robuster Ordner-Erstellung"""
    logger.info("🔗 Integration mit Website-Crawler gestartet")
    
    try:
        # Sicherstellen dass das Crawler-Output-Directory existiert
        crawler_path = Path(crawler_output_dir)
        crawler_path.mkdir(parents=True, exist_ok=True)
        
        base_url = urls[0] if urls else "unknown"
        downloader = VideoDownloader(base_url, crawler_output_dir)
        
        all_videos = []
        
        for url in urls:
            try:
                videos = downloader.process_url(url)
                all_videos.extend(videos)
            except Exception as e:
                logger.error(f"Fehler beim Verarbeiten von {url}: {e}")
        
        # Zusammenfassung erstellen
        downloader.create_video_summary()
        downloader.print_summary()
        
        # Integration-Log erstellen
        integration_log_path = crawler_path / "crawler_video_integration.log"
        try:
            with open(integration_log_path, 'w', encoding='utf-8') as f:
                f.write("=== Crawler-Video-Integration ===\n")
                f.write(f"Zeitpunkt: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Crawler Output Dir: {crawler_output_dir}\n")
                f.write(f"Verarbeitete URLs: {len(urls)}\n")
                f.write(f"Gefundene Videos: {len(all_videos)}\n\n")
                
                f.write("URLs:\n")
                for i, url in enumerate(urls, 1):
                    f.write(f"{i:3d}. {url}\n")
                
                f.write("\nVideos:\n")
                for i, video in enumerate(all_videos, 1):
                    f.write(f"{i:3d}. {video.title} ({video.download_method})\n")
                    f.write(f"     {video.file_path}\n")
            
            logger.info(f"📝 Integration-Log erstellt: {integration_log_path}")
        except Exception as e:
            logger.warning(f"Integration-Log konnte nicht erstellt werden: {e}")
        
        return all_videos
        
    except Exception as e:
        logger.error(f"Fehler bei der Crawler-Integration: {e}")
        return []

def main():
    """Hauptfunktion für eigenständige Verwendung mit verbesserter Ordner-Verwaltung"""
    print("🎬 === Video Downloader & Recorder ===")
    print("Lädt Videos von Websites herunter oder zeichnet sie auf")
    print()
    
    # Systemvoraussetzungen prüfen
    print("🔧 Prüfe Systemvoraussetzungen...")
    
    # Temporären Downloader für Requirement-Check erstellen
    temp_output = Path("./temp_check")
    try:
        temp_downloader = VideoDownloader("https://example.com", str(temp_output))
        requirements = temp_downloader.check_system_requirements()
        
        # Cleanup temp directory
        import shutil
        if temp_output.exists():
            shutil.rmtree(temp_output, ignore_errors=True)
    except Exception as e:
        logger.warning(f"System-Check teilweise fehlgeschlagen: {e}")
        requirements = {
            'gui_available': GUI_AVAILABLE,
            'display_available': DISPLAY_AVAILABLE,
            'ffmpeg': False,
            'chromedriver': False,
            'python_packages': True
        }
    
    print(f"✅ GUI verfügbar: {requirements['gui_available']}")
    print(f"✅ Display verfügbar: {requirements['display_available']}")
    print(f"✅ FFmpeg: {requirements['ffmpeg']}")
    print(f"✅ ChromeDriver: {requirements['chromedriver']}")
    print(f"✅ Python Pakete: {requirements['python_packages']}")
    
    if not requirements['python_packages']:
        print("\n❌ Erforderliche Python-Pakete fehlen!")
        print("Installieren Sie: pip install requests beautifulsoup4")
        print("Optional: pip install yt-dlp selenium opencv-python pillow pyautogui psutil")
        return
    
    # Zeige verfügbare Features
    print(f"\n🎯 Verfügbare Download-Methoden:")
    print(f"   📥 Direkte HTTP-Downloads: ✅ Immer verfügbar")
    print(f"   🎯 yt-dlp (YouTube/Vimeo): {'✅' if yt_dlp else '❌'}")
    print(f"   🌐 Browser-Automation: {'✅' if SELENIUM_AVAILABLE else '❌'}")
    print(f"   📹 Screen-Recording: {'✅' if GUI_AVAILABLE and VIDEO_PROCESSING_AVAILABLE else '❌'}")
    
    if not GUI_AVAILABLE:
        print("\n⚠️  GUI nicht verfügbar - Screen-Recording deaktiviert")
        print("   💡 Für Screen-Recording: GUI-Umgebung erforderlich")
    
    if not SELENIUM_AVAILABLE:
        print("\n⚠️  Selenium nicht verfügbar - Browser-Automation deaktiviert")
        print("   💡 Installieren: pip install selenium")
        print("   💡 ChromeDriver: https://chromedriver.chromium.org/")
    
    print()
    
    # Benutzer-Eingaben mit Validierung
    target_url = input("URL zum Scannen nach Videos: ").strip()
    if not target_url:
        print("❌ Keine URL angegeben!")
        return
    
    if not target_url.startswith(('http://', 'https://')):
        target_url = 'https://' + target_url
    
    output_dir = input("Ausgabeordner (Standard: ./video_downloads): ").strip() or "./video_downloads"
    
    # Validiere Ausgabeordner
    try:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Test ob wir Schreibberechtigung haben
        test_file = output_path / ".write_test"
        test_file.touch()
        test_file.unlink()
        
    except PermissionError:
        print(f"❌ Keine Schreibberechtigung für {output_dir}")
        return
    except Exception as e:
        print(f"❌ Fehler beim Erstellen des Ausgabeordners: {e}")
        return
    
    print(f"\n⚙️  Einstellungen:")
    print(f"🎯 Ziel-URL: {target_url}")
    print(f"📁 Ausgabe: {output_path.absolute()}")
    print(f"🔧 Verfügbare Methoden: {sum(1 for v in [True, yt_dlp is not None, SELENIUM_AVAILABLE, GUI_AVAILABLE and VIDEO_PROCESSING_AVAILABLE] if v)}/4")
    print()
    
    # Warnungen für eingeschränkte Umgebungen
    if not GUI_AVAILABLE:
        print("⚠️  Headless-Modus: Nur HTTP-Downloads und yt-dlp verfügbar")
    
    confirm = input("🚀 Download starten? (j/n): ").strip().lower()
    if confirm not in ['j', 'ja', 'y', 'yes']:
        print("❌ Abgebrochen.")
        return
    
    # Video-Downloader starten
    try:
        downloader = VideoDownloader(target_url, str(output_path))
        videos = downloader.process_url(target_url)
        
        downloader.create_video_summary()
        downloader.print_summary()
        
        # Cleanup
        if hasattr(downloader, 'driver') and downloader.driver:
            try:
                downloader.driver.quit()
            except:
                pass
        
    except KeyboardInterrupt:
        print("\n⏸️  Download wurde vom Benutzer abgebrochen.")
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {e}")
        print(f"❌ Fehler: {e}")
        
        # Debug-Info für Entwickler
        if '--debug' in os.sys.argv:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()