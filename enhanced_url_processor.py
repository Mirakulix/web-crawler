#!/usr/bin/env python3
"""
Enhanced URL processor with database integration and progress tracking
"""

import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import json
import uuid
from datetime import datetime
from dataclasses import dataclass
import hashlib

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from website_crawler import WebsiteCrawler, CrawlScope
from services.database_service import DatabaseService

# Setup logging with progress indicators
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/enhanced_processor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class CrawlJob:
    """Data class for crawl job tracking"""
    job_id: str
    url: str
    status: str  # pending, running, completed, error
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    pages_crawled: int = 0
    images_downloaded: int = 0
    error_message: Optional[str] = None
    output_directory: Optional[str] = None

class EnhancedURLProcessor:
    """Enhanced URL processor with database integration and progress tracking"""
    
    def __init__(self):
        self.db = DatabaseService()
        self.jobs: Dict[str, CrawlJob] = {}
        self.progress_file = Path("progress_state.json")
        
        # Ensure logs directory exists
        Path("logs").mkdir(exist_ok=True)
        
        # Load previous progress if exists
        self.load_progress_state()
    
    def load_progress_state(self):
        """Load previous progress from file"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r') as f:
                    data = json.load(f)
                    for job_data in data.get('jobs', []):
                        job = CrawlJob(**job_data)
                        if job.start_time:
                            job.start_time = datetime.fromisoformat(job.start_time)
                        if job.end_time:
                            job.end_time = datetime.fromisoformat(job.end_time)
                        self.jobs[job.job_id] = job
                logger.info(f"Loaded {len(self.jobs)} previous jobs from progress file")
            except Exception as e:
                logger.warning(f"Could not load progress state: {e}")
    
    def save_progress_state(self):
        """Save current progress to file"""
        try:
            jobs_data = []
            for job in self.jobs.values():
                job_dict = {
                    'job_id': job.job_id,
                    'url': job.url,
                    'status': job.status,
                    'start_time': job.start_time.isoformat() if job.start_time else None,
                    'end_time': job.end_time.isoformat() if job.end_time else None,
                    'pages_crawled': job.pages_crawled,
                    'images_downloaded': job.images_downloaded,
                    'error_message': job.error_message,
                    'output_directory': job.output_directory
                }
                jobs_data.append(job_dict)
            
            with open(self.progress_file, 'w') as f:
                json.dump({'jobs': jobs_data}, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save progress state: {e}")
    
    def create_database_job_record(self, job: CrawlJob, request_data: Dict[str, Any]) -> Optional[str]:
        """Create job record in database"""
        if not self.db.database_available:
            logger.warning("Database not available, skipping database record creation")
            return None
        
        try:
            db_job_id = self.db.create_job(
                job_type='crawl',
                request_data=request_data
            )
            logger.info(f"Created database job record: {db_job_id}")
            return db_job_id
        except Exception as e:
            logger.error(f"Failed to create database job record: {e}")
            return None
    
    def update_database_job(self, db_job_id: str, job: CrawlJob):
        """Update job record in database"""
        if not self.db.database_available or not db_job_id:
            return
        
        try:
            status_map = {
                'pending': 'pending',
                'running': 'running', 
                'completed': 'completed',
                'error': 'error'
            }
            
            self.db.update_job_status(
                job_id=db_job_id,
                status=status_map.get(job.status, 'pending'),
                error_message=job.error_message,
                statistics={
                    'pages_crawled': job.pages_crawled,
                    'images_downloaded': job.images_downloaded,
                    'output_directory': job.output_directory
                }
            )
        except Exception as e:
            logger.error(f"Failed to update database job {db_job_id}: {e}")
    
    def store_crawled_pages(self, db_job_id: str, crawler: WebsiteCrawler):
        """Store crawled page data in database"""
        if not self.db.database_available or not db_job_id:
            return
        
        try:
            for page in crawler.pages:
                # Calculate content hash for deduplication
                content_hash = hashlib.sha256(page.content.encode()).hexdigest()
                
                self.db.store_crawled_page(
                    job_id=db_job_id,
                    url=page.url,
                    title=page.title,
                    content_text=page.content[:50000],  # Limit content size
                    html_content=None,  # Could store HTML if needed
                    pdf_path=page.pdf_path,
                    word_count=len(page.content.split()),
                    page_size_kb=len(page.content.encode()) / 1024
                )
            
            logger.info(f"Stored {len(crawler.pages)} pages in database")
        except Exception as e:
            logger.error(f"Failed to store pages in database: {e}")
    
    def generate_job_id(self, url: str) -> str:
        """Generate consistent job ID based on URL"""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, url))
    
    def display_progress(self):
        """Display current progress"""
        total_jobs = len(self.jobs)
        completed_jobs = sum(1 for job in self.jobs.values() if job.status == 'completed')
        running_jobs = sum(1 for job in self.jobs.values() if job.status == 'running')
        error_jobs = sum(1 for job in self.jobs.values() if job.status == 'error')
        
        print("\n" + "="*80)
        print(f"📊 PROGRESS OVERVIEW")
        print("="*80)
        print(f"Total Jobs: {total_jobs}")
        print(f"✅ Completed: {completed_jobs}")
        print(f"🔄 Running: {running_jobs}")  
        print(f"❌ Errors: {error_jobs}")
        print(f"⏳ Pending: {total_jobs - completed_jobs - running_jobs - error_jobs}")
        
        if total_jobs > 0:
            progress_percent = (completed_jobs / total_jobs) * 100
            print(f"📈 Overall Progress: {progress_percent:.1f}%")
        
        # Show recent activity
        if self.jobs:
            print(f"\n📋 RECENT JOBS:")
            for job in list(self.jobs.values())[-5:]:
                status_icon = {"completed": "✅", "running": "🔄", "error": "❌", "pending": "⏳"}.get(job.status, "❓")
                print(f"  {status_icon} {job.url[:60]}... [{job.status}]")
        
        print("="*80 + "\n")
    
    def process_urls_from_file(self, urls_file: Path, max_urls_per_site: int = 50) -> None:
        """Process URLs from file with progress tracking"""
        
        if not urls_file.exists():
            logger.error(f"File {urls_file} not found")
            return
        
        # Read URLs
        with open(urls_file, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        
        logger.info(f"Found {len(urls)} URLs to process")
        
        # Create or update job entries
        for i, url in enumerate(urls, 1):
            job_id = self.generate_job_id(url)
            
            if job_id not in self.jobs:
                self.jobs[job_id] = CrawlJob(
                    job_id=job_id,
                    url=url,
                    status='pending'
                )
            elif self.jobs[job_id].status == 'completed':
                logger.info(f"Skipping already completed job: {url}")
                continue
        
        # Display initial progress
        self.display_progress()
        
        # Process each URL
        for i, url in enumerate(urls, 1):
            job_id = self.generate_job_id(url)
            job = self.jobs[job_id]
            
            # Skip if already completed
            if job.status == 'completed':
                continue
            
            try:
                logger.info(f"🔄 Processing URL {i}/{len(urls)}: {url}")
                
                # Update job status
                job.status = 'running'
                job.start_time = datetime.now()
                self.save_progress_state()
                
                # Generate safe title for directory
                url_title = url.replace('https://', '').replace('http://', '').replace('www.','')
                url_title = url_title.replace('/', '-').replace('.', '_').replace('?', '-').replace('&', '-').replace('=', '-')
                url_title = url_title.strip('-').strip('_')[:50]
                
                # Create output path
                output_name = f"missing_urls_processed/{i:03d}_{url_title}"
                
                # Create database job record
                request_data = {
                    'base_url': url,
                    'max_urls': max_urls_per_site,
                    'single_pdf': True,
                    'crawl_scope': 'hierarchical'
                }
                db_job_id = self.create_database_job_record(job, request_data)
                
                # Initialize crawler
                crawler = WebsiteCrawler(
                    base_url=url,
                    url_title=output_name,
                    max_urls=max_urls_per_site,
                    single_pdf=True,
                    delete_individual_pdfs=True,
                    crawl_scope=CrawlScope.HIERARCHICAL
                )
                
                # Start crawling
                crawler.crawl()
                
                # Update job with results
                job.status = 'completed'
                job.end_time = datetime.now()
                job.pages_crawled = len(crawler.pages)
                job.images_downloaded = crawler.stats.get('images_downloaded', 0)
                job.output_directory = str(crawler.output_dir)
                
                # Update database
                self.update_database_job(db_job_id, job)
                self.store_crawled_pages(db_job_id, crawler)
                
                logger.info(f"✅ Successfully processed {url}")
                logger.info(f"📄 Pages crawled: {job.pages_crawled}")
                logger.info(f"🖼️ Images downloaded: {job.images_downloaded}")
                logger.info(f"📁 Output: {job.output_directory}")
                
                # Display progress after each completion
                self.display_progress()
                
            except Exception as e:
                job.status = 'error'
                job.error_message = str(e)
                job.end_time = datetime.now()
                
                logger.error(f"❌ Error processing {url}: {e}")
                
                # Update database with error
                if 'db_job_id' in locals():
                    self.update_database_job(db_job_id, job)
            
            # Save progress after each job
            self.save_progress_state()
            
            # Small delay between jobs
            time.sleep(2)
        
        # Final progress display
        self.display_progress()
        logger.info("🎉 Processing complete!")
    
    def resume_processing(self):
        """Resume processing from where we left off"""
        logger.info("🔄 Resuming processing from saved state...")
        
        # Check for incomplete jobs
        incomplete_jobs = [job for job in self.jobs.values() if job.status in ['pending', 'running']]
        
        if not incomplete_jobs:
            logger.info("✅ No incomplete jobs found")
            return
        
        logger.info(f"Found {len(incomplete_jobs)} incomplete jobs to resume")
        
        # Reset running jobs to pending (in case of crash)
        for job in incomplete_jobs:
            if job.status == 'running':
                job.status = 'pending'
                job.start_time = None
                job.error_message = None
        
        # Extract URLs and continue processing
        urls = [job.url for job in incomplete_jobs]
        with open('temp_resume_urls.txt', 'w') as f:
            f.write('\n'.join(urls))
        
        self.process_urls_from_file(Path('temp_resume_urls.txt'))
        
        # Clean up temp file
        Path('temp_resume_urls.txt').unlink(missing_ok=True)
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive processing report"""
        total_pages = sum(job.pages_crawled for job in self.jobs.values())
        total_images = sum(job.images_downloaded for job in self.jobs.values())
        completed_jobs = [job for job in self.jobs.values() if job.status == 'completed']
        
        if completed_jobs:
            avg_pages_per_job = total_pages / len(completed_jobs)
            avg_images_per_job = total_images / len(completed_jobs)
            
            # Calculate processing times
            processing_times = []
            for job in completed_jobs:
                if job.start_time and job.end_time:
                    duration = (job.end_time - job.start_time).total_seconds()
                    processing_times.append(duration)
            
            avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0
        else:
            avg_pages_per_job = 0
            avg_images_per_job = 0
            avg_processing_time = 0
        
        report = {
            'summary': {
                'total_jobs': len(self.jobs),
                'completed_jobs': len(completed_jobs),
                'failed_jobs': len([job for job in self.jobs.values() if job.status == 'error']),
                'total_pages_crawled': total_pages,
                'total_images_downloaded': total_images
            },
            'averages': {
                'pages_per_job': round(avg_pages_per_job, 2),
                'images_per_job': round(avg_images_per_job, 2),
                'processing_time_seconds': round(avg_processing_time, 2)
            },
            'jobs': [
                {
                    'url': job.url,
                    'status': job.status,
                    'pages_crawled': job.pages_crawled,
                    'images_downloaded': job.images_downloaded,
                    'duration_seconds': (job.end_time - job.start_time).total_seconds() if job.start_time and job.end_time else None,
                    'error_message': job.error_message
                }
                for job in self.jobs.values()
            ]
        }
        
        return report

def main():
    """Main function"""
    processor = EnhancedURLProcessor()
    
    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == '--resume':
        processor.resume_processing()
    else:
        urls_file = Path("missing-urls-for-scraping.txt")
        processor.process_urls_from_file(urls_file)
    
    # Generate and save final report
    report = processor.generate_report()
    
    # Save report
    with open('crawling_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    logger.info("📊 Final report saved to crawling_report.json")
    
    # Display summary
    print("\n" + "="*80)
    print("🎯 FINAL SUMMARY")
    print("="*80)
    print(f"Total Jobs: {report['summary']['total_jobs']}")
    print(f"✅ Completed: {report['summary']['completed_jobs']}")
    print(f"❌ Failed: {report['summary']['failed_jobs']}")
    print(f"📄 Total Pages: {report['summary']['total_pages_crawled']}")
    print(f"🖼️ Total Images: {report['summary']['total_images_downloaded']}")
    print(f"⏱️ Avg Processing Time: {report['averages']['processing_time_seconds']:.1f}s per job")
    print("="*80)

if __name__ == "__main__":
    main()