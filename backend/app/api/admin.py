import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Annotated, Optional

# Ensure scripts directory is importable for re-ingestion
_scripts_path = str(Path(__file__).resolve().parent.parent.parent.parent / "scripts")
if _scripts_path not in sys.path:
    sys.path.insert(0, _scripts_path)
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, Query
from pydantic import BaseModel

from app.services.llm.groq_service import get_groq_service

from app.auth import get_current_admin
from app.config import settings
from app.limiter import limiter
from app.services.backup import BackupService
from app.services.document_processor import DocumentProcessor
from ingest_knowledge_base import ingest_kb

logger = logging.getLogger(__name__)
router = APIRouter()

document_processor = DocumentProcessor(settings.upload_dir)
backup_service = BackupService()


@router.post("/upload")
@limiter.limit("5/minute")
async def upload_files(
    request: Request,
    files: Annotated[list[UploadFile], File(...)],
    current_user: Annotated[str, Depends(get_current_admin)],
    background_tasks: BackgroundTasks = None,
):
    """
    Upload files to the server and process them in the background.
    """
    uploaded_files = []

    os.makedirs(settings.upload_dir, exist_ok=True)

    for file in files:
        file_path = os.path.join(settings.upload_dir, file.filename)
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            uploaded_files.append(file.filename)
        except Exception as e:
            logger.error(f"Error saving file {file.filename}: {e}")

    # Trigger processing in background
    if background_tasks:
        background_tasks.add_task(process_and_index_files, uploaded_files)

    return {
        "message": f"Successfully uploaded {len(uploaded_files)} files",
        "files": uploaded_files,
    }


@router.get("/files")
async def list_files(current_user: str = Depends(get_current_admin)):
    """
    List uploaded files with processing status.
    """
    try:
        if not os.path.exists(settings.upload_dir):
            return {"files": []}

        files = os.listdir(settings.upload_dir)
        file_list = []

        # Load existing documents to check which files have been processed
        storage_file = Path(settings.db_dir) / "documents.json"
        processed_sources = set()

        if storage_file.exists():
            try:
                with open(storage_file, encoding="utf-8") as f:
                    all_documents = json.load(f)
                    processed_sources = {doc["source"] for doc in all_documents}
            except Exception as e:
                logger.error(f"Error loading existing documents: {e}")

        for f in files:
            file_path = os.path.join(settings.upload_dir, f)
            file_info = {
                "filename": f,
                "size": os.path.getsize(file_path),
                "processed": f in processed_sources,
                "uploaded_at": os.path.getmtime(file_path),
            }
            file_list.append(file_info)

        return {"files": file_list}
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


async def process_and_index_files(filenames: list[str]):
    """
    Process uploaded files and update the index.
    """
    all_documents = []

    # Load existing documents if any
    storage_file = Path(settings.db_dir) / "documents.json"

    # Create directory if not exists
    os.makedirs(settings.db_dir, exist_ok=True)

    if storage_file.exists():
        try:
            with open(storage_file, encoding="utf-8") as f:
                all_documents = json.load(f)
        except Exception as e:
            logger.error(f"Error loading existing documents: {e}")

    # Process new files
    new_docs = []
    for filename in filenames:
        file_path = os.path.join(settings.upload_dir, filename)
        try:
            docs = await document_processor.process_file(file_path)
            new_docs.extend(docs)
            logger.info(f"Processed {filename}: {len(docs)} chunks")
        except Exception as e:
            logger.error(f"Error processing {filename}: {e}")

    # Remove old documents from the same source to avoid duplicates
    # (Simple logic: if we re-upload a file, we replace its chunks)
    processed_sources = {doc["source"] for doc in new_docs}
    all_documents = [doc for doc in all_documents if doc.get("source") not in processed_sources]

    # Add new documents
    all_documents.extend(new_docs)

    # Save updated documents
    try:
        with open(storage_file, "w", encoding="utf-8") as f:
            json.dump(all_documents, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(all_documents)} documents to {storage_file}")

    except Exception as e:
        logger.error(f"Error saving documents: {e}")


# ==========================================
# Backup Endpoints
# ==========================================


@router.post("/backup/create")
@limiter.limit("5/minute")
async def create_backup(request: Request, current_user: str = Depends(get_current_admin)):
    """Create a new backup"""
    try:
        result = backup_service.create_backup()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/backups")
async def list_backups(current_user: str = Depends(get_current_admin)):
    """List available backups"""
    try:
        return backup_service.list_backups()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/backup/{filename}")
async def delete_backup(filename: str, current_user: str = Depends(get_current_admin)):
    """Delete a backup"""
    if backup_service.delete_backup(filename):
        return {"message": "Backup deleted"}
    raise HTTPException(status_code=404, detail="Backup not found")


# ==========================================
# Knowledge Base FAQ Management
# ==========================================

KB_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "knowledge_base" / "combined_kb.json"
)


def _load_kb() -> dict:
    with open(KB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_kb(kb: dict):
    with open(KB_PATH, "w", encoding="utf-8") as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)


@router.get("/kb/faq")
async def list_faq_entries(current_user: str = Depends(get_current_admin)):
    """List all FAQ entries in voice_ready_answers."""
    kb = _load_kb()
    vra = kb.get("voice_ready_answers", {})
    entries = []
    for key, entry in vra.items():
        entries.append(
            {
                "key": key,
                "keywords": entry.get("keywords", []),
                "languages": list(entry.get("answers", {}).keys()) if "answers" in entry else [],
                "has_sub_answers": "sub_answers" in entry,
            }
        )
    return {"entries": entries, "total": len(entries)}


class FAQEntryIn(BaseModel):
    keywords: list[str]
    answers: dict[str, str] = {}
    sub_answers: dict[str, dict] = {}


@router.post("/kb/faq/{key}")
@limiter.limit("10/minute")
async def add_or_update_faq(
    request: Request,
    key: str,
    entry: FAQEntryIn,
    current_user: str = Depends(get_current_admin),
):
    """Add or update a FAQ entry in voice_ready_answers. Reloads KB immediately."""
    kb = _load_kb()
    if "voice_ready_answers" not in kb:
        kb["voice_ready_answers"] = {}
    new_entry = {"keywords": entry.keywords}
    if entry.answers:
        new_entry["answers"] = entry.answers
    if entry.sub_answers:
        new_entry["sub_answers"] = entry.sub_answers
    kb["voice_ready_answers"][key] = new_entry
    _save_kb(kb)
    count = get_groq_service().reload_kb()
    return {"message": f"FAQ entry '{key}' saved and KB reloaded", "key": key, "faq_count": count}


@router.delete("/kb/faq/{key}")
@limiter.limit("10/minute")
async def delete_faq(request: Request, key: str, current_user: str = Depends(get_current_admin)):
    """Delete a FAQ entry from voice_ready_answers. Reloads KB immediately."""
    kb = _load_kb()
    vra = kb.get("voice_ready_answers", {})
    if key not in vra:
        raise HTTPException(status_code=404, detail=f"FAQ entry '{key}' not found")
    del vra[key]
    kb["voice_ready_answers"] = vra
    _save_kb(kb)
    count = get_groq_service().reload_kb()
    return {"message": f"FAQ entry '{key}' deleted and KB reloaded", "faq_count": count}


@router.post("/kb/reload")
@limiter.limit("5/minute")
async def reload_kb(request: Request, current_user: str = Depends(get_current_admin)):
    """Force-reload the KB from disk (no service restart needed)."""
    count = get_groq_service().reload_kb()
    return {"message": "KB reloaded", "faq_count": count}


@router.post("/cache/invalidate")
@limiter.limit("5/minute")
async def invalidate_cache(request: Request, current_user: str = Depends(get_current_admin)):
    """Clear the in-memory query cache."""
    cleared = get_groq_service().invalidate_cache()
    return {"message": "Query cache invalidated", "entries_cleared": cleared}


@router.get("/cache/stats")
async def cache_stats(current_user: str = Depends(get_current_admin)):
    """Show query cache hit/miss stats."""
    stats = get_groq_service().get_cache_stats()
    return stats


@router.post("/kb/update-anchor")
@limiter.limit("10/minute")
async def update_semantic_anchor(
    request: Request,
    section: str = Query(...),
    subsection: Optional[str] = Query(None),
    new_anchor: str = Query(...),
    current_user: str = Depends(get_current_admin),
):
    """Update semantic anchor for a KB entry and trigger re-ingestion."""
    kb = _load_kb()
    vra = kb.get("voice_ready_answers", {})
    if section not in vra:
        raise HTTPException(status_code=404, detail=f"Section '{section}' not found")
    if subsection:
        if subsection not in vra[section]:
            raise HTTPException(
                status_code=404, detail=f"Subsection '{subsection}' not found in '{section}'"
            )
        vra[section][subsection]["semantic_anchor"] = new_anchor
    else:
        vra[section]["semantic_anchor"] = new_anchor
    _save_kb(kb)
    await ingest_kb()
    return {
        "status": "success",
        "message": f"Updated anchor for {section}/{subsection or ''}: {new_anchor}",
    }
