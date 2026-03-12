"""
HEM Product Catalogue - Cloudinary Client Module
Cloudinary configuration, image operations, and cloud backup.
"""
import os
import io
import base64
import time
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from PIL import Image

import cloudinary
import cloudinary.api
import cloudinary.uploader

from config import (
    CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET,
    PRODUCTS_DB_FILE, SAVED_TEMPLATES_FILE,
)

logger = logging.getLogger(__name__)

# Reusable HTTP session for connection pooling (avoids TCP/TLS handshake per image)
_http_session = requests.Session()
_http_session.headers.update({"User-Agent": "Mozilla/5.0"})
adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
_http_session.mount("https://", adapter)
_http_session.mount("http://", adapter)

# --- Initialize Cloudinary ---
def init_cloudinary():
    """Configure cloudinary SDK. Call once at startup."""
    secret = CLOUDINARY_API_SECRET
    if not secret:
        logger.warning("CLOUDINARY_API_SECRET not set - cloud features will be limited")
    cloudinary.config(
        cloud_name = "dddtoqebz",
        api_key = "157864912291655",
        api_secret = "YkhyT4hxge0fh-zACddSnsI0-S4",
        secure = True
    )

# --- Image Processing ---
def get_image_as_base64_str(url_or_path, resize=None, max_size=None, retries=1):
    """Download/open an image and return it as a base64-encoded JPEG string.
    Supports both HTTP URLs and local file paths.
    Includes retry logic for network fetches."""
    if not url_or_path:
        return ""
    for attempt in range(retries + 1):
        try:
            img = None
            if str(url_or_path).startswith("http"):
                response = _http_session.get(url_or_path, timeout=5)
                if response.status_code != 200:
                    return ""
                img = Image.open(io.BytesIO(response.content))
            else:
                if not os.path.exists(url_or_path):
                    return ""
                img = Image.open(url_or_path)

            if max_size:
                img.thumbnail(max_size)
            elif resize:
                img = img.resize(resize)

            buffered = io.BytesIO()
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(buffered, format="JPEG", quality=75)
            return base64.b64encode(buffered.getvalue()).decode()

        except requests.exceptions.Timeout:
            if attempt < retries:
                time.sleep(0.3 * (attempt + 1))
                continue
            logger.warning(f"Image fetch timed out: {url_or_path}")
            return ""
        except Exception as e:
            logger.warning(f"Error processing image {url_or_path}: {e}")
            return ""
    return ""


def batch_download_images(url_list, max_workers=16):
    """Download multiple images in parallel and return a dict of {url: base64_str}.
    Uses ThreadPoolExecutor for concurrent HTTP requests."""
    results = {}
    if not url_list:
        return results

    def _fetch_one(url):
        return url, get_image_as_base64_str(url, max_size=None)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, url): url for url in url_list}
        for future in as_completed(futures):
            try:
                url, b64 = future.result()
                results[url] = b64
            except Exception:
                results[futures[future]] = ""
    return results


# --- Cloudinary Database Backup ---
def download_db_from_cloudinary():
    """Try to download products_db.json from Cloudinary backup."""
    try:
        res = cloudinary.api.resource("app_data/products_db", resource_type="raw")
        url = res.get("secure_url", "")
        if url:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
    except cloudinary.exceptions.NotFound:
        logger.info("No products_db found on Cloudinary (first run)")
    except Exception as e:
        logger.warning(f"Cloudinary DB download failed: {e}")
    return None


def upload_db_to_cloudinary(db):
    """Backup products_db.json to Cloudinary as a raw file."""
    try:
        data_dir = os.path.dirname(PRODUCTS_DB_FILE)
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        temp_path = PRODUCTS_DB_FILE + ".upload_tmp"
        with open(temp_path, 'w') as f:
            json.dump(db, f, indent=2)
        cloudinary.uploader.upload(
            temp_path,
            resource_type="raw",
            public_id="products_db",
            folder="app_data",
            overwrite=True,
        )
        if os.path.exists(temp_path):
            os.remove(temp_path)
        logger.info("Database backed up to Cloudinary")
    except Exception as e:
        logger.error(f"Cloudinary DB backup error: {e}")


# --- Cloudinary Templates Backup ---
def download_templates_from_cloudinary():
    """Try to download saved_templates.json from Cloudinary backup."""
    try:
        res = cloudinary.api.resource("app_data/saved_templates", resource_type="raw")
        url = res.get("secure_url", "")
        if url:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
    except cloudinary.exceptions.NotFound:
        pass
    except Exception as e:
        logger.warning(f"Cloudinary templates download failed: {e}")
    return None


def upload_templates_to_cloudinary():
    """Backup saved_templates.json to Cloudinary."""
    try:
        if os.path.exists(SAVED_TEMPLATES_FILE):
            cloudinary.uploader.upload(
                SAVED_TEMPLATES_FILE,
                resource_type="raw",
                public_id="saved_templates",
                folder="app_data",
                overwrite=True,
            )
            logger.info("Templates backed up to Cloudinary")
    except Exception as e:
        logger.error(f"Cloudinary templates backup error: {e}")


# --- Cloudinary Image Indexing ---
def fetch_all_cloudinary_resources():
    """Fetch all uploaded resources from Cloudinary.
    Returns a list of resource dicts."""
    resources = []
    try:
        next_cursor = None
        while True:
            res = cloudinary.api.resources(
                type="upload", max_results=500, next_cursor=next_cursor
            )
            resources.extend(res.get('resources', []))
            next_cursor = res.get('next_cursor')
            if not next_cursor:
                break
        logger.info(f"Fetched {len(resources)} resources from Cloudinary")
    except Exception as e:
        logger.warning(f"Cloudinary resource fetch failed: {e}")
    return resources


def upload_custom_image(image_file):
    """Upload a custom product image to Cloudinary.
    Returns the secure URL or empty string."""
    try:
        res = cloudinary.uploader.upload(image_file, folder="custom_uploads")
        return res.get("secure_url", "")
    except Exception as e:
        logger.error(f"Custom image upload failed: {e}")
        return ""

