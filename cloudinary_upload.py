from pathlib import Path

import requests


def upload_file(path: str, cloud_name: str, upload_preset: str, resource_type: str = "auto") -> str:
    """Upload a local file using Cloudinary's unsigned upload endpoint."""
    cloud_name = cloud_name.strip()
    upload_preset = upload_preset.strip()
    if not cloud_name or not upload_preset:
        raise RuntimeError("Cloudinary is not configured. Use /setcloudinary first.")

    endpoint = f"https://api.cloudinary.com/v1_1/{cloud_name}/{resource_type}/upload"
    with open(path, "rb") as media:
        response = requests.post(
            endpoint,
            data={"upload_preset": upload_preset},
            files={"file": (Path(path).name, media)},
            timeout=120,
        )
    response.raise_for_status()
    secure_url = response.json().get("secure_url")
    if not secure_url:
        raise RuntimeError("Cloudinary response did not include secure_url")
    return secure_url
