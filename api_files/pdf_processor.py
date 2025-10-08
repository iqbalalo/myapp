import json
import re
import hashlib
import io
import logging
import base64
import tempfile
import os
from typing import Dict, List, Tuple, Any, Union, Optional
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
import concurrent.futures
import threading

# Configuration
pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

logging.getLogger().setLevel(logging.ERROR)

# Lock for concurrent access to mutable resources
_results_lock = threading.Lock()

# Constants
DEFAULT_MIN_CHARS = 50
DEFAULT_DPI = 150
DEFAULT_MAX_IMAGE_DIMENSION = 3000
DEFAULT_RESIZED_DIMENSION = 2000


class PDFProcessor:
    """
    Handles file conversion, text extraction using hybrid PDF/OCR methods,
    and ensures temporary files are cleaned up.
    """

    def __init__(
        self,
        min_chars: int = DEFAULT_MIN_CHARS,
        dpi: int = DEFAULT_DPI,
        max_image_dimension: int = DEFAULT_MAX_IMAGE_DIMENSION,
    ):
        """
        Initializes processor with Tesseract configuration.

        Args:
            min_chars: Minimum characters to consider a page text-rich
            dpi: DPI for pdf2image conversion
            max_image_dimension: Maximum image dimension before resizing
        """
        self.min_chars = min_chars
        self.dpi = dpi
        self.max_image_dimension = max_image_dimension

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
    def _clean_text(text: str) -> str:
        """Cleans extracted text by removing empty lines and excess whitespace."""
        if not text:
            return ""

        cleaned_lines = [line.strip() for line in text.split("\n") if line.strip()]
        return "\n".join(cleaned_lines)

    def _is_text_rich_page(
        self, page_text: str, min_chars: Optional[int] = None
    ) -> bool:
        """
        Checks if a page has a minimum number of meaningful characters.

        Args:
            page_text: Text extracted from the page
            min_chars: Optional override for minimum characters threshold
        """
        if not page_text:
            return False

        threshold = min_chars if min_chars is not None else self.min_chars
        meaningful_chars = len(re.sub(r"\s+", "", page_text))
        return meaningful_chars >= threshold

    def _extract_text_from_pdf_memory(
        self, pdf_data: bytes
    ) -> List[Tuple[int, str, bool]]:
        """
        Extracts text directly from PDF data using pdfplumber.

        Returns:
            List of tuples: (page_number, text, is_text_rich)
        """
        try:
            import pdfplumber
        except ImportError:
            raise ImportError(
                "pdfplumber is required but not installed. "
                "Install it with: pip install pdfplumber"
            )

        pages_data = []

        try:
            with pdfplumber.open(io.BytesIO(pdf_data)) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    try:
                        text = page.extract_text()
                        cleaned_text = self._clean_text(text) if text else ""
                        is_rich = self._is_text_rich_page(cleaned_text)
                        pages_data.append((page_num, cleaned_text, is_rich))

                    except Exception as e:
                        logging.error(
                            f"Error extracting text from page {page_num}: {e}"
                        )
                        pages_data.append((page_num, "", False))
        except Exception as e:
            raise Exception(f"Error opening PDF with pdfplumber: {e}")

        return pages_data

    def _resize_image_if_needed(self, image: Image.Image) -> Image.Image:
        """
        Resizes image if it exceeds maximum dimensions while maintaining aspect ratio.

        Args:
            image: PIL Image object

        Returns:
            Resized image or original if no resizing needed
        """
        width, height = image.size

        if width <= self.max_image_dimension and height <= self.max_image_dimension:
            return image

        # Calculate new dimensions maintaining aspect ratio
        ratio = min(
            DEFAULT_RESIZED_DIMENSION / width, DEFAULT_RESIZED_DIMENSION / height
        )
        new_size = (int(width * ratio), int(height * ratio))

        return image.resize(new_size, Image.Resampling.LANCZOS)

    def _process_single_page_ocr(
        self, image: Image.Image, page_num: int, ocr_language: str
    ) -> Tuple[int, str]:
        """
        Processes a single page with OCR, optimized for speed and quality.

        Args:
            image: PIL Image object
            page_num: Page number for tracking
            ocr_language: Tesseract language code

        Returns:
            Tuple of (page_number, extracted_text)
        """
        try:
            # Convert to grayscale for better OCR performance
            if image.mode != "L":
                image = image.convert("L")

            # Resize if needed
            image = self._resize_image_if_needed(image)

            # Optimized Tesseract config
            # PSM 3: Fully automatic page segmentation
            # OEM 1: Neural nets LSTM engine only
            custom_config = r"--oem 1 --psm 3"

            extracted_text = pytesseract.image_to_string(
                image,
                config=custom_config,
                lang=ocr_language,
            )

            # Post-process text
            fixed_text = self._fix_japanese_spacing(extracted_text)
            cleaned_text = self._clean_text(fixed_text)

            return page_num, cleaned_text

        except Exception as e:
            logging.error(f"OCR error on page {page_num}: {e}")
            return page_num, f"[OCR Error: {type(e).__name__} - {str(e)}]"

    def _extract_text_with_ocr_memory(
        self, pdf_data: bytes, page_numbers: List[int], ocr_language: str
    ) -> Dict[int, str]:
        """
        Performs OCR on specific PDF pages in parallel using pdf2image and pytesseract.

        Args:
            pdf_data: Binary PDF data
            page_numbers: List of page numbers to process
            ocr_language: Tesseract language code

        Returns:
            Dictionary mapping page numbers to extracted text
        """
        if not page_numbers:
            return {}

        ocr_results = {}
        min_page = min(page_numbers)
        max_page = max(page_numbers)

        try:
            # Convert pages to images
            images = convert_from_bytes(
                pdf_data,
                dpi=self.dpi,
                fmt="jpeg",
                first_page=min_page,
                last_page=max_page,
                thread_count=2,
            )

            # Map images to their actual page numbers
            page_images = []
            for i, image in enumerate(images):
                page_num = min_page + i
                if page_num in page_numbers:
                    page_images.append((image, page_num))

            # Process pages in parallel
            max_workers = min(os.cpu_count() * 2 or 4, len(page_images))

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            ) as executor:
                future_to_page = {
                    executor.submit(
                        self._process_single_page_ocr,
                        image,
                        page_num,
                        ocr_language,
                    ): page_num
                    for image, page_num in page_images
                }

                # Collect results as they complete
                for future in concurrent.futures.as_completed(future_to_page):
                    page_num = future_to_page[future]
                    try:
                        result_page_num, text = future.result()
                        with _results_lock:
                            ocr_results[result_page_num] = text
                    except Exception as e:
                        logging.error(
                            f"Error processing future for page {page_num}: {e}"
                        )
                        with _results_lock:
                            ocr_results[page_num] = f"[Threading Error: {str(e)}]"

            return ocr_results

        except Exception as e:
            raise Exception(f"Error in OCR processing: {e}")

    def extract_text(
        self, pdf_data: bytes, use_ocr: bool = True, ocr_language: str = "eng+jpn"
    ) -> Dict[str, Any]:
        """
        Main entry point for hybrid text extraction.
        Prioritizes PDF text and falls back to OCR for image-only pages.

        Args:
            pdf_data: Binary PDF data
            use_ocr: Whether to use OCR for pages with insufficient text
            ocr_language: Tesseract language code (e.g., 'eng+jpn', 'eng+ben')

        Returns:
            Dictionary containing:
                - file_hash: SHA256 hash of the file
                - file_text: Extracted text with page markers
                - error: Error message if extraction failed (None otherwise)
                - metadata: Additional processing metadata
        """
        response = {
            "file_hash": create_file_hash(pdf_data),
            "file_text": "",
            "error": None,
            "metadata": {
                "total_pages": 0,
                "pdf_pages": 0,
                "ocr_pages": 0,
            },
        }

        try:
            # Step 1: Extract text directly from PDF
            pdf_pages = self._extract_text_from_pdf_memory(pdf_data)

            if not pdf_pages:
                raise ValueError("Could not extract any page data from PDF")

            response["metadata"]["total_pages"] = len(pdf_pages)

            ocr_pages = []
            final_results = []

            # Step 2: Identify pages that need OCR
            for page_num, text, is_rich in pdf_pages:
                if is_rich:
                    # Page has sufficient text, use PDF extraction
                    final_results.append((page_num, text, "PDF"))
                    response["metadata"]["pdf_pages"] += 1
                else:
                    # Page has insufficient text
                    if use_ocr:
                        ocr_pages.append(page_num)
                        final_results.append((page_num, text, "OCR_PENDING"))
                    else:
                        # OCR not requested, use whatever PDF text is available
                        final_results.append(
                            (page_num, text or "[No text detected]", "PDF_ONLY")
                        )
                        response["metadata"]["pdf_pages"] += 1

            # Step 3: Process pages with OCR if needed
            if ocr_pages and use_ocr:
                ocr_results = self._extract_text_with_ocr_memory(
                    pdf_data, ocr_pages, ocr_language
                )

                # Update results with OCR text
                for i, (page_num, text, method) in enumerate(final_results):
                    if method == "OCR_PENDING":
                        ocr_text = ocr_results.get(page_num, text)
                        final_results[i] = (page_num, ocr_text, "OCR")
                        response["metadata"]["ocr_pages"] += 1

            # Step 4: Combine all text into single string
            all_text_parts = []
            for page_num, text, method in final_results:
                # Skip empty or error pages
                if text and not text.startswith("["):
                    all_text_parts.append(f"Page {page_num} [{method}]:\n{text}\n")

            response["file_text"] = "\n".join(all_text_parts)

            # Add summary if no text was extracted
            if not response["file_text"].strip():
                response["file_text"] = "[No text could be extracted from this PDF]"

        except Exception as e:
            response["error"] = f"Extraction Failed: {type(e).__name__} - {str(e)}"
            logging.error(f"Extraction failed: {response['error']}")

        return response


def create_file_hash(data: bytes) -> str:
    """Generates a SHA256 hash for the file data."""
    return hashlib.sha256(data).hexdigest()
