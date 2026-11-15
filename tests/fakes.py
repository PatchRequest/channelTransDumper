"""Test doubles shared by the test modules."""

from __future__ import annotations

import re
import zlib

import numpy as np

from channeltrans import ingest
from channeltrans.embedding import DIMENSIONS
from channeltrans.transcript import Cue
from channeltrans.youtube import ChannelListing, FetchedVideo, ListedVideo, Transcript


class FakeClient:
    def __init__(self, videos: dict[str, FetchedVideo | Exception]):
        self.videos = videos
        self.fetched: list[str] = []

    def list_channel(self, channel_url: str) -> ChannelListing:
        return ChannelListing(
            "UC1", "@falconer", "Falconer", channel_url,
            [ListedVideo(video_id, f"Title {video_id}") for video_id in self.videos],
        )

    def fetch_video(self, video_id: str) -> FetchedVideo:
        self.fetched.append(video_id)
        outcome = self.videos[video_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def video(video_id: str, *lines: str) -> FetchedVideo:
    cues = [Cue(i * 5000, (i + 1) * 5000, line) for i, line in enumerate(lines)]
    transcript = Transcript("en", "auto", cues) if lines else None
    return FetchedVideo(video_id, f"Title {video_id}", "2026-01-02", 600, "Description", transcript)


class FakeEmbedder:
    """Bag-of-words vectors: texts sharing words are similar to each other."""

    def _vector(self, text: str) -> bytes:
        vector = np.zeros(DIMENSIONS, dtype=np.float32)
        for word in re.findall(r"\w+", text.lower()):
            vector[zlib.crc32(word.encode()) % DIMENSIONS] += 1.0
        return (vector / (np.linalg.norm(vector) or 1.0)).tobytes()

    def embed_documents(self, documents: list[tuple[str, str]]) -> list[bytes]:
        return [self._vector(f"{title} {text}") for title, text in documents]

    def embed_query(self, query: str) -> bytes:
        return self._vector(query)


EMBEDDER = FakeEmbedder()
OPTIONS = ingest.SyncOptions(delay_s=0)
