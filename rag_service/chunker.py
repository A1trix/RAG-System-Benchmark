from collections.abc import Iterable


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0:
        return [text]
    if overlap >= chunk_size:
        overlap = max(chunk_size // 4, 0)
    clean = " ".join(text.split())
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + chunk_size)
        chunks.append(clean[start:end])
        if end == len(clean):
            break
        start = end - overlap
    return chunks


def flatten(items: Iterable[str]) -> list[str]:
    return [item for item in items if item]
