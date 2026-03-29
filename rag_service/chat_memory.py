"""Chat memory operations matching n8n's Postgres Chat Memory behavior."""
import json
import time
from typing import List, Dict, Any
import asyncpg


# SQL to create table matching n8n's schema (n8n doesn't have created_at column)
CREATE_CHAT_MEMORY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chat_history (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    message JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_id ON chat_history(session_id);
"""


async def ensure_chat_memory_table(pool: asyncpg.Pool) -> None:
    """Create the chat memory table if it doesn't exist."""
    async with pool.acquire() as conn:
        await conn.execute(CREATE_CHAT_MEMORY_TABLE_SQL)


async def get_chat_history(
    pool: asyncpg.Pool, 
    session_id: str, 
    limit: int = 20
) -> tuple[List[Dict[str, Any]], float]:
    """
    Retrieve chat history for a session.
    
    Returns:
        Tuple of (messages list, read_time_ms)
    """
    start_time = time.monotonic()
    
    if not session_id:
        return [], 0.0
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT message 
            FROM chat_history 
            WHERE session_id = $1 
            ORDER BY id ASC 
            LIMIT $2
            """,
            session_id,
            limit
        )
    
    messages = []
    for row in rows:
        msg = row["message"]
        if isinstance(msg, str):
            try:
                msg = json.loads(msg)
            except json.JSONDecodeError:
                continue
        messages.append(msg)
    
    read_time_ms = (time.monotonic() - start_time) * 1000
    return messages, read_time_ms


async def save_chat_message(
    pool: asyncpg.Pool,
    session_id: str,
    role: str,
    content: str,
    additional_data: Dict[str, Any] = None
) -> float:
    """
    Save a message to chat history.
    
    Args:
        pool: Database connection pool
        session_id: Session identifier
        role: 'human' or 'ai'
        content: Message content
        additional_data: Optional additional fields (tool_calls, metadata, etc.)
    
    Returns:
        write_time_ms: Time taken to write in milliseconds
    """
    start_time = time.monotonic()
    
    if not session_id:
        return 0.0
    
    # Build message in n8n/LangChain format
    message = {
        "type": role,
        "content": content,
    }
    
    if additional_data:
        message.update(additional_data)
    
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO chat_history (session_id, message)
            VALUES ($1, $2::jsonb)
            """,
            session_id,
            json.dumps(message)
        )
    
    write_time_ms = (time.monotonic() - start_time) * 1000
    return write_time_ms


def format_history_for_llm(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Convert n8n chat history format to OpenAI message format.
    
    n8n uses: {"type": "human"/"ai", "content": "..."}
    OpenAI uses: {"role": "user"/"assistant", "content": "..."}
    """
    formatted = []
    for msg in messages:
        role = msg.get("type", "")
        content = msg.get("content", "")
        
        # Map n8n types to OpenAI roles
        if role == "human":
            formatted.append({"role": "user", "content": content})
        elif role == "ai":
            formatted.append({"role": "assistant", "content": content})
        # Skip system messages as they'll be handled separately
    
    return formatted


def format_history_as_text(messages: List[Dict[str, Any]]) -> str:
    """
    Format chat history as a text block for inclusion in prompt.
    Alternative to passing as message list.
    """
    if not messages:
        return ""
    
    lines = []
    for msg in messages:
        role = msg.get("type", "")
        content = msg.get("content", "")
        
        if role == "human":
            lines.append(f"User: {content}")
        elif role == "ai":
            lines.append(f"Assistant: {content}")
    
    return "\n\n".join(lines)
