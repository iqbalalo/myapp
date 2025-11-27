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
    APIRouter,
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
    filename: Optional[str] = None  # Add optional filename


class Base64ImageRequest(BaseModel):
    file_base64: str
    ocr_language: Optional[str] = "eng+jpn"
    filename: Optional[str] = None  # Add optional filename


class PDFSplitRequest(BaseModel):
    file_base64: str
    pages_per_split: int
    original_filename: Optional[str] = "document"


class PDFAnalysisRequest(BaseModel):
    file_base64: str


class CreateAPIKeyRequest(BaseModel):
    email: EmailStr
    expires: str


class DeleteAPIKeyRequest(BaseModel):
    api_key: str


# --- API Key Management Functions ---


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


# --- ROOT ENDPOINT ---


@app.get("/", tags=["Root"])
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


# --- API KEY MANAGEMENT ENDPOINTS ---


@app.post("/api-keys/create/", tags=["API Key Management"])
async def create_api_key(
    request: CreateAPIKeyRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Creates a new API key (requires master key).
    
    Expires format: "never", "30d", "90d", "1y", or ISO datetime string.
    """
    # Verify master key
    if api_key != _get_default_api_key():
        raise HTTPException(
            status_code=403, detail="Only master key can create new API keys"
        )

    # Parse expiration
    expires = None
    if request.expires.lower() != "never":
        if request.expires.endswith("d"):
            days = int(request.expires[:-1])
            expires = datetime.now() + timedelta(days=days)
        elif request.expires.endswith("y"):
            years = int(request.expires[:-1])
            expires = datetime.now() + timedelta(days=years * 365)
        else:
            try:
                expires = datetime.fromisoformat(request.expires)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid expiration format"
                )

    # Generate new API key
    new_key = secrets.token_urlsafe(32)

    # Save to database
    try:
        conn = _get_db_connection()
        if not conn:
            raise HTTPException(
                status_code=500, detail="Database connection failed"
            )
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO api.api_keys (api_key, email, expires)
            VALUES (%s, %s, %s);
        """,
            (new_key, request.email, expires),
        )
        conn.commit()
        cursor.close()
        conn.close()

        return JSONResponse(
            content={
                "api_key": new_key,
                "email": request.email,
                "expires": expires.isoformat() if expires else "Never",
                "created_at": datetime.now().isoformat(),
            }
        )
    except Exception as e:
        logging.error(f"Failed to create API key: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create API key: {str(e)}"
        )


@app.get("/api-keys/list/", tags=["API Key Management"])
async def list_api_keys(api_key: str = Depends(verify_api_key)):
    """Lists all API keys (requires master key)."""
    if api_key != _get_default_api_key():
        raise HTTPException(
            status_code=403, detail="Only master key can list API keys"
        )

    api_keys = _load_api_keys()
    return JSONResponse(content={"api_keys": api_keys, "count": len(api_keys)})


@app.delete("/api-keys/delete/", tags=["API Key Management"])
async def delete_api_key(
    request: DeleteAPIKeyRequest,
    api_key: str = Depends(verify_api_key),
):
    """Deletes an API key (requires master key)."""
    if api_key != _get_default_api_key():
        raise HTTPException(
            status_code=403, detail="Only master key can delete API keys"
        )

    try:
        conn = _get_db_connection()
        if not conn:
            raise HTTPException(
                status_code=500, detail="Database connection failed"
            )
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM api.api_keys WHERE api_key = %s;", (request.api_key,)
        )
        deleted_count = cursor.rowcount
        conn.commit()
        cursor.close()
        conn.close()

        if deleted_count == 0:
            raise HTTPException(status_code=404, detail="API key not found")

        return JSONResponse(
            content={
                "message": "API key deleted successfully",
                "deleted_key": request.api_key,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Failed to delete API key: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete API key: {str(e)}"
        )


@app.get("/api-keys/usage/", tags=["API Key Management"])
async def get_usage_stats(
    api_key: str = Depends(verify_api_key),
    days: int = 30,
    limit: int = 100,
):
    """
    Gets API usage statistics (requires master key).
    
    Query parameters:
    - days: Number of days to look back (default: 30)
    - limit: Maximum number of records to return (default: 100)
    """
    if api_key != _get_default_api_key():
        raise HTTPException(
            status_code=403, detail="Only master key can view usage stats"
        )

    try:
        conn = _get_db_connection()
        if not conn:
            raise HTTPException(
                status_code=500, detail="Database connection failed"
            )
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get usage records
        cursor.execute(
            """
            SELECT email, api_key, api_endpoint, used, ip
            FROM api.api_key_usage
            WHERE used >= NOW() - INTERVAL '%s days'
            ORDER BY used DESC
            LIMIT %s;
        """,
            (days, limit),
        )
        usage_records = cursor.fetchall()

        # Get summary by email
        cursor.execute(
            """
            SELECT email, COUNT(*) as request_count
            FROM api.api_key_usage
            WHERE used >= NOW() - INTERVAL '%s days'
            GROUP BY email
            ORDER BY request_count DESC;
        """,
            (days,),
        )
        summary = cursor.fetchall()

        cursor.close()
        conn.close()

        return JSONResponse(
            content={
                "period_days": days,
                "total_requests": len(usage_records),
                "summary_by_email": [dict(row) for row in summary],
                "recent_usage": [
                    {
                        "email": row["email"],
                        "api_endpoint": row["api_endpoint"],
                        "used": row["used"].isoformat() if row["used"] else None,
                        "ip": row["ip"],
                    }
                    for row in usage_records
                ],
            }
        )
    except Exception as e:
        logging.error(f"Failed to get usage stats: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get usage stats: {str(e)}"
        )


# --- PDF/IMAGE EXTRACTION ENDPOINTS ---


@app.post("/extract/file/", tags=["Text Extraction"])
async def extract_from_file(
    request: Request,
    file: UploadFile = File(...),
    use_ocr: bool = Form(True),
    ocr_language: str = Form("eng+jpn"),
    api_key: str = Depends(verify_api_key),
):
    """
    Extracts text from uploaded PDF or image file.
    
    Supports: PDF, JPEG, PNG, TIFF, BMP, GIF, WEBP
    """
    try:
        file_data = await file.read()
        filename = file.filename or "unknown"
        content_type = file.content_type

        # Process based on file type
        if content_type == "application/pdf":
            result = await asyncio.get_event_loop().run_in_executor(
                PROCESS_EXECUTOR,
                pdf_processor.extract_text,
                file_data,
                use_ocr,
                ocr_language,
            )
        elif content_type in SUPPORTED_IMAGE_TYPES:
            result = await asyncio.get_event_loop().run_in_executor(
                PROCESS_EXECUTOR,
                image_processor.extract_text,
                file_data,
                ocr_language,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {content_type}. Supported: PDF, JPEG, PNG, TIFF, BMP, GIF, WEBP",
            )

        # Add filename to response
        result["filename"] = filename
        
        # Prepend filename to file_text
        if result.get("file_text"):
            result["file_text"] = f"Filename: {filename}\n{result['file_text']}"

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")


@app.post("/extract/base64/", tags=["Text Extraction"])
async def extract_from_base64(
    request: Base64FileRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Extracts text from base64-encoded PDF file.
    
    Request body:
    {
        "file_base64": "base64_encoded_pdf_data",
        "use_ocr": true,
        "ocr_language": "eng+jpn",
        "filename": "optional_filename.pdf"
    }
    """
    try:
        file_data = base64.b64decode(request.file_base64)
        filename = request.filename or "document.pdf"

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            pdf_processor.extract_text,
            file_data,
            request.use_ocr,
            request.ocr_language,
        )

        # Add filename to response
        result["filename"] = filename
        
        # Prepend filename to file_text
        if result.get("file_text"):
            result["file_text"] = f"Filename: {filename}\n{result['file_text']}"

        return JSONResponse(content=result)

    except Exception as e:
        logging.error(f"Base64 extraction failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Base64 extraction failed: {str(e)}"
        )


@app.post("/extract/image/base64/", tags=["Text Extraction"])
async def extract_from_image_base64(
    request: Base64ImageRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Extracts text from base64-encoded image file using OCR.
    
    Supports: JPEG, PNG, TIFF, BMP, GIF, WEBP
    
    Request body:
    {
        "file_base64": "base64_encoded_image_data",
        "ocr_language": "eng+jpn",
        "filename": "optional_filename.jpg"
    }
    """
    try:
        file_data = base64.b64decode(request.file_base64)
        filename = request.filename or "image"

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            image_processor.extract_text,
            file_data,
            request.ocr_language,
        )

        # Add filename to response
        result["filename"] = filename
        
        # Prepend filename to file_text
        if result.get("file_text"):
            result["file_text"] = f"Filename: {filename}\n{result['file_text']}"

        return JSONResponse(content=result)

    except Exception as e:
        logging.error(f"Image extraction failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Image extraction failed: {str(e)}"
        )


@app.get("/tesseract/languages/", tags=["Text Extraction"])
async def get_tesseract_languages(api_key: str = Depends(verify_api_key)):
    """
    Returns available Tesseract OCR languages.
    
    Common language codes:
    - eng: English
    - jpn: Japanese
    - chi_sim: Chinese Simplified
    - chi_tra: Chinese Traditional
    - kor: Korean
    - ara: Arabic
    - fra: French
    - deu: German
    - spa: Spanish
    - rus: Russian
    - ben: Bengali
    - hin: Hindi
    
    Use "+" to combine languages (e.g., "eng+jpn")
    """
    try:
        import pytesseract

        languages = pytesseract.get_languages(config="")
        return JSONResponse(
            content={
                "available_languages": languages,
                "example_usage": "eng+jpn (for English and Japanese)",
            }
        )
    except Exception as e:
        logging.error(f"Failed to get languages: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get languages: {str(e)}"
        )


# --- PDF SPLITTING ENDPOINTS ---


@app.post("/split/file/", tags=["PDF Operations"])
async def split_pdf_file(
    file: UploadFile = File(...),
    pages_per_split: int = Form(...),
    api_key: str = Depends(verify_api_key),
):
    """
    Splits uploaded PDF into multiple files.
    
    Returns JSON with base64-encoded split files.
    """
    try:
        if file.content_type != "application/pdf":
            raise HTTPException(
                status_code=400, detail="Only PDF files are supported"
            )

        file_data = await file.read()
        original_filename = file.filename or "document"

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            pdf_splitter.split_pdf,
            file_data,
            pages_per_split,
            original_filename,
        )

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"PDF split failed: {e}")
        raise HTTPException(status_code=500, detail=f"PDF split failed: {str(e)}")


@app.post("/split/base64/", tags=["PDF Operations"])
async def split_pdf_base64(
    request: PDFSplitRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Splits base64-encoded PDF into multiple files.
    
    Returns JSON with base64-encoded split files.
    """
    try:
        file_data = base64.b64decode(request.file_base64)

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            pdf_splitter.split_pdf,
            file_data,
            request.pages_per_split,
            request.original_filename,
        )

        return JSONResponse(content=result)

    except Exception as e:
        logging.error(f"PDF split failed: {e}")
        raise HTTPException(status_code=500, detail=f"PDF split failed: {str(e)}")


# --- PDF ANALYSIS ENDPOINTS ---


@app.post("/analyze/file/", tags=["PDF Operations"])
async def analyze_pdf_file(
    file: UploadFile = File(...),
    api_key: str = Depends(verify_api_key),
):
    """
    Analyzes PDF to identify image-based pages (fast, no OCR).
    
    Returns page analysis without extracting text.
    """
    try:
        if file.content_type != "application/pdf":
            raise HTTPException(
                status_code=400, detail="Only PDF files are supported"
            )

        file_data = await file.read()

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            pdf_processor.analyze_pages,
            file_data,
        )

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"PDF analysis failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"PDF analysis failed: {str(e)}"
        )


@app.post("/analyze/base64/", tags=["PDF Operations"])
async def analyze_pdf_base64(
    request: PDFAnalysisRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Analyzes base64-encoded PDF to identify image-based pages.
    
    Returns page analysis without extracting text.
    """
    try:
        file_data = base64.b64decode(request.file_base64)

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            pdf_processor.analyze_pages,
            file_data,
        )

        return JSONResponse(content=result)

    except Exception as e:
        logging.error(f"PDF analysis failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"PDF analysis failed: {str(e)}"
        )


# --- STARTUP EVENT ---


@app.on_event("startup")
async def startup_event():
    """Initialize database tables on application startup."""
    logging.info("Initializing database tables...")
    _init_db_tables()
    logging.info("Application startup complete.")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
