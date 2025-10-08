import json
import re
import hashlib
import io
import requests
import logging
import base64
import tempfile
import os
from typing import Dict, List, Tuple, Any, Union
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image
import concurrent.futures
import threading

# Configuration
pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
TESSERACT_LANGUAGES = "eng+jpn+ben"  # English, Japanese, and Bengali

logging.getLogger().setLevel(logging.ERROR)
# Lock for concurrent access to mutable resources (though mostly managed by futures here)
_results_lock = threading.Lock()


class PDFProcessor:
    """
    Handles file conversion, text extraction using hybrid PDF/OCR methods,
    and ensures temporary files are cleaned up.
    """

    def __init__(self):
        """Initializes processor with Tesseract configuration."""
        # Ensure Tesseract path is set (done globally, but reiterated for clarity)
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
    def _is_text_rich_page(page_text: str, min_chars: int = 50) -> bool:
        """Checks if a page has a minimum number of meaningful characters."""
        if not page_text:
            return False
        meaningful_chars = len(re.sub(r"\s+", "", page_text))
        return meaningful_chars >= min_chars

    def _extract_text_from_pdf_memory(
        self, pdf_data: bytes
    ) -> List[Tuple[int, str, bool]]:
        """Extracts text directly from PDF data using pdfplumber."""
        try:
            import pdfplumber
        except ImportError:
            # Should be handled by requirements.txt and Dockerfile.api
            raise ImportError("pdfplumber not available.")

        pages_data = []

        with pdfplumber.open(io.BytesIO(pdf_data)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                try:
                    text = page.extract_text()
                    if text:
                        cleaned_text = "\n".join(
                            line.strip() for line in text.split("\n") if line.strip()
                        )
                    else:
                        cleaned_text = ""

                    is_rich = self._is_text_rich_page(cleaned_text)
                    pages_data.append((page_num, cleaned_text, is_rich))

                except Exception as e:
                    logging.error(f"Error extracting text from page {page_num}: {e}")
                    pages_data.append((page_num, "", False))
        return pages_data

    def _process_single_page_ocr(self, image, page_num) -> Tuple[int, str]:
        """Processes a single page with OCR, optimized for speed and quality."""
        try:
            # Optimization: Convert to grayscale
            if image.mode != "L":
                image = image.convert("L")

            # Optimization: Resize if image is very large (to prevent memory/CPU spikes)
            width, height = image.size
            if width > 3000 or height > 3000:
                image = image.resize((2000, 2000), Image.Resampling.LANCZOS)

            # Optimized Tesseract config: PSM 1 (sparse text, best fit) or PSM 3 (default)
            # Using PSM 3, which is the default for a fully structured page.
            custom_config = r"--oem 1 --psm 3"

            extracted_text = pytesseract.image_to_string(
                image, config=custom_config, lang=TESSERACT_LANGUAGES
            )

            fixed_text = self._fix_japanese_spacing(extracted_text)
            cleaned_text = "\n".join(
                line.strip() for line in fixed_text.split("\n") if line.strip()
            )

            return page_num, cleaned_text

        except Exception as e:
            return page_num, f"[OCR Error: {type(e).__name__} - {str(e)}]"

    def _extract_text_with_ocr_memory(
        self, pdf_data: bytes, page_numbers: List[int]
    ) -> Dict[int, str]:
        """Performs OCR on specific PDF pages in parallel using pdf2image and pytesseract."""
        if not page_numbers:
            return {}

        ocr_results = {}

        # Determine the number of pages to process
        min_page = min(page_numbers)
        max_page = max(page_numbers)

        try:
            # Convert pages to images. DPI 150 is a good balance for speed/accuracy.
            images = convert_from_bytes(
                pdf_data,
                dpi=150,
                fmt="jpeg",
                first_page=min_page,
                last_page=max_page,
                thread_count=2,  # pdf2image can use multiple threads internally
                # Use poppler's file object read
            )

            # Filter images for only the pages we need
            page_images = []
            for i, image in enumerate(images):
                page_num = min_page + i
                if page_num in page_numbers:
                    page_images.append((image, page_num))

            # Process pages in parallel using the ThreadPoolExecutor
            # Limit workers to manage CPU usage, typically 2x CPU cores is safe.
            max_workers = min(os.cpu_count() * 2 or 4, len(page_images))

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            ) as executor:
                future_to_page = {
                    executor.submit(
                        self._process_single_page_ocr, image, page_num
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

    def extract_text(self, pdf_data: bytes, use_ocr: bool = True) -> Dict[str, Any]:
        """
        Main entry point for hybrid text extraction.
        Prioritizes PDF text and falls back to OCR for image-only pages.
        """
        response = {
            "file_hash": create_file_hash(pdf_data),
            "file_text": "",
            "error": None,
        }

        try:
            # Step 1: Extract text directly from PDF
            pdf_pages = self._extract_text_from_pdf_memory(pdf_data)

            if not pdf_pages:
                raise ValueError("Could not extract any page data from PDF")

            ocr_pages = []
            final_results = []

            # Identify pages that need OCR
            for page_num, text, is_rich in pdf_pages:
                if self._is_text_rich_page(text):
                    # Page has sufficient text, use PDF extraction
                    final_results.append((page_num, text, "PDF"))
                else:
                    # Page has insufficient text, mark for OCR
                    if use_ocr:
                        ocr_pages.append(page_num)
                        final_results.append((page_num, text, "OCR_PENDING"))
                    else:
                        # OCR not requested, use whatever PDF text is available
                        final_results.append(
                            (page_num, text or "[No text detected]", "PDF_ONLY")
                        )

            # Step 3: Process pages with OCR if needed
            if ocr_pages and use_ocr:
                ocr_results = self._extract_text_with_ocr_memory(pdf_data, ocr_pages)

                # Update results with OCR text
                for i, (page_num, text, method) in enumerate(final_results):
                    if method == "OCR_PENDING":
                        ocr_text = ocr_results.get(page_num, text)
                        final_results[i] = (page_num, ocr_text, "OCR")

            # Step 4: Combine all text into single string
            all_text_parts = []
            for page_num, text, method in final_results:
                if text and not text.startswith("["):  # Skip empty or error pages
                    all_text_parts.append(f"Page {page_num} [{method}]:\n{text}\n")

            response["file_text"] = "\n".join(all_text_parts)

        except Exception as e:
            response["error"] = f"Extraction Failed: {type(e).__name__} - {str(e)}"
            logging.error(f"Extraction failed: {response['error']}")

        return response


def create_file_hash(data: bytes) -> str:
    """Generates a SHA256 hash for the file data."""
    return hashlib.sha256(data).hexdigest()
