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
from fastapi.responses import JSONResponse
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

# Import core processor logic
from pdf_processor import PDFProcessor
from image_processor import ImageProcessor

# Configuration
PROCESS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=16)
TEMP_DIR_ROOT = "/tmp/api_uploads"
API_KEYS_FILE = "api-keys.json"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(threadName)s - %(levelname)s - %(message)s",
)

# Initialize processors
pdf_processor = PDFProcessor()
image_processor = ImageProcessor()

app = FastAPI(
    title="PDF and Image OCR Text Extractor API",
    description="Accepts PDF files and images (JPEG, PNG, TIFF, BMP, GIF, WEBP) for text extraction using hybrid PDF/OCR methods. Requires API key authentication.",
    version="1.2.0",
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


class CreateAPIKeyRequest(BaseModel):
    email: EmailStr
    expires: str  # "never" or number of days like "30", "90", "365"


class DeleteAPIKeyRequest(BaseModel):
    api_key: str


# --- API Key Management Functions ---


def _get_db_connection():
    """
    Gets a database connection.

    Returns:
        Database connection or None if connection fails
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logging.error(f"Database connection failed: {e}")
        return None


def _init_api_usage_table():
    """
    Initializes the api_key_usage table if it doesn't exist.
    Creates the table in the 'api' schema.
    """
    try:
        conn = _get_db_connection()
        if not conn:
            return False

        cursor = conn.cursor()

        # Create schema if it doesn't exist
        cursor.execute("CREATE SCHEMA IF NOT EXISTS api;")

        # Create table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api.api_key_usage (
                id SERIAL PRIMARY KEY,
                email TEXT,
                api_key TEXT,
                used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip TEXT
            );
        """)

        # Create indexes for faster queries
        # Index on api_key for filtering by specific key
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_key_usage_api_key 
            ON api.api_key_usage(api_key);
        """)

        # Index on email for filtering/verifying by user email
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_key_usage_email 
            ON api.api_key_usage(email);
        """)

        # Index on used timestamp for time-based queries (e.g., last 7 days, ordering)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_key_usage_used 
            ON api.api_key_usage(used);
        """)

        # Composite index for combined email + date range queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_key_usage_email_used 
            ON api.api_key_usage(email, used);
        """)

        conn.commit()
        cursor.close()
        conn.close()

        logging.info("API usage table initialized successfully")
        return True

    except Exception as e:
        logging.error(f"Failed to initialize API usage table: {e}")
        return False


def _log_api_usage(api_key: str, ip: Optional[str] = None):
    """
    Logs API key usage to the database.

    Args:
        api_key: The API key used
        ip: Optional IP address of the requester
    """
    try:
        conn = _get_db_connection()
        if not conn:
            logging.warning("Skipping API usage logging - database not accessible")
            return

        # Get email associated with the API key
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
            INSERT INTO api.api_key_usage (email, api_key, used, ip)
            VALUES (%s, %s, %s, %s);
        """,
            (email, api_key, datetime.now(), ip),
        )

        conn.commit()
        cursor.close()
        conn.close()

        logging.debug(f"API usage logged for {email}")

    except Exception as e:
        logging.error(f"Failed to log API usage: {e}")
        # Don't raise exception - logging failure shouldn't break the API


def _get_client_ip(request: Request) -> Optional[str]:
    """
    Extracts client IP address from request.

    Args:
        request: FastAPI Request object

    Returns:
        IP address string or None
    """
    # Check for forwarded IP first (in case of proxy/nginx)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, get the first one
        return forwarded_for.split(",")[0].strip()

    # Check for real IP
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fall back to direct client IP
    if request.client:
        return request.client.host

    return None


def _get_default_api_key() -> str:
    """Gets the default master API key from environment variable."""
    default_key = os.getenv("DEFAULT_API_KEY", "Pass#0123456789#?")
    return default_key


def _load_api_keys() -> Dict[str, Any]:
    """Loads API keys from JSON file."""
    if not os.path.exists(API_KEYS_FILE):
        return {}

    try:
        with open(API_KEYS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error loading API keys: {e}")
        return {}


def _save_api_keys(api_keys: Dict[str, Any]) -> bool:
    """Saves API keys to JSON file."""
    try:
        with open(API_KEYS_FILE, "w") as f:
            json.dump(api_keys, f, indent=4)
        return True
    except Exception as e:
        logging.error(f"Error saving API keys: {e}")
        return False


def _generate_api_key() -> str:
    """Generates a secure random API key."""
    return f"sk_{secrets.token_urlsafe(32)}"


def _calculate_expiry_date(expires: str) -> Optional[str]:
    """
    Calculates expiry date based on input.

    Args:
        expires: "never" or number of days as string

    Returns:
        ISO format date string or None for never
    """
    if expires.lower() == "never":
        return None

    try:
        days = int(expires)
        expiry_date = datetime.now() + timedelta(days=days)
        return expiry_date.isoformat()
    except ValueError:
        raise ValueError("Expires must be 'never' or a number of days")


def _is_api_key_valid(api_key: str) -> bool:
    """
    Validates an API key.

    Args:
        api_key: The API key to validate

    Returns:
        True if valid, False otherwise
    """
    # Check if it's the default master key
    if api_key == _get_default_api_key():
        return True

    # Check in stored keys
    api_keys = _load_api_keys()

    if api_key not in api_keys:
        return False

    key_info = api_keys[api_key]

    # Check if expired
    if key_info.get("expires"):
        expiry_date = datetime.fromisoformat(key_info["expires"])
        if datetime.now() > expiry_date:
            return False

    return True


async def verify_api_key(
    request: Request, x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    Dependency to verify API key from header and log usage.

    Args:
        request: FastAPI Request object
        x_api_key: API key from X-API-Key header

    Raises:
        HTTPException: If API key is invalid or expired
    """
    if not _is_api_key_valid(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    # Log API usage
    client_ip = _get_client_ip(request)
    _log_api_usage(x_api_key, client_ip)

    return x_api_key


async def verify_master_api_key(
    request: Request, x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    Dependency to verify master API key for admin operations and log usage.

    Args:
        request: FastAPI Request object
        x_api_key: API key from X-API-Key header

    Raises:
        HTTPException: If not the master API key
    """
    if x_api_key != _get_default_api_key():
        raise HTTPException(
            status_code=403, detail="Master API key required for this operation"
        )

    # Log API usage
    client_ip = _get_client_ip(request)
    _log_api_usage(x_api_key, client_ip)

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
            "file_hash": "N/A",
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
            "file_hash": "N/A",
            "file_text": None,
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

    # Initialize database table for API usage logging
    _init_api_usage_table()

    # Log installed Tesseract languages for debugging
    try:
        import pytesseract

        languages = pytesseract.get_languages(config="")
        logging.info(f"Tesseract installed languages: {languages}")
    except Exception as e:
        logging.error(f"Could not retrieve Tesseract languages: {e}")

    # Log default API key info (masked)
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


@app.post("/api/keys/create/")
async def create_api_key(
    request: CreateAPIKeyRequest,
    fastapi_request: Request,
    _: str = Depends(verify_master_api_key),
) -> JSONResponse:
    """
    Creates a new API key (requires master API key).

    Args:
        request: Email and expiration details

    Returns:
        New API key details
    """
    try:
        # Load existing keys
        api_keys = _load_api_keys()

        # Generate new key
        new_key = _generate_api_key()

        # Calculate expiry
        expiry_date = _calculate_expiry_date(request.expires)

        # Create key entry
        api_keys[new_key] = {
            "email": request.email,
            "created_at": datetime.now().isoformat(),
            "expires": expiry_date,
            "expires_display": "Never" if expiry_date is None else expiry_date,
        }

        # Save to file
        if not _save_api_keys(api_keys):
            raise HTTPException(status_code=500, detail="Failed to save API key")

        return JSONResponse(
            content={
                "success": True,
                "api_key": new_key,
                "email": request.email,
                "created_at": api_keys[new_key]["created_at"],
                "expires": api_keys[new_key]["expires_display"],
                "message": "API key created successfully. Store this key securely - it won't be shown again.",
            }
        )

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logging.error(f"Error creating API key: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create API key: {str(e)}"
        )


@app.get("/api/keys/list/")
async def list_api_keys(
    fastapi_request: Request, _: str = Depends(verify_master_api_key)
) -> JSONResponse:
    """
    Lists all API keys (requires master API key).

    Returns:
        List of all API keys with their details (keys are masked)
    """
    try:
        api_keys = _load_api_keys()

        # Mask API keys for security
        masked_keys = []
        for key, info in api_keys.items():
            # Check if expired
            is_expired = False
            if info.get("expires"):
                expiry_date = datetime.fromisoformat(info["expires"])
                is_expired = datetime.now() > expiry_date

            masked_keys.append(
                {
                    "api_key_masked": key[:12] + "..." + key[-8:],
                    "api_key_full": key,  # Include full key for admin purposes
                    "email": info.get("email"),
                    "created_at": info.get("created_at"),
                    "expires": info.get("expires_display", info.get("expires")),
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


@app.delete("/api/keys/delete/")
async def delete_api_key(
    request: DeleteAPIKeyRequest,
    fastapi_request: Request,
    _: str = Depends(verify_master_api_key),
) -> JSONResponse:
    """
    Deletes an API key (requires master API key).

    Args:
        request: API key to delete

    Returns:
        Deletion confirmation
    """
    try:
        # Prevent deletion of master key
        if request.api_key == _get_default_api_key():
            raise HTTPException(
                status_code=400, detail="Cannot delete the master API key"
            )

        # Load existing keys
        api_keys = _load_api_keys()

        # Check if key exists
        if request.api_key not in api_keys:
            raise HTTPException(status_code=404, detail="API key not found")

        # Get key info before deletion
        key_info = api_keys[request.api_key]

        # Delete key
        del api_keys[request.api_key]

        # Save updated keys
        if not _save_api_keys(api_keys):
            raise HTTPException(status_code=500, detail="Failed to save changes")

        return JSONResponse(
            content={
                "success": True,
                "message": "API key deleted successfully",
                "deleted_key": {
                    "email": key_info.get("email"),
                    "created_at": key_info.get("created_at"),
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


@app.get("/api/keys/usage/")
async def get_api_usage_stats(
    fastapi_request: Request,
    api_key: Optional[str] = None,
    email: Optional[str] = None,
    limit: Optional[int] = 100,
    _: str = Depends(verify_master_api_key),
) -> JSONResponse:
    """
    Gets API usage statistics (requires master API key).

    Args:
        api_key: Optional - filter by specific API key
        email: Optional - filter by user email
        limit: Maximum number of records to return (default: 100)

    Returns:
        API usage statistics
    """
    try:
        conn = _get_db_connection()
        if not conn:
            raise HTTPException(status_code=503, detail="Database not accessible")

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Build query based on filters
        if api_key and email:
            # Filter by both api_key and email
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
            # Filter by api_key only
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
            # Filter by email only
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
            # Get all usage
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

        # Get summary statistics (with same filters)
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

        # Convert records to serializable format
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
async def get_tesseract_languages(
    fastapi_request: Request, _: str = Depends(verify_api_key)
):
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
    """
    Accepts a PDF or image file via multipart/form-data and extracts text.
    For PDFs: Uses hybrid PDF/OCR extraction.
    For images: Uses OCR directly.
    """
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
                _process_pdf_concurrently,
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
    fastapi_request: Request,
    _: str = Depends(verify_api_key),
) -> JSONResponse:
    """
    Accepts a PDF file encoded as a Base64 string and extracts text.
    """
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
    fastapi_request: Request,
    _: str = Depends(verify_api_key),
) -> JSONResponse:
    """
    Accepts an image file encoded as a Base64 string and extracts text using OCR.
    """
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


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return JSONResponse(
        content={
            "message": "PDF and Image OCR Text Extractor API",
            "version": "1.2.0",
            "documentation": "/docs",
            "authentication": "All endpoints require X-API-Key header",
            "endpoints": {
                "admin": {
                    "create_key": "/api/keys/create/ (POST) - Requires master key",
                    "list_keys": "/api/keys/list/ (GET) - Requires master key",
                    "delete_key": "/api/keys/delete/ (DELETE) - Requires master key",
                    "usage_stats": "/api/keys/usage/ (GET) - Requires master key",
                },
                "extraction": {
                    "file": "/extract/file/ (POST)",
                    "pdf_base64": "/extract/base64/ (POST)",
                    "image_base64": "/extract/image/base64/ (POST)",
                    "languages": "/tesseract/languages/ (GET)",
                },
            },
        }
    )
