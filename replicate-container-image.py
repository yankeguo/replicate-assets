#!/usr/bin/env -S uv run --script

# /// script
# dependencies = ["requests", "python-dotenv"]
# ///

import logging
import os
import subprocess
import sys
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

REGISTRY_USERNAME = os.getenv("REGISTRY_USERNAME")
REGISTRY_PASSWORD = os.getenv("REGISTRY_PASSWORD")
REGISTRY_BASE_URL = os.getenv("REGISTRY_BASE_URL", "").rstrip("/")

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)


def parse_image(image: str) -> tuple[str, str, str]:
    """
    Parse Docker image reference into (org, name, tag).
    Handles formats like:
    - docker.io/library/name:tag
    - docker.io/org/name:tag
    - org/name:tag
    - name:tag
    - name (defaults to latest tag)
    """
    # Remove docker.io or docker.io/library prefix
    image = image.replace("docker.io/library/", "").replace("docker.io/", "")

    # Split tag
    if ":" in image:
        image_part, tag = image.rsplit(":", 1)
    else:
        image_part = image
        tag = "latest"

    # Split org and name
    parts = image_part.split("/")
    if len(parts) == 1:
        # No org, default to library
        org = "library"
        name = parts[0]
    elif len(parts) == 2:
        org, name = parts
    else:
        # Multiple slashes, treat first as org, rest as name
        org = parts[0]
        name = "/".join(parts[1:])

    return org, name, tag


def build_target_image(org: str, name: str, tag: str) -> str:
    """Build target image name: REGISTRY_BASE_URL/[ORG]-[NAME]:[TAG]"""
    return f"{REGISTRY_BASE_URL}/{org}-{name}:{tag}"


def docker_login(username: str, password: str, registry: str) -> None:
    """Login to Docker registry."""
    logger.info(f"Logging in to {registry}...")
    cmd = [
        "docker",
        "login",
        "-u",
        username,
        "--password-stdin",
        registry,
    ]
    result = subprocess.run(cmd, input=password, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker login failed: {result.stderr}")
    logger.info("Login successful")


def docker_pull(image: str) -> None:
    """Pull Docker image with platform linux/amd64."""
    logger.info(f"Pulling {image}...")
    cmd = [
        "docker",
        "pull",
        "--platform",
        "linux/amd64",
        image,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker pull failed: {result.stderr}")
    logger.info(f"Pulled {image} successfully")


def docker_tag(source: str, target: str) -> None:
    """Tag Docker image."""
    logger.info(f"Tagging {source} as {target}...")
    cmd = ["docker", "tag", source, target]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker tag failed: {result.stderr}")
    logger.info(f"Tagged {source} as {target}")


def docker_push(image: str) -> None:
    """Push Docker image."""
    logger.info(f"Pushing {image}...")
    cmd = ["docker", "push", image]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker push failed: {result.stderr}")
    logger.info(f"Pushed {image} successfully")


def fetch_images_from_url(url: str) -> list[str]:
    """Fetch URL and parse each line as an image."""
    logger.info(f"Fetching images from {url}...")
    response = requests.get(url)
    response.raise_for_status()
    images = []
    for line in response.text.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            images.append(line)
    logger.info(f"Found {len(images)} images from URL")
    return images


def replicate_image(source_image: str) -> None:
    """Replicate a single image: pull, tag, and push."""
    logger.info(f"Processing image: {source_image}")

    # Parse source image
    org, name, tag = parse_image(source_image)
    target_image = build_target_image(org, name, tag)

    logger.info(f"Source: {source_image}")
    logger.info(f"Target: {target_image}")

    # Pull source image
    docker_pull(source_image)

    # Tag image
    docker_tag(source_image, target_image)

    # Push target image
    docker_push(target_image)

    logger.info(f"Successfully replicated {source_image} -> {target_image}")


def main():
    # Validate required environment variables
    if not REGISTRY_USERNAME or not REGISTRY_PASSWORD or not REGISTRY_BASE_URL:
        raise ValueError(
            "Missing required environment variables: REGISTRY_USERNAME, REGISTRY_PASSWORD, REGISTRY_BASE_URL"
        )

    # Extract registry host from REGISTRY_BASE_URL for login
    parsed = urlparse(REGISTRY_BASE_URL)
    registry_host = parsed.netloc or parsed.path.split("/")[0]

    # Login to registry
    docker_login(REGISTRY_USERNAME, REGISTRY_PASSWORD, registry_host)

    # Parse arguments
    images = []
    for arg in sys.argv[1:]:
        if arg.startswith("https://"):
            # Fetch images from URL
            images.extend(fetch_images_from_url(arg))
        else:
            # Treat as direct image reference
            images.append(arg)

    if not images:
        raise ValueError(
            "No images provided. Provide image names or URLs as arguments."
        )

    # Replicate each image
    for image in images:
        try:
            replicate_image(image)
        except Exception as e:
            logger.error(f"Failed to replicate {image}: {e}")
            raise

    logger.info("All images replicated successfully!")


if __name__ == "__main__":
    main()
