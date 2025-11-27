import asyncio
from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Form,
    HTTPException,
    Header,
    Depends,
    Request,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr
from typing import Optional, Union, Dict, Any, List
import concurrent.futures
import base64
import os
import json
import secrets
import logging
from datetime import datetime, timedelta
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi.middleware.cors import CORSMiddleware

# Import core processor logic
from pdf_processor import PDFProcessor, create_file_hash
from image_processor import ImageProcessor
from pdf_splitter import PDFSplitter

from media_conversion_router import router as media_conversion_router

# Import database CRUD router
from db_router import router as db_router


# Configuration
PROCESS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=16)
TEMP_DIR_ROOT = "/tmp/api_uploads"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(threadName)s - %(levelname)s - %(message)s",
)

# Initialize processors
pdf_processor = PDFProcessor()
image_processor = ImageProcessor()
pdf_splitter = PDFSplitter()

app = FastAPI(
    title="PDF and Image OCR Text Extractor API with Database CRUD",
    description="Accepts PDF files and images (JPEG, PNG, TIFF, BMP, GIF, WEBP) for text extraction using hybrid PDF/OCR methods. Identifies image-based (non-editable) pages. Also supports PDF splitting and comprehensive PostgreSQL database CRUD operations. Requires API key authentication.",
    version="2.0.0",
)

# Include routers
app.include_router(media_conversion_router)
app.include_router(db_router)  # Add database CRUD router

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://www.aloraloy.com",
        "https://aloraloy.com",
        "https://myapi.suslab-data.com",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supported image MIME types
SUPPORTED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/tiff",
    "image/bmp",
    "image/gif",
    "image/webp",
}

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "db"),
    "port": os.getenv("DB_PORT", "5432"),
    "database": os.getenv("POSTGRES_DB", "postgres"),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", "Pass#0123456789"),
}


# Request schemas
class Base64FileRequest(BaseModel):
    file_base64: str
    use_ocr: Optional[bool] = True
    ocr_language: Optional[str] = "eng+jpn"


class Base64ImageRequest(BaseModel):
    file_base64: str
    ocr_language: Optional[str] = "eng+jpn"


class PDFSplitRequest(BaseModel):
    file_base64: str
    pages_per_split: int
    original_filename: Optional[str] = "document"


class CreateAPIKeyRequest(BaseModel):
    email: EmailStr
    expires: str


class DeleteAPIKeyRequest(BaseModel):
    api_key: str


# --- API Key Management Functions ---
# (Keep all existing API key management functions from the original file)


def _get_db_connection():
    """Gets a database connection."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logging.error(f"Database connection failed: {e}")
        return None


def _init_db_tables():
    """Initializes the api_key_usage and api_keys tables if they don't exist."""
    try:
        conn = _get_db_connection()
        if not conn:
            return False

        cursor = conn.cursor()
        cursor.execute("CREATE SCHEMA IF NOT EXISTS api;")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api.api_key_usage (
                id SERIAL PRIMARY KEY,
                email TEXT,
                api_key TEXT,
                api_endpoint TEXT,
                used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip TEXT
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api.api_keys (
                id SERIAL PRIMARY KEY,
                api_key TEXT UNIQUE NOT NULL,
                email TEXT,
                expires TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_key_usage_api_key
            ON api.api_key_usage(api_key);
            CREATE INDEX IF NOT EXISTS idx_api_key_usage_email
            ON api.api_key_usage(email);
            CREATE INDEX IF NOT EXISTS idx_api_key_usage_used
            ON api.api_key_usage(used);
            CREATE INDEX IF NOT EXISTS idx_api_key_usage_email_used
            ON api.api_key_usage(email, used);
            CREATE INDEX IF NOT EXISTS idx_api_keys_api_key
            ON api.api_keys(api_key);
        """)
        conn.commit()
        cursor.close()
        conn.close()
        logging.info("Database tables initialized successfully.")
        return True
    except Exception as e:
        logging.error(f"Failed to initialize database tables: {e}")
        return False


def _load_api_keys() -> Dict[str, Any]:
    """Loads API keys from the database."""
    conn = _get_db_connection()
    if not conn:
        return {}
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT api_key, email, expires, created_at FROM api.api_keys;")
    api_keys = {}
    for row in cursor.fetchall():
        api_keys[row["api_key"]] = {
            "email": row["email"],
            "expires": row["expires"].isoformat() if row["expires"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "expires_display": "Never"
            if row["expires"] is None
            else row["expires"].isoformat(),
        }
    cursor.close()
    conn.close()
    return api_keys


def _log_api_usage(
    api_key: str, api_endpoint: Optional[str] = None, ip: Optional[str] = None
):
    """Logs API key usage to the database."""
    try:
        conn = _get_db_connection()
        if not conn:
            logging.warning("Skipping API usage logging - database not accessible")
            return
        email = None
        if api_key == _get_default_api_key():
            email = "master@system"
        else:
            api_keys = _load_api_keys()
            if api_key in api_keys:
                email = api_keys[api_key].get("email")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO api.api_key_usage (email, api_key, api_endpoint, used, ip)
            VALUES (%s, %s, %s, %s, %s);
        """,
            (email, api_key, api_endpoint, datetime.now(), ip),
        )
        conn.commit()
        cursor.close()
        conn.close()
        logging.debug(f"API usage logged for {email}")
    except Exception as e:
        logging.error(f"Failed to log API usage: {e}")


def _get_client_ip(request: Request) -> Optional[str]:
    """Extracts client IP address from request."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    if request.client:
        return request.client.host
    return None


def _get_default_api_key() -> str:
    """Returns the default/master API key."""
    return os.getenv("DEFAULT_API_KEY", "default-master-key-change-me")


def verify_api_key(request: Request, x_api_key: str = Header(..., alias="X-API-Key")):
    """Verifies the API key from request headers."""
    default_key = _get_default_api_key()
    api_keys = _load_api_keys()
    
    client_ip = _get_client_ip(request)
    
    # Check default key
    if x_api_key == default_key:
        _log_api_usage(x_api_key, request.url.path, client_ip)
        return x_api_key
    
    # Check stored keys
    if x_api_key in api_keys:
        key_info = api_keys[x_api_key]
        if key_info["expires"]:
            expires = datetime.fromisoformat(key_info["expires"])
            if datetime.now() > expires:
                raise HTTPException(status_code=401, detail="API key has expired")
        
        _log_api_usage(x_api_key, request.url.path, client_ip)
        return x_api_key
    
    raise HTTPException(status_code=401, detail="Invalid API key")


# Keep all existing endpoints from main.py
# ... (all the PDF, OCR, image processing endpoints remain the same)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return JSONResponse(
        content={
            "message": "PDF and Image OCR Text Extractor API with Database CRUD",
            "version": "2.0.0",
            "documentation": "/docs",
            "authentication": "All endpoints require X-API-Key header",
            "endpoints": {
                "admin": {
                    "create_key": "/api-keys/create/ (POST) - Requires master key",
                    "list_keys": "/api-keys/list/ (GET) - Requires master key",
                    "delete_key": "/api-keys/delete/ (DELETE) - Requires master key",
                    "usage_stats": "/api-keys/usage/ (GET) - Requires master key",
                },
                "extraction": {
                    "file": "/extract/file/ (POST)",
                    "pdf_base64": "/extract/base64/ (POST)",
                    "image_base64": "/extract/image/base64/ (POST)",
                    "languages": "/tesseract/languages/ (GET)",
                },
                "pdf_split": {
                    "file": "/split/file/ (POST) - Returns JSON with base64 files",
                    "base64": "/split/base64/ (POST) - Returns JSON with base64 files",
                },
                "pdf_analysis": {
                    "file": "/analyze/file/ (POST) - Identify image-based pages (fast, no OCR)",
                    "base64": "/analyze/base64/ (POST) - Identify image-based pages (fast, no OCR)",
                },
                "database_crud": {
                    "read": "/db/read (POST) - Read records with filtering and pagination",
                    "create": "/db/create (POST) - Create single or multiple records",
                    "update": "/db/update (POST) - Update records based on filters",
                    "delete": "/db/delete (POST) - Delete records based on filters",
                    "join_read": "/db/join-read (POST) - Multi-table JOIN queries",
                    "raw_query": "/db/raw-query (POST) - Execute raw SQL queries",
                    "verify_password": "/db/verify-password (POST) - Verify user password",
                    "bulk_operation": "/db/bulk-operation (POST) - Bulk create/update/delete",
                    "list_tables": "/db/schema/{schema_name}/tables (GET) - List all tables in schema",
                    "get_columns": "/db/schema/{schema_name}/table/{table_name}/columns (GET) - Get table columns",
                    "health": "/db/health (GET) - Check database connection",
                },
            },
        }
    )


# Initialize database tables on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database tables on application startup."""
    logging.info("Initializing database tables...")
    _init_db_tables()
    logging.info("Application startup complete.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
