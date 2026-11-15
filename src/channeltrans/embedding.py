"""Local embedding model for semantic search."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

# Multilingual model: a question in one language also finds transcripts in another.
# Model and dimension are part of the database schema (see db.py); changing them
# requires a new schema step that recomputes all vectors.
MODEL = "google/embeddinggemma-300m"
DIMENSIONS = 768
MODEL_CACHE = Path.home() / ".channeltrans" / "models"

# Input formats the model prescribes for retrieval (query against document).
_QUERY_FORMAT = "task: search result | query: {query}"
_DOCUMENT_FORMAT = "title: {title} | text: {text}"


class Embedder(Protocol):
    def embed_documents(self, documents: list[tuple[str, str]]) -> list[bytes]:
        """Embed (title, text) pairs; one float32 vector as bytes per document."""

    def embed_query(self, query: str) -> bytes:
        """Embed a search query."""


class LocalEmbedder:
    """Loads the model on first use (one-time download of about 1.2 GB)."""

    def __init__(self) -> None:
        self._model = None

    def _embed(self, texts: list[str]) -> list[bytes]:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(MODEL, cache_dir=str(MODEL_CACHE))
        return [
            np.asarray(vector, dtype=np.float32).tobytes()
            for vector in self._model.embed(texts, batch_size=8)
        ]

    def embed_documents(self, documents: list[tuple[str, str]]) -> list[bytes]:
        return self._embed(
            [_DOCUMENT_FORMAT.format(title=title, text=text) for title, text in documents]
        )

    def embed_query(self, query: str) -> bytes:
        return self._embed([_QUERY_FORMAT.format(query=query)])[0]
