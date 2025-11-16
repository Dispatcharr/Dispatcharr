"""
Image processing utilities for converting program banners to portrait format.
"""
import os
import hashlib
import requests
from io import BytesIO
from PIL import Image
from django.conf import settings
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Target aspect ratio for portrait images (width:height)
TARGET_ASPECT_RATIO = (2, 3)  # 2:3 ratio recommended for Emby

# Directory to store processed portrait images
PROCESSED_IMAGES_DIR = "processed_banners"


def get_processed_images_path():
    """Get the full path to the processed images directory."""
    path = Path(settings.MEDIA_ROOT) / PROCESSED_IMAGES_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def generate_image_filename(url):
    """Generate a unique filename for an image URL using MD5 hash."""
    url_hash = hashlib.md5(url.encode()).hexdigest()
    # Keep original extension if possible
    original_ext = Path(url.split('?')[0]).suffix.lower()
    if original_ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
        original_ext = '.jpg'  # Default to jpg
    return f"{url_hash}{original_ext}"


def download_image(url, timeout=10):
    """
    Download an image from a URL.

    Args:
        url: The image URL to download
        timeout: Request timeout in seconds

    Returns:
        PIL.Image object or None if download fails
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, timeout=timeout, headers=headers, stream=True)
        response.raise_for_status()

        # Load image from response content
        image = Image.open(BytesIO(response.content))

        # Convert to RGB if necessary (handles RGBA, P, etc.)
        if image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')

        return image

    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return None


def is_landscape(image):
    """
    Check if an image is landscape orientation.

    Args:
        image: PIL.Image object

    Returns:
        True if landscape (width > height), False otherwise
    """
    width, height = image.size
    return width > height


def calculate_target_dimensions(original_width, original_height):
    """
    Calculate target dimensions maintaining 2:3 aspect ratio.
    Keeps the original size, just adjusts to fit 2:3 ratio.

    Args:
        original_width: Original image width
        original_height: Original image height

    Returns:
        Tuple of (target_width, target_height)
    """
    target_ratio = TARGET_ASPECT_RATIO[0] / TARGET_ASPECT_RATIO[1]  # 2/3 = 0.6667
    current_ratio = original_width / original_height

    if current_ratio > target_ratio:
        # Image is too wide, need to crop width
        target_height = original_height
        target_width = int(target_height * target_ratio)
    else:
        # Image is too tall or already portrait, need to crop height
        target_width = original_width
        target_height = int(target_width / target_ratio)

    return target_width, target_height


def convert_to_portrait(image):
    """
    Convert an image to portrait format with 2:3 aspect ratio by fitting the entire image with padding.

    Args:
        image: PIL.Image object

    Returns:
        PIL.Image object in portrait format (2:3 aspect ratio)
    """
    original_width, original_height = image.size
    target_ratio = TARGET_ASPECT_RATIO[0] / TARGET_ASPECT_RATIO[1]  # 2/3 = 0.666...
    current_ratio = original_width / original_height

    # Calculate target dimensions that will contain the entire original image
    if current_ratio > target_ratio:
        # Image is wider than target ratio - fit to width
        new_width = original_width
        new_height = int(original_width / target_ratio)
    else:
        # Image is taller than target ratio - fit to height
        new_height = original_height
        new_width = int(original_height * target_ratio)

    # Create new canvas with black background
    new_image = Image.new('RGB', (new_width, new_height), (0, 0, 0))

    # Calculate position to paste original image (centered)
    paste_x = (new_width - original_width) // 2
    paste_y = (new_height - original_height) // 2

    # Paste original image onto canvas
    new_image.paste(image, (paste_x, paste_y))

    logger.info(f"Fitted image from {original_width}x{original_height} to {new_width}x{new_height} (2:3 ratio) with padding")

    return new_image


def process_image_to_portrait(url):
    """
    Download an image and convert it to portrait format if needed.

    Args:
        url: Image URL to process

    Returns:
        Tuple of (success, local_path_or_error)
        - If successful: (True, relative_path_to_image)
        - If failed: (False, error_message)
    """
    try:
        # Download the image
        image = download_image(url)
        if image is None:
            return False, "Failed to download image"

        # Check if conversion is needed
        width, height = image.size
        current_ratio = width / height
        target_ratio = TARGET_ASPECT_RATIO[0] / TARGET_ASPECT_RATIO[1]

        # Only process if not already 2:3 ratio (with 5% tolerance)
        if abs(current_ratio - target_ratio) > 0.05:
            logger.info(f"Converting image from {width}x{height} (ratio: {current_ratio:.2f}) to 2:3 portrait")
            image = convert_to_portrait(image)
        else:
            logger.info(f"Image already has 2:3 ratio ({width}x{height}), skipping conversion")

        # Generate filename and save
        filename = generate_image_filename(url)
        full_path = get_processed_images_path() / filename

        # Save as JPEG with good quality
        image.save(full_path, 'JPEG', quality=90, optimize=True)

        # Return relative path for storage in database
        relative_path = f"{PROCESSED_IMAGES_DIR}/{filename}"
        logger.info(f"Saved processed image to {relative_path}")

        return True, relative_path

    except Exception as e:
        logger.error(f"Failed to process image {url}: {e}")
        return False, str(e)


def get_processed_image_url(request, relative_path):
    """
    Generate a full URL for a processed image.

    Args:
        request: Django request object
        relative_path: Relative path to the image (e.g., "processed_banners/abc123.jpg")

    Returns:
        Full URL to access the processed image
    """
    base_url = request.build_absolute_uri('/')[:-1]  # Remove trailing slash
    return f"{base_url}/media/{relative_path}"


def cleanup_orphaned_images(active_filenames):
    """
    Remove processed images that are no longer referenced.

    Args:
        active_filenames: Set of filenames that are currently in use
    """
    try:
        processed_path = get_processed_images_path()
        for file in processed_path.glob('*'):
            if file.is_file() and file.name not in active_filenames:
                logger.info(f"Removing orphaned processed image: {file.name}")
                file.unlink()
    except Exception as e:
        logger.error(f"Failed to cleanup orphaned images: {e}")
