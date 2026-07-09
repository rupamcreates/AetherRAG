import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.db.models import Document, DocumentChunk
from app.services.storage import StorageService
from app.worker.tasks import process_document_task
from pydantic import BaseModel
from datetime import datetime

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
