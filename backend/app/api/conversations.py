from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Dict, Any
from datetime import datetime, UTC
import uuid

from app.database import get_db

router = APIRouter()


# Models
class CreateConversationResponse(BaseModel):
    id: str
    title: str
    created_at: str


class Message(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str


class ConversationWithMessages(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    messages: List[Dict[str, Any]]


class ConversationListItem(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class AddMessageRequest(BaseModel):
    role: str
    content: str


class UpdateTitleRequest(BaseModel):
    title: str


# Endpoints
@router.post("/conversations", response_model=CreateConversationResponse)
async def create_conversation():
    """Create a new conversation"""
    conn = get_db()
    cursor = conn.cursor()
    
    conv_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    
    cursor.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (conv_id, "New Chat", now, now)
    )
    
    conn.commit()
    conn.close()
    
    return CreateConversationResponse(
        id=conv_id,
        title="New Chat",
        created_at=now
    )


@router.get("/conversations", response_model=List[ConversationListItem])
async def list_conversations():
    """List all conversations"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) as message_count
        FROM conversations c
        LEFT JOIN messages m ON c.id = m.conversation_id
        GROUP BY c.id
        ORDER BY c.updated_at DESC
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    return [
        ConversationListItem(
            id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            message_count=row["message_count"]
        )
        for row in rows
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationWithMessages)
async def get_conversation(conversation_id: str):
    """Get a conversation with all messages"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
        (conversation_id,)
    )
    conv = cursor.fetchone()
    
    if not conv:
        conn.close()
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    cursor.execute(
        "SELECT id, conversation_id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
        (conversation_id,)
    )
    messages = cursor.fetchall()
    conn.close()
    
    return ConversationWithMessages(
        id=conv["id"],
        title=conv["title"],
        created_at=conv["created_at"],
        updated_at=conv["updated_at"],
        messages=[
            {
                "id": m["id"],
                "role": m["role"],
                "content": m["content"],
                "created_at": m["created_at"]
            }
            for m in messages
        ]
    )


@router.get("/conversations/{conversation_id}/messages", response_model=List[Message])
async def get_conversation_messages(conversation_id: str, limit: int = 10):
    """Get recent messages from a conversation"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute(
        """SELECT id, conversation_id, role, content, created_at 
           FROM messages 
           WHERE conversation_id = ? 
           ORDER BY created_at DESC 
           LIMIT ?""",
        (conversation_id, limit)
    )
    messages = cursor.fetchall()
    conn.close()
    
    # Return in chronological order (oldest first)
    return list(reversed([
        Message(
            id=m["id"],
            conversation_id=m["conversation_id"],
            role=m["role"],
            content=m["content"],
            created_at=m["created_at"]
        )
        for m in messages
    ]))


@router.post("/conversations/{conversation_id}/messages")
async def add_message(conversation_id: str, request: AddMessageRequest):
    """Add a message to a conversation"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Check conversation exists
    cursor.execute("SELECT id FROM conversations WHERE id = ?", (conversation_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    msg_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    
    cursor.execute(
        "INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (msg_id, conversation_id, request.role, request.content, now)
    )
    
    # Update conversation timestamp
    cursor.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (now, conversation_id)
    )
    
    conn.commit()
    conn.close()
    
    return Message(
        id=msg_id,
        conversation_id=conversation_id,
        role=request.role,
        content=request.content,
        created_at=now
    )


@router.patch("/conversations/{conversation_id}")
async def update_conversation_title(conversation_id: str, request: UpdateTitleRequest):
    """Update conversation title"""
    conn = get_db()
    cursor = conn.cursor()
    
    now = datetime.now(UTC).isoformat()
    
    cursor.execute(
        "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
        (request.title, now, conversation_id)
    )
    
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conn.commit()
    conn.close()
    
    return {"status": "ok", "title": request.title}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a conversation and all its messages"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Delete messages first
    cursor.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    
    # Delete conversation
    cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conn.commit()
    conn.close()
    
    return {"status": "deleted"}


@router.delete("/conversations")
async def delete_all_conversations():
    """Delete all conversations (for privacy/reset)"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM messages")
    cursor.execute("DELETE FROM conversations")
    
    conn.commit()
    conn.close()
    
    return {"status": "all deleted"}


