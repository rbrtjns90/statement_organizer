"""
Image Normalization for OCR
-----------------------------
Pre-processing pipeline to standardize images for optimal text extraction.
Handles deskewing, contrast enhancement, DPI standardization, and more.
"""

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from typing import Tuple, Optional
import os


class ImageNormalizer:
    """Standardizes images for optimal OCR performance."""
    
    # Standard settings for financial documents
    TARGET_DPI = 300
    MIN_DIMENSION = 1000  # Minimum width/height in pixels
    MAX_DIMENSION = 4000  # Maximum to prevent memory issues
    
    def __init__(self, target_dpi: int = 300, enhance_contrast: bool = True):
        """
        Initialize normalizer.
        
        Args:
            target_dpi: Target resolution for OCR (300 recommended minimum)
            enhance_contrast: Whether to apply contrast enhancement
        """
        self.target_dpi = target_dpi
        self.enhance_contrast = enhance_contrast
    
    def normalize(self, image_path: str) -> Image.Image:
        """
        Full normalization pipeline for an image file.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Normalized PIL Image ready for OCR
        """
        # Load image
        image = Image.open(image_path)
        
        # Apply normalization steps in order
        image = self.convert_to_grayscale(image)
        image = self.deskew(image)
        image = self.standardize_dpi(image)
        image = self.enhance_contrast(image)
        image = self.reduce_noise(image)
        image = self.binarize_if_needed(image)
        
        return image
    
    def normalize_pil(self, image: Image.Image) -> Image.Image:
        """
        Normalize an already-loaded PIL Image.
        
        Args:
            image: PIL Image object
            
        Returns:
            Normalized PIL Image
        """
        image = self.convert_to_grayscale(image)
        image = self.deskew(image)
        image = self.standardize_dpi(image)
        image = self.enhance_contrast(image)
        image = self.reduce_noise(image)
        image = self.binarize_if_needed(image)
        
        return image
    
    def convert_to_grayscale(self, image: Image.Image) -> Image.Image:
        """Convert image to grayscale (L mode)."""
        if image.mode != 'L':
            return image.convert('L')
        return image
    
    def deskew(self, image: Image.Image, max_skew_angle: float = 45.0) -> Image.Image:
        """
        Detect and correct rotation in scanned documents.
        
        Uses projection profile method to find optimal rotation angle.
        
        Args:
            image: Grayscale PIL Image
            max_skew_angle: Maximum angle to search (degrees)
            
        Returns:
            Deskewed image
        """
        # Check if scipy is available
        try:
            from scipy import ndimage
        except ImportError:
            print("⚠️ scipy not available for deskewing, skipping")
            return image
        
        # Convert to numpy array
        img_array = np.array(image)
        
        # Calculate projection profiles for different angles
        angles = np.linspace(-max_skew_angle, max_skew_angle, 91)  # 1 degree increments
        scores = []
        
        for angle in angles:
            rotated = ndimage.rotate(img_array, angle, reshape=False, order=1, mode='constant', cval=255)
            # Calculate variance of row sums (text lines create high variance)
            projection = np.sum(rotated, axis=1)
            score = np.var(projection)
            scores.append(score)
        
        # Find angle with maximum variance (best alignment with text lines)
        best_angle = angles[np.argmax(scores)]
        
        # If angle is significant, rotate image
        if abs(best_angle) > 0.5:  # Only correct if more than 0.5 degrees
            print(f"🔄 Deskewing image by {best_angle:.1f} degrees")
            return image.rotate(best_angle, expand=True, fillcolor=255)
        
        return image
    
    def _rotate_image(self, img_array: np.ndarray, angle: float) -> np.ndarray:
        """Helper to rotate numpy array by given angle."""
        try:
            from scipy import ndimage
        except ImportError:
            print("⚠️ scipy not available for rotating, skipping")
            return img_array
        
        return ndimage.rotate(img_array, angle, reshape=False, order=1, mode='constant', cval=255)
    
    def standardize_dpi(self, image: Image.Image) -> Image.Image:
        """
        Resize image to standard DPI while maintaining aspect ratio.
        
        Args:
            image: PIL Image
            
        Returns:
            Resized image at target DPI
        """
        # Get current dimensions
        width, height = image.size
        
        # Calculate current DPI if available, otherwise assume 72
        current_dpi = getattr(image, 'info', {}).get('dpi', (72, 72))[0]
        
        # Calculate scale factor
        scale = self.target_dpi / current_dpi
        
        # Calculate new dimensions
        new_width = int(width * scale)
        new_height = int(height * scale)
        
        # Apply min/max constraints
        if new_width < self.MIN_DIMENSION:
            scale = self.MIN_DIMENSION / width
            new_width = self.MIN_DIMENSION
            new_height = int(height * scale)
        
        if new_width > self.MAX_DIMENSION:
            scale = self.MAX_DIMENSION / width
            new_width = self.MAX_DIMENSION
            new_height = int(height * scale)
        
        # Resize with high-quality filter
        if scale != 1.0:
            image = image.resize((new_width, new_height), Image.LANCZOS)
            print(f"📐 Resized image to {new_width}x{new_height} ({self.target_dpi} DPI equivalent)")
        
        return image
    
    def enhance_contrast(self, image: Image.Image) -> Image.Image:
        """
        Enhance image contrast for better OCR.
        
        Args:
            image: Grayscale PIL Image
            
        Returns:
            Contrast-enhanced image
        """
        if not self.enhance_contrast:
            return image
        
        # Use adaptive contrast enhancement
        # Calculate current contrast
        img_array = np.array(image)
        mean = np.mean(img_array)
        std = np.std(img_array)
        
        # If contrast is low, enhance it
        if std < 40:  # Low contrast threshold
            print("📊 Enhancing low-contrast image")
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)  # Double contrast
        
        # Also apply sharpness enhancement
        sharpener = ImageEnhance.Sharpness(image)
        image = sharpener.enhance(1.5)
        
        return image
    
    def reduce_noise(self, image: Image.Image) -> Image.Image:
        """
        Apply noise reduction while preserving text edges.
        
        Args:
            image: PIL Image
            
        Returns:
            Denoised image
        """
        # Use mild median filter for noise reduction
        # Kernel size 3 preserves fine text details
        image = image.filter(ImageFilter.MedianFilter(size=3))
        
        return image
    
    def binarize_if_needed(self, image: Image.Image) -> Image.Image:
        """
        Apply adaptive thresholding for very low-contrast images.
        
        Only applies if image has poor contrast.
        
        Args:
            image: Grayscale PIL Image
            
        Returns:
            Binarized or original image
        """
        img_array = np.array(image)
        
        # Calculate contrast
        contrast = np.std(img_array)
        
        # Only binarize if contrast is very low
        if contrast < 30:
            print("⚫ Applying adaptive thresholding")
            
            # Use Otsu's method for thresholding
            from skimage.filters import threshold_otsu
            thresh = threshold_otsu(img_array)
            binary = img_array > thresh
            
            # Convert back to PIL
            binary_img = Image.fromarray((binary * 255).astype(np.uint8))
            return binary_img
        
        return image
    
    def save_normalized(self, image_path: str, output_path: Optional[str] = None) -> str:
        """
        Normalize image and save to file.
        
        Args:
            image_path: Path to input image
            output_path: Path for output (default: input_path + .normalized.png)
            
        Returns:
            Path to normalized image
        """
        image = self.normalize(image_path)
        
        if output_path is None:
            base = os.path.splitext(image_path)[0]
            output_path = f"{base}.normalized.png"
        
        image.save(output_path, "PNG")
        return output_path


# Convenience functions
def normalize_image(image_path: str) -> Image.Image:
    """Quick normalization of an image file."""
    normalizer = ImageNormalizer()
    return normalizer.normalize(image_path)


def normalize_for_ocr(image: Image.Image) -> Image.Image:
    """Normalize an already-loaded PIL Image for OCR."""
    normalizer = ImageNormalizer()
    return normalizer.normalize_pil(image)


def is_low_quality(image: Image.Image, min_dpi: int = 150) -> bool:
    """
    Check if image quality is too low for reliable OCR.
    
    Args:
        image: PIL Image
        min_dpi: Minimum acceptable DPI
        
    Returns:
        True if image quality is insufficient
    """
    # Check resolution
    width, height = image.size
    current_dpi = getattr(image, 'info', {}).get('dpi', (72, 72))[0]
    
    if current_dpi < min_dpi and width < 1000:
        return True
    
    # Check contrast
    img_array = np.array(image.convert('L'))
    if np.std(img_array) < 20:
        return True
    
    return False
