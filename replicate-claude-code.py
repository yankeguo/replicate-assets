#!/usr/bin/env -S uv run --script

# /// script
# dependencies = ["cos-python-sdk-v5", "requests", "python-dotenv"]
# ///

import json
import logging
import os
import re
import sys
import tempfile
from typing import Tuple

import requests
from dotenv import load_dotenv
from qcloud_cos import CosConfig, CosS3Client

load_dotenv()

COS_BUCKET = os.getenv("COS_BUCKET")
COS_REGION = os.getenv("COS_REGION", "ap-guangzhou")
COS_PUBLIC_URL = os.getenv("COS_PUBLIC_URL", "").rstrip("/")
COS_SECRET_ID = os.getenv("COS_SECRET_ID")
COS_SECRET_KEY = os.getenv("COS_SECRET_KEY")
COS_PATH_PREFIX = os.getenv("COS_PATH_PREFIX", "cc").lstrip("/").rstrip("/")

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

logger = logging.getLogger(__name__)

config = CosConfig(
    Region=COS_REGION, SecretId=COS_SECRET_ID, SecretKey=COS_SECRET_KEY, Scheme="https"
)
client = CosS3Client(config)


def simple_get(url: str) -> Tuple[str, bytes]:
    res = requests.get(url)
    res.raise_for_status()
    return res.text, res.content


def simple_upload_content(content: str | bytes, key: str) -> None:
    if COS_PATH_PREFIX:
        key = COS_PATH_PREFIX + "/" + key
    if isinstance(content, str):
        content = content.encode("utf-8")
    client.put_object(Bucket=COS_BUCKET, Body=content, Key=key)


def extract_src_base_url(install_sh_content: str) -> str:
    """Extract the first complete HTTPS URL from install.sh content."""
    # Pattern to match URLs like: GCS_BUCKET="https://storage.googleapis.com/..."
    # Match https:// followed by URL characters until whitespace, quote, or newline
    pattern = r'https://[^\s"\'\n\r]+'
    matches = re.findall(pattern, install_sh_content)
    if not matches:
        raise ValueError("No HTTPS URL found in install.sh")
    # Return the first complete URL, strip trailing quotes if any
    url = matches[0].rstrip('"').rstrip("'")
    return url


def simple_download_and_upload(url: str, key: str) -> None:
    if COS_PATH_PREFIX:
        key = COS_PATH_PREFIX + "/" + key

    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        local_path = tmp_file.name
        try:
            res = requests.get(url, stream=True)
            res.raise_for_status()
            for chunk in res.iter_content(chunk_size=8192):
                tmp_file.write(chunk)
            tmp_file.flush()

            client.upload_file(
                COS_BUCKET,
                key,
                local_path,
                PartSize=128 * 1024 * 1024,  # 128 MB
            )
        finally:
            os.unlink(local_path)


def main():
    # Validate required environment variables
    if not COS_BUCKET or not COS_SECRET_ID or not COS_SECRET_KEY or not COS_PUBLIC_URL:
        raise ValueError(
            "Missing required environment variables: COS_BUCKET, COS_SECRET_ID, COS_SECRET_KEY, COS_PUBLIC_URL"
        )

    # Build destination base URL
    dst_base_url = COS_PUBLIC_URL.rstrip("/")
    if COS_PATH_PREFIX:
        dst_base_url = f"{dst_base_url}/{COS_PATH_PREFIX}"

    # Download and process install.sh
    install_sh, raw_install_sh = simple_get("https://claude.ai/install.sh")
    src_base_url = extract_src_base_url(install_sh)
    logger.info(f"extracted src_base_url: {src_base_url}")

    # Replace URL in install.sh and upload (replace in text first, then encode)
    modified_install_sh_text = install_sh.replace(src_base_url, dst_base_url)
    simple_upload_content(modified_install_sh_text, "install.sh")
    logger.info("uploaded install.sh")

    # Download and process install.ps1
    install_ps1, raw_install_ps1 = simple_get("https://claude.ai/install.ps1")
    if src_base_url not in install_ps1:
        raise ValueError("src_base_url not found in install.ps1")

    # Replace URL in install.ps1 and upload (replace in text first, then encode)
    modified_install_ps1_text = install_ps1.replace(src_base_url, dst_base_url)
    simple_upload_content(modified_install_ps1_text, "install.ps1")
    logger.info("uploaded install.ps1")

    # Download stable version file
    version_text, raw_version = simple_get(f"{src_base_url}/stable")
    version = version_text.strip()  # Remove any newlines/whitespace
    simple_upload_content(raw_version, "stable")
    logger.info(f"version: {version}")

    # Download manifest.json
    manifest_text, raw_manifest = simple_get(f"{src_base_url}/{version}/manifest.json")
    manifest_json = json.loads(manifest_text)
    platforms = list(manifest_json["platforms"].keys())
    simple_upload_content(raw_manifest, f"{version}/manifest.json")
    logger.info(f"platforms: {platforms}")

    # Download and upload binaries for each platform
    for platform in platforms:
        binary_name = "claude.exe" if platform.startswith("win") else "claude"
        src_url = f"{src_base_url}/{version}/{platform}/{binary_name}"
        dst_key = f"{version}/{platform}/{binary_name}"
        logger.info(f"downloading {src_url}...")
        simple_download_and_upload(src_url, dst_key)
        logger.info(f"uploaded {dst_key}")

    logger.info("All files replicated successfully!")


if __name__ == "__main__":
    main()
