#!/usr/bin/env python3
"""
Script to process URLs from missing-urls-for-scraping.txt
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from website_crawler import WebsiteCrawler, CrawlScope
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def process_missing_urls():
    """Process URLs from missing-urls-for-scraping.txt"""
    
    urls_file = Path("missing-urls-for-scraping.txt")
    if not urls_file.exists():
        logger.error(f"File {urls_file} not found")
        return
    
    # Read URLs
    with open(urls_file, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    logger.info(f"Found {len(urls)} URLs to process")
    
    # Process each URL
    for i, url in enumerate(urls, 1):
        try:
            logger.info(f"Processing URL {i}/{len(urls)}: {url}")
            
            # Generate safe title for directory
            url_title = url.replace('https://', '').replace('http://', '').replace('www.','')
            url_title = url_title.replace('/', '-').replace('.', '_').replace('?', '-').replace('&', '-').replace('=', '-')
            url_title = url_title.strip('-').strip('_')[:50]  # Limit length
            
            # Let WebsiteCrawler handle the path creation (it adds 'collection' automatically)
            output_name = f"missing_urls_processed/{i:03d}_{url_title}"
            
            # Initialize crawler
            crawler = WebsiteCrawler(
                base_url=url,
                url_title=output_name,
                max_urls=50,  # Limit to avoid too much data
                single_pdf=True,  # Create single PDF
                delete_individual_pdfs=True,  # Keep only combined PDF
                crawl_scope=CrawlScope.HIERARCHICAL
            )
            
            # Start crawling
            crawler.crawl()
            
            logger.info(f"Successfully processed {url}")
            logger.info(f"Pages crawled: {len(crawler.pages)}")
            logger.info(f"Output directory: {crawler.output_dir}")
            
        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            continue
    
    logger.info("Processing complete!")

if __name__ == "__main__":
    process_missing_urls()