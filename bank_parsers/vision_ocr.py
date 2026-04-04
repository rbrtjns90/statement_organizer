"""
macOS Vision Framework OCR Integration
----------------------------------------
Uses Apple's native Vision framework for high-accuracy OCR on macOS.
Falls back to pdfplumber for PDFs with embedded text.
"""

import platform
import os
from pathlib import Path
from typing import Optional, List

# Check if we're on macOS
IS_MACOS = platform.system() == "Darwin"

# Lazy import Vision framework only on macOS
VISION_AVAILABLE = False
if IS_MACOS:
    try:
        import Quartz
        import Vision
        from Cocoa import NSURL
        import objc
        VISION_AVAILABLE = True
    except ImportError:
        pass


def is_scanned_pdf(pdf_path: str) -> bool:
    """Check if PDF appears to be scanned (image-based with little/no text)."""
    try:
        import pdfplumber
        
        with pdfplumber.open(pdf_path) as pdf:
            # Check first few pages
            total_text = ""
            for i, page in enumerate(pdf.pages[:3]):
                text = page.extract_text() or ""
                total_text += text
            
            # If very little text extracted, likely scanned
            return len(total_text.strip()) < 100
    except Exception:
        return False


def pdf_page_to_image(pdf_path: str, page_num: int = 0, dpi: int = 200) -> Optional[str]:
    """Convert PDF page to image file for Vision OCR.
    
    Returns:
        Path to temporary image file, or None if failed
    """
    try:
        import pdf2image
        from PIL import Image
        
        # Convert PDF page to image
        images = pdf2image.convert_from_path(
            pdf_path,
            first_page=page_num + 1,
            last_page=page_num + 1,
            dpi=dpi
        )
        
        if not images:
            return None
        
        # Save to temp file
        temp_path = f"/tmp/vision_ocr_page_{page_num}_{os.getpid()}.png"
        images[0].save(temp_path, "PNG")
        return temp_path
        
    except ImportError:
        print("⚠️ pdf2image not available, install with: pip install pdf2image")
        return None
    except Exception as e:
        print(f"⚠️ PDF to image conversion failed: {e}")
        return None


def extract_text_with_vision(image_path: str) -> str:
    """Extract text from image using macOS Vision framework.
    
    Args:
        image_path: Path to image file (PNG, JPG, etc.)
        
    Returns:
        Extracted text
    """
    if not VISION_AVAILABLE:
        raise RuntimeError("Vision framework not available")
    
    try:
        # Load image
        image_url = NSURL.fileURLWithPath_(image_path)
        
        # Create image request handler
        request_handler = Vision.VNImageRequestHandler.alloc()
        request_handler.initWithURL_options_(image_url, None)
        
        # Create text recognition request
        request = Vision.VNRecognizeTextRequest.alloc()
        request.init()
        
        # Configure for accurate recognition (slower but better for financial docs)
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)
        
        # Perform request
        success, error = request_handler.performRequests_error_([request], None)
        
        if not success:
            print(f"⚠️ Vision OCR failed: {error}")
            return ""
        
        # Extract text from results
        results = request.results()
        extracted_lines = []
        
        for observation in results:
            for candidate in observation.topCandidates_(1):
                text = candidate.string()
                if text.strip():
                    extracted_lines.append(text)
        
        return "\n".join(extracted_lines)
        
    except Exception as e:
        print(f"⚠️ Vision OCR error: {e}")
        return ""


def extract_text_from_pdf(pdf_path: str, use_vision_if_scanned: bool = True) -> str:
    """Extract text from PDF, using Vision OCR if it appears to be scanned.
    
    Args:
        pdf_path: Path to PDF file
        use_vision_if_scanned: Whether to use Vision OCR for scanned PDFs
        
    Returns:
        Extracted text from all pages
    """
    # First try pdfplumber for text-based PDFs
    try:
        import pdfplumber
        
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
        
        full_text = "\n".join(text_parts)
        
        # If we got substantial text, return it
        if len(full_text.strip()) > 200:
            return full_text
        
    except Exception as e:
        print(f"⚠️ pdfplumber extraction failed: {e}")
    
    # If little/no text or pdfplumber failed, try Vision OCR if available
    if use_vision_if_scanned and VISION_AVAILABLE:
        print("🤖 PDF appears scanned, using Vision OCR...")
        
        try:
            import pdf2image
            
            # Convert all pages to images
            images = pdf2image.convert_from_path(pdf_path, dpi=200)
            
            all_text = []
            for i, image in enumerate(images):
                # Save page as temp image
                temp_path = f"/tmp/vision_ocr_page_{i}_{os.getpid()}.png"
                image.save(temp_path, "PNG")
                
                # OCR the page
                page_text = extract_text_with_vision(temp_path)
                if page_text:
                    all_text.append(f"--- Page {i+1} ---")
                    all_text.append(page_text)
                
                # Clean up temp file
                try:
                    os.remove(temp_path)
                except:
                    pass
            
            return "\n".join(all_text)
            
        except ImportError:
            print("⚠️ pdf2image required for Vision OCR, install with: pip install pdf2image")
        except Exception as e:
            print(f"⚠️ Vision OCR failed: {e}")
    
    # Final fallback - return whatever we got from pdfplumber
    return full_text if 'full_text' in locals() else ""


def extract_text_from_image(image_path: str) -> str:
    """Extract text from an image file using Vision OCR.
    
    Args:
        image_path: Path to image file (PNG, JPG, TIFF, etc.)
        
    Returns:
        Extracted text
    """
    if not VISION_AVAILABLE:
        raise RuntimeError("Vision framework only available on macOS")
    
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    print(f"🤖 Extracting text from image with Vision OCR: {Path(image_path).name}")
    return extract_text_with_vision(image_path)


def detect_bank_with_vision(pdf_path: str) -> Optional[str]:
    """Detect bank from PDF using Vision OCR on the first page.
    
    This is useful for scanned statements where pdfplumber can't extract text.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Detected bank name or None
    """
    if not VISION_AVAILABLE:
        return None
    
    try:
        # Extract text from first page using Vision
        text = extract_text_from_pdf(pdf_path, use_vision_if_scanned=True)
        
        if not text:
            return None
        
        # Use existing regex detection on the OCR'd text
        from .registry import detect_bank
        return detect_bank(text, pdf_path)
        
    except Exception as e:
        print(f"⚠️ Vision bank detection failed: {e}")
        return None


# Convenience function for the main pipeline
def extract_text(file_path: str, prefer_vision_on_mac: bool = True) -> str:
    """Universal text extraction - handles PDFs and images.
    
    On macOS, Vision OCR is used by default for best accuracy.
    On other platforms, pdfplumber is used for PDFs.
    
    Args:
        file_path: Path to PDF or image file
        prefer_vision_on_mac: If True (default), use Vision OCR on macOS
        
    Returns:
        Extracted text
    """
    file_path = str(file_path)
    ext = Path(file_path).suffix.lower()
    
    if ext in ['.pdf']:
        # On macOS with Vision available, default to Vision OCR for best results
        if prefer_vision_on_mac and VISION_AVAILABLE:
            print("🤖 Using Vision OCR as default on macOS for best accuracy...")
            return extract_text_from_pdf(file_path, use_vision_if_scanned=True)
        else:
            # On non-macOS or if Vision disabled, use pdfplumber with Vision fallback
            return extract_text_from_pdf(file_path, use_vision_if_scanned=True)
    elif ext in ['.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.gif']:
        if VISION_AVAILABLE:
            return extract_text_from_image(file_path)
        else:
            raise RuntimeError("Image OCR requires macOS Vision framework")
    else:
        raise ValueError(f"Unsupported file type: {ext}")
