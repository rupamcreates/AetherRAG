import os
import logging
from abc import ABC, abstractmethod
import requests
from app.core.config import settings

logger = logging.getLogger(__name__)

class BaseStorage(ABC):
    @abstractmethod
    def upload_file(self, file_content: bytes, filename: str) -> str:
        """Uploads file content and returns the unique storage path/identifier."""
        pass

    @abstractmethod
    def download_file(self, storage_path: str, local_destination: str) -> str:
        """Downloads the file from storage and saves it to local_destination."""
        pass

    @abstractmethod
    def delete_file(self, storage_path: str) -> None:
        """Deletes the file from storage."""
        pass

class LocalStorage(BaseStorage):
    def __init__(self):
        self.storage_dir = settings.LOCAL_STORAGE_DIR
        os.makedirs(self.storage_dir, exist_ok=True)
        logger.info(f"Using local storage directory: {self.storage_dir}")

    def upload_file(self, file_content: bytes, filename: str) -> str:
        # Generate a unique filename using subfolders if necessary
        # Simply using the filename or appending a timestamp
        unique_name = f"{filename}"
        dest_path = os.path.join(self.storage_dir, unique_name)
        
        # Ensure parent dirs exist
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        with open(dest_path, "wb") as f:
            f.write(file_content)
        
        logger.info(f"Uploaded file to local storage: {dest_path}")
        return unique_name

    def download_file(self, storage_path: str, local_destination: str) -> str:
        source_path = os.path.join(self.storage_dir, storage_path)
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Local storage file not found: {source_path}")
        
        os.makedirs(os.path.dirname(local_destination), exist_ok=True)
        with open(source_path, "rb") as src, open(local_destination, "wb") as dest:
            dest.write(src.read())
            
        logger.info(f"Downloaded local storage file from {source_path} to {local_destination}")
        return local_destination

    def delete_file(self, storage_path: str) -> None:
        source_path = os.path.join(self.storage_dir, storage_path)
        if os.path.exists(source_path):
            os.remove(source_path)
            logger.info(f"Deleted local file: {source_path}")

class SupabaseStorage(BaseStorage):
    def __init__(self):
        self.supabase_url = settings.SUPABASE_URL
        self.service_role_key = settings.SUPABASE_SERVICE_ROLE_KEY
        self.bucket = settings.STORAGE_BUCKET_NAME
        
        if not self.supabase_url or not self.service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set for Supabase storage provider.")
            
        self.base_api_url = f"{self.supabase_url.rstrip('/')}/storage/v1/object/{self.bucket}"
        self.headers = {
            "Authorization": f"Bearer {self.service_role_key}",
        }

    def upload_file(self, file_content: bytes, filename: str) -> str:
        # Uploading to Supabase Storage endpoint
        # URL format: BASE_URL/filename
        upload_url = f"{self.base_api_url}/{filename}"
        
        # We need to set Content-Type header dynamically or fallback to octet-stream
        headers = self.headers.copy()
        headers["Content-Type"] = "application/octet-stream"
        
        logger.info(f"Uploading file to Supabase Storage: {filename}")
        response = requests.post(upload_url, headers=headers, data=file_content, timeout=60)
        
        if response.status_code == 200 or response.status_code == 201:
            logger.info(f"Successfully uploaded {filename} to Supabase Storage.")
            return filename
        else:
            logger.error(f"Failed to upload to Supabase Storage: {response.status_code} - {response.text}")
            response.raise_for_status()

    def download_file(self, storage_path: str, local_destination: str) -> str:
        # Download authenticated object
        # URL format: BASE_URL/storage_path
        download_url = f"{self.base_api_url}/{storage_path}"
        
        logger.info(f"Downloading file from Supabase Storage: {storage_path}")
        response = requests.get(download_url, headers=self.headers, stream=True, timeout=60)
        
        if response.status_code == 200:
            os.makedirs(os.path.dirname(local_destination), exist_ok=True)
            with open(local_destination, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Successfully downloaded Supabase file to {local_destination}")
            return local_destination
        else:
            logger.error(f"Failed to download from Supabase Storage: {response.status_code} - {response.text}")
            response.raise_for_status()

    def delete_file(self, storage_path: str) -> None:
        url = f"{self.base_api_url}/{storage_path}"
        logger.info(f"Deleting file from Supabase Storage: {storage_path}")
        response = requests.delete(url, headers=self.headers, timeout=30)
        if response.status_code != 200:
            logger.warning(f"Failed to delete file from Supabase Storage: {response.status_code} - {response.text}")


class StorageService:
    _instance: BaseStorage = None

    @classmethod
    def get_storage(cls) -> BaseStorage:
        if cls._instance is None:
            provider = settings.STORAGE_PROVIDER.lower()
            if provider == "local":
                cls._instance = LocalStorage()
            elif provider == "supabase":
                cls._instance = SupabaseStorage()
            else:
                raise ValueError(f"Unknown storage provider: {provider}")
        return cls._instance
