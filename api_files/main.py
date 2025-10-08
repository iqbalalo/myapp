import asyncio  # ADDED: Import asyncio for loop access
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
# NOTE: pytesseract.pytesseract.tesseract_cmd is set inside pdf_processor.py
from pdf_processor import PDFProcessor

# Configuration
# FastAPI is optimized to handle I/O bound tasks in its own internal thread pool,
# which is perfect for file I/O and network operations.
# We will use a separate executor for the PDF processing pipeline.
PROCESS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=16
)  # Configured for high concurrency
TEMP_DIR_ROOT = "/tmp/api_uploads"  # Use a dedicated temp directory

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(threadName)s - %(levelname)s - %(message)s",
)

# Initialize the PDF Processor
processor = PDFProcessor()
app = FastAPI(
    title="PDF OCR Text Extractor API",
    description="Accepts PDF files (as multipart or base64) for hybrid PDF/OCR text extraction. Optimized for concurrent requests.",
    version="1.0.0",
)


# Request schema for Base64 input
class Base64FileRequest(BaseModel):
    # Base64 string of the PDF file
    file_base64: str
    # Optional field to control OCR use
    use_ocr: Optional[bool] = True
    # ADDED: Optional field to specify Tesseract languages
    ocr_language: Optional[str] = "eng+jpn"


# --- Helper Functions ---


def _process_file_concurrently(
    file_data: bytes, use_ocr: bool, ocr_language: str
) -> Dict[str, Any]:
    """
    Submits the CPU-bound PDF extraction task to the dedicated ThreadPoolExecutor.
    """
    try:
        # Pass ocr_language to the processor
        future = PROCESS_EXECUTOR.submit(
            processor.extract_text, file_data, use_ocr, ocr_language
        )

        # Wait for the result and raise any exception that occurred during processing
        result = future.result()
        return result
    except Exception as e:
        logging.error(f"Concurrent processing failed: {e}")
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
        # We don't delete the root, just the contents if needed.
        # But for this implementation, data is passed in memory (bytes), so
        # explicit cleanup is mainly a safeguard for file-based processing.
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
    PROCESS_EXECUTOR.shutdown(wait=False)  # Wait for running tasks to finish gracefully
    _cleanup_temp_dir()
    logging.info("FastAPI service shutting down.")


@app.post("/extract/file/")
async def extract_text_from_file(
    file: UploadFile = File(..., description="PDF file to process"),
    use_ocr: Optional[bool] = Form(
        True, description="Enable OCR fallback for image pages"
    ),
    # ADDED: New parameter with default value excluding Bengali
    ocr_language: Optional[str] = Form(
        "eng+jpn", description="Tesseract language code (e.g., 'eng+jpn', 'eng+ben')"
    ),
) -> JSONResponse:
    """
    Accepts a PDF file via multipart/form-data and extracts text.
    """
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Only application/pdf is supported.",
        )

    try:
        # Read file data directly into memory (bytes)
        file_data = await file.read()

        # FIX: Replace app.loop with explicit asyncio.get_event_loop()
        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            _process_file_concurrently,
            file_data,
            use_ocr,
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
    temp_file_path = None
    try:
        # 1. Convert Base64 to binary data
        file_data = base64.b64decode(request.file_base64)

        # Basic check to ensure it's PDF data
        if not file_data.startswith(b"%PDF"):
            raise HTTPException(
                status_code=400,
                detail="Base64 string does not decode to valid PDF data.",
            )

        # 2. Process data in the thread pool (I/O and CPU bound)
        # FIX: Replace app.loop with explicit asyncio.get_event_loop()
        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            _process_file_concurrently,
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
