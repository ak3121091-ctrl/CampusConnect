"""
image_utils.py - Secure Image Processing & Validation Layer
------------------------------------------------------------
Handles secure image upload validation, content inspection via Pillow,
stripping unnecessary EXIF metadata, dimension resizing, and safe storage
with random server-side filenames to prevent path traversal and unsafe uploads.
"""

import os
import uuid
import logging
from PIL import Image, ImageOps, UnidentifiedImageError

# Configuration & Security Limits
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 Megabytes in bytes
MAX_DIMENSION = 1200              # Maximum width or height in pixels


def is_allowed_extension(filename):
    """Checks if the filename has an allowed extension."""
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def validate_and_process_image(file_storage, upload_folder):
    """
    Validates and processes an uploaded image:
    1. Validates file existence and non-zero size.
    2. Enforces maximum file size of 5 MB.
    3. Validates actual image content using Pillow (magic bytes & structure).
    4. Enforces allowed formats: JPEG, PNG, WebP only.
    5. Normalizes EXIF orientation before stripping all EXIF metadata.
    6. Resizes large images (up to MAX_DIMENSION) preserving aspect ratio.
    7. Generates a cryptographically random filename (UUID4).
    8. Saves to the upload directory and returns the secure filename.

    Raises ValueError with a user-facing explanation on validation failure.
    Returns None if no file was uploaded.
    """
    if not file_storage or not file_storage.filename or file_storage.filename.strip() == '':
        return None

    # 1. Enforce file size limit <= 5 MB
    file_storage.seek(0, os.SEEK_END)
    file_size = file_storage.tell()
    file_storage.seek(0)

    if file_size == 0:
        return None

    if file_size > MAX_FILE_SIZE:
        raise ValueError(
            f"Image file size ({file_size / (1024 * 1024):.1f} MB) exceeds the 5 MB limit. "
            "Please select a smaller photo."
        )

    # 2. Inspect content with Pillow
    try:
        img = Image.open(file_storage.stream)
        fmt = (img.format or '').upper()

        if fmt not in ALLOWED_FORMATS:
            raise ValueError(
                f"Unsupported image format '{fmt or 'unknown'}'. "
                "Only JPEG, PNG, and WebP images are accepted."
            )

        # Basic integrity verification (detects truncated/corrupt image streams)
        img.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as e:
        if isinstance(e, ValueError) and "Unsupported image format" in str(e):
            raise
        raise ValueError("The uploaded file is corrupt or not a valid image. Please select a valid photo.")

    # 3. Re-open image stream for processing (verify() invalidates stream state)
    file_storage.seek(0)
    try:
        img = Image.open(file_storage.stream)

        # Transpose based on EXIF orientation so mobile photos aren't rotated sideways
        img = ImageOps.exif_transpose(img)

        # Resize if dimensions exceed MAX_DIMENSION
        if img.width > MAX_DIMENSION or img.height > MAX_DIMENSION:
            img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)

        # Determine extension and save parameters
        actual_fmt = (img.format or fmt).upper()
        if actual_fmt == 'JPEG':
            ext = '.jpg'
            save_format = 'JPEG'
            # Convert RGBA/P/LA to RGB for clean JPEG saving without artifacts
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                alpha_channel = img.split()[-1] if 'A' in img.getbands() else None
                rgb_img.paste(img, mask=alpha_channel)
                img = rgb_img
            elif img.mode != 'RGB':
                img = img.convert('RGB')
        elif actual_fmt == 'PNG':
            ext = '.png'
            save_format = 'PNG'
        elif actual_fmt == 'WEBP':
            ext = '.webp'
            save_format = 'WEBP'
        else:
            raise ValueError("Unsupported image format. Only JPEG, PNG, and WebP images are accepted.")

        # Generate unique random filename
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        os.makedirs(upload_folder, exist_ok=True)
        dest_path = os.path.join(upload_folder, unique_filename)

        # Save without exif parameter - this completely strips unnecessary EXIF metadata
        save_params = {'format': save_format, 'optimize': True}
        if save_format in ('JPEG', 'WEBP'):
            save_params['quality'] = 85

        try:
            img.save(dest_path, **save_params)
            return unique_filename
        except Exception:
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
            raise

    except ValueError:
        raise
    except Exception as e:
        logging.error("Image processing error: %s", str(e), exc_info=True)
        raise ValueError("An error occurred while processing the image. Please try another photo.")


def delete_image_file(filename, upload_folder):
    """
    Safely deletes an image file from the upload folder.
    Guards against path traversal by enforcing os.path.basename.
    """
    if not filename:
        return False
    safe_name = os.path.basename(filename)
    if safe_name != filename or not safe_name:
        return False

    target_path = os.path.join(upload_folder, safe_name)
    if os.path.isfile(target_path):
        try:
            os.remove(target_path)
            return True
        except OSError:
            return False
    return False

