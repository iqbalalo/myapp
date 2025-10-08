import hashlib
import io
import logging
import re
from typing import Dict, Any
from PIL import Image
import pytesseract

# Configuration
pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

logging.getLogger().setLevel(logging.ERROR)


class ImageProcessor:
    """
    Handles image text extraction using OCR (Tesseract).
    Supports multiple image formats: JPEG, PNG, TIFF, BMP, GIF, WEBP.
    """

    def __init__(self):
        """Initializes processor with Tesseract configuration."""
        pass

    @staticmethod
    def _fix_japanese_spacing(text: str) -> str:
        """Removes spaces between Japanese characters and cleans punctuation spaces."""
        if not text:
            return text

        hiragana = r"[\u3040-\u309F]"
        katakana = r"[\u30A0-\u30FF]"
        kanji = r"[\u4E00-\u9FAF]"
        japanese_punctuation = r"[\u3000-\u303F]"
        japanese_char = f"({hiragana}|{katakana}|{kanji}|{japanese_punctuation})"

        # Remove spaces between Japanese characters
        text = re.sub(f"({japanese_char})\\s+({japanese_char})", r"\1\2", text)

        # Fix spaces around Japanese punctuation
        text = re.sub(r"\s+([。、！？）」』】])", r"\1", text)
        text = re.sub(r"([（「『【])\s+", r"\1", text)

        # Clean up multiple spaces
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _validate_image(image_data: bytes) -> bool:
        """Validates if the data is a valid image."""
        try:
            image = Image.open(io.BytesIO(image_data))
            image.verify()
            return True
        except Exception:
            return False

    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Preprocesses the image for optimal OCR performance.
        - Converts to grayscale
        - Resizes if too large
        """
        # Convert to grayscale for better OCR performance
        if image.mode != "L":
            image = image.convert("L")

        # Resize if image is very large to prevent memory/CPU spikes
        width, height = image.size
        max_dimension = 3000

        if width > max_dimension or height > max_dimension:
            # Maintain aspect ratio while resizing
            ratio = min(max_dimension / width, max_dimension / height)
            new_size = (int(width * ratio), int(height * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)

        return image

    def extract_text(
        self, image_data: bytes, ocr_language: str = "eng+jpn"
    ) -> Dict[str, Any]:
        """
        Main entry point for image text extraction using OCR.

        Args:
            image_data: Binary image data
            ocr_language: Tesseract language code (e.g., 'eng+jpn', 'eng+ben')

        Returns:
            Dictionary containing file_hash, file_text, and error (if any)
        """
        response = {
            "file_hash": create_file_hash(image_data),
            "file_text": "",
            "error": None,
        }

        try:
            # Validate image data
            if not self._validate_image(image_data):
                raise ValueError("Invalid image data")

            # Load image
            image = Image.open(io.BytesIO(image_data))

            # Preprocess image
            processed_image = self._preprocess_image(image)

            # Perform OCR with optimized configuration
            # PSM 3: Fully automatic page segmentation (default)
            # OEM 1: Neural nets LSTM engine only
            custom_config = r"--oem 1 --psm 3"

            extracted_text = pytesseract.image_to_string(
                processed_image,
                config=custom_config,
                lang=ocr_language,
            )

            # Post-process text
            fixed_text = self._fix_japanese_spacing(extracted_text)
            cleaned_text = "\n".join(
                line.strip() for line in fixed_text.split("\n") if line.strip()
            )

            if not cleaned_text:
                response["file_text"] = "[No text detected in image]"
            else:
                response["file_text"] = f"[OCR]:\n{cleaned_text}"

        except ValueError as ve:
            response["error"] = f"Validation Error: {str(ve)}"
            logging.error(f"Image validation failed: {response['error']}")
        except Exception as e:
            response["error"] = f"Extraction Failed: {type(e).__name__} - {str(e)}"
            logging.error(f"Extraction failed: {response['error']}")

        return response


def create_file_hash(data: bytes) -> str:
    """Generates a SHA256 hash for the file data."""
    return hashlib.sha256(data).hexdigest()
