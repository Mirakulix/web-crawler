-- Web Crawler Database Schema

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Jobs Table
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_type VARCHAR(50) NOT NULL CHECK (job_type IN ('crawl', 'video_download')),
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'error')),
    request_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    result_path TEXT,
    statistics JSONB
);

-- Crawled Pages Table
CREATE TABLE crawled_pages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    title TEXT,
    content_text TEXT,
    html_content TEXT,
    pdf_path TEXT,
    extracted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    word_count INTEGER,
    page_size_kb DECIMAL(10,2),
    response_time_ms INTEGER
);

-- Downloaded Videos Table
CREATE TABLE downloaded_videos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    video_title TEXT,
    file_path TEXT NOT NULL,
    file_size_mb DECIMAL(10,2),
    duration_seconds INTEGER,
    format VARCHAR(10),
    resolution VARCHAR(20),
    download_method VARCHAR(50),
    downloaded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    google_drive_file_id TEXT,
    metadata JSONB
);

-- Downloaded Images Table
CREATE TABLE downloaded_images (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    page_id UUID REFERENCES crawled_pages(id) ON DELETE SET NULL,
    source_url TEXT NOT NULL,
    image_alt_text TEXT,
    file_path TEXT NOT NULL,
    file_size_kb DECIMAL(10,2),
    width_px INTEGER,
    height_px INTEGER,
    format VARCHAR(10),
    downloaded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    google_drive_file_id TEXT,
    image_hash VARCHAR(64),
    is_duplicate BOOLEAN DEFAULT FALSE,
    metadata JSONB
);

-- Email Logs Table
CREATE TABLE email_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    recipient_email VARCHAR(255) NOT NULL,
    subject TEXT NOT NULL,
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    error_message TEXT,
    attachment_count INTEGER DEFAULT 0
);

-- Google Drive Files Table
CREATE TABLE google_drive_files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    local_file_path TEXT NOT NULL,
    google_drive_file_id TEXT UNIQUE NOT NULL,
    google_drive_file_name TEXT NOT NULL,
    file_type VARCHAR(20) NOT NULL CHECK (file_type IN ('pdf', 'video', 'zip')),
    file_size_mb DECIMAL(10,2),
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    drive_folder_id TEXT,
    share_url TEXT
);

-- Search Index für Full-Text Search
CREATE INDEX idx_crawled_pages_content_gin ON crawled_pages USING gin(to_tsvector('german', coalesce(title, '') || ' ' || coalesce(content_text, '')));
CREATE INDEX idx_crawled_pages_url_gin ON crawled_pages USING gin(url gin_trgm_ops);
CREATE INDEX idx_downloaded_videos_title_gin ON downloaded_videos USING gin(to_tsvector('german', coalesce(video_title, '')));

-- Performance Indices
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created_at ON jobs(created_at);
CREATE INDEX idx_jobs_job_type ON jobs(job_type);
CREATE INDEX idx_crawled_pages_job_id ON crawled_pages(job_id);
CREATE INDEX idx_downloaded_videos_job_id ON downloaded_videos(job_id);
CREATE INDEX idx_email_logs_job_id ON email_logs(job_id);
CREATE INDEX idx_google_drive_files_job_id ON google_drive_files(job_id);

-- Views für häufige Abfragen
CREATE VIEW job_statistics AS
SELECT 
    j.id,
    j.job_type,
    j.status,
    j.created_at,
    j.completed_at,
    (j.completed_at - j.started_at) AS duration,
    CASE 
        WHEN j.job_type = 'crawl' THEN (
            SELECT COUNT(*) FROM crawled_pages cp WHERE cp.job_id = j.id
        )
        ELSE 0
    END AS pages_crawled,
    CASE 
        WHEN j.job_type = 'video_download' THEN (
            SELECT COUNT(*) FROM downloaded_videos dv WHERE dv.job_id = j.id
        )
        ELSE 0
    END AS videos_downloaded,
    (
        SELECT COUNT(*) FROM google_drive_files gdf WHERE gdf.job_id = j.id
    ) AS files_uploaded_to_drive,
    (
        SELECT COUNT(*) FROM email_logs el WHERE el.job_id = j.id AND el.status = 'sent'
    ) AS emails_sent
FROM jobs j;

-- Full-Text Search Function
CREATE OR REPLACE FUNCTION search_content(search_query TEXT)
RETURNS TABLE(
    page_id UUID,
    job_id UUID,
    url TEXT,
    title TEXT,
    content_snippet TEXT,
    rank REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        cp.id,
        cp.job_id,
        cp.url,
        cp.title,
        ts_headline('german', cp.content_text, plainto_tsquery('german', search_query)) AS content_snippet,
        ts_rank(to_tsvector('german', coalesce(cp.title, '') || ' ' || coalesce(cp.content_text, '')), 
                plainto_tsquery('german', search_query)) AS rank
    FROM crawled_pages cp
    WHERE to_tsvector('german', coalesce(cp.title, '') || ' ' || coalesce(cp.content_text, '')) @@ plainto_tsquery('german', search_query)
    ORDER BY rank DESC;
END;
$$ LANGUAGE plpgsql;

-- Cleanup old jobs function
CREATE OR REPLACE FUNCTION cleanup_old_jobs(days_old INTEGER DEFAULT 30)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    WITH deleted_jobs AS (
        DELETE FROM jobs 
        WHERE created_at < NOW() - INTERVAL '1 day' * days_old
        AND status IN ('completed', 'error')
        RETURNING id
    )
    SELECT COUNT(*) INTO deleted_count FROM deleted_jobs;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Insert sample configuration
INSERT INTO jobs (job_type, status, request_data) VALUES 
('crawl', 'completed', '{"base_url": "https://example.com", "max_urls": 10}')