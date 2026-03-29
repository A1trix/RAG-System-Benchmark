from . import db
from .vector_store import delete_by_file_id


async def delete_document(file_id: str, settings, pool):
    await delete_by_file_id(pool, settings.pgvector_table, file_id)
    await db.execute(pool, f"DELETE FROM {settings.document_rows_table} WHERE dataset_id LIKE '%' || $1 || '%';", file_id)
    await db.execute(pool, f"DELETE FROM {settings.document_metadata_table} WHERE id = $1;", file_id)
