#!/usr/bin/env python3
"""
Zentrale Download-Schnittstelle
Ermöglicht Video-Download oder Website-Crawling über eine einheitliche Benutzeroberfläche
"""

import os
import sys
import re
import time
from pathlib import Path
from urllib.parse import urlparse
import logging

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('download_service.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def validate_url(url: str) -> str:
    """Validiert und normalisiert eine URL"""
    if not url:
        raise ValueError("Keine URL angegeben")
    
    # URL-Format prüfen und korrigieren
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Basis-Validierung
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            raise ValueError("Ungültiges URL-Format")
    except Exception as e:
        raise ValueError(f"URL-Validierung fehlgeschlagen: {e}")
    
    return url

def create_safe_filename(url: str) -> str:
    """Erstellt einen sicheren Dateinamen aus einer URL"""
    # Domain extrahieren und bereinigen
    domain = urlparse(url).netloc
    safe_name = domain.replace('www.', '').replace('.', '_').replace(':', '_')
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', safe_name)
    return safe_name.strip('_')

def get_output_directory(base_name: str, service_type: str) -> Path:
    """Erstellt und gibt den Ausgabeordner zurück"""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    dir_name = f"{base_name}_{service_type}_{timestamp}"
    
    # Standardmäßig im 'collection' Ordner wenn wir im web-crawler Verzeichnis sind
    if os.getcwd().endswith("web-crawler"):
        output_dir = Path(os.getcwd()) / 'collection' / dir_name
    else:
        output_dir = Path(os.getcwd()) / dir_name
    
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir

def show_welcome():
    """Zeigt Willkommensnachricht"""
    print("=" * 70)
    print("🚀 DOWNLOAD SERVICE - Zentrale Schnittstelle")
    print("=" * 70)
    print("Wählen Sie zwischen Website-Crawling und Video-Download")
    print("Beide Services nutzen spezialisierte, getestete Module")
    print()

def get_user_choice() -> str:
    """Fragt den User nach dem gewünschten Service"""
    print("📋 Verfügbare Services:")
    print("1. 🌐 Website-Crawling (PDF-Erstellung, Bild-Download, Login-Support)")
    print("2. 🎬 Video-Download (YouTube, Vimeo, direkte Videos, Screen-Recording)")
    print("3. ❓ Hilfe anzeigen")
    print("4. 🚪 Beenden")
    print()
    
    while True:
        choice = input("Ihre Wahl (1-4): ").strip()
        if choice in ['1', '2', '3', '4']:
            return choice
        print("❌ Ungültige Eingabe. Bitte wählen Sie 1, 2, 3 oder 4.")

def show_help():
    """Zeigt Hilfe-Informationen"""
    print("\n" + "=" * 70)
    print("📚 HILFE - Download Service")
    print("=" * 70)
    print()
    print("🌐 WEBSITE-CRAWLING:")
    print("   • Lädt komplette Websites als PDF und Text herunter")
    print("   • Extrahiert und speichert alle Bilder")
    print("   • Unterstützt verschiedene Crawling-Modi (hierarchisch, domain-weit, unbeschränkt)")
    print("   • Login-Support für geschützte Bereiche")
    print("   • PDF-Fusion aller Seiten möglich")
    print("   • Erstellt detaillierte Sitemaps und JSON-Berichte")
    print()
    print("🎬 VIDEO-DOWNLOAD:")
    print("   • Unterstützt YouTube, Vimeo und viele andere Plattformen")
    print("   • Direkte Video-Downloads von Websites")
    print("   • Browser-basierte Screen-Aufnahmen als Fallback")
    print("   • Automatische Video-Erkennung auf Webseiten")
    print("   • Parallele Downloads für Effizienz")
    print("   • Detaillierte Download-Statistiken")
    print()
    print("📁 AUSGABE-STRUKTUR:")
    print("   • Alle Downloads werden in 'collection/' gespeichert")
    print("   • Eindeutige Ordnernamen mit Zeitstempel")
    print("   • Separate Unterordner für verschiedene Dateitypen")
    print("   • JSON-Berichte für detaillierte Metadaten")
    print()
    print("⚙️  SYSTEMANFORDERUNGEN:")
    print("   • Python 3.8+ mit erforderlichen Bibliotheken")
    print("   • Für Video-Downloads: yt-dlp, selenium (optional)")
    print("   • Für GUI-Features: Display-Umgebung erforderlich")
    print("   • ChromeDriver für Browser-Automation (optional)")
    print()

def run_website_crawler(url: str):
    """Führt Website-Crawling durch"""
    try:
        # Import nur wenn benötigt
        from website_crawler import WebsiteCrawler, CrawlScope, main as crawler_main
        
        print(f"\n🌐 Starte Website-Crawling für: {url}")
        print("=" * 50)
        
        # Website-Crawler mit seinen eigenen Parametern starten
        # Der Crawler hat seine eigene interaktive Konfiguration
        crawler_main()
        
    except ImportError as e:
        logger.error(f"Website-Crawler konnte nicht importiert werden: {e}")
        print("❌ Website-Crawler-Modul nicht verfügbar!")
        print("Stellen Sie sicher, dass website_crawler.py vorhanden ist.")
    except Exception as e:
        logger.error(f"Fehler beim Website-Crawling: {e}")
        print(f"❌ Fehler beim Website-Crawling: {e}")

def run_video_downloader(url: str):
    """Führt Video-Download durch"""
    try:
        # Import nur wenn benötigt
        from video_downloader import VideoDownloader, main as downloader_main
        
        print(f"\n🎬 Starte Video-Download für: {url}")
        print("=" * 50)
        
        # Video-Downloader mit seinen eigenen Parametern starten
        # Der Downloader hat seine eigene interaktive Konfiguration
        downloader_main()
        
    except ImportError as e:
        logger.error(f"Video-Downloader konnte nicht importiert werden: {e}")
        print("❌ Video-Downloader-Modul nicht verfügbar!")
        print("Stellen Sie sicher, dass video_downloader.py vorhanden ist.")
    except Exception as e:
        logger.error(f"Fehler beim Video-Download: {e}")
        print(f"❌ Fehler beim Video-Download: {e}")

def check_dependencies():
    """Prüft grundlegende Abhängigkeiten"""
    missing_modules = []
    
    # Grundlegende Module prüfen
    try:
        import requests
        import urllib.parse
    except ImportError as e:
        missing_modules.append(f"requests: {e}")
    
    # Website-Crawler Module prüfen
    try:
        import bs4
        import weasyprint
    except ImportError:
        print("⚠️  Website-Crawler: Einige optionale Module fehlen (bs4, weasyprint)")
    
    # Video-Downloader Module prüfen
    try:
        import yt_dlp
    except ImportError:
        print("⚠️  Video-Downloader: yt-dlp nicht verfügbar (optional)")
    
    if missing_modules:
        print("❌ Kritische Module fehlen:")
        for module in missing_modules:
            print(f"   • {module}")
        print("\nInstallieren Sie fehlende Module mit:")
        print("pip install -r requirements.txt")
        return False
    
    return True

def main():
    """Hauptfunktion - Zentrale Benutzeroberfläche"""
    try:
        # System-Check
        if not check_dependencies():
            print("\n❌ Bitte installieren Sie die fehlenden Abhängigkeiten.")
            return
        
        # Willkommensnachricht
        show_welcome()
        
        while True:
            choice = get_user_choice()
            
            if choice == '1':
                # Website-Crawling
                print("\n🌐 Website-Crawling ausgewählt")
                print("Sie werden nun zum Website-Crawler weitergeleitet...")
                print("Der Crawler hat seine eigene Benutzeroberfläche für detaillierte Konfiguration.")
                input("\nDrücken Sie Enter um fortzufahren...")
                run_website_crawler("")
                
            elif choice == '2':
                # Video-Download
                print("\n🎬 Video-Download ausgewählt")
                print("Sie werden nun zum Video-Downloader weitergeleitet...")
                print("Der Downloader hat seine eigene Benutzeroberfläche für detaillierte Konfiguration.")
                input("\nDrücken Sie Enter um fortzufahren...")
                run_video_downloader("")
                
            elif choice == '3':
                # Hilfe
                show_help()
                input("\nDrücken Sie Enter um zum Hauptmenü zurückzukehren...")
                
            elif choice == '4':
                # Beenden
                print("\n👋 Auf Wiedersehen!")
                break
            
            # Zurück zum Hauptmenü
            print("\n" + "=" * 50)
            print("Zurück zum Hauptmenü")
            print("=" * 50)
    
    except KeyboardInterrupt:
        print("\n\n⏸️  Programm wurde durch Benutzer abgebrochen.")
        print("👋 Auf Wiedersehen!")
    except Exception as e:
        logger.error(f"Unerwarteter Fehler in main(): {e}")
        print(f"\n❌ Unerwarteter Fehler: {e}")
        if '--debug' in sys.argv:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()