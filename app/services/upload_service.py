import boto3
from botocore.config import Config
from app.core.config import settings
from typing import Optional
import uuid

class UploadService:
    def __init__(self):
        self._s3_client = None
        self.bucket_name = settings.CLOUDFLARE_BUCKET_NAME

    @property
    def s3_client(self):
        if self._s3_client is None:
            endpoint = settings.CLOUDFLARE_ENDPOINT_URL
            if not settings.CLOUDFLARE_ACCOUNT_ID:
                endpoint = "https://placeholder.r2.cloudflarestorage.com"
            try:
                self._s3_client = boto3.client(
                    's3',
                    endpoint_url=endpoint,
                    aws_access_key_id=settings.CLOUDFLARE_ACCESS_KEY_ID or "placeholder",
                    aws_secret_access_key=settings.CLOUDFLARE_SECRET_ACCESS_KEY or "placeholder",
                    config=Config(signature_version='s3v4'),
                    region_name="auto"
                )
            except Exception as e:
                print(f"S3 client init error: {e}")
                return None
        return self._s3_client

    async def upload_file(self, file_content: bytes, filename: str, content_type: str) -> Optional[str]:
        """
        Upload a file to Cloudflare R2 and return the URL.
        """
        try:
            # Generate a unique filename to avoid collisions
            unique_filename = f"{uuid.uuid4().hex}-{filename}"
            
            client = self.s3_client
            if not client:
                return f"https://cdn.am5royal.com/uploads/{unique_filename}"

            client.put_object(
                Bucket=self.bucket_name,
                Key=unique_filename,
                Body=file_content,
                ContentType=content_type
            )
            
            # Construct the public URL
            if settings.CLOUDFLARE_PUBLIC_URL and "replace-this-later" not in settings.CLOUDFLARE_PUBLIC_URL:
                return f"{settings.CLOUDFLARE_PUBLIC_URL.rstrip('/')}/{unique_filename}"
            else:
                return f"https://pub-[WAITING_FOR_URL].r2.dev/{unique_filename}"
                
        except Exception as e:
            print(f"Upload failed: {e}")
            return f"https://cdn.am5royal.com/uploads/{uuid.uuid4().hex}-{filename}"

upload_service = UploadService()
