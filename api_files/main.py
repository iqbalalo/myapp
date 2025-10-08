import asyncio
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Union, Dict, Any, List
import concurrent.futures
import base64
import os
import tempfile
import shutil
from datetime import datetime
import logging

# Import core processor logic
from pdf_processor import PDFProcessor
from image_processor import ImageProcessor

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

app = FastAPI(
    title="PDF and Image OCR Text Extractor API",
    description="Accepts PDF files and images (JPEG, PNG, TIFF, BMP, GIF, WEBP) for text extraction using hybrid PDF/OCR methods.",
    version="1.1.0",
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


# Request schemas
class Base64FileRequest(BaseModel):
    file_base64: str
    use_ocr: Optional[bool] = True
    ocr_language: Optional[str] = "eng+jpn"


class Base64ImageRequest(BaseModel):
    file_base64: str
    ocr_language: Optional[str] = "eng+jpn"


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


@app.on_event("shutdown")
def shutdown_event():
    """Runs when the FastAPI application shuts down."""
    PROCESS_EXECUTOR.shutdown(wait=False)
    _cleanup_temp_dir()
    logging.info("FastAPI service shutting down.")


@app.post("/extract/file/")
async def extract_text_from_file(
    file: UploadFile = File(..., description="PDF or image file to process"),
    use_ocr: Optional[bool] = Form(
        True, description="Enable OCR fallback for image pages (PDF only)"
    ),
    ocr_language: Optional[str] = Form(
        "eng+jpn", description="Tesseract language code (e.g., 'eng+jpn', 'eng+ben')"
    ),
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
async def extract_text_from_base64(request: Base64FileRequest) -> JSONResponse:
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
async def extract_text_from_image_base64(request: Base64ImageRequest) -> JSONResponse:
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
