"""
Unified Text Extraction System
-------------------------------
Provides a single interface for extracting text from PDFs and images
with automatic backend selection and consistent error handling.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
import os
import platform


@dataclass
class ExtractionResult:
    """Result from text extraction."""
    text: str
    backend: str
    pages: int
    is_scanned: bool
    confidence: float  # 0-1 scale
    metadata: Dict[str, Any]


class ExtractionBackend(ABC):
    """Abstract base for text extraction backends."""
    
    name: str = ""
    available: bool = False
    
    @abstractmethod
    def extract(self, file_path: str) -> ExtractionResult:
        """Extract text from file."""
        pass
    
    @abstractmethod
    def check_available(self) -> bool:
        """Check if this backend is available on this system."""
        pass


class PdfPlumberBackend(ExtractionBackend):
    """Backend using pdfplumber for text-based PDFs."""
    
    name = "pdfplumber"
    
    def check_available(self) -> bool:
        try:
            import pdfplumber
            return True
        except ImportError:
            return False
    
    def extract(self, file_path: str) -> ExtractionResult:
        import pdfplumber
        
        text_parts = []
        total_chars = 0
        
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
                total_chars += len(page_text.strip())
        
        full_text = "\n".join(text_parts)
        
        # Determine if scanned based on text density
        is_scanned = total_chars < 200
        
        return ExtractionResult(
            text=full_text,
            backend=self.name,
            pages=len(pdf.pages),
            is_scanned=is_scanned,
            confidence=1.0 if not is_scanned else 0.3,
            metadata={"chars_per_page": total_chars / len(pdf.pages) if pdf.pages else 0}
        )


class VisionOCRBackend(ExtractionBackend):
    """Backend using macOS Vision framework."""
    
    name = "vision_ocr"
    
    def check_available(self) -> bool:
        if platform.system() != "Darwin":
            return False
        try:
            import Quartz
            import Vision
            return True
        except ImportError:
            return False
    
    def extract(self, file_path: str) -> ExtractionResult:
        from .vision_ocr import extract_text_from_pdf
        
        text = extract_text_from_pdf(file_path, use_vision_if_scanned=True)
        
        # Count pages from page markers
        pages = text.count("--- Page") + 1 if "--- Page" in text else 1
        
        return ExtractionResult(
            text=text,
            backend=self.name,
            pages=pages,
            is_scanned=True,  # Vision is typically used for scanned docs
            confidence=0.9,  # Vision is generally accurate
            metadata={"platform": "macOS"}
        )


class TesseractBackend(ExtractionBackend):
    """Backend using Tesseract OCR for Linux/Windows."""
    
    name = "tesseract"
    
    def check_available(self) -> bool:
        try:
            import pytesseract
            from PIL import Image
            # Test if tesseract is installed
            pytesseract.get_tesseract_version()
            return True
        except (ImportError, Exception):
            return False
    
    def _pdf_to_images(self, pdf_path: str, dpi: int = 300) -> List[str]:
        """Convert PDF to images."""
        from pdf2image import convert_from_path
        
        images = convert_from_path(pdf_path, dpi=dpi)
        temp_paths = []
        
        for i, image in enumerate(images):
            temp_path = f"/tmp/tesseract_page_{i}_{os.getpid()}.png"
            image.save(temp_path, "PNG")
            temp_paths.append(temp_path)
        
        return temp_paths
    
    def extract(self, file_path: str) -> ExtractionResult:
        import pytesseract
        from PIL import Image
        
        ext = Path(file_path).suffix.lower()
        
        if ext == '.pdf':
            # Convert PDF to images first
            image_paths = self._pdf_to_images(file_path)
            all_text = []
            
            for i, img_path in enumerate(image_paths):
                image = Image.open(img_path)
                text = pytesseract.image_to_string(image, config='--psm 6')
                all_text.append(f"--- Page {i+1} ---")
                all_text.append(text)
                
                # Cleanup
                try:
                    os.remove(img_path)
                except:
                    pass
            
            full_text = "\n".join(all_text)
            pages = len(image_paths)
        else:
            # Direct image OCR
            image = Image.open(file_path)
            full_text = pytesseract.image_to_string(image, config='--psm 6')
            pages = 1
        
        return ExtractionResult(
            text=full_text,
            backend=self.name,
            pages=pages,
            is_scanned=True,
            confidence=0.7,  # Tesseract is less accurate than Vision
            metadata={"platform": platform.system()}
        )


class TextExtractor:
    """Unified text extraction with automatic backend selection."""
    
    def __init__(self, preferred_order: Optional[List[str]] = None):
        """
        Initialize text extractor.
        
        Args:
            preferred_order: List of backend names in priority order.
                           Default: ['vision_ocr', 'tesseract', 'pdfplumber']
        """
        self.backends: Dict[str, ExtractionBackend] = {
            'pdfplumber': PdfPlumberBackend(),
            'vision_ocr': VisionOCRBackend(),
            'tesseract': TesseractBackend(),
        }
        
        # Check which backends are available
        self.available_backends = [
            name for name, backend in self.backends.items()
            if backend.check_available()
        ]
        
        # Set preferred order
        if preferred_order:
            self.preferred_order = [
                name for name in preferred_order
                if name in self.available_backends
            ]
        else:
            # Default: Vision OCR on macOS, then Tesseract, then pdfplumber
            if 'vision_ocr' in self.available_backends:
                self.preferred_order = ['vision_ocr', 'pdfplumber']
            elif 'tesseract' in self.available_backends:
                self.preferred_order = ['tesseract', 'pdfplumber']
            else:
                self.preferred_order = ['pdfplumber']
    
    def extract(self, file_path: str, prefer_ocr: bool = True) -> ExtractionResult:
        """
        Extract text from file with automatic backend selection.
        
        Args:
            file_path: Path to PDF or image file
            prefer_ocr: If True, prefer OCR backends for better accuracy
            
        Returns:
            ExtractionResult with extracted text and metadata
        """
        file_path = str(file_path)
        ext = Path(file_path).suffix.lower()
        
        # Validate file exists
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # For images, must use OCR
        if ext in ['.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.gif']:
            return self._extract_image(file_path)
        
        # For PDFs, try backends in order
        return self._extract_pdf(file_path, prefer_ocr)
    
    def _extract_image(self, file_path: str) -> ExtractionResult:
        """Extract text from image file."""
        # Try OCR backends in order
        for backend_name in ['vision_ocr', 'tesseract']:
            if backend_name in self.available_backends:
                try:
                    backend = self.backends[backend_name]
                    return backend.extract(file_path)
                except Exception as e:
                    print(f"⚠️ {backend_name} failed: {e}")
                    continue
        
        raise RuntimeError("No OCR backend available for image extraction")
    
    def _extract_pdf(self, file_path: str, prefer_ocr: bool) -> ExtractionResult:
        """Extract text from PDF with smart backend selection."""
        
        # First, try pdfplumber to check if text-based
        if 'pdfplumber' in self.available_backends:
            try:
                result = self.backends['pdfplumber'].extract(file_path)
                
                # If substantial text found, use it (Vision OCR causes crashes)
                if not result.is_scanned:
                    return result
                
                # Save for fallback
                text_result = result
                    
            except Exception as e:
                print(f"⚠️ pdfplumber failed: {e}")
                text_result = None
        else:
            text_result = None
        
        # For scanned PDFs, try OCR backends (skip vision_ocr to avoid crashes)
        for backend_name in ['tesseract']:
            if backend_name in self.available_backends:
                try:
                    print(f"🤖 Using {backend_name} for PDF extraction...")
                    return self.backends[backend_name].extract(file_path)
                except Exception as e:
                    print(f"⚠️ {backend_name} failed: {e}")
                    continue
        
        # Fallback to text-based result if available
        if text_result:
            print("⚠️ OCR not available, using pdfplumber text extraction")
            return text_result
        
        raise RuntimeError("All text extraction backends failed")
    
    def extract_with_fallback(self, file_path: str) -> ExtractionResult:
        """
        Extract text trying all backends until one succeeds.
        
        Args:
            file_path: Path to PDF or image file
            
        Returns:
            ExtractionResult from first successful backend
        """
        file_path = str(file_path)
        last_error = None
        
        for backend_name in self.preferred_order:
            try:
                backend = self.backends[backend_name]
                return backend.extract(file_path)
            except Exception as e:
                last_error = e
                print(f"⚠️ {backend_name} failed: {e}")
                continue
        
        raise RuntimeError(f"All extraction backends failed. Last error: {last_error}")


# Convenience function for direct use
def extract_text(file_path: str, prefer_ocr: bool = True) -> str:
    """
    Simple interface to extract text from file.
    
    Args:
        file_path: Path to PDF or image file
        prefer_ocr: If True, use OCR for better accuracy
        
    Returns:
        Extracted text string
    """
    extractor = TextExtractor()
    result = extractor.extract(file_path, prefer_ocr=prefer_ocr)
    return result.text
