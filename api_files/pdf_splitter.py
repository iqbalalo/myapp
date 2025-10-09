import io
import logging
from typing import List, Dict, Any
from PyPDF2 import PdfReader, PdfWriter

logging.getLogger().setLevel(logging.ERROR)


class PDFSplitter:
    """
    Handles PDF splitting into smaller files.
    Each split file will be a complete, readable PDF.
    """

    def __init__(self):
        """Initializes the PDF splitter."""
        pass

    @staticmethod
    def _validate_pdf(pdf_data: bytes) -> bool:
        """Validates if the data is a valid PDF."""
        try:
            reader = PdfReader(io.BytesIO(pdf_data))
            _ = len(reader.pages)
            return True
        except Exception:
            return False

    @staticmethod
    def _get_original_filename(filename: str) -> str:
        """Extracts the base filename without extension."""
        if filename.endswith(".pdf"):
            return filename[:-4]
        return filename

    def split_pdf(
        self, pdf_data: bytes, pages_per_split: int, original_filename: str = "document"
    ) -> Dict[str, Any]:
        """
        Splits a PDF into multiple smaller PDF files.

        Args:
            pdf_data: Binary PDF data
            pages_per_split: Number of pages per split file
            original_filename: Original filename (without or with .pdf extension)

        Returns:
            Dictionary containing:
                - success: Boolean indicating success
                - total_pages: Total number of pages in original PDF
                - total_splits: Number of split files created
                - files: List of dictionaries with filename and file_data (bytes)
                - error: Error message if splitting failed (None otherwise)
        """
        response = {
            "success": False,
            "total_pages": 0,
            "total_splits": 0,
            "files": [],
            "error": None,
        }

        try:
            # Validate PDF data
            if not self._validate_pdf(pdf_data):
                raise ValueError("Invalid PDF data")

            # Validate pages_per_split
            if pages_per_split < 1:
                raise ValueError("pages_per_split must be at least 1")

            # Read the PDF
            reader = PdfReader(io.BytesIO(pdf_data))
            total_pages = len(reader.pages)

            if total_pages == 0:
                raise ValueError("PDF has no pages")

            response["total_pages"] = total_pages

            # Get base filename
            base_filename = self._get_original_filename(original_filename)

            # Calculate number of splits
            num_splits = (total_pages + pages_per_split - 1) // pages_per_split
            response["total_splits"] = num_splits

            # Split the PDF
            for split_idx in range(num_splits):
                # Calculate page range for this split
                start_page = split_idx * pages_per_split
                end_page = min(start_page + pages_per_split, total_pages)

                # Create a new PDF writer for this split
                writer = PdfWriter()

                # Add pages to this split
                for page_idx in range(start_page, end_page):
                    writer.add_page(reader.pages[page_idx])

                # Write to bytes buffer
                output_buffer = io.BytesIO()
                writer.write(output_buffer)
                output_buffer.seek(0)
                split_data = output_buffer.read()

                # Create filename for this split
                split_filename = f"{base_filename}_{split_idx + 1}.pdf"

                # Add to response
                response["files"].append(
                    {
                        "filename": split_filename,
                        "file_data": split_data,
                        "pages": f"{start_page + 1}-{end_page}",
                        "page_count": end_page - start_page,
                        "size_bytes": len(split_data),
                    }
                )

            response["success"] = True

        except ValueError as ve:
            response["error"] = f"Validation Error: {str(ve)}"
            logging.error(f"PDF split validation failed: {response['error']}")
        except Exception as e:
            response["error"] = f"Split Failed: {type(e).__name__} - {str(e)}"
            logging.error(f"PDF split failed: {response['error']}")

        return response
