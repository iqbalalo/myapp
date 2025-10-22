"""
Image to WebP Converter API Module
Optimized for API usage - handles individual image conversions
Converts PNG and JPEG images to WebP format with optional dimension reduction
"""

from PIL import Image
import io
import os
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class ImageToWebPAPI:
    """Image to WebP converter optimized for API usage with in-memory processing."""

    @staticmethod
    def resize_image(
        img: Image.Image,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
    ) -> Tuple[Image.Image, bool]:
        """
        Resize image while maintaining aspect ratio.

        Args:
            img (PIL.Image): Image object to resize
            max_width (int, optional): Maximum width in pixels
            max_height (int, optional): Maximum height in pixels

        Returns:
            Tuple[PIL.Image, bool]: (Resized image, was_resized flag)
        """
        original_width, original_height = img.size

        # If no max dimensions specified, return original
        if max_width is None and max_height is None:
            return img, False

        # Calculate new dimensions
        new_width = original_width
        new_height = original_height

        # Resize based on max_width
        if max_width and original_width > max_width:
            ratio = max_width / original_width
            new_width = max_width
            new_height = int(original_height * ratio)

        # Resize based on max_height
        if max_height and original_height > max_height:
            ratio = max_height / original_height
            new_height = max_height
            new_width = int(original_width * ratio)

            # If both constraints exist, use the smaller dimension
            if max_width and new_width > max_width:
                ratio = max_width / original_width
                new_width = max_width
                new_height = int(original_height * ratio)

        # Only resize if dimensions changed
        if new_width != original_width or new_height != original_height:
            img = img.resize((new_width, new_height), Image.LANCZOS)
            return img, True

        return img, False

    @staticmethod
    def convert_to_webp(
        file_data: bytes,
        filename: str,
        quality: int = 80,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
    ) -> Tuple[bytes, str, dict]:
        """
        Convert an image file to WebP format with optional resizing.

        Args:
            file_data (bytes): Binary data of the input image
            filename (str): Original filename (used to get extension)
            quality (int): Quality of the output image (1-100, default 80)
            max_width (int, optional): Maximum width in pixels (maintains aspect ratio)
            max_height (int, optional): Maximum height in pixels (maintains aspect ratio)

        Returns:
            Tuple[bytes, str, dict]: (WebP file data, output filename, conversion info)

        Raises:
            Exception: If conversion fails
        """
        try:
            # Open the image from bytes
            img = Image.open(io.BytesIO(file_data))
            original_size = img.size
            original_file_size = len(file_data)

            # Resize if needed
            img, was_resized = ImageToWebPAPI.resize_image(img, max_width, max_height)
            new_size = img.size

            # Generate output filename
            base_name = os.path.splitext(filename)[0]
            output_filename = f"{base_name}.webp"

            # Convert and save as WebP to bytes
            output_buffer = io.BytesIO()
            img.save(output_buffer, "WEBP", quality=quality)
            output_data = output_buffer.getvalue()
            output_file_size = len(output_data)

            # Calculate size reduction
            reduction = (
                (original_file_size - output_file_size) / original_file_size
            ) * 100

            # Prepare conversion info
            info = {
                "original_filename": filename,
                "output_filename": output_filename,
                "original_size_kb": round(original_file_size / 1024, 2),
                "output_size_kb": round(output_file_size / 1024, 2),
                "size_reduction_percent": round(reduction, 1),
                "original_dimensions": {
                    "width": original_size[0],
                    "height": original_size[1],
                },
                "output_dimensions": {"width": new_size[0], "height": new_size[1]},
                "was_resized": was_resized,
                "quality": quality,
            }

            logger.info(
                f"Converted {filename} to WebP: "
                f"{original_size[0]}x{original_size[1]} -> {new_size[0]}x{new_size[1]}, "
                f"size reduction: {reduction:.1f}%"
            )

            return output_data, output_filename, info

        except Exception as e:
            logger.error(f"Error converting {filename} to WebP: {str(e)}")
            raise Exception(f"Failed to convert to WebP: {str(e)}")

    @staticmethod
    def get_image_info(file_data: bytes, filename: str) -> dict:
        """
        Get information about an image file.

        Args:
            file_data (bytes): Binary data of the image
            filename (str): Original filename

        Returns:
            dict: Image information including format, size, dimensions, mode
        """
        try:
            img = Image.open(io.BytesIO(file_data))

            info = {
                "filename": filename,
                "format": img.format,
                "mode": img.mode,
                "size_bytes": len(file_data),
                "size_kb": round(len(file_data) / 1024, 2),
                "dimensions": {"width": img.width, "height": img.height},
            }

            return info

        except Exception as e:
            logger.error(f"Error getting image info for {filename}: {str(e)}")
            raise Exception(f"Failed to get image info: {str(e)}")
