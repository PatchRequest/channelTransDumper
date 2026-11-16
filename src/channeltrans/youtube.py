"""YouTube access through yt-dlp: list a channel, load metadata and subtitles."""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from yt_dlp import YoutubeDL
from yt_dlp.utils import YoutubeDLError

from .transcript import Cue, TranscriptFormatError, parse_json3

_ytdlp_log = logging.getLogger("channeltrans.ytdlp")

TrackKind = Literal["manual", "auto"]


class FetchError(Exception):
    """Fetching from YouTube failed (network, blocking, video unavailable)."""


class VideoNotReady(Exception):
    """The video is a running or scheduled live stream and has no transcript yet."""


@dataclass(frozen=True)
class FetchSettings:
    proxy: str | None = None
    # For TLS-intercepting proxies with their own CA (e.g. thermoptic).
    proxy_insecure_tls: bool = False


@dataclass(frozen=True)
class ListedVideo:
    id: str
    title: str


@dataclass(frozen=True)
class ChannelListing:
    channel_id: str
    handle: str | None
    title: str
    url: str
    videos: list[ListedVideo]  # in listing order, newest first


@dataclass(frozen=True)
class Track:
    key: str  # yt-dlp's key of the subtitle track, e.g. "en" or "en-orig"
    language: str  # original language of the video, e.g. "en-US"
    kind: TrackKind


@dataclass(frozen=True)
class Transcript:
    language: str
    kind: TrackKind
    cues: list[Cue]


@dataclass(frozen=True)
class FetchedVideo:
    id: str
    title: str
    upload_date: str | None  # ISO date
    duration_s: int | None
    description: str | None
    transcript: Transcript | None  # None: no subtitles in the original language
    # YouTube's availability, e.g. "public", "unlisted", "subscriber_only" (members only)
    availability: str | None = None


def select_track(info: dict[str, Any]) -> Track | None:
    """Pick the subtitle track in the video's original language.

    Manually maintained subtitles win over automatic captions. Translated tracks
    are never picked, so the transcript matches what was actually said.
    """
    language = info.get("language")
    if not language:
        return None
    base = language.split("-")[0]

    manual = [key for key in info.get("subtitles") or {} if key.split("-")[0] == base]
    if manual:
        key = language if language in manual else base if base in manual else sorted(manual)[0]
        return Track(key, language, "manual")

    automatic = info.get("automatic_captions") or {}
    for key in (f"{base}-orig", language, base):
        if key in automatic:
            return Track(key, language, "auto")
    return None


class YouTubeClient:
    def __init__(self, settings: FetchSettings) -> None:
        self._settings = settings

    def _params(self, **extra: Any) -> dict[str, Any]:
        params: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _ytdlp_log,
            "js_runtimes": {"deno": {}, "node": {}},
            # Only metadata and subtitles are needed, no video formats.
            "ignore_no_formats_error": True,
            "nocheckcertificate": self._settings.proxy_insecure_tls,
        }
        if self._settings.proxy:
            params["proxy"] = self._settings.proxy
        return params | extra

    def list_channel(self, channel_url: str) -> ChannelListing:
        """List all videos of a channel (videos, live streams, shorts)."""
        try:
            with YoutubeDL(self._params(extract_flat="in_playlist")) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                if info.get("_type") != "playlist" or not info.get("channel_id"):
                    raise FetchError(f"{channel_url} is not a YouTube channel URL.")
                videos = list(_dedupe(_flatten(info["entries"])))
        except YoutubeDLError as exc:
            raise FetchError(str(exc)) from exc
        return ChannelListing(
            channel_id=info["channel_id"],
            handle=info.get("uploader_id"),
            title=info.get("channel") or info["channel_id"],
            url=info.get("channel_url") or channel_url,
            videos=videos,
        )

    def fetch_video(self, video_id: str) -> FetchedVideo:
        """Load a video's metadata and, if available, its transcript."""
        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            with YoutubeDL(self._params()) as ydl:
                info = ydl.sanitize_info(ydl.extract_info(url, download=False))
            if info.get("live_status") in ("is_live", "is_upcoming"):
                raise VideoNotReady(video_id)
            track = select_track(info)
            transcript = None
            if track is not None:
                cues = parse_json3(self._download_track(info, track))
                transcript = Transcript(track.language, track.kind, cues)
        except YoutubeDLError as exc:
            raise FetchError(str(exc)) from exc
        except TranscriptFormatError as exc:
            raise FetchError(str(exc)) from exc

        upload_date = info.get("upload_date")
        return FetchedVideo(
            id=video_id,
            title=info.get("title") or video_id,
            upload_date=(
                f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}" if upload_date else None
            ),
            duration_s=int(info["duration"]) if info.get("duration") else None,
            description=info.get("description"),
            transcript=transcript,
            availability=info.get("availability"),
        )

    def _download_track(self, info: dict[str, Any], track: Track) -> bytes:
        """Download a subtitle track with yt-dlp's own downloader (incl. impersonation)."""
        with tempfile.TemporaryDirectory(prefix="channeltrans-") as tmp:
            params = self._params(
                skip_download=True,
                writesubtitles=track.kind == "manual",
                writeautomaticsub=track.kind == "auto",
                subtitleslangs=[re.escape(track.key)],
                subtitlesformat="json3",
                outtmpl={"default": str(Path(tmp) / "%(id)s.%(ext)s")},
            )
            with YoutubeDL(params) as ydl:
                ydl.process_ie_result(info, download=True)
            path = Path(tmp) / f"{info['id']}.{track.key}.json3"
            if not path.is_file():
                raise FetchError(f"Subtitle track {track.key!r} could not be downloaded.")
            return path.read_bytes()


def _flatten(entries: Iterable[dict[str, Any]]) -> Iterable[ListedVideo]:
    """A channel yields one nested playlist per tab (Videos, Live, Shorts)."""
    for entry in entries:
        if entry.get("entries") is not None:
            yield from _flatten(entry["entries"])
        elif entry.get("ie_key") == "Youtube" and entry.get("id"):
            yield ListedVideo(entry["id"], entry.get("title") or entry["id"])


def _dedupe(videos: Iterable[ListedVideo]) -> Iterable[ListedVideo]:
    seen: set[str] = set()
    for video in videos:
        if video.id not in seen:
            seen.add(video.id)
            yield video
