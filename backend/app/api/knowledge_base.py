"""
Knowledge Base Management API

Provides a reindex endpoint so you never have to manually run
`python scripts/ingest_knowledge_base.py` again.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.documents import Document as LCDocument

from app.auth import get_current_admin
from app.services.document_processor import DocumentProcessor
from app.services.vector_store import get_vector_store

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/reindex")
async def reindex_knowledge_base(current_user: str = Depends(get_current_admin)):
    """
    Full re-index: clears ChromaDB, re-ingests all markdown files from
    knowledge_base/ and all uploaded files from uploads/.

    This replaces the manual `python scripts/ingest_knowledge_base.py` step.
    """
    vector_store = get_vector_store()
    doc_processor = DocumentProcessor()
    all_docs = []

    # Resolve paths relative to project root
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    kb_dir = project_root / "backend" / "data" / "knowledge_base"
    uploads_dir = project_root / "uploads"

    # 1. Clear existing collection
    logger.info("Reindex: Clearing existing vector store...")
    vector_store.clear_collection()

    # 2. Ingest markdown files from knowledge_base/
    markdown_dirs = [kb_dir / "departments", kb_dir / "topics"]
    for mdir in markdown_dirs:
        if not mdir.exists():
            continue

        logger.info(f"Reindex: Processing markdown files in {mdir}...")
        for md_file in mdir.glob("*.md"):
            try:
                chunks = await doc_processor.process_file(str(md_file))
                for chunk in chunks:
                    all_docs.append(
                        LCDocument(
                            page_content=chunk["text"],
                            metadata=chunk.get("metadata", {"source": md_file.name}),
                        )
                    )
            except Exception as e:
                logger.error(f"Error processing {md_file.name}: {e}")

    # 3. Ingest uploaded files from uploads/
    if uploads_dir.exists():
        logger.info(f"Reindex: Processing uploaded files in {uploads_dir}...")
        for upload_file in uploads_dir.iterdir():
            if upload_file.is_file() and upload_file.suffix.lower() in {
                ".pdf", ".txt", ".csv", ".xlsx", ".xls", ".md"
            }:
                try:
                    chunks = await doc_processor.process_file(str(upload_file))
                    for chunk in chunks:
                        all_docs.append(
                            LCDocument(
                                page_content=chunk["text"],
                                metadata=chunk.get("metadata", {"source": upload_file.name}),
                            )
                        )
                except Exception as e:
                    logger.error(f"Error processing upload {upload_file.name}: {e}")

    # 4. Add all documents to vector store
    if all_docs:
        batch_size = 50
        for i in range(0, len(all_docs), batch_size):
            batch = all_docs[i : i + batch_size]
            vector_store.add_documents(batch)
        logger.info(f"Reindex complete: {len(all_docs)} chunks indexed.")
    else:
        logger.warning("Reindex: No documents found to ingest!")

    return {
        "message": f"Reindex complete. {len(all_docs)} chunks indexed.",
        "chunks": len(all_docs),
    }
