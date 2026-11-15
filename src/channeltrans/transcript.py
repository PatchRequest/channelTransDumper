"""Parsing YouTube subtitles (json3) and splitting them into searchable passages."""

from __future__ import annotations

import json
from dataclasses import dataclass

# Target size of a passage. About 1000 characters is roughly one minute of speech:
# large enough for a coherent statement, small enough for precise hits.
PASSAGE_TARGET_CHARS = 1000


@dataclass(frozen=True)
class Cue:
    """One subtitle line with timestamps."""

    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class Passage:
    start_ms: int
    end_ms: int
    text: str


class TranscriptFormatError(Exception):
    """The subtitle file is not in the expected json3 format."""


def parse_json3(data: bytes) -> list[Cue]:
    """Read a json3 subtitle file into a list of non-empty lines.

    Automatic captions show lines overlapping each other, so the end of a line is
    capped at the start of the next one.
    """
    try:
        events = json.loads(data)["events"]
    except (ValueError, KeyError, TypeError) as exc:
        raise TranscriptFormatError("Subtitles are not valid json3.") from exc

    raw: list[tuple[int, int, str]] = []
    for event in events:
        segments = event.get("segs")
        if not segments or "tStartMs" not in event:
            continue
        text = " ".join("".join(seg.get("utf8", "") for seg in segments).split())
        if not text:
            continue
        start = int(event["tStartMs"])
        raw.append((start, start + int(event.get("dDurationMs", 0)), text))

    raw.sort(key=lambda item: item[0])
    cues = []
    for index, (start, end, text) in enumerate(raw):
        if index + 1 < len(raw):
            end = min(end, raw[index + 1][0])
        cues.append(Cue(start, max(end, start), text))
    return cues


def build_passages(cues: list[Cue], target_chars: int = PASSAGE_TARGET_CHARS) -> list[Passage]:
    """Merge consecutive lines into passages of about ``target_chars`` characters."""
    passages: list[Passage] = []
    current: list[Cue] = []
    length = 0
    for cue in cues:
        current.append(cue)
        length += len(cue.text) + 1
        if length >= target_chars:
            passages.append(_join(current))
            current, length = [], 0
    if current:
        passages.append(_join(current))
    return passages


def _join(cues: list[Cue]) -> Passage:
    return Passage(cues[0].start_ms, cues[-1].end_ms, " ".join(cue.text for cue in cues))


def cues_to_json(cues: list[Cue]) -> str:
    return json.dumps([[c.start_ms, c.end_ms, c.text] for c in cues], ensure_ascii=False)


def cues_from_json(data: str) -> list[Cue]:
    return [Cue(start, end, text) for start, end, text in json.loads(data)]
