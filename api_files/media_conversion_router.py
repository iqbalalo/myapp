"""
Media Conversion API Router
Handles video, audio, and image conversions with S3 storage support

All converted files are uploaded to: s3://bucket/converted/
No subfolders - all files (mp3, webp, mp4) in same location

Usage in main.py:
    from media_conversion_router import router as media_conversion_router
    app.include_router(media_conversion_router)
"""

import asyncio
from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException,
    Depends,
    Request,
    Header,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import base64
import os
import logging
from datetime import datetime, timedelta
import concurrent.futures
import boto3
from botocore.exceptions import ClientError

# Import converter modules
from media_converter_api import MediaConverterAPI
from image_to_webp_api import ImageToWebPAPI

# Setup logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/convert", tags=["Media Conversion"])

# Configuration
PROCESS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=8)

# S3 Configuration
S3_BUCKET = os.getenv("S3_BUCKET", "www.aloraloy.com")
S3_REGION = os.getenv("S3_REGION", "ap-northeast-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# Initialize converters
media_converter = MediaConverterAPI()
image_to_webp = ImageToWebPAPI()

# Initialize S3 client
try:
    s3_client = boto3.client(
        "s3",
        region_name=S3_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )
    logger.info("S3 client initialized successfully for media conversions")
except Exception as e:
    logger.error(f"Failed to initialize S3 client: {e}")
    s3_client = None


# --- Authentication ---
async def verify_api_key_for_conversions(
    request: Request, x_api_key: str = Header(..., alias="X-API-Key")
):
    """
    Placeholder authentication function.

    REPLACE THIS with your actual verify_api_key function from main.py

    Option 1: Create auth.py with your verify_api_key and import it
    Option 2: Copy your verify_api_key logic here
    Option 3: Keep this placeholder for testing (accepts any key)
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

    # TODO: Add your actual authentication logic here
    # Example:
    # if not _is_api_key_valid(x_api_key):
    #     raise HTTPException(status_code=401, detail="Invalid or expired API key")

    return x_api_key


# --- Request Models ---
class MediaConversionRequest(BaseModel):
    file_base64: str
    filename: str
    bitrate: Optional[str] = "192k"
    use_s3: Optional[bool] = False
    return_base64: Optional[bool] = True


class VideoCompressionRequest(BaseModel):
    file_base64: str
    filename: str
    resolution: Optional[str] = "720p"
    bitrate: Optional[str] = "1000k"
    use_s3: Optional[bool] = False
    return_base64: Optional[bool] = True


class ImageToWebPRequest(BaseModel):
    file_base64: str
    filename: str
    quality: Optional[int] = 80
    max_width: Optional[int] = None
    max_height: Optional[int] = None
    use_s3: Optional[bool] = False
    return_base64: Optional[bool] = True


# --- S3 Helper Functions ---
def upload_to_s3(
    file_data: bytes,
    filename: str,
    content_type: str,
    folder: str = "convert-it/converted",
) -> Optional[str]:
    """
    Upload file to S3 and return the public URL.
    All files go to converted/ folder (no subfolders for mp3/webp/mp4).

    Args:
        file_data: Binary file data
        filename: Name of the file
        content_type: MIME type of the file
        folder: S3 folder path (default: converted)

    Returns:
        Public URL: https://www.aloraloy.com/convert-it/converted/20251022_143052_video.mp3
    """
    if not s3_client:
        logger.error("S3 client not initialized")
        return None

    try:
        # Generate unique filename to avoid collisions
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{timestamp}_{filename}"
        s3_key = f"{folder}/{unique_filename}"

        # Upload to S3 with public ACL
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=file_data,
            ContentType=content_type,
            # ACL="public-read",
        )

        # Generate direct URL
        download_url = f"https://{S3_BUCKET}/{s3_key}"

        logger.info(f"Successfully uploaded {filename} to S3: {download_url}")
        return download_url

    except ClientError as e:
        logger.error(f"Failed to upload {filename} to S3: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error uploading to S3: {e}")
        return None


def get_content_type(filename: str) -> str:
    """Get content type based on file extension."""
    ext = filename.lower().split(".")[-1]

    content_types = {
        "mp3": "audio/mpeg",
        "mp4": "video/mp4",
        "webp": "image/webp",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "wav": "audio/wav",
        "avi": "video/x-msvideo",
        "mov": "video/quicktime",
    }

    return content_types.get(ext, "application/octet-stream")


# --- Audio Conversion Endpoints ---


@router.post("/mp3/file/")
async def convert_to_mp3_from_file(
    fastapi_request: Request,
    file: UploadFile = File(..., description="Audio/video file to convert to MP3"),
    bitrate: str = Form("192k", description="Audio bitrate (128k, 192k, 256k, 320k)"),
    use_s3: bool = Form(False, description="Upload to S3 and return download URL"),
    return_base64: bool = Form(True, description="Include base64 in response"),
    _: str = Depends(verify_api_key_for_conversions),
) -> JSONResponse:
    """
    Convert audio/video file to MP3 format with optional S3 upload.
    Supports: MP4, AVI, MOV, MKV, FLV, WMV, MP3, WAV, AAC, FLAC, OGG
    Files uploaded to: s3://bucket/converted/
    """
    try:
        valid_bitrates = ["128k", "192k", "256k", "320k"]
        if bitrate not in valid_bitrates:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid bitrate. Must be one of: {', '.join(valid_bitrates)}",
            )

        file_data = await file.read()
        filename = file.filename or "audio.mp3"

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            media_converter.convert_to_mp3,
            file_data,
            filename,
            bitrate,
        )

        mp3_data, output_filename = result

        response_data = {
            "success": True,
            "original_filename": filename,
            "output_filename": output_filename,
            "bitrate": bitrate,
            "output_size_mb": round(len(mp3_data) / (1024 * 1024), 2),
        }

        if use_s3:
            download_url = upload_to_s3(
                file_data=mp3_data,
                filename=output_filename,
                content_type="audio/mpeg",
                folder="convert-it/converted",
            )

            if download_url:
                response_data["download_url"] = download_url
                response_data["expires_at"] = (
                    datetime.now() + timedelta(days=30)
                ).isoformat()
            else:
                response_data["s3_upload_error"] = "Failed to upload to S3"

        if return_base64:
            response_data["file_base64"] = base64.b64encode(mp3_data).decode("utf-8")

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during MP3 conversion: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to convert to MP3: {str(e)}"
        )


@router.post("/mp3/base64/")
async def convert_to_mp3_from_base64(
    fastapi_request: Request,
    request: MediaConversionRequest,
    _: str = Depends(verify_api_key_for_conversions),
) -> JSONResponse:
    """
    Convert audio/video file to MP3 format (from base64) with optional S3 upload.
    Files uploaded to: s3://bucket/converted/
    """
    try:
        valid_bitrates = ["128k", "192k", "256k", "320k"]
        if request.bitrate not in valid_bitrates:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid bitrate. Must be one of: {', '.join(valid_bitrates)}",
            )

        try:
            file_data = base64.b64decode(request.file_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid Base64 string format.")

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            media_converter.convert_to_mp3,
            file_data,
            request.filename,
            request.bitrate,
        )

        mp3_data, output_filename = result

        response_data = {
            "success": True,
            "original_filename": request.filename,
            "output_filename": output_filename,
            "bitrate": request.bitrate,
            "output_size_mb": round(len(mp3_data) / (1024 * 1024), 2),
        }

        if request.use_s3:
            download_url = upload_to_s3(
                file_data=mp3_data,
                filename=output_filename,
                content_type="audio/mpeg",
                folder="convert-it/converted",
            )

            if download_url:
                response_data["download_url"] = download_url
                response_data["expires_at"] = (
                    datetime.now() + timedelta(days=30)
                ).isoformat()
            else:
                response_data["s3_upload_error"] = "Failed to upload to S3"

        if request.return_base64:
            response_data["file_base64"] = base64.b64encode(mp3_data).decode("utf-8")

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during MP3 conversion from base64: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to convert to MP3: {str(e)}"
        )


# --- Video Compression Endpoints ---


@router.post("/compress-video/file/")
async def compress_video_from_file(
    fastapi_request: Request,
    file: UploadFile = File(..., description="MP4 video file to compress"),
    resolution: str = Form(
        "720p", description="Target resolution (1080p, 720p, 480p, 360p)"
    ),
    bitrate: str = Form("1000k", description="Video bitrate (e.g., 1000k, 2000k)"),
    use_s3: bool = Form(False, description="Upload to S3 and return download URL"),
    return_base64: bool = Form(True, description="Include base64 in response"),
    _: str = Depends(verify_api_key_for_conversions),
) -> JSONResponse:
    """
    Compress MP4 video by reducing resolution and bitrate with optional S3 upload.
    Files uploaded to: s3://bucket/converted/
    """
    try:
        file_data = await file.read()
        filename = file.filename or "video.mp4"

        if not filename.lower().endswith(".mp4"):
            raise HTTPException(
                status_code=400,
                detail="Only MP4 files are supported for video compression.",
            )

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            media_converter.compress_video,
            file_data,
            filename,
            resolution,
            bitrate,
        )

        compressed_data, output_filename = result

        input_size = len(file_data)
        output_size = len(compressed_data)
        reduction = ((input_size - output_size) / input_size) * 100

        response_data = {
            "success": True,
            "original_filename": filename,
            "output_filename": output_filename,
            "resolution": resolution,
            "bitrate": bitrate,
            "input_size_mb": round(input_size / (1024 * 1024), 2),
            "output_size_mb": round(output_size / (1024 * 1024), 2),
            "size_reduction_percent": round(reduction, 1),
        }

        if use_s3:
            download_url = upload_to_s3(
                file_data=compressed_data,
                filename=output_filename,
                content_type="video/mp4",
                folder="convert-it/converted",
            )

            if download_url:
                response_data["download_url"] = download_url
                response_data["expires_at"] = (
                    datetime.now() + timedelta(days=30)
                ).isoformat()
            else:
                response_data["s3_upload_error"] = "Failed to upload to S3"

        if return_base64:
            response_data["file_base64"] = base64.b64encode(compressed_data).decode(
                "utf-8"
            )

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during video compression: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to compress video: {str(e)}"
        )


@router.post("/compress-video/base64/")
async def compress_video_from_base64(
    fastapi_request: Request,
    request: VideoCompressionRequest,
    _: str = Depends(verify_api_key_for_conversions),
) -> JSONResponse:
    """
    Compress MP4 video by reducing resolution and bitrate with optional S3 upload.
    Files uploaded to: s3://bucket/converted/
    """
    try:
        try:
            file_data = base64.b64decode(request.file_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid Base64 string format.")

        if not request.filename.lower().endswith(".mp4"):
            raise HTTPException(
                status_code=400,
                detail="Only MP4 files are supported for video compression.",
            )

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            media_converter.compress_video,
            file_data,
            request.filename,
            request.resolution,
            request.bitrate,
        )

        compressed_data, output_filename = result

        input_size = len(file_data)
        output_size = len(compressed_data)
        reduction = ((input_size - output_size) / input_size) * 100

        response_data = {
            "success": True,
            "original_filename": request.filename,
            "output_filename": output_filename,
            "resolution": request.resolution,
            "bitrate": request.bitrate,
            "input_size_mb": round(input_size / (1024 * 1024), 2),
            "output_size_mb": round(output_size / (1024 * 1024), 2),
            "size_reduction_percent": round(reduction, 1),
        }

        if request.use_s3:
            download_url = upload_to_s3(
                file_data=compressed_data,
                filename=output_filename,
                content_type="video/mp4",
                folder="convert-it/converted",
            )

            if download_url:
                response_data["download_url"] = download_url
                response_data["expires_at"] = (
                    datetime.now() + timedelta(days=30)
                ).isoformat()
            else:
                response_data["s3_upload_error"] = "Failed to upload to S3"

        if request.return_base64:
            response_data["file_base64"] = base64.b64encode(compressed_data).decode(
                "utf-8"
            )

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during video compression from base64: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to compress video: {str(e)}"
        )


@router.post("/video-info/file/")
async def get_video_info_from_file(
    fastapi_request: Request,
    file: UploadFile = File(..., description="Video file to analyze"),
    _: str = Depends(verify_api_key_for_conversions),
) -> JSONResponse:
    """Get information about a video file (duration, resolution, fps, etc.)."""
    try:
        file_data = await file.read()
        filename = file.filename or "video.mp4"

        info = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            media_converter.get_video_info,
            file_data,
            filename,
        )

        return JSONResponse(
            content={
                "success": True,
                "filename": filename,
                "video_info": info,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get video info: {str(e)}"
        )


# --- Image Conversion Endpoints ---


@router.post("/webp/file/")
async def convert_to_webp_from_file(
    fastapi_request: Request,
    file: UploadFile = File(..., description="Image file to convert to WebP"),
    quality: int = Form(80, description="WebP quality (1-100)"),
    max_width: Optional[int] = Form(None, description="Maximum width in pixels"),
    max_height: Optional[int] = Form(None, description="Maximum height in pixels"),
    use_s3: bool = Form(False, description="Upload to S3 and return download URL"),
    return_base64: bool = Form(True, description="Include base64 in response"),
    _: str = Depends(verify_api_key_for_conversions),
) -> JSONResponse:
    """
    Convert image to WebP format with optional resizing and S3 upload.
    Supports: PNG, JPEG, JPG, BMP, TIFF, GIF
    Files uploaded to: s3://bucket/converted/
    """
    try:
        if not 1 <= quality <= 100:
            raise HTTPException(
                status_code=400, detail="Quality must be between 1 and 100."
            )

        file_data = await file.read()
        filename = file.filename or "image.webp"

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            image_to_webp.convert_to_webp,
            file_data,
            filename,
            quality,
            max_width,
            max_height,
        )

        webp_data, output_filename, info = result

        response_data = {
            "success": True,
            "conversion_info": info,
        }

        if use_s3:
            download_url = upload_to_s3(
                file_data=webp_data,
                filename=output_filename,
                content_type="image/webp",
                folder="convert-it/converted",
            )

            if download_url:
                response_data["download_url"] = download_url
                response_data["expires_at"] = (
                    datetime.now() + timedelta(days=30)
                ).isoformat()
            else:
                response_data["s3_upload_error"] = "Failed to upload to S3"

        if return_base64:
            response_data["file_base64"] = base64.b64encode(webp_data).decode("utf-8")

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during WebP conversion: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to convert to WebP: {str(e)}"
        )


@router.post("/webp/base64/")
async def convert_to_webp_from_base64(
    fastapi_request: Request,
    request: ImageToWebPRequest,
    _: str = Depends(verify_api_key_for_conversions),
) -> JSONResponse:
    """
    Convert image to WebP format with optional resizing and S3 upload (from base64).
    Files uploaded to: s3://bucket/converted/
    """
    try:
        if not 1 <= request.quality <= 100:
            raise HTTPException(
                status_code=400, detail="Quality must be between 1 and 100."
            )

        try:
            file_data = base64.b64decode(request.file_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid Base64 string format.")

        result = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            image_to_webp.convert_to_webp,
            file_data,
            request.filename,
            request.quality,
            request.max_width,
            request.max_height,
        )

        webp_data, output_filename, info = result

        response_data = {
            "success": True,
            "conversion_info": info,
        }

        if request.use_s3:
            download_url = upload_to_s3(
                file_data=webp_data,
                filename=output_filename,
                content_type="image/webp",
                folder="convert-it/converted",
            )

            if download_url:
                response_data["download_url"] = download_url
                response_data["expires_at"] = (
                    datetime.now() + timedelta(days=30)
                ).isoformat()
            else:
                response_data["s3_upload_error"] = "Failed to upload to S3"

        if request.return_base64:
            response_data["file_base64"] = base64.b64encode(webp_data).decode("utf-8")

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during WebP conversion from base64: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to convert to WebP: {str(e)}"
        )


@router.post("/image-info/file/")
async def get_image_info_from_file(
    fastapi_request: Request,
    file: UploadFile = File(..., description="Image file to analyze"),
    _: str = Depends(verify_api_key_for_conversions),
) -> JSONResponse:
    """Get information about an image file (format, dimensions, size, etc.)."""
    try:
        file_data = await file.read()
        filename = file.filename or "image"

        info = await asyncio.get_event_loop().run_in_executor(
            PROCESS_EXECUTOR,
            image_to_webp.get_image_info,
            file_data,
            filename,
        )

        return JSONResponse(
            content={
                "success": True,
                "image_info": info,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting image info: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get image info: {str(e)}"
        )


# --- Status Endpoint ---


@router.get("/status/")
async def conversion_status():
    """Get status of media conversion service including S3 availability."""
    return {
        "service": "Media Conversion API",
        "status": "operational",
        "s3_enabled": s3_client is not None,
        "s3_bucket": S3_BUCKET if s3_client else None,
        "s3_folder": "convert-it/converted/",
        "note": "All converted files (mp3, webp, mp4) are stored in the same folder",
        "converters": {
            "audio": "operational",
            "video": "operational",
            "image": "operational",
        },
        "endpoints": {
            "audio_conversion": "/converted/*",
            "video_compression": "/converted/*",
            "image_conversion": "/converted/*",
            "media_info": "/converted/*",
        },
    }
