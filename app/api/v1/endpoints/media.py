import io
from PIL import Image, ImageOps
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.vendor_media import VendorMedia
from app.services.upload_service import upload_service
from app.dependencies.auth import get_current_vendor

router = APIRouter()

def compress_image_bytes(contents: bytes, filename: str, content_type: str) -> tuple[bytes, str, str]:
    """Compress image files (JPEG, PNG, WebP) to JPEG format with max size 1600x1600 and quality 80."""
    try:
        image = Image.open(io.BytesIO(contents))
        image = ImageOps.exif_transpose(image)

        # Convert to RGB if RGBA or P mode
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")

        # Resize if larger than 1600x1600 while maintaining aspect ratio
        max_dim = 1600
        if image.width > max_dim or image.height > max_dim:
            image.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        out_io = io.BytesIO()
        image.save(out_io, format="JPEG", quality=80, optimize=True)
        compressed_bytes = out_io.getvalue()

        # Update extension to .jpg
        base_name = filename.rsplit(".", 1)[0] if "." in filename else filename
        new_filename = f"{base_name}.jpg"
        return compressed_bytes, new_filename, "image/jpeg"
    except Exception as e:
        # Fallback to original contents if compression fails
        return contents, filename, content_type

@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    # Require authentication (e.g., must be a vendor)
    vendor = Depends(get_current_vendor),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload an image or video to Cloudflare R2 and return the URL and media type.
    Images are compressed on-the-fly to optimize speed and storage.
    """
    content_type = file.content_type or "image/jpeg"
    filename = file.filename or "camera_upload.jpg"

    if not (content_type.startswith("image/") or content_type.startswith("video/")):
        content_type = "image/jpeg"
        filename = f"{filename.split('.')[0]}.jpg" if '.' in filename else f"{filename}.jpg"

    contents = await file.read()

    if content_type.startswith("image/"):
        contents, filename, content_type = compress_image_bytes(contents, filename, content_type)

    url = await upload_service.upload_file(contents, filename, content_type)
    
    if not url:
        raise HTTPException(status_code=500, detail="Failed to upload file")
        
    media_type = "image" if content_type.startswith("image/") else "video"
    # Record the upload so category APIs can reference it by id (ownership + type checks).
    record = VendorMedia(vendor_id=vendor.id, media_type=media_type, url=url)
    db.add(record)
    await db.flush()
    return {"url": url, "media_type": media_type, "media_id": record.id}
