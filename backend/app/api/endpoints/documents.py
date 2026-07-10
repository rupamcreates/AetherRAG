import uuid
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.db.models import Document, DocumentChunk
from app.services.storage import StorageService
from app.worker.tasks import process_document_task
from pydantic import BaseModel
from datetime import datetime
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

class DocumentOut(BaseModel):
    id: uuid.UUID
    name: str
    file_type: str
    status: str
    error_message: str | None
    created_at: datetime
    
    class Config:
        from_attributes = True

class PresignOut(BaseModel):
    upload_url: str | None = None
    storage_path: str | None = None
    use_local_upload: bool = False

class RegisterIn(BaseModel):
    filename: str
    file_type: str
    storage_path: str

@router.get("/presign", response_model=PresignOut)
def generate_presigned_url(
    filename: str,
    file_type: str,
    user_id: str = Depends(get_current_user)
):
    # Generate a unique name for storage to prevent collisions
    unique_filename = f"{user_id}/{uuid.uuid4()}_{filename}"
    provider = settings.STORAGE_PROVIDER.lower()
    
    if provider in ("r2", "s3") and settings.CLOUDFLARE_ACCOUNT_ID and settings.R2_ACCESS_KEY_ID:
        try:
            import boto3
            from botocore.config import Config
            
            endpoint_url = f"https://{settings.CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"
            s3_client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=settings.R2_ACCESS_KEY_ID or settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY or settings.AWS_SECRET_ACCESS_KEY,
                config=Config(signature_version="s3v4"),
                region_name="us-east-1"
            )
            
            bucket = settings.R2_BUCKET_NAME or settings.STORAGE_BUCKET_NAME
            
            # Generate pre-signed PUT URL valid for 5 minutes (300 seconds)
            presigned_url = s3_client.generate_presigned_url(
                ClientMethod="put_object",
                Params={
                    "Bucket": bucket,
                    "Key": unique_filename,
                    "ContentType": file_type
                },
                ExpiresIn=300
            )
            return PresignOut(
                upload_url=presigned_url,
                storage_path=unique_filename,
                use_local_upload=False
            )
        except Exception as e:
            logger.error(f"Failed to generate R2 presigned URL: {e}")
            # Fallback to local upload endpoint on error
            return PresignOut(use_local_upload=True)
    else:
        # Fallback for local testing/offline provider
        return PresignOut(use_local_upload=True)

@router.post("/register", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def register_document(
    reg: RegisterIn,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    try:
        doc = Document(
            id=uuid.uuid4(),
            name=reg.filename,
            file_type=reg.file_type,
            storage_path=reg.storage_path,
            user_id=user_id,
            status="pending"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        
        # Trigger Celery background parsing task
        process_document_task.delay(str(doc.id))
        
        return doc
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {e}"
        )

@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    # Read file content
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    
    # Generate unique filename for storage (to avoid collision)
    unique_filename = f"{user_id}/{uuid.uuid4()}_{file.filename}"
    
    try:
        # Save to storage
        storage = StorageService.get_storage()
        storage.upload_file(content, unique_filename)
        
        # Create database entry
        doc = Document(
            id=uuid.uuid4(),
            name=file.filename,
            file_type=file.content_type or "application/octet-stream",
            storage_path=unique_filename,
            user_id=user_id,
            status="pending"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        
        # Trigger Celery background parsing task
        process_document_task.delay(str(doc.id))
        
        return doc
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {e}"
        )

@router.get("/", response_model=List[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    docs = db.query(Document).filter(Document.user_id == user_id).order_by(Document.created_at.desc()).all()
    return docs

@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    doc = db.query(Document).filter(Document.id == document_id, Document.user_id == user_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    doc = db.query(Document).filter(Document.id == document_id, Document.user_id == user_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
        
    try:
        # Delete from storage
        storage = StorageService.get_storage()
        storage.delete_file(doc.storage_path)
        
        # Delete from database (cascade deletes chunks too)
        db.delete(doc)
        db.commit()
        return
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deletion failed: {e}"
        )

from app.worker.celery_app import celery_app

class TaskStatusOut(BaseModel):
    task_id: str
    status: str
    result: str | None = None
    error: str | None = None

@router.get("/tasks/{task_id}", response_model=TaskStatusOut)
def get_task_status(
    task_id: str,
    user_id: str = Depends(get_current_user)
):
    try:
        task_result = celery_app.AsyncResult(task_id)
        error_msg = None
        if task_result.status == "FAILURE":
            error_msg = str(task_result.result)
        return TaskStatusOut(
            task_id=task_id,
            status=task_result.status,
            result=str(task_result.result) if task_result.status == "SUCCESS" else None,
            error=error_msg
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query task status: {e}"
        )
