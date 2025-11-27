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
    title="PDF and Image OCR Text Extractor API",
    description="Accepts PDF files and images (JPEG, PNG, TIFF, BMP, GIF, WEBP) for text extraction using hybrid PDF/OCR methods. Identifies image-based (non-editable) pages. Also supports PDF splitting. Requires API key authentication.",
    version="1.4.0",
)
app.include_router(media_conversion_router)

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
    """Gets the default master API key from environment variable."""
    default_key = os.getenv("DEFAULT_API_KEY", "Pass#0123456789#?")
    return default_key


def _generate_api_key() -> str:
    """Generates a secure random API key."""
    return f"aa_{secrets.token_urlsafe(32)}"


def _calculate_expiry_date(expires: str) -> Optional[datetime]:
    """Calculates expiry date based on input."""
    if expires.lower() == "never":
        return None
    try:
        days = int(expires)
        expiry_date = datetime.now() + timedelta(days=days)
        return expiry_date
    except ValueError:
        raise ValueError("Expires must be 'never' or a number of days")


def _is_api_key_valid(api_key: str) -> bool:
    """Validates an API key."""
    if api_key == _get_default_api_key():
        return True
    conn = _get_db_connection()
    if not conn:
        logging.error("Failed to validate API key: Database connection failed.")
        return False
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(
        "SELECT email, expires FROM api.api_keys WHERE api_key = %s;", (api_key,)
    )
    key_info = cursor.fetchone()
    cursor.close()
    conn.close()
    if not key_info:
        return False
    if key_info.get("expires"):
        if datetime.now() > key_info["expires"]:
            return False
    return True


async def verify_api_key(
    request: Request, x_api_key: str = Header(..., alias="X-API-Key")
):
    """Dependency to verify API key from header and log usage."""
    endpoint_path = request.url.path
    if not _is_api_key_valid(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid or expired API key")
    client_ip = _get_client_ip(request)
    _log_api_usage(x_api_key, endpoint_path, client_ip)
    return x_api_key


async def verify_master_api_key(
    request: Request, x_api_key: str = Header(..., alias="X-API-Key")
):
    """Dependency to verify master API key for admin operations and log usage."""
    endpoint_path = request.url.path
    if x_api_key != _get_default_api_key():
        raise HTTPException(
            status_code=403, detail="Master API key required for this operation"
        )
    client_ip = _get_client_ip(request)
    _log_api_usage(x_api_key, endpoint_path, client_ip)
    return x_api_key


# --- Helper Functions ---


def _process_pdf_concurrently(
    file_data: bytes, use_ocr: bool, ocr_language: str
) -> Dict[str, Any]:
    """Submits the PDF extraction task to the dedicated ThreadPoolExecutor."""
    try:
        future = PROCESS_EXECUTOR.submit(
            pdf_processor.extract_text, file_data, use_ocr, ocr_language
        )
        result = future.result()
        return result
    except Exception as e:
        logging.error(f"Concurrent PDF processing failed: {e}")
        return {
            "file_hash": None,
            "file_text": None,
            "error": f"Internal Processing Error: {str(e)}",
        }


def _process_image_concurrently(file_data: bytes, ocr_language: str) -> Dict[str, Any]:
    """Submits the image extraction task to the dedicated ThreadPoolExecutor."""
    try:
        future = PROCESS_EXECUTOR.submit(
            image_processor.extract_text, file_data, ocr_language
        )
        result = future.result()
        return result
    except Exception as e:
        logging.error(f"Concurrent image processing failed: {e}")
        return {
            "file_hash": None,
            "file_text": None,
            "error": f"Internal Processing Error: {str(e)}",
        }


def _split_pdf_concurrently(
    file_data: bytes, pages_per_split: int, original_filename: str
) -> Dict[str, Any]:
    """Submits the PDF split task to the dedicated ThreadPoolExecutor."""
    try:
        future = PROCESS_EXECUTOR.submit(
            pdf_splitter.split_pdf, file_data, pages_per_split, original_filename
        )
        result = future.result()
        return result
    except Exception as e:
        logging.error(f"Concurrent PDF splitting failed: {e}")
        return {
            "success": False,
            "error": f"Internal Processing Error: {str(e)}",
            "total_pages": 0,
            "total_splits": 0,
            "files": [],
        }


def _analyze_pdf_structure_concurrently(file_data: bytes) -> Dict[str, Any]:
    """Submits the PDF structure analysis task to the dedicated ThreadPoolExecutor."""
    try:
        future = PROCESS_EXECUTOR.submit(pdf_processor.analyze_pdf_structure, file_data)
        result = future.result()
        return result
    except Exception as e:
        logging.error(f"Concurrent PDF analysis failed: {e}")
        return {
            "file_hash": None,
            "total_pages": 0,
            "text_based_pages": [],
            "image_based_pages": [],
            "error": f"Internal Processing Error: {str(e)}",
        }


def _setup_temp_dir():
    """Ensure the temporary directory exists."""
    os.makedirs(TEMP_DIR_ROOT, exist_ok=True)


def _cleanup_temp_dir():
    """Clean up the temporary directory."""
    if os.path.exists(TEMP_DIR_ROOT):
        pass


# --- API Endpoints ---


@app.on_event("startup")
async def startup_event():
    """Runs when the FastAPI application starts."""
    _setup_temp_dir()
    logging.info("FastAPI service started and temporary directory initialized.")
    _init_db_tables()
    try:
        import pytesseract

        languages = pytesseract.get_languages(config="")
        logging.info(f"Tesseract installed languages: {languages}")
    except Exception as e:
        logging.error(f"Could not retrieve Tesseract languages: {e}")
    default_key = _get_default_api_key()
    masked_key = (
        default_key[:8] + "..." + default_key[-4:] if len(default_key) > 12 else "***"
    )
    logging.info(f"Master API key loaded: {masked_key}")


@app.on_event("shutdown")
def shutdown_event():
    """Runs when the FastAPI application shuts down."""
    PROCESS_EXECUTOR.shutdown(wait=False)
    _cleanup_temp_dir()
    logging.info("FastAPI service shutting down.")


# --- API Key Management Endpoints ---
# (Keep all existing API key management endpoints - create, list, delete, usage)


@app.post("/api-keys/create/")
async def create_api_key(
    request: CreateAPIKeyRequest,
    _: str = Depends(verify_master_api_key),
) -> JSONResponse:
    """Creates a new API key (requires master API key)."""
    try:
        new_key = _generate_api_key()
        expiry_date_dt = _calculate_expiry_date(request.expires)
        conn = _get_db_connection()
        if not conn:
            raise HTTPException(status_code=503, detail="Database not accessible")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO api.api_keys (api_key, email, expires)
            VALUES (%s, %s, %s)
            RETURNING created_at;
        """,
            (new_key, request.email, expiry_date_dt),
        )
        created_at = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return JSONResponse(
            content={
                "success": True,
                "api_key": new_key,
                "email": request.email,
                "created_at": created_at.isoformat(),
                "expires": expiry_date_dt.isoformat() if expiry_date_dt else "Never",
                "message": "API key created successfully. Store this key securely - it won't be shown again.",
            }
        )
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(
            status_code=409, detail="API key already exists, please try again."
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logging.error(f"Error creating API key: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create API key: {str(e)}"
        )


@app.get("/api-keys/list/")
async def list_api_keys(_: str = Depends(verify_master_api_key)) -> JSONResponse:
    """Lists all API keys (requires master API key)."""
    try:
        conn = _get_db_connection()
        if not conn:
            raise HTTPException(status_code=503, detail="Database not accessible")
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT api_key, email, created_at, expires FROM api.api_keys;")
        db_keys = cursor.fetchall()
        cursor.close()
        conn.close()
        masked_keys = []
        for key_info in db_keys:
            is_expired = False
            if key_info.get("expires"):
                is_expired = datetime.now() > key_info["expires"]
            masked_keys.append(
                {
                    "api_key_masked": key_info["api_key"][:12]
                    + "..."
                    + key_info["api_key"][-8:],
                    "api_key_full": key_info["api_key"],
                    "email": key_info["email"],
                    "created_at": key_info["created_at"].isoformat()
                    if key_info["created_at"]
                    else None,
                    "expires": key_info["expires"].isoformat()
                    if key_info["expires"]
                    else "Never",
                    "status": "Expired" if is_expired else "Active",
                }
            )
        return JSONResponse(
            content={
                "success": True,
                "total_keys": len(masked_keys),
                "api_keys": masked_keys,
            }
        )
    except Exception as e:
        logging.error(f"Error listing API keys: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to list API keys: {str(e)}"
        )


@app.delete("/api-keys/delete/")
async def delete_api_key(
    request: DeleteAPIKeyRequest,
    _: str = Depends(verify_master_api_key),
) -> JSONResponse:
    """Deletes an API key (requires master API key)."""
    try:
        if request.api_key == _get_default_api_key():
            raise HTTPException(
                status_code=400, detail="Cannot delete the master API key"
            )
        conn = _get_db_connection()
        if not conn:
            raise HTTPException(status_code=503, detail="Database not accessible")
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT email, created_at FROM api.api_keys WHERE api_key = %s;",
            (request.api_key,),
        )
        key_info = cursor.fetchone()
        if not key_info:
            raise HTTPException(status_code=404, detail="API key not found")
        cursor.execute(
            "DELETE FROM api.api_keys WHERE api_key = %s;", (request.api_key,)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return JSONResponse(
            content={
                "success": True,
                "message": "API key deleted successfully",
                "deleted_key": {
                    "email": key_info["email"],
                    "created_at": key_info["created_at"].isoformat()
                    if key_info["created_at"]
                    else None,
                },
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error deleting API key: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete API key: {str(e)}"
        )


@app.get("/api-keys/usage/")
async def get_api_usage_stats(
    fastapi_request: Request,
    api_key: Optional[str] = None,
    email: Optional[str] = None,
    limit: Optional[int] = 100,
    _: str = Depends(verify_master_api_key),
) -> JSONResponse:
    """Gets API usage statistics (requires master API key)."""
    try:
        conn = _get_db_connection()
        if not conn:
            raise HTTPException(status_code=503, detail="Database not accessible")
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if api_key and email:
            cursor.execute(
                """
                SELECT id, email, api_key, used, ip
                FROM api.api_key_usage
                WHERE api_key = %s AND email = %s
                ORDER BY used DESC
                LIMIT %s;
            """,
                (api_key, email, limit),
            )
        elif api_key:
            cursor.execute(
                """
                SELECT id, email, api_key, used, ip
                FROM api.api_key_usage
                WHERE api_key = %s
                ORDER BY used DESC
                LIMIT %s;
            """,
                (api_key, limit),
            )
        elif email:
            cursor.execute(
                """
                SELECT id, email, api_key, used, ip
                FROM api.api_key_usage
                WHERE email = %s
                ORDER BY used DESC
                LIMIT %s;
            """,
                (email, limit),
            )
        else:
            cursor.execute(
                """
                SELECT id, email, api_key, used, ip
                FROM api.api_key_usage
                ORDER BY used DESC
                LIMIT %s;
            """,
                (limit,),
            )
        records = cursor.fetchall()
        if api_key and email:
            cursor.execute(
                """
                SELECT 
                    COUNT(*) as total_requests,
                    COUNT(DISTINCT api_key) as unique_keys,
                    COUNT(DISTINCT email) as unique_users,
                    MIN(used) as first_request,
                    MAX(used) as last_request
                FROM api.api_key_usage
                WHERE api_key = %s AND email = %s;
            """,
                (api_key, email),
            )
        elif api_key:
            cursor.execute(
                """
                SELECT 
                    COUNT(*) as total_requests,
                    COUNT(DISTINCT api_key) as unique_keys,
                    COUNT(DISTINCT email) as unique_users,
                    MIN(used) as first_request,
                    MAX(used) as last_request
                FROM api.api_key_usage
                WHERE api_key = %s;
            """,
                (api_key,),
            )
        elif email:
            cursor.execute(
                """
                SELECT 
                    COUNT(*) as total_requests,
                    COUNT(DISTINCT api_key) as unique_keys,
                    COUNT(DISTINCT email) as unique_users,
                    MIN(used) as first_request,
                    MAX(used) as last_request
                FROM api.api_key_usage
                WHERE email = %s;
            """,
                (email,),
            )
        else:
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_requests,
                    COUNT(DISTINCT api_key) as unique_keys,
                    COUNT(DISTINCT email) as unique_users,
                    MIN(used) as first_request,
                    MAX(used) as last_request
                FROM api.api_key_usage;
            """)
        summary = cursor.fetchone()
        cursor.close()
        conn.close()
        usage_records = []
        for record in records:
            usage_records.append(
                {
                    "id": record["id"],
                    "email": record["email"],
                    "api_key_masked": record["api_key"][:12]
                    + "..."
                    + record["api_key"][-8:]
                    if record["api_key"]
                    else None,
                    "used": record["used"].isoformat() if record["used"] else None,
                    "ip": record["ip"],
                }
            )
        return JSONResponse(
            content={
                "success": True,
                "filters": {"api_key": api_key, "email": email, "limit": limit},
                "summary": {
                    "total_requests": summary["total_requests"],
                    "unique_keys": summary["unique_keys"],
                    "unique_users": summary["unique_users"],
                    "first_request": summary["first_request"].isoformat()
                    if summary["first_request"]
                    else None,
                    "last_request": summary["last_request"].isoformat()
                    if summary["last_request"]
                    else None,
                },
                "records": usage_records,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting API usage stats: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get usage stats: {str(e)}"
        )


# --- OCR Extraction Endpoints (Protected) ---


@app.get("/tesseract/languages/")
async def get_tesseract_languages(_: str = Depends(verify_api_key)):
    """Returns list of installed Tesseract languages."""
    try:
        import pytesseract

        languages = pytesseract.get_languages(config="")
        return JSONResponse(
            content={
                "installed_languages": languages,
                "note": "Use '+' to combine languages, e.g., 'eng+ben' for English and Bengali",
            }
        )
    except Exception as e:
        logging.error(f"Error getting Tesseract languages: {e}")
        return JSONResponse(
            status_code=500, content={"error": f"Failed to get languages: {str(e)}"}
        )


@app.post("/extract/file/")
async def extract_text_from_file(
    fastapi_request: Request,
    file: UploadFile = File(..., description="PDF or image file to process"),
    use_ocr: Optional[bool] = Form(
        True, description="Enable OCR fallback for image pages (PDF only)"
    ),
    ocr_language: Optional[str] = Form(
        "eng+jpn", description="Tesseract language code (e.g., 'eng+jpn', 'eng+ben')"
    ),
    _: str = Depends(verify_api_key),
) -> JSONResponse:
    """Accepts a PDF or image file via multipart/form-data and extracts text."""
    content_type = file.content_type.lower()

    # Validate file type
    if content_type == "application/pdf":
        is_pdf = True
    elif content_type in SUPPORTED_IMAGE_TYPES:
        is_pdf = False
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {content_type}. Supported types: PDF and images (JPEG, PNG, TIFF, BMP, GIF, WEBP).",
        )

    try:
        # Read file data
        file_data = await file.read()

        # Process based on file type
        if is_pdf:
            result = await asyncio.get_event_loop().run_in_executor(
                PROCESS_EXECUTOR,
                pdf_processor.extract_text,
                file_data,
                use_ocr,
                ocr_language,
            )
        else:
            result = await asyncio.get_event_loop().run_in_executor(
                PROCESS_EXECUTOR,
                _process_image_concurrently,
                file_data,
                ocr_language,
            )

        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error during file upload/processing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")


@app.post("/extract/base64/")
async def extract_text_from_base64(
    request: Base64FileRequest,
    _: str = Depends(verify_api_key),
) -> JSONResponse:
    """Accepts a PDF file encoded as a Base64 string and extracts text."""
    try:
        # Convert Base64 to binary data
        file_data = base64.b64decode(request.file_base64)

        # Check if it's PDF data
        if not file_data.startswith(b"%PDF"):
            raise HTTPException(
                status_code=400,
                detail="Base64 string does not decode to valid PDF data.",
            )

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            _process_pdf_concurrently,
            file_data,
            request.use_ocr,
            request.ocr_language,
        )

        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except base64.binascii.Error:
        raise HTTPException(status_code=400, detail="Invalid Base64 string format.")
    except Exception as e:
        logging.error(f"Error during base64 processing: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to process Base64 data: {str(e)}"
        )


@app.post("/extract/image/base64/")
async def extract_text_from_image_base64(
    request: Base64ImageRequest,
    _: str = Depends(verify_api_key),
) -> JSONResponse:
    """Accepts an image file encoded as a Base64 string and extracts text using OCR."""
    try:
        # Convert Base64 to binary data
        file_data = base64.b64decode(request.file_base64)

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            _process_image_concurrently,
            file_data,
            request.ocr_language,
        )

        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])

        return JSONResponse(content=result)

    except HTTPException:
        raise
    except base64.binascii.Error:
        raise HTTPException(status_code=400, detail="Invalid Base64 string format.")
    except Exception as e:
        logging.error(f"Error during image base64 processing: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to process Base64 image: {str(e)}"
        )


# --- NEW PDF Split Endpoints ---


@app.post("/split/file/")
async def split_pdf_from_file(
    fastapi_request: Request,
    file: UploadFile = File(..., description="PDF file to split"),
    pages_per_split: int = Form(
        ..., description="Number of pages per split file", ge=1
    ),
    _: str = Depends(verify_api_key),
) -> JSONResponse:
    """
    Splits a PDF file into multiple smaller PDF files.
    Returns JSON with base64-encoded PDF files.

    Args:
        file: PDF file to split
        pages_per_split: Number of pages per split file (must be >= 1)

    Returns:
        JSON with base64-encoded split PDF files and metadata
    """
    content_type = file.content_type.lower()

    # Validate file type
    if content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {content_type}. Only PDF files are supported.",
        )

    try:
        # Read file data
        file_data = await file.read()
        original_filename = file.filename or "document.pdf"

        # Split the PDF
        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            _split_pdf_concurrently,
            file_data,
            pages_per_split,
            original_filename,
        )

        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])

        if not result.get("success"):
            raise HTTPException(status_code=500, detail="PDF split failed")

        # Convert file data to base64 for JSON response
        files_with_base64 = []
        for file_info in result["files"]:
            files_with_base64.append(
                {
                    "filename": file_info["filename"],
                    "file_base64": base64.b64encode(file_info["file_data"]).decode(
                        "utf-8"
                    ),
                    "pages": file_info["pages"],
                    "page_count": file_info["page_count"],
                    "size_bytes": file_info["size_bytes"],
                }
            )

        return JSONResponse(
            content={
                "success": True,
                "total_pages": result["total_pages"],
                "total_splits": result["total_splits"],
                "files": files_with_base64,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error during PDF split from file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to split PDF: {str(e)}")


@app.post("/split/base64/")
async def split_pdf_from_base64(
    request: PDFSplitRequest,
    _: str = Depends(verify_api_key),
) -> JSONResponse:
    """
    Splits a PDF file (provided as base64) into multiple smaller PDF files.
    Returns the split files as base64-encoded strings in JSON.

    Args:
        request: Contains base64-encoded PDF, pages_per_split, and optional filename

    Returns:
        JSON with split file information and base64-encoded file data
    """
    try:
        # Validate pages_per_split
        if request.pages_per_split < 1:
            raise HTTPException(
                status_code=400, detail="pages_per_split must be at least 1"
            )

        # Convert Base64 to binary data
        try:
            file_data = base64.b64decode(request.file_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid Base64 string format.")

        # Check if it's PDF data
        if not file_data.startswith(b"%PDF"):
            raise HTTPException(
                status_code=400,
                detail="Base64 string does not decode to valid PDF data.",
            )

        # Split the PDF
        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            _split_pdf_concurrently,
            file_data,
            request.pages_per_split,
            request.original_filename,
        )

        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])

        if not result.get("success"):
            raise HTTPException(status_code=500, detail="PDF split failed")

        # Convert file data to base64 for JSON response
        files_with_base64 = []
        for file_info in result["files"]:
            files_with_base64.append(
                {
                    "filename": file_info["filename"],
                    "file_base64": base64.b64encode(file_info["file_data"]).decode(
                        "utf-8"
                    ),
                    "pages": file_info["pages"],
                    "page_count": file_info["page_count"],
                    "size_bytes": file_info["size_bytes"],
                }
            )

        return JSONResponse(
            content={
                "success": True,
                "total_pages": result["total_pages"],
                "total_splits": result["total_splits"],
                "files": files_with_base64,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error during PDF split from base64: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to split PDF: {str(e)}")


# --- PDF Structure Analysis Endpoints ---


@app.post("/analyze/file/")
async def analyze_pdf_structure_from_file(
    fastapi_request: Request,
    file: UploadFile = File(..., description="PDF file to analyze"),
    _: str = Depends(verify_api_key),
) -> JSONResponse:
    """
    Analyzes PDF structure to identify image-based pages without performing OCR.
    This is a fast, lightweight operation.

    Args:
        file: PDF file to analyze

    Returns:
        JSON with page classification (text-based vs image-based)
    """
    content_type = file.content_type.lower()

    # Validate file type
    if content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {content_type}. Only PDF files are supported.",
        )

    try:
        # Read file data
        file_data = await file.read()

        # Analyze the PDF structure
        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            _analyze_pdf_structure_concurrently,
            file_data,
        )

        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])

        return JSONResponse(
            content={
                "success": True,
                "file_hash": result["file_hash"],
                "total_pages": result["total_pages"],
                "text_based_pages": {
                    "count": len(result["text_based_pages"]),
                    "page_numbers": result["text_based_pages"],
                },
                "image_based_pages": {
                    "count": len(result["image_based_pages"]),
                    "page_numbers": result["image_based_pages"],
                    "note": "These pages have insufficient selectable text and would require OCR for text extraction",
                },
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error during PDF structure analysis: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze PDF: {str(e)}")


@app.post("/analyze/base64/")
async def analyze_pdf_structure_from_base64(
    request: Base64FileRequest,
    _: str = Depends(verify_api_key),
) -> JSONResponse:
    """
    Analyzes PDF structure (from base64) to identify image-based pages without performing OCR.
    This is a fast, lightweight operation.

    Args:
        request: Contains base64-encoded PDF

    Returns:
        JSON with page classification (text-based vs image-based)
    """
    try:
        # Convert Base64 to binary data
        try:
            file_data = base64.b64decode(request.file_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid Base64 string format.")

        # Check if it's PDF data
        if not file_data.startswith(b"%PDF"):
            raise HTTPException(
                status_code=400,
                detail="Base64 string does not decode to valid PDF data.",
            )

        # Analyze the PDF structure
        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            _analyze_pdf_structure_concurrently,
            file_data,
        )

        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])

        return JSONResponse(
            content={
                "success": True,
                "file_hash": result["file_hash"],
                "total_pages": result["total_pages"],
                "text_based_pages": {
                    "count": len(result["text_based_pages"]),
                    "page_numbers": result["text_based_pages"],
                },
                "image_based_pages": {
                    "count": len(result["image_based_pages"]),
                    "page_numbers": result["image_based_pages"],
                    "note": "These pages have insufficient selectable text and would require OCR for text extraction",
                },
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error during PDF structure analysis from base64: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze PDF: {str(e)}")


class FileHashResponse(BaseModel):
    file_hash: str


@app.post("/file-hash/", response_model=FileHashResponse)
async def get_file_hash(
    file: UploadFile = File(..., description="File to get hash for"),
    _: str = Depends(verify_api_key),
):
    """
    Accepts a file via multipart/form-data and returns its SHA256 hash.
    """
    try:
        file_data = await file.read()
        file_hash = create_file_hash(file_data)
        return {"file_hash": file_hash}  # Return dict instead of JSONResponse
    except Exception as e:
        logging.error(f"Error getting file hash: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to process file for hashing: {str(e)}"
        )


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return JSONResponse(
        content={
            "message": "PDF and Image OCR Text Extractor API",
            "version": "1.4.0",
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
            },
        }
    )
