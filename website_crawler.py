#!/usr/bin/env python3
"""
Website Crawler und Archiver
Crawlt eine Website und speichert alle Inhalte als Text und PDF
Mit Login-Unterstützung und PDF-Fusion-Option
"""

import os
import re
import json
import requests
import random
from urllib.parse import urljoin, urlparse, quote
from urllib.robotparser import RobotFileParser
from pathlib import Path
import time
from typing import Set, List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
import logging
import getpass  # Für versteckte Passwort-Eingabe
from enum import Enum

class CrawlScope(Enum):
    """Definiert den Umfang des Crawlings"""
    HIERARCHICAL = "hierarchical"  # Nur unter/neben der Basis-URL
    DOMAIN_ONLY = "domain_only"    # Alle URLs der gleichen Domain
    ALL_URLS = "all_urls"          # Alle URLs ohne Einschränkung

# Third-party imports
try:
    from bs4 import BeautifulSoup
    from weasyprint import HTML, CSS
    import base64
    from PIL import Image
    from PyPDF2 import PdfMerger  # Für PDF-Fusion
except ImportError as e:
    print(f"Fehler: Benötigte Bibliotheken nicht installiert: {e}")
    print("Bitte installieren Sie: pip install beautifulsoup4 weasyprint requests pillow PyPDF2")
    print("Zusätzlich für WeasyPrint: sudo apt-get install libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 (Linux)")
    print("Oder: brew install pango (macOS)")
    exit(1)

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/crawler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Debug-Modus aktivieren falls gewünscht
DEBUG_MODE = False

def enable_debug():
    """Aktiviert Debug-Logging"""
    global DEBUG_MODE
    DEBUG_MODE = True
    logger.setLevel(logging.DEBUG)
    logging.getLogger().setLevel(logging.DEBUG)
    logger.debug("Debug-Modus aktiviert")

def disable_debug():
    """Deaktiviert Debug-Logging"""
    global DEBUG_MODE
    DEBUG_MODE = False
    logger.setLevel(logging.WARN)
    logging.getLogger().setLevel(logging.INFO)
    logger.debug("Debug-Modus deaktiviert")

@dataclass
class WebPage:
    """Datenklasse für eine Webseite"""
    url: str
    title: str
    content: str
    images: List[Dict[str, str]]  # Geändert zu Dictionary mit Metadaten
    links: List[Tuple[str, str]]  # (display_text, url)
    file_path: str
    pdf_path: str
    timestamp: str

class WebsiteCrawler:
    """Haupt-Crawler-Klasse"""
    
    def __init__(self, base_url: str, url_title: str, max_urls: int, single_pdf: bool = False, delete_individual_pdfs: bool | str = False, crawl_scope: CrawlScope = CrawlScope.HIERARCHICAL):
        self.base_url = base_url.rstrip('/')
        self.url_title = url_title
        self.max_urls = max_urls
        self.single_pdf = single_pdf
        self.delete_individual = delete_individual_pdfs
        self.crawl_scope = crawl_scope
        self.visited_urls: Set[str] = set()
        self.pages: List[WebPage] = []
        self.queue: List[str] = [base_url]
        
        # Login-Credentials (nur für diese Session)
        self.login_credentials: Dict[str, Dict[str, str]] = {}
        self.login_attempted: Set[str] = set()
        
        # Basis-Domain und Pfad für Filterung
        parsed_base = urlparse(base_url)
        self.base_domain = parsed_base.netloc
        self.base_path = parsed_base.path
        
        # Ordner erstellen
        self.output_dir = self._create_output_directory()
        self.images_dir = self.output_dir / "images"
        self.texts_dir = self.output_dir / "texts"  # Neuer Texts-Ordner
        self.images_dir.mkdir(exist_ok=True)
        self.texts_dir.mkdir(exist_ok=True)
        
        # Session für effiziente Requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # PDF-Pfade für eventuelle Fusion
        self.pdf_paths: List[str] = []
        
        # Statistiken
        self.stats = {
            'processed': 0,
            'errors': 0,
            'images_downloaded': 0,
            'pagination_links_found': 0,
            'total_links_found': 0,
            'skipped_external': 0,
            'skipped_invalid': 0,
            'login_pages_found': 0,
            'login_attempts': 0,
            'login_successes': 0,
            'crawl_scope': crawl_scope.value
        }
    
    def _create_output_directory(self) -> Path:
        """Erstellt den Ausgabeordner mit korrektem Namen"""
        # URL zu gültigem Ordnernamen konvertieren
        
        output_dir = self.url_title
        if os.getcwd().endswith("web-crawler"):
            output_dir = Path(os.path.join(os.getcwd(), 'collection', output_dir))
        elif output_dir.startswith('/'):
            output_dir = Path(output_dir)
        elif output_dir.startswith('./'):
            output_dir = Path(os.path.join(os.getcwd(), output_dir[2:]))
        elif "/" or "\\" in output_dir and not output_dir.startswith("/"):
            output_dir = Path(os.path.join(os.getcwd(), output_dir))
        else:
            output_dir = Path(os.path.join(os.getcwd(), output_dir))
        
        # logger.(f"Erstelle Ausgabeordner: {output_dir}")
        output_dir.mkdir(exist_ok=True)
        # logger.(f"Ausgabeordner erstellt: {output_dir}")
        return output_dir
    
    def _is_valid_url(self, url: str) -> bool:
        """Prüft, ob eine URL verarbeitet werden soll basierend auf dem Crawl-Scope"""
        try:
            parsed = urlparse(url)
            
            # Bestimmte Dateitypen immer ausschließen
            excluded_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.zip', '.rar', '.exe', '.doc', '.docx', '.xls', '.xlsx'}
            if any(parsed.path.lower().endswith(ext) for ext in excluded_extensions):
                logger.debug(f"URL {url} ausgeschlossen: Dateierweiterung")
                return False
            
            # Bestimmte URL-Parameter ausschließen (z.B. Logout-Links)
            excluded_params = {'logout', 'signout', 'exit', 'delete', 'remove'}
            if any(param in parsed.query.lower() for param in excluded_params):
                logger.debug(f"URL {url} ausgeschlossen: ausgeschlossene Parameter")
                return False
            
            # Je nach Crawl-Scope unterschiedliche Validierung
            if self.crawl_scope == CrawlScope.ALL_URLS:
                # Alle URLs sind erlaubt (außer die oben ausgeschlossenen)
                logger.debug(f"URL {url} erlaubt: ALL_URLS Modus")
                return True
                
            elif self.crawl_scope == CrawlScope.DOMAIN_ONLY:
                # Nur URLs der gleichen Domain
                if parsed.netloc != self.base_domain:
                    logger.debug(f"URL {url} ausgeschlossen: andere Domain {parsed.netloc} vs {self.base_domain}")
                    return False
                logger.debug(f"URL {url} erlaubt: gleiche Domain")
                return True
                
            elif self.crawl_scope == CrawlScope.HIERARCHICAL:
                # Hierarchische Validierung (ursprüngliches Verhalten)
                
                # Externe Domains ausschließen
                if parsed.netloc != self.base_domain:
                    logger.debug(f"URL {url} ausgeschlossen: externe Domain {parsed.netloc}")
                    return False
                
                # URLs die hierarchisch unter oder neben der Basis-URL liegen sind erlaubt
                base_path_parts = [part for part in self.base_path.split('/') if part]
                url_path_parts = [part for part in parsed.path.split('/') if part]
                
                logger.debug(f"URL-Validation: {url}")
                logger.debug(f"Base path parts: {base_path_parts}")
                logger.debug(f"URL path parts: {url_path_parts}")
                
                # Überprüfen ob URL unter oder neben der Basis-URL liegt
                if len(url_path_parts) < len(base_path_parts):
                    # URL ist hierarchisch über der Basis-URL -> ausschließen
                    logger.debug(f"URL {url} ausgeschlossen: hierarchisch über Basis-URL")
                    return False
                
                # Prüfen ob die gemeinsamen Pfad-Teile übereinstimmen
                if len(base_path_parts) > 0:
                    if len(url_path_parts) == len(base_path_parts):
                        # Gleiche Ebene: ersten N-1 Teile müssen übereinstimmen (Nachbar-Pfade)
                        if len(base_path_parts) > 1:
                            for i in range(len(base_path_parts) - 1):
                                if url_path_parts[i] != base_path_parts[i]:
                                    logger.debug(f"URL {url} ausgeschlossen: Nachbar-Pfad stimmt nicht überein bei Teil {i}")
                                    return False
                        # Letzter Teil kann unterschiedlich sein (Nachbar-Pfad)
                        logger.debug(f"URL {url} erlaubt: Nachbar-Pfad")
                        
                    elif len(url_path_parts) > len(base_path_parts):
                        # URL ist tiefer: alle Basis-Teile müssen übereinstimmen
                        for i, base_part in enumerate(base_path_parts):
                            if url_path_parts[i] != base_part:
                                logger.debug(f"URL {url} ausgeschlossen: Unter-Pfad stimmt nicht überein bei Teil {i}")
                                return False
                        logger.debug(f"URL {url} erlaubt: Unter-Pfad")
                
                logger.debug(f"URL {url} erlaubt: hierarchische Validierung bestanden")
                return True
            
            else:
                logger.warning(f"Unbekannter Crawl-Scope: {self.crawl_scope}")
                return False
            
        except Exception as e:
            logger.error(f"Fehler beim Validieren der URL {url}: {e}")
            return False
    
    def _detect_login_page(self, soup: BeautifulSoup, url: str) -> bool:
        """Erkennt ob es sich um eine Login-Seite handelt"""
        
        # Verschiedene Indikatoren für Login-Seiten
        login_indicators = [
            # Form-basierte Erkennung
            soup.find('form', {'action': re.compile(r'login|signin|auth', re.I)}),
            soup.find('input', {'type': 'password'}),
            soup.find('input', {'name': re.compile(r'password|pass|pwd', re.I)}),
            soup.find('input', {'name': re.compile(r'username|user|email|login', re.I)}),
            
            # Button/Link-basierte Erkennung
            soup.find('button', string=re.compile(r'(log|sign)\s*in|anmelden|login', re.I)),
            soup.find('input', {'type': 'submit', 'value': re.compile(r'(log|sign)\s*in|anmelden|login', re.I)}),
            
            # URL-basierte Erkennung
            re.search(r'/(login|signin|auth|anmelden)', url, re.I),
            
            # Text-basierte Erkennung
            soup.find(string=re.compile(r'(bitte|please)\s*(log|sign)\s*in|anmeldung\s*erforderlich|authentication\s*required', re.I)),
            
            # Meta-basierte Erkennung
            soup.find('title', string=re.compile(r'login|signin|anmelden|authentication', re.I)),
            
            # Class/ID-basierte Erkennung
            soup.find(attrs={'class': re.compile(r'login|signin|auth', re.I)}),
            soup.find(attrs={'id': re.compile(r'login|signin|auth', re.I)})
        ]
        
        # Wenn mindestens 2 Indikatoren zutreffen, ist es wahrscheinlich eine Login-Seite
        indicators_found = sum(1 for indicator in login_indicators if indicator)
        
        logger.debug(f"Login-Indikatoren für {url}: {indicators_found}//{len(login_indicators)}")
        
        return indicators_found >= 2
    
    def _get_login_credentials(self, url: str) -> Optional[Dict[str, str]]:
        """Fragt Benutzer nach Login-Credentials"""
        
        # Prüfen ob bereits Credentials für diese Domain vorhanden sind
        domain = urlparse(url).netloc
        if domain in self.login_credentials:
            # logger.(f"Verwende gespeicherte Credentials für {domain}")
            return self.login_credentials[domain]
        
        print(f"\n🔐 Login erforderlich für {url}")
        print("=" * 60)
        
        # Benutzer fragen ob Login versucht werden soll
        attempt_login = input("Möchten Sie sich anmelden? (j/n, Standard: n): ").strip().lower()
        
        if attempt_login not in ['j', 'ja', 'y', 'yes']:
            print("⏭️  Login übersprungen - Seite wird als Login-geschützt markiert")
            return None
        
        # Credentials abfragen
        username = input("Username/E-Mail: ").strip()
        if not username:
            print("❌ Kein Username angegeben - Login übersprungen")
            return None
        
        password = getpass.getpass("Password: ")
        if not password:
            print("❌ Kein Password angegeben - Login übersprungen")
            return None
        
        credentials = {
            'username': username,
            'password': password
        }
        
        # Credentials für diese Domain speichern (nur für diese Session)
        self.login_credentials[domain] = credentials
        
        print("✅ Credentials gespeichert für diese Session")
        return credentials
    
    def _attempt_login(self, url: str, soup: BeautifulSoup, credentials: Dict[str, str]) -> bool:
        """Versucht Login mit den gegebenen Credentials"""
        self.stats['login_attempts'] += 1
        
        # Login-Form finden
        login_form = (
            soup.find('form', {'action': re.compile(r'login|signin|auth', re.I)}) or
            soup.find('form', lambda tag: tag and tag.find('input', {'type': 'password'}))
        )
        
        if not login_form:
            logger.warning(f"Keine Login-Form gefunden auf {url}")
            return False
        
        # Form-Action bestimmen
        action = login_form.get('action', '')
        if not action:
            action = url  # Fallback zur aktuellen URL
        else:
            action = urljoin(url, action)
        
        # Form-Daten sammeln
        form_data = {}
        
        # Alle Input-Felder finden
        for input_field in login_form.find_all('input'):
            field_name = input_field.get('name')
            field_type = input_field.get('type', 'text')
            field_value = input_field.get('value', '')
            
            if not field_name:
                continue
            
            # Username-Felder
            if (field_type.lower() in ['text', 'email'] or 
                re.search(r'username|user|email|login', field_name, re.I)):
                form_data[field_name] = credentials['username']
                logger.debug(f"Username-Feld gefunden: {field_name}")
            
            # Password-Felder
            elif field_type.lower() == 'password':
                form_data[field_name] = credentials['password']
                logger.debug(f"Password-Feld gefunden: {field_name}")
            
            # Hidden-Felder und andere Werte beibehalten
            elif field_type.lower() in ['hidden', 'submit']:
                if field_value:
                    form_data[field_name] = field_value
                    logger.debug(f"Hidden-Feld gefunden: {field_name} = {field_value}")
        
        # CSRF-Token suchen (falls vorhanden)
        csrf_token = soup.find('input', {'name': re.compile(r'csrf|token|_token', re.I)})
        if csrf_token:
            token_name = csrf_token.get('name')
            token_value = csrf_token.get('value')
            if token_name and token_value:
                form_data[token_name] = token_value
                logger.debug(f"CSRF-Token gefunden: {token_name}")
        
        logger.debug(f"Versuche Login auf {action} mit {len(form_data)} Feldern")
        
        # POST-Request für Login
        response = self.session.post(
            action,
            data=form_data,
            timeout=15,
            allow_redirects=True
        )
        
        # Login-Erfolg prüfen
        success_indicators = [
            response.status_code == 200,
            'dashboard' in response.url.lower(),
            'profile' in response.url.lower(),
            'welcome' in response.text.lower(),
            'logout' in response.text.lower(),
            not self._detect_login_page(BeautifulSoup(response.content, 'html.parser'), response.url)
        ]
        
        login_success = sum(success_indicators) >= 2
        
        if login_success:
            logger.info(f"✅ Login erfolgreich für {urlparse(url).netloc}")
            self.stats['login_successes'] += 1
            print(f"✅ Login erfolgreich für {urlparse(url).netloc}")
            return True
        else:
            logger.warning(f"❌ Login fehlgeschlagen für {urlparse(url).netloc}")
            print(f"❌ Login fehlgeschlagen für {urlparse(url).netloc}")
            return False
                
    def _extract_pagination_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extrahiert Pagination-Links (Next, Nächste Seite, etc.)"""
        pagination_urls = []
        
        # Verschiedene Pagination-Begriffe in mehreren Sprachen
        pagination_patterns = [
            # Deutsch
            r'nächste\s*(seite|page)?', r'weiter', r'vorwärts', r'folgende',
            # Englisch
            r'next\s*(page|step)?', r'forward', r'continue', r'more',
            # Französisch
            r'suivant', r'prochain', r'continuer',
            # Spanisch
            r'siguiente', r'próximo', r'continuar',
            # Italienisch
            r'successivo', r'avanti', r'continua',
            # Allgemein
            r'→', r'►', r'»', r'>>',
            # Numerische Pagination
            r'page\s*\d+', r'seite\s*\d+', r'\d+\s*/'
        ]
        
        # Kompilierte Regex-Pattern für bessere Performance
        compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in pagination_patterns]
        
        # Suche nach Pagination-Links
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            if not href:
                continue
            
            # Link-Text und umgebende Elemente analysieren
            link_text = link.get_text(strip=True).lower()
            
            # Auch title, aria-label und andere Attribute prüfen
            title = (link.get('title') or '').lower()
            aria_label = (link.get('aria-label') or '').lower()
            class_attr = ' '.join(link.get('class', [])).lower()
            
            # Alle relevanten Texte kombinieren
            all_text = f"{link_text} {title} {aria_label} {class_attr}"
            
            # Prüfen ob einer der Pagination-Pattern zutrifft
            for pattern in compiled_patterns:
                if pattern.search(all_text):
                    absolute_url = urljoin(base_url, href)
                    absolute_url = absolute_url.split('#')[0]  # Anker entfernen
                    
                    if self._is_valid_url(absolute_url):
                        pagination_urls.append(absolute_url)
                        logger.debug(f"Pagination-Link gefunden: {link_text} -> {absolute_url}")
                    break
        
        # Auch Buttons und andere Elemente prüfen
        for button in soup.find_all(['button', 'input'], type=['button', 'submit']):
            onclick = button.get('onclick') or ''
            value = button.get('value') or ''
            button_text = button.get_text(strip=True).lower()
            
            all_text = f"{button_text} {value} {onclick}".lower()
            
            for pattern in compiled_patterns:
                if pattern.search(all_text):
                    # JavaScript-Links extrahieren (falls vorhanden)
                    url_match = re.search(r'location\.href\s*=\s*["\']([^"\']+)["\']', onclick)
                    if url_match:
                        absolute_url = urljoin(base_url, url_match.group(1))
                        if self._is_valid_url(absolute_url):
                            pagination_urls.append(absolute_url)
                            logger.debug(f"Button-Pagination gefunden: {button_text} -> {absolute_url}")
                    break
        
        return list(set(pagination_urls))  # Duplikate entfernen
        """Extrahiert Pagination-Links (Next, Nächste Seite, etc.)"""
        pagination_urls = []
        
        # Verschiedene Pagination-Begriffe in mehreren Sprachen
        pagination_patterns = [
            # Deutsch
            r'nächste\s*(seite|page)?', r'weiter', r'vorwärts', r'folgende',
            # Englisch
            r'next\s*(page|step)?', r'forward', r'continue', r'more',
            # Französisch
            r'suivant', r'prochain', r'continuer',
            # Spanisch
            r'siguiente', r'próximo', r'continuar',
            # Italienisch
            r'successivo', r'avanti', r'continua',
            # Allgemein
            r'→', r'►', r'»', r'>>',
            # Numerische Pagination
            r'page\s*\d+', r'seite\s*\d+', r'\d+\s*/'
        ]
        
        # Kompilierte Regex-Pattern für bessere Performance
        compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in pagination_patterns]
        
        # Suche nach Pagination-Links
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            if not href:
                continue
            
            # Link-Text und umgebende Elemente analysieren
            link_text = link.get_text(strip=True).lower()
            
            # Auch title, aria-label und andere Attribute prüfen
            title = (link.get('title') or '').lower()
            aria_label = (link.get('aria-label') or '').lower()
            class_attr = ' '.join(link.get('class', [])).lower()
            
            # Alle relevanten Texte kombinieren
            all_text = f"{link_text} {title} {aria_label} {class_attr}"
            
            # Prüfen ob einer der Pagination-Pattern zutrifft
            for pattern in compiled_patterns:
                if pattern.search(all_text):
                    absolute_url = urljoin(base_url, href)
                    absolute_url = absolute_url.split('#')[0]  # Anker entfernen
                    
                    if self._is_valid_url(absolute_url):
                        pagination_urls.append(absolute_url)
                        logger.debug(f"Pagination-Link gefunden: {link_text} -> {absolute_url}")
                    break
        
        # Auch Buttons und andere Elemente prüfen
        for button in soup.find_all(['button', 'input'], type=['button', 'submit']):
            onclick = button.get('onclick') or ''
            value = button.get('value') or ''
            button_text = button.get_text(strip=True).lower()
            
            all_text = f"{button_text} {value} {onclick}".lower()
            
            for pattern in compiled_patterns:
                if pattern.search(all_text):
                    # JavaScript-Links extrahieren (falls vorhanden)
                    url_match = re.search(r'location\.href\s*=\s*["\']([^"\']+)["\']', onclick)
                    if url_match:
                        absolute_url = urljoin(base_url, url_match.group(1))
                        if self._is_valid_url(absolute_url):
                            pagination_urls.append(absolute_url)
                            logger.debug(f"Button-Pagination gefunden: {button_text} -> {absolute_url}")
                    break
        
        return list(set(pagination_urls))  # Duplikate entfernen
    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[Tuple[str, str]]:
        """Extrahiert alle Links aus einer Seite"""
        links = []
        new_urls = []
        
        # Erst normale Links extrahieren
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            if not href:
                continue
                
            # Relative URLs zu absoluten URLs konvertieren
            absolute_url = urljoin(base_url, href)
            
            # Ankerlinks entfernen
            absolute_url = absolute_url.split('#')[0]
            
            # Link-Text extrahieren
            link_text = link.get_text(strip=True) or href
            
            links.append((link_text, absolute_url))
            
            # URL-Validierung und Queue-Management
            if self._is_valid_url(absolute_url):
                if absolute_url not in self.visited_urls and absolute_url not in self.queue:
                    new_urls.append(absolute_url)
                    logger.debug(f"Neue gültige URL gefunden: {absolute_url}")
            else:
                # Statistik für ungültige URLs
                parsed = urlparse(absolute_url)
                if parsed.netloc != self.base_domain:
                    self.stats['skipped_external'] += 1
                    logger.debug(f"Externe URL übersprungen: {absolute_url}")
                else:
                    self.stats['skipped_invalid'] += 1
                    logger.debug(f"Ungültige URL übersprungen: {absolute_url}")
        
        # Pagination-Links extrahieren (höhere Priorität)
        pagination_urls = self._extract_pagination_links(soup, base_url)
        self.stats['pagination_links_found'] += len(pagination_urls)
        
        # Normale URLs zählen
        self.stats['total_links_found'] += len(new_urls)
        
        # Pagination-URLs zur Queue hinzufügen (mit höherer Priorität)
        for page_url in pagination_urls:
            if page_url not in self.visited_urls and page_url not in self.queue:
                # Pagination-Links werden am Anfang der Queue eingefügt (höhere Priorität)
                self.queue.insert(0, page_url)
                logger.debug(f"Pagination-URL zur Queue hinzugefügt: {page_url}")
        
        # Normale URLs am Ende der Queue hinzufügen
        for url in new_urls:
            if url not in pagination_urls:  # Vermeiden von Duplikaten
                self.queue.append(url)
                logger.debug(f"Normale URL zur Queue hinzugefügt: {url}")
        
        logger.debug(f"Link-Extraktion abgeschlossen: {len(links)} Links gefunden, {len(new_urls)} neue URLs, {len(pagination_urls)} Pagination-URLs")
        return links
    
    def _download_image(self, img_url: str, img_name: str) -> Optional[str]:
        """Lädt ein Bild herunter und speichert es"""
        try:
            response = self.session.get(img_url, timeout=10)
            response.raise_for_status()
            
            img_path = self.images_dir / img_name
            
            with open(img_path, 'wb') as f:
                f.write(response.content)
            
            # Bildgröße für Web/PDF optimieren
            try:
                with Image.open(img_path) as img:
                    # Bild für Web-Anzeige optimieren (max 1200px breit)
                    if img.width > 1200:
                        ratio = 1200 / img.width
                        new_height = int(img.height * ratio)
                        img = img.resize((1200, new_height), Image.Resampling.LANCZOS)
                        img.save(img_path, optimize=True, quality=85)
            except Exception as e:
                logger.debug(f"Bildoptimierung fehlgeschlagen für {img_name}: {e}")
                pass  # Bild trotzdem verwenden
            
            self.stats['images_downloaded'] += 1
            return str(img_path.absolute())
            
        except Exception as e:
            logger.error(f"Fehler beim Herunterladen von {img_url}: {e}")
            return None
    
    def _extract_images_and_embed(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extrahiert Bilder und embeddet sie direkt in das HTML als Base64"""
        images = []
        
        for idx, img in enumerate(soup.find_all('img', src=True)):
            src = img.get('src')
            if not src:
                continue
            
            # Relative URLs zu absoluten URLs konvertieren
            img_url = urljoin(base_url, src)
            
            # Dateiname generieren
            img_name = os.path.basename(urlparse(img_url).path)
            if not img_name or '.' not in img_name:
                img_name = f"image_{idx}.jpg"
            
            # Dateiname bereinigen
            img_name = re.sub(r'[<>:"/\\|?*]', '_', img_name)
            
            # Bild herunterladen
            img_path = self._download_image(img_url, img_name)
            if img_path:
                try:
                    # Bild als Base64 einbetten
                    with open(img_path, 'rb') as f:
                        img_data = f.read()
                    
                    # MIME-Type bestimmen
                    if img_path.lower().endswith(('.png', '.PNG')):
                        mime_type = 'image/png'
                    elif img_path.lower().endswith(('.jpg', '.jpeg', '.JPG', '.JPEG')):
                        mime_type = 'image/jpeg'
                    elif img_path.lower().endswith(('.gif', '.GIF')):
                        mime_type = 'image/gif'
                    elif img_path.lower().endswith(('.svg', '.SVG')):
                        mime_type = 'image/svg+xml'
                    else:
                        mime_type = 'image/jpeg'  # Fallback
                    
                    # Base64-Kodierung
                    img_base64 = base64.b64encode(img_data).decode('utf-8')
                    data_uri = f"data:{mime_type};base64,{img_base64}"
                    
                    # Img-Tag im HTML aktualisieren
                    img['src'] = data_uri
                    
                    # Responsive Bildgröße für PDF setzen
                    img['style'] = img.get('style', '') + ' max-width: 100%; height: auto;'
                    
                    # Bild-Metadaten sammeln
                    img_data_info = {
                        'path': img_path,
                        'url': img_url,
                        'alt': img.get('alt', ''),
                        'title': img.get('title', ''),
                        'position': idx,
                        'embedded': True
                    }
                    images.append(img_data_info)
                    
                    # logger.debug(f"Bild als Base64 eingebettet: {img_name}")
                    
                except Exception as e:
                    logger.error(f"Fehler beim Einbetten von Bild {img_path}: {e}")
                    # Fallback: ursprüngliche URL beibehalten
                    img['src'] = img_url
        
        return images
    
    def _clean_text(self, text: str) -> str:
        """Bereinigt Text von überflüssigen Whitespaces"""
        # Mehrfache Leerzeichen und Zeilenumbrüche reduzieren
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n\n', text)
        return text.strip()
    
    def _create_text_content(self, page: WebPage) -> str:
        """Erstellt den Textinhalt mit Links und Bildpfaden"""
        content = f"Titel: {page.title}\n"
        content += f"URL: {page.url}\n"
        content += f"Zeitpunkt: {page.timestamp}\n"
        content += "=" * 50 + "\n\n"
        
        # Hauptinhalt mit eingefügten Bildern
        main_content = page.content
        
        # Bilder in den Text einfügen
        for img_data in page.images:
            placeholder = f"[IMAGE_{img_data['position']}]"
            if placeholder in main_content:
                img_info = f"\n\n[BILD: {img_data['path']}"
                if img_data['alt']:
                    img_info += f" | Alt: {img_data['alt']}"
                if img_data['title']:
                    img_info += f" | Titel: {img_data['title']}"
                img_info += f" | URL: {img_data['url']}]\n\n"
                main_content = main_content.replace(placeholder, img_info)
        
        content += main_content + "\n\n"
        
        # Links hinzufügen
        if page.links:
            content += "LINKS:\n"
            content += "-" * 10 + "\n"
            for link_text, link_url in page.links:
                content += f"[{link_text}|{link_url}]\n"
            content += "\n"
        
        # Alle Bilder am Ende auflisten
        if page.images:
            content += "BILDER-VERZEICHNIS:\n"
            content += "-" * 20 + "\n"
            for img_data in page.images:
                content += f"Datei: {img_data['path']}\n"
                content += f"URL: {img_data['url']}\n"
                if img_data['alt']:
                    content += f"Alt-Text: {img_data['alt']}\n"
                if img_data['title']:
                    content += f"Titel: {img_data['title']}\n"
                content += "\n"
        
        # Quelle hinzufügen
        content += f"Quelle: {page.url}\n"
        
        return content
    
    def _create_pdf_html(self, page: WebPage, original_html: str) -> None:
        """Erstellt ein PDF aus HTML mit vollständiger Formatierung"""
        try:
            # HTML für PDF aufbereiten
            soup = BeautifulSoup(original_html, 'html.parser')
            
            # Überflüssige Elemente für PDF entfernen
            for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe']):
                element.decompose()
            
            # Content-Bereich extrahieren
            content_element = (
                soup.find('main') or 
                soup.find('article') or 
                soup.find('div', class_=re.compile(r'content|main|article', re.I)) or
                soup.find('body')
            )
            
            if not content_element:
                content_element = soup
            
            # Bilder einbetten
            images = self._extract_images_and_embed(content_element, page.url)
            
            # CSS für PDF-Styling
            pdf_css = """
            @page {
                size: A4;
                margin: 2cm 2cm 3cm 2cm;
                
                @bottom-left {
                    content: "Quelle: """ + page.url + """";
                    font-size: 10px;
                    font-family: Arial, sans-serif;
                    color: #666;
                }
                
                @bottom-right {
                    content: "Seite " counter(page) " von " counter(pages);
                    font-size: 10px;
                    font-family: Arial, sans-serif;
                    color: #666;
                }
            }
            
            body {
                font-family: Arial, Helvetica, sans-serif;
                font-size: 12px;
                line-height: 1.6;
                color: #333;
                margin: 0;
                padding: 0;
            }
            
            h1, h2, h3, h4, h5, h6 {
                color: #2c3e50;
                margin: 1.5em 0 0.5em 0;
                page-break-after: avoid;
            }
            
            h1 {
                font-size: 24px;
                border-bottom: 2px solid #3498db;
                padding-bottom: 10px;
            }
            
            h2 {
                font-size: 20px;
                border-bottom: 1px solid #bdc3c7;
                padding-bottom: 5px;
            }
            
            h3 {
                font-size: 18px;
                color: #34495e;
            }
            
            h4 {
                font-size: 16px;
                color: #34495e;
            }
            
            p {
                margin: 0.8em 0;
                text-align: justify;
            }
            
            img {
                max-width: 100%;
                height: auto;
                display: block;
                margin: 1em auto;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 5px;
                background-color: #f9f9f9;
            }
            
            code {
                background-color: #f4f4f4;
                padding: 2px 4px;
                border-radius: 3px;
                font-family: "Courier New", monospace;
                font-size: 11px;
            }
            
            pre {
                background-color: #f4f4f4;
                padding: 15px;
                border-radius: 5px;
                border-left: 4px solid #3498db;
                overflow-x: auto;
                font-family: "Courier New", monospace;
                font-size: 11px;
                line-height: 1.4;
            }
            
            blockquote {
                border-left: 4px solid #3498db;
                padding-left: 20px;
                margin: 1em 0;
                font-style: italic;
                color: #555;
            }
            
            ul, ol {
                margin: 1em 0;
                padding-left: 2em;
            }
            
            li {
                margin: 0.3em 0;
            }
            
            table {
                border-collapse: collapse;
                width: 100%;
                margin: 1em 0;
                font-size: 11px;
            }
            
            th, td {
                border: 1px solid #ddd;
                padding: 8px;
                text-align: left;
            }
            
            th {
                background-color: #f2f2f2;
                font-weight: bold;
            }
            
            tr:nth-child(even) {
                background-color: #f9f9f9;
            }
            
            a {
                color: #3498db;
                text-decoration: none;
            }
            
            a:hover {
                text-decoration: underline;
            }
            
            .highlight {
                background-color: #fff3cd;
                padding: 2px 4px;
                border-radius: 3px;
            }
            
            .text-center {
                text-align: center;
            }
            
            .text-right {
                text-align: right;
            }
            
            .page-break {
                page-break-before: always;
            }
            
            .no-break {
                page-break-inside: avoid;
            }
            
            /* Responsive Tabellen für PDF */
            @media print {
                table {
                    page-break-inside: auto;
                }
                
                tr {
                    page-break-inside: avoid;
                    page-break-after: auto;
                }
            }
            """
            
            # Vollständige HTML-Struktur erstellen
            html_content = f"""
            <!DOCTYPE html>
            <html lang="de">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>{page.title}</title>
                <style>{pdf_css}</style>
            </head>
            <body>
                <div class="header">
                    <h1>{page.title}</h1>
                    <p><strong>URL:</strong> {page.url}</p>
                    <p><strong>Archiviert am:</strong> {page.timestamp}</p>
                    <hr>
                </div>
                
                <div class="content">
                    {content_element}
                </div>
            </body>
            </html>
            """
            
            # PDF mit WeasyPrint erstellen
            html_doc = HTML(string=html_content)
            html_doc.write_pdf(page.pdf_path)
            
            # Bilder-Info aktualisieren
            page.images = images
            
            logger.debug(f"PDF mit HTML-Formatting erstellt: {page.pdf_path} ({len(images)} Bilder eingebettet)")
            
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des HTML-PDFs für {page.url}: {e}")
            # Fallback: Einfaches Text-PDF erstellen
            try:
                self._create_simple_pdf_fallback(page)
            except Exception as fallback_error:
                logger.error(f"Auch Fallback-PDF fehlgeschlagen: {fallback_error}")
    
    def _create_simple_pdf_fallback(self, page: WebPage) -> None:
        """Erstellt ein einfaches Text-PDF als Fallback"""
        try:
            # Einfaches HTML für Fallback
            simple_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>{page.title}</title>
                <style>
                    @page {{
                        size: A4;
                        margin: 2cm;
                        @bottom-left {{
                            content: "Quelle: {page.url}";
                            font-size: 10px;
                        }}
                        @bottom-right {{
                            content: "Seite " counter(page) " von " counter(pages);
                            font-size: 10px;
                        }}
                    }}
                    body {{
                        font-family: Arial, sans-serif;
                        font-size: 12px;
                        line-height: 1.6;
                    }}
                    h1 {{
                        color: #333;
                        border-bottom: 2px solid #ccc;
                        padding-bottom: 10px;
                    }}
                    p {{
                        margin: 1em 0;
                        text-align: justify;
                    }}
                </style>
            </head>
            <body>
                <h1>{page.title}</h1>
                <p><strong>URL:</strong> {page.url}</p>
                <p><strong>Archiviert am:</strong> {page.timestamp}</p>
                <hr>
                <div>
                    {'<p>' + page.content.replace('\n\n', '</p><p>') + '</p>'}
                </div>
            </body>
            </html>
            """
            
            html_doc = HTML(string=simple_html)
            html_doc.write_pdf(page.pdf_path)
            
            logger.debug(f"Fallback-PDF erstellt: {page.pdf_path}")
            
        except Exception as e:
            logger.error(f"Fallback-PDF fehlgeschlagen: {e}")
    
    def _process_url(self, url: str) -> Optional[WebPage]:
        """Verarbeitet eine einzelne URL mit Login-Support"""
        try:
            logger.debug(f"Verarbeite URL: {url}")
            
            # Ersten Request machen
            pause_duration = random.randint(2, 6)
            time.sleep(pause_duration)
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            # Login-Detection
            soup = BeautifulSoup(response.content, 'html.parser')
            
            if self._detect_login_page(soup, url):
                self.stats['login_pages_found'] += 1
                logger.info(f"🔐 Login-Seite erkannt: {url}")
                
                # Prüfen ob bereits Login versucht wurde für diese Domain
                domain = urlparse(url).netloc
                if domain not in self.login_attempted:
                    self.login_attempted.add(domain)
                    
                    # Credentials abfragen
                    credentials = self._get_login_credentials(url)
                    
                    if credentials:
                        # Login versuchen
                        if self._attempt_login(url, soup, credentials):
                            # Nach erfolgreichem Login erneut versuchen
                            response = self.session.get(url, timeout=15)
                            response.raise_for_status()
                            soup = BeautifulSoup(response.content, 'html.parser')
                        else:
                            # Login fehlgeschlagen - erstelle Login-geschützte Seite
                            return self._create_login_protected_page(url)
                    else:
                        # Keine Credentials - erstelle Login-geschützte Seite
                        return self._create_login_protected_page(url)
                else:
                    # Login bereits versucht - prüfen ob Session noch gültig
                    if domain in self.login_credentials:
                        logger.debug(f"Verwende bestehende Session für {domain}")
                    else:
                        # Session ungültig oder Login nicht versucht
                        return self._create_login_protected_page(url)
            
            # Ursprüngliches HTML für PDF-Erstellung speichern
            original_html = response.text
            
            # Backup der ursprünglichen Seite für Bildextraktion
            original_soup = BeautifulSoup(response.content, 'html.parser')
            
            # Arbeits-Kopie für Content-Extraktion
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Titel extrahieren
            title = soup.find('title')
            title = title.get_text(strip=True) if title else "Ohne Titel"
            
            # Für Textdatei: vereinfachte Bildextraktion
            text_images = []
            for idx, img in enumerate(soup.find_all('img', src=True)):
                src = img.get('src')
                if src:
                    img_url = urljoin(url, src)
                    img_name = os.path.basename(urlparse(img_url).path) or f"image_{idx}.jpg"
                    img_name = re.sub(r'[<>:"/\\|?*]', '_', img_name)
                    
                    img_path = self._download_image(img_url, img_name)
                    if img_path:
                        img_data = {
                            'path': img_path,
                            'url': img_url,
                            'alt': img.get('alt', ''),
                            'title': img.get('title', ''),
                            'position': idx
                        }
                        text_images.append(img_data)
            
            # Content für Textdatei extrahieren
            # Überflüssige Elemente entfernen
            for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                element.decompose()
            
            # Content-Bereich finden
            content_element = (
                soup.find('main') or 
                soup.find('article') or 
                soup.find('div', class_=re.compile(r'content|main|article', re.I)) or
                soup.find('body')
            )
            
            if content_element:
                content = content_element.get_text(separator='\n', strip=True)
            else:
                content = soup.get_text(separator='\n', strip=True)
            
            content = self._clean_text(content)
            
            # Links extrahieren (mit Original-Soup)
            links = self._extract_links(original_soup, url)
            
            # Dateinamen erstellen
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:100]
            file_name = f"{len(self.pages) + 1:03d}_{safe_title}"
            
            # Textdatei im /texts Unterordner speichern
            text_path = self.texts_dir / f"{file_name}.txt"
            pdf_path = self.output_dir / f"{file_name}.pdf"
            
            # WebPage-Objekt erstellen
            page = WebPage(
                url=url,
                title=title,
                content=content,
                images=text_images,  # Vorläufig für Textdatei
                links=links,
                file_path=str(text_path),
                pdf_path=str(pdf_path),
                timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # Textdatei erstellen
            text_content = self._create_text_content(page)
            with open(text_path, 'w', encoding='utf-8') as f:
                f.write(text_content)
            
            # PDF erstellen (einzeln oder für späteren Merge)
            self._create_pdf_html(page, original_html)
            
            # PDF-Pfad für eventuelle Fusion speichern
            if self.single_pdf:
                self.pdf_paths.append(str(pdf_path))
            
            self.stats['processed'] += 1
            logger.debug(f"Seite erfolgreich verarbeitet: {title} ({len(text_images)} Bilder)")
            
            return page
            
        except Exception as e:
            logger.error(f"Fehler beim Verarbeiten von {url}: {e}")
            self.stats['errors'] += 1
            return None
    
    def _create_login_protected_page(self, url: str) -> WebPage:
        """Erstellt eine Placeholder-Seite für Login-geschützte Inhalte"""
        
        title = "Login-geschützte Seite"
        content = "Diese Seite ist nur über einen Login erreichbar und konnte nicht automatisch verarbeitet werden."
        
        # Dateinamen erstellen
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:100]
        file_name = f"{len(self.pages) + 1:03d}_{safe_title}_{urlparse(url).path.split('/')[-1]}"
        
        text_path = self.texts_dir / f"{file_name}.txt"
        pdf_path = self.output_dir / f"{file_name}.pdf"
        
        # WebPage-Objekt erstellen
        page = WebPage(
            url=url,
            title=title,
            content=content,
            images=[],
            links=[],
            file_path=str(text_path),
            pdf_path=str(pdf_path),
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
        )
        
        # Textdatei erstellen
        text_content = self._create_text_content(page)
        with open(text_path, 'w', encoding='utf-8') as f:
            f.write(text_content)
        
        # Einfaches PDF für Login-geschützte Seite erstellen
        self._create_simple_pdf_fallback(page)
        
        if self.single_pdf:
            self.pdf_paths.append(str(pdf_path))
        
        logger.debug(f"Login-geschützte Seite erstellt: {title}")
        return page
    
    def _merge_pdfs(self) -> None:
        """Fusioniert alle einzelnen PDFs zu einem großen PDF"""
        if not self.pdf_paths:
            logger.warning("Keine PDFs zum Fusionieren gefunden")
            return
        
        try:
            merger = PdfMerger()
            
            # Alle PDFs in der richtigen Reihenfolge hinzufügen
            for pdf_path in self.pdf_paths:
                if os.path.exists(pdf_path):
                    merger.append(pdf_path)
                    logger.debug(f"PDF zur Fusion hinzugefügt: {pdf_path}")
                else:
                    logger.warning(f"PDF nicht gefunden: {pdf_path}")
            pdf_filename = f"{self.base_domain}.pdf"
            # Fusioniertes PDF speichern
            merged_pdf_path = self.output_dir / pdf_filename
            merger.write(str(merged_pdf_path))
            merger.close()
            
            logger.info(f"✅ PDFs erfolgreich fusioniert: {merged_pdf_path}")
            logger.info(f"📖 Einzelne PDFs wurden zu einer Datei zusammengefügt: {merged_pdf_path}")
            
            # Einzelne PDFs optional löschen (User fragen)
            
            if self.delete_individual in ['j', 'ja', 'y', 'yes', True, 'true']:
                deleted_count = 0
                for pdf_path in self.pdf_paths:
                    try:
                        os.remove(pdf_path)
                        deleted_count += 1
                    except Exception as e:
                        logger.error(f"Fehler beim Löschen von {pdf_path}: {e}")
                
                logger.info(f"🗑️  {deleted_count} einzelne PDF-Dateien gelöscht")
                print(f"🗑️  {deleted_count} einzelne PDF-Dateien gelöscht")
        
        except Exception as e:
            logger.error(f"Fehler beim Fusionieren der PDFs: {e}")
            print(f"❌ Fehler beim Fusionieren der PDFs: {e}")
    
    def _create_url_collection_json(self) -> None:
        """Erstellt url-collection.json (ehemals summary.json)"""
        # Seiten nach URL-Pfad gruppieren
        grouped_pages = defaultdict(list)
        
        for page in self.pages:
            parsed_url = urlparse(page.url)
            path_parts = parsed_url.path.split('/')
            
            # Gruppierung nach Pfad-Tiefe
            if len(path_parts) <= 2:
                group_key = "/"
            else:
                group_key = '/'.join(path_parts[:3])
            
            grouped_pages[group_key].append(page)
        
        # Innerhalb jeder Gruppe nach URL sortieren
        for group in grouped_pages.values():
            group.sort(key=lambda x: x.url)
        
        # JSON-Struktur erstellen
        json_data = {
            "base_url": self.base_url,
            "crawl_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "single_pdf_created": self.single_pdf,
            "statistics": self.stats,
            "groups": {}
        }
        
        for group_key, pages in grouped_pages.items():
            json_data["groups"][group_key] = []
            for page in pages:
                # Bilder-Informationen für JSON aufbereiten
                image_info = []
                for img_data in page.images:
                    image_info.append({
                        "path": img_data["path"],
                        "url": img_data["url"],
                        "alt": img_data.get("alt", ""),
                        "title": img_data.get("title", ""),
                        "position": img_data.get("position", 0)
                    })
                
                page_data = {
                    "url": page.url,
                    "title": page.title,
                    "content": page.content[:500] + "..." if len(page.content) > 500 else page.content,
                    "images": image_info,
                    "links": page.links,
                    "file_path": page.file_path,
                    "pdf_path": page.pdf_path,
                    "timestamp": page.timestamp
                }
                json_data["groups"][group_key].append(page_data)
        
        json_path = self.output_dir / "url-collection.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"URL-Collection JSON erstellt: {json_path}")
    
    def _create_summary_json(self) -> None:
        """Erstellt das neue summary.json in Sitemap-Reihenfolge"""
        
        # URLs in derselben Reihenfolge wie in der Sitemap sortieren
        sorted_pages = sorted(self.pages, key=lambda x: x.url)
        
        # JSON-Struktur für Summary erstellen
        summary_data = []
        
        for page in sorted_pages:
            # Bildpfade als Liste extrahieren
            image_paths = [img_data["path"] for img_data in page.images]
            
            page_summary = {
                "title": page.title,
                "url": page.url,
                "textcontent": page.content,
                "image_paths": image_paths,
                "date": time.strftime("%Y-%m-%d")
            }
            
            summary_data.append(page_summary)
        
        # Summary JSON speichern
        summary_path = self.output_dir / "summary.json"
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Summary JSON erstellt: {summary_path}")
        
        # Zusätzliche Bild-Statistiken
        total_images = sum(len(page.images) for page in self.pages)
        successful_images = sum(1 for page in self.pages for img in page.images if os.path.exists(img['path']))
        
        logger.info(f"Bilder-Statistiken: {successful_images}/{total_images} erfolgreich heruntergeladen")
    
    def _create_sitemap(self) -> None:
        """Erstellt eine Sitemap-Datei"""
        sitemap_content = f"SITEMAP für {self.base_url}\n"
        sitemap_content += "=" * 50 + "\n\n"
        
        # URLs hierarchisch sortieren
        urls = [page.url for page in self.pages]
        urls.sort()
        
        # Hierarchische Struktur aufbauen
        url_tree = {}
        for url in urls:
            parsed = urlparse(url)
            path_parts = [part for part in parsed.path.split('/') if part]
            
            current = url_tree
            for part in path_parts:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current['__url__'] = url
        
        def build_tree_string(tree, indent=0):
            result = ""
            for key, value in sorted(tree.items()):
                if key == '__url__':
                    continue
                spaces = "  " * indent
                result += f"{spaces}{key}/\n"
                if isinstance(value, dict):
                    if '__url__' in value:
                        result += f"{spaces}  → {value['__url__']}\n"
                    result += build_tree_string(value, indent + 1)
            return result
        
        sitemap_content += build_tree_string(url_tree)
        sitemap_content += "\n\nAlle URLs:\n"
        sitemap_content += "-" * 20 + "\n"
        for page in self.pages:
            sitemap_content += f"{page.url}\n"
        
        sitemap_path = self.output_dir / "sitemap.txt"
        with open(sitemap_path, 'w', encoding='utf-8') as f:
            f.write(sitemap_content)
        
        logger.info(f"Sitemap erstellt: {sitemap_path}")
    
    def crawl(self) -> None:
        """Hauptmethode zum Crawlen der Website"""
        logger.info(f"Starte Crawling von: {self.base_url}")
        logger.info(f"Maximale URLs: {self.max_urls}")
        logger.info(f"PDF-Modus: {'Einzelnes PDF' if self.single_pdf else 'Separate PDFs'}")
        logger.info(f"Crawl-Scope: {self.crawl_scope.value}")
        
        while self.queue and len(self.visited_urls) < self.max_urls:
            url = self.queue.pop(0)
            
            if url in self.visited_urls:
                continue
            
            self.visited_urls.add(url)
            
            # URL verarbeiten
            page = self._process_url(url)
            if page:
                self.pages.append(page)
            
            # Kurze Pause zwischen Requests
            time.sleep(1)
            
            # Fortschritt anzeigen mit detaillierten Informationen
            progress = len(self.visited_urls)
            queue_size = len(self.queue) if len(self.queue) <= self.max_urls else self.max_urls
            
            print("\n\n")
            
            print("=" * 60)
            print(f"\r🔄 Verarbeitet: {progress} | Queue: {queue_size} URLs | "
                  f"Bilder: {self.stats['images_downloaded']} | "
                  f"Login: {self.stats['login_pages_found']} | "
                  f"Pagination: {self.stats['pagination_links_found']} | "
                  f"Scope: {self.crawl_scope.value} | "
                  f"Fehler: {self.stats['errors']}\n", end="", flush=True)
            print("=" * 60)
            
            time.sleep(1)
            # Bei bestimmten Meilensteinen zusätzliche Info ausgeben
            if progress % 10 == 0 and progress > 0:
                print(f"\n📊 Zwischenbericht nach {progress} URLs:")
                print(f"   ✅ Erfolgreich: {self.stats['processed']}")
                print(f"   ❌ Fehler: {self.stats['errors']}")
                print(f"   🖼️  Bilder: {self.stats['images_downloaded']}")
                print(f"   📄 Pagination: {self.stats['pagination_links_found']}")
                print(f"   🔗 Links: {self.stats['total_links_found']}")
                print(f"   🔐 Login-Seiten: {self.stats['login_pages_found']}")
                print(f"   🎯 Scope: {self.crawl_scope.value}")
                
                # Aktuelle URL anzeigen
                if self.pages:
                    last_page = self.pages[-1]
                    print(f"   🌐 Letzte URL: {last_page.url}")
                    print(f"   📝 Titel: {last_page.title[:50]}...")
                    
                print()  # Neue Zeile für bessere Lesbarkeit
        
        print("\n")  # Abschließende neue Zeile
        
        # PDF-Fusion falls gewünscht
        if self.single_pdf and self.pdf_paths:
            logger.info("📖 Starte PDF-Fusion...")
            self._merge_pdfs()
        
        # Abschließende Dateien erstellen
        self._create_url_collection_json()
        self._create_summary_json()
        self._create_sitemap()
        
        # Statistiken ausgeben
        logger.info("=" * 60)
        logger.info("CRAWLING ABGESCHLOSSEN - STATISTIKEN")
        logger.info("=" * 60)
        logger.info(f"📊 Verarbeitete URLs: {self.stats['processed']}")
        logger.info(f"❌ Fehler: {self.stats['errors']}")
        logger.info(f"🖼️  Heruntergeladene Bilder: {self.stats['images_downloaded']}")
        logger.info(f"📄 Pagination-Links gefunden: {self.stats['pagination_links_found']}")
        logger.info(f"🔗 Gesamte Links gefunden: {self.stats['total_links_found']}")
        logger.info(f"🌐 Externe URLs übersprungen: {self.stats['skipped_external']}")
        logger.info(f"⚠️  Ungültige URLs übersprungen: {self.stats['skipped_invalid']}")
        logger.info(f"🔐 Login-Seiten gefunden: {self.stats['login_pages_found']}")
        logger.info(f"🔑 Login-Versuche: {self.stats['login_attempts']}")
        logger.info(f"✅ Erfolgreiche Logins: {self.stats['login_successes']}")
        logger.info(f"🎯 Crawl-Scope: {self.crawl_scope.value}")
        logger.info(f"📁 Ausgabeordner: {self.output_dir}")
        logger.info("=" * 60)
        
        # Erfolgsrate berechnen
        if self.stats['processed'] > 0:
            success_rate = (self.stats['processed'] / (self.stats['processed'] + self.stats['errors'])) * 100
            logger.info(f"✅ Erfolgsrate: {success_rate:.1f}%")
        
        # Login-Erfolgsrate berechnen
        if self.stats['login_attempts'] > 0:
            login_success_rate = (self.stats['login_successes'] / self.stats['login_attempts']) * 100
            logger.info(f"🔐 Login-Erfolgsrate: {login_success_rate:.1f}%")
        
        # Empfehlungen basierend auf Statistiken
        if self.stats['pagination_links_found'] > 0:
            logger.info(f"💡 Tipp: {self.stats['pagination_links_found']} Pagination-Links wurden erkannt und priorisiert verarbeitet.")
        
        if self.stats['skipped_external'] > 10:
            logger.info(f"💡 Tipp: {self.stats['skipped_external']} externe Links übersprungen. Erwägen Sie Domain-Erweiterung falls nötig.")
        
        if self.stats['login_pages_found'] > 0:
            logger.info(f"💡 Tipp: {self.stats['login_pages_found']} Login-geschützte Seiten gefunden. Session-Cookies wurden für weitere Requests verwendet.")
        
        # Scope-spezifische Empfehlungen
        if self.crawl_scope == CrawlScope.ALL_URLS:
            logger.info(f"💡 Tipp: ALL_URLS Modus verwendet - alle gefundenen URLs wurden verarbeitet, unabhängig von der Domain.")
        elif self.crawl_scope == CrawlScope.DOMAIN_ONLY:
            logger.info(f"💡 Tipp: DOMAIN_ONLY Modus - nur URLs der Domain {self.base_domain} wurden verarbeitet.")
        
        print(f"\n🎉 Crawling erfolgreich abgeschlossen!")
        print(f"📊 {self.stats['processed']} Seiten verarbeitet")
        print(f"📁 Dateien gespeichert in: {self.output_dir}")
        print(f"📄 Pagination-Links: {self.stats['pagination_links_found']}")
        print(f"🖼️  Bilder: {self.stats['images_downloaded']}")
        print(f"🔗 Links: {self.stats['total_links_found']}")
        print(f"🔐 Login-Seiten: {self.stats['login_pages_found']}")
        print(f"🎯 Crawl-Scope: {self.crawl_scope.value}")
        if self.single_pdf:
            print(f"📖 Fusioniertes PDF: Website_Komplett.pdf")
        print(f"📋 Logs: crawler.log")
        print(f"📂 Textdateien: /texts/ Ordner")
        print(f"📊 JSON-Berichte: url-collection.json & summary.json")

def main():
    """Hauptfunktion"""
    print("=== Website Crawler und Archiver ===")
    print("🔥 Mit Login-Support, PDF-Fusion und flexiblen Crawling-Modi")
    print()
    
    # Debug-Modus abfragen
    debug_input = input("Debug-Modus aktivieren? (j/n, Standard: n): ").strip().lower() or 'n'
    if debug_input in ['j', 'ja', 'y', 'yes']:
        enable_debug()
        print("🔍 Debug-Modus aktiviert - detaillierte Logs werden angezeigt")
    else:
        disable_debug()
        DEBUG_MODE = False
        logger.setLevel(logging.INFO)
        logging.getLogger().setLevel(logging.INFO)
        print("🔍 Debug-Modus deaktiviert - nur wichtige Logs werden angezeigt")
    
    # Benutzer-Eingaben
    base_url = input("Bitte geben Sie die Basis-URL ein: ").strip()
    if not base_url:
        print("Fehler: Keine URL angegeben!")
        return
    
    dir_name = base_url.replace('https://', '').replace('http://', '').replace('www.','').rstrip('/')
    dir_name = dir_name.replace('/', '-').replace('.', '_').strip("-")
    dir_name = re.sub(r'[<>:"/\\|?*]', '_', dir_name)
    
    url_title = input(f"Der Ausgabeordner wird {dir_name} benannt, zum Umbenennen Name eingeben:\n").strip()
    url_title = url_title if url_title else dir_name
    
    # URL-Format prüfen
    if not base_url.startswith(('http://', 'https://')):
        base_url = 'https://' + base_url
    
    # Basis-Domain extrahieren für Anzeige
    parsed_url = urlparse(base_url)
    base_domain = parsed_url.netloc
    base_path = parsed_url.path
    
    # Crawling-Scope abfragen
    print(f"\n🎯 Crawling-Bereich für {base_url}:")
    print("=" * 60)
    print("1. 📂 Hierarchisch (Standard)")
    print(f"   └─ Nur URLs unter/neben: {base_path}")
    print(f"   └─ Beispiel: {base_domain}{base_path}/subpage, {base_domain}{base_path}/../neighbor")
    print()
    print("2. 🌐 Domain-weit")
    print(f"   └─ Alle URLs der Domain: {base_domain}")
    print(f"   └─ Beispiel: {base_domain}/any/path, {base_domain}/different/section")
    print()
    print("3. 🌍 Unbeschränkt")
    print("   └─ Alle gefundenen URLs, auch externe Domains")
    print("   └─ Beispiel: other-site.com, external-docs.org")
    print()
    print("⚠️  Hinweis: Modus 3 kann sehr viele URLs finden - niedrigere max. Anzahl empfohlen!")
    print()
    
    scope_choice = input("Wählen Sie einen Modus (1/2/3, Standard: 1): ").strip()
    
    if scope_choice == '2':
        crawl_scope = CrawlScope.DOMAIN_ONLY
        scope_description = f"Domain-weit ({base_domain})"
    elif scope_choice == '3':
        crawl_scope = CrawlScope.ALL_URLS
        scope_description = "Unbeschränkt (alle URLs)"
        print("⚠️  ACHTUNG: Unbeschränkter Modus ausgewählt!")
        print("💡 Empfehlung: Niedrigere max. URL-Anzahl (10-50) verwenden")
    else:
        crawl_scope = CrawlScope.HIERARCHICAL
        scope_description = f"Hierarchisch ({base_path})"
    
    try:
        if crawl_scope == CrawlScope.ALL_URLS:
            default_max = "20"  # Niedrigere Standard-Anzahl für unbeschränktes Crawling
        else:
            default_max = "1000"
        
        max_urls = input(f"Wie viele URLs sollen maximal verarbeitet werden? (Standard: {default_max}): ").strip() or default_max
        max_urls = 999999 if max_urls in ["*", "-1", "0"] else int(max_urls)
    except ValueError:
        max_urls = int(default_max)
    
    # PDF-Option abfragen
    print("\n📖 PDF-Ausgabe-Optionen:")
    print("1. Jede Seite als separate PDF-Datei")
    print("2. Alle Seiten in einem einzelnen PDF fusioniert, einzelne PDFs behalten")
    print("3. Alle Seiten in einem einzelnen PDF fusioniert, einzelne PDFs löschen")
    pdf_choice = input("Wählen Sie eine Option (1/2/3, Standard: 2): ").strip()
    # delete_individual = input("\n🗑️  Einzelne PDF-Dateien löschen? (j/n, Standard: n): ").strip().lower()
    single_pdf = pdf_choice in ["1", "2"]
    delete_individual = pdf_choice == "3"
    
    print(f"\n⚙️  Einstellungen:")
    print(f"📍 Basis-URL: {base_url}")
    print(f"🎯 Crawling-Bereich: {scope_description}")
    print(f"🔢 Max. URLs: {max_urls}")
    print(f"📖 PDF-Modus: {'Einzelnes PDF' if single_pdf else 'Separate PDFs'}")
    print(f"🔍 Debug-Modus: {'Aktiviert' if DEBUG_MODE else 'Deaktiviert'}")
    print(f"🔐 Login-Support: Aktiviert (bei Bedarf wird nachgefragt)")
    print()
    
    # Scope-spezifische Warnungen
    if crawl_scope == CrawlScope.ALL_URLS:
        print("⚠️  WARNUNGEN für unbeschränkten Modus:")
        print("   • Kann sehr viele externe URLs finden")
        print("   • Längere Laufzeit und höherer Speicherverbrauch")
        print("   • Respektiert robots.txt anderer Domains möglicherweise nicht")
        print("   • Bei Problemen mit Ctrl+C abbrechen")
        print()
    elif crawl_scope == CrawlScope.DOMAIN_ONLY:
        print("💡 Info: Domain-weiter Modus erfasst alle Bereiche von", base_domain)
        print()
    
    print("📁Ausgabeordner:")
    print("    ├── images/          # Heruntergeladene Bilder")
    print("    ├── *.pdf            # PDF-Dateien")
    print("    ├── texts/           # Text-Dateien (.txt)")
    if single_pdf:
        print("    ├── Website_Komplett.pdf  # Fusioniertes PDF")
    print("    ├── url-collection.json   # Detaillierte URL-Sammlung")
    print("    ├── summary.json          # Kompakte Zusammenfassung")
    print("    ├── sitemap.txt           # Hierarchische Sitemap")
    print("    └── crawler.log           # Detaillierte Logs")
    print()
    
    confirm = input("🚀 Crawling starten? (j/n): ").strip().lower()
    if confirm not in ['j', 'ja', 'y', 'yes']:
        print("❌ Abgebrochen.")
        return
    
    # Hinweise für Login-geschützte Seiten
    print("\n💡 Hinweise:")
    print("🔐 Bei Login-geschützten Seiten werden Sie nach Credentials gefragt")
    print("⏳ Zwischen Requests wird eine Pause eingelegt (höfliches Crawling)")
    print("🛑 Drücken Sie Ctrl+C um das Crawling zu stoppen")
    if crawl_scope == CrawlScope.ALL_URLS:
        print("🌍 Unbeschränkter Modus: Beobachten Sie die Logs auf unerwartete Domains")
    print()
    
    
    # Crawler starten
    try:
        crawler = WebsiteCrawler(base_url, url_title, max_urls, single_pdf, crawl_scope)
        crawler.crawl()
    except KeyboardInterrupt:
        print("\n⏸️  Crawling wurde vom Benutzer abgebrochen.")
        print("📊 Bis hierhin gesammelte Daten wurden gespeichert.")
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {e}")
        print(f"❌ Fehler: {e}")
        if DEBUG_MODE:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()