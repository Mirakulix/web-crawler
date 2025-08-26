import os
from PyPDF2 import PdfReader, PdfWriter
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_pdf_size_mb(file_path):
    """Get PDF file size in MB."""
    return os.path.getsize(file_path) / (1024 * 1024)

def split_pdf_chunk(reader, output_dir, start_page, end_page, base_name, part_counter):
    """Split a chunk of PDF and return number of parts created."""
    max_size_mb = 9.0
    parts_created = 0
    
    # Create a new writer for this chunk
    writer = PdfWriter()
    
    try:
        # Add pages to writer
        for page_num in range(start_page, end_page):
            writer.add_page(reader.pages[page_num])
            logger.debug(f"Adding page {page_num + 1} to chunk")
        
        # Create temporary file to check size
        temp_output = os.path.join(output_dir, f"temp_{base_name}.pdf")
        with open(temp_output, 'wb') as output_file:
            writer.write(output_file)
        
        chunk_size = get_pdf_size_mb(temp_output)
        os.remove(temp_output)
        
        if chunk_size > max_size_mb and (end_page - start_page) > 1:
            # Split chunk further if too large
            mid_point = start_page + ((end_page - start_page) // 2)
            logger.info(f"Chunk too large ({chunk_size:.2f} MB), splitting at page {mid_point}")
            
            parts_created += split_pdf_chunk(reader, output_dir, start_page, mid_point, 
                                           base_name, part_counter + parts_created)
            parts_created += split_pdf_chunk(reader, output_dir, mid_point, end_page, 
                                           base_name, part_counter + parts_created)
        else:
            # Save chunk if size is acceptable or can't split further
            output_filename = f"{base_name}_part{(part_counter + 1):03d}.pdf"
            output_path = os.path.join(output_dir, output_filename)
            
            # Create a new writer for the final chunk
            final_writer = PdfWriter()
            for page_num in range(start_page, end_page):
                final_writer.add_page(reader.pages[page_num])
            
            with open(output_path, 'wb') as output_file:
                final_writer.write(output_file)
            
            actual_size = get_pdf_size_mb(output_path)
            logger.info(f"Created: {output_filename} ({actual_size:.2f} MB, pages {start_page + 1}-{end_page})")
            parts_created = 1
            
        return parts_created
        
    except Exception as e:
        logger.error(f"Error in split_pdf_chunk: {str(e)}")
        raise

def split_pdf(input_path, output_dir):
    """Split PDF into multiple files under 9MB."""
    try:
        with open(input_path, 'rb') as file:
            reader = PdfReader(file)
            total_pages = len(reader.pages)
            max_size_mb = 9.0
            
            # Initial estimate of pages per chunk
            file_size_mb = get_pdf_size_mb(input_path)
            pages_per_chunk = max(1, int((max_size_mb * total_pages) / file_size_mb))
            
            base_name = Path(input_path).stem
            start_page = 0
            part_counter = 0
            
            while start_page < total_pages:
                end_page = min(start_page + pages_per_chunk, total_pages)
                logger.info(f"Processing pages {start_page + 1} to {end_page}")
                
                parts_created = split_pdf_chunk(reader, output_dir, start_page, end_page, 
                                              base_name, part_counter)
                part_counter += parts_created
                start_page = end_page
                
    except Exception as e:
        logger.error(f"Error in split_pdf: {str(e)}")
        raise

def main():
    try:
        input_dir = input("Please enter the input directory path (or press Enter for default 'KNOWLEDGEBASE'): ").strip()
        output_dir = "chunkedPDFs"
        min_size_mb = 9.0
        
        if input_dir:
            if not os.path.exists(input_dir):
                os.makedirs(input_dir)
                logger.info(f"Created input directory: {input_dir}")
        else:
            input_dir = "KNOWLEDGEBASE"
            logger.info("Using default PDF Directory 'KNOWLEDGEBASE'")
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            logger.info(f"Created output directory: {output_dir}")
        
        # Process each PDF file
        pdf_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.pdf')]
        logger.info(f"Found {len(pdf_files)} PDF files to process")
        
        for filename in pdf_files:
            file_path = os.path.join(input_dir, filename)
            file_size = get_pdf_size_mb(file_path)
            
            if file_size > min_size_mb:
                logger.info(f"\nProcessing {filename} ({file_size:.2f} MB)")
                try:
                    split_pdf(file_path, output_dir)
                except Exception as e:
                    logger.error(f"Error processing {filename}: {str(e)}")
                    continue
            else:
                logger.info(f"\nSkipping {filename} ({file_size:.2f} MB)")
        
        logger.info("Processing completed")
        
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
    
    finally:
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()