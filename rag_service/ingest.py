import json
import logging
from pathlib import Path
from typing import Any

import pdfplumber
import pandas as pd
from docx import Document
from pdfminer.high_level import extract_text as pdfminer_extract_text
import subprocess
import tempfile
import pytesseract
from pdf2image import convert_from_path

from .chunker import chunk_text
from .embeddings import EmbeddingClient
from .vector_store import upsert_chunks, delete_by_file_id, ensure_table
from . import db


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def read_pdf(path: Path) -> str:
    logger = logging.getLogger(__name__)

    # Strategy 1: pdfplumber default
    try:
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n".join(pages).strip()
        if text:
            return text
    except Exception as exc:  # pragma: no cover
        logger.warning("pdfplumber failed on %s: %s", path, exc)

    # Strategy 2: pdfplumber with tighter tolerances
    try:
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text(x_tolerance=1, y_tolerance=1) or "" for page in pdf.pages]
        text = "\n".join(pages).strip()
        if text:
            return text
    except Exception as exc:  # pragma: no cover
        logger.warning("pdfplumber (tight) failed on %s: %s", path, exc)

    # Strategy 3: pdfminer.six
    try:
        text = pdfminer_extract_text(str(path)) or ""
        text = text.strip()
        if text:
            return text
    except Exception as exc:  # pragma: no cover
        logger.warning("pdfminer extract_text failed on %s: %s", path, exc)

    # Strategy 4: poppler pdftotext (if installed)
    try:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            out_path = tmp.name
        result = subprocess.run(
            ["pdftotext", "-layout", str(path), out_path],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            txt = Path(out_path).read_text(encoding="utf-8", errors="ignore").strip()
            Path(out_path).unlink(missing_ok=True)
            if txt:
                return txt
        else:
            logger.warning("pdftotext failed on %s: %s", path, result.stderr)
    except Exception as exc:  # pragma: no cover
        logger.warning("pdftotext exception on %s: %s", path, exc)

    # Strategy 5: OCR fallback via Tesseract + pdf2image
    try:
        images = convert_from_path(str(path))
        ocr_texts = []
        for img in images:
            ocr_texts.append(pytesseract.image_to_string(img))
        ocr_text = "\n".join(ocr_texts).strip()
        if ocr_text:
            logger.info("OCR extracted %d chars for %s", len(ocr_text), path)
            return ocr_text
    except Exception as exc:  # pragma: no cover
        logger.warning("OCR fallback failed on %s: %s", path, exc)

    # If all attempts fail, return empty
    return ""


def read_docx(path: Path) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


def load_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path)


async def persist_metadata(pool, table: str, file_id: str, title: str | None, url: str | None, schema: list[str] | None):
    cols = {"id": file_id, "title": title or file_id, "url": url, "schema": json.dumps(schema) if schema else None}
    await db.execute(
        pool,
        f"""
        INSERT INTO {table} (id, title, url, schema)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, url = EXCLUDED.url, schema = EXCLUDED.schema;
        """,
        cols["id"],
        cols["title"],
        cols["url"],
        cols["schema"],
    )


async def persist_rows(pool, table: str, file_id: str, rows: list[dict[str, Any]]):
    if not rows:
        return
    async with pool.acquire() as conn:
        async with conn.transaction():
            for row in rows:
                await conn.execute(
                    f"INSERT INTO {table} (dataset_id, row_data) VALUES ($1, $2)",
                    file_id,
                    json.dumps(row),
                )


async def ingest_document(request, settings, pool):
    logger = logging.getLogger(__name__)
    logger.info("Ingest start file_id=%s path=%s", request.file_id, request.path or "(none)")
    await ensure_table(pool, settings.pgvector_table)
    await delete_by_file_id(pool, settings.pgvector_table, request.file_id)
    await db.execute(
        pool,
        f"DELETE FROM {settings.document_rows_table} WHERE dataset_id LIKE '%' || $1 || '%';",
        request.file_id,
    )

    text_content = request.content or ""
    schema = request.doc_schema
    rows: list[dict[str, Any]] = request.rows or []

    resolved_url = request.url

    if request.path:
        path = Path(request.path)
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        resolved_url = str(path)
        if path.suffix.lower() in {".csv", ".xlsx", ".xls"}:
            df = load_table(path)
            rows = df.to_dict(orient="records")
            schema = list(df.columns)
            text_content = "\n".join(df.astype(str).agg(" ".join, axis=1).tolist())
        elif path.suffix.lower() == ".pdf":
            text_content = read_pdf(path)
        elif path.suffix.lower() in {".docx"}:
            text_content = read_docx(path)
        else:
            text_content = read_text_file(path)

    if rows:
        await persist_rows(pool, settings.document_rows_table, request.file_id, rows)
        logger.info("Persisted %d tabular rows for %s", len(rows), request.file_id)

    await persist_metadata(pool, settings.document_metadata_table, request.file_id, request.title, resolved_url, schema)

    if not text_content:
        logger.info("No text extracted for %s; skipping embeddings", request.file_id)
        return

    embedder = EmbeddingClient(api_key=settings.openai_api_key, model=settings.embedding_model, base_url=settings.openai_base_url)
    chunks = chunk_text(text_content, settings.chunk_size, settings.chunk_overlap)
    logger.info("Embedding %d chunks for %s", len(chunks), request.file_id)
    embeddings = await embedder.embed(chunks)
    metadata = {"file_id": request.file_id, "file_title": request.title or request.file_id, "url": resolved_url}
    await upsert_chunks(pool, settings.pgvector_table, chunks, embeddings, metadata)
    logger.info("Inserted %d vector rows for %s", len(chunks), request.file_id)
