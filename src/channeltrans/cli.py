"""Command line: synchronise, search, show status, start the MCP server."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from contextlib import closing
from pathlib import Path

from . import ingest, search
from .db import DatabaseError, connect, connect_read_only
from .embedding import LocalEmbedder
from .youtube import FetchError, FetchSettings, YouTubeClient

DEFAULT_DB = Path.home() / ".channeltrans" / "transcripts.db"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="channeltrans",
        description="YouTube channel transcripts in a searchable database for AI agents.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("CHANNELTRANS_DB", DEFAULT_DB)),
        help="path of the SQLite database (env CHANNELTRANS_DB, default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="also show yt-dlp messages")
    commands = parser.add_subparsers(dest="command", required=True)

    sync = commands.add_parser("sync", help="list a channel and fetch its open transcripts")
    sync.add_argument("channel_url", help="e.g. https://www.youtube.com/@somechannel")
    sync.add_argument("--limit", type=int, help="fetch at most this many videos in this run")
    sync.add_argument("--delay", type=float, default=3.0, help="pause between videos in seconds")
    sync.add_argument(
        "--recheck-missing",
        action="store_true",
        help="check videos without a transcript again (captions often appear late)",
    )
    sync.add_argument(
        "--proxy",
        default=os.environ.get("CHANNELTRANS_PROXY"),
        help="HTTP proxy for YouTube, e.g. http://127.0.0.1:1234 (env CHANNELTRANS_PROXY)",
    )
    sync.add_argument(
        "--proxy-insecure-tls",
        action="store_true",
        default=os.environ.get("CHANNELTRANS_PROXY_INSECURE_TLS") == "1",
        help="do not verify TLS certificates; needed for TLS-intercepting proxies such as "
        "thermoptic (env CHANNELTRANS_PROXY_INSECURE_TLS=1)",
    )

    find = commands.add_parser("search", help="hybrid search (full text + semantic), JSON output")
    find.add_argument(
        "queries",
        nargs="+",
        metavar="query",
        help="one or more phrasings of the question (e.g. in several languages), fused",
    )
    find.add_argument("--channel", help="channel ID, @handle or title")
    find.add_argument("--any", action="store_true", help="one search term is enough (not all)")
    find.add_argument("--limit", type=int, default=10)
    find.add_argument("--offset", type=int, default=0, help="skip this many hits (paging)")

    mentions = commands.add_parser(
        "mentions", help="every passage naming one of the terms, grouped by video, JSON output"
    )
    mentions.add_argument("terms", nargs="+", metavar="term")
    mentions.add_argument("--channel", help="channel ID, @handle or title")
    mentions.add_argument("--limit", type=int, default=50, help="videos per page")
    mentions.add_argument("--offset", type=int, default=0, help="skip this many videos")

    commands.add_parser("status", help="capture progress per channel, JSON output")
    commands.add_parser("reindex", help="rebuild passages and vectors from stored transcripts")
    commands.add_parser("mcp", help="start the MCP server on stdio")
    return parser


def main() -> None:
    args = _parser().parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)
    logging.getLogger("channeltrans").setLevel(logging.INFO)
    logging.getLogger("channeltrans.ytdlp").setLevel(logging.DEBUG if args.verbose else logging.ERROR)
    try:
        sys.exit(_run(args))
    except (DatabaseError, FetchError, search.QueryError) as exc:
        sys.exit(f"Error: {exc}")


def _run(args: argparse.Namespace) -> int:
    if args.command == "sync":
        return _sync(args)
    if args.command == "mcp":
        from .mcp_server import build_server

        build_server(args.db).run()
        return 0
    if args.command == "reindex":
        with closing(connect(args.db)) as conn:
            print(f"Rebuilt the passages of {ingest.reindex(conn, LocalEmbedder())} transcripts.")
        return 0

    with closing(connect_read_only(args.db)) as conn:
        if args.command == "search":
            output = search.search_passages(
                conn,
                LocalEmbedder(),
                args.queries,
                channel=args.channel,
                match="any" if args.any else "all",
                limit=args.limit,
                offset=args.offset,
            )
        elif args.command == "mentions":
            output = search.find_mentions(
                conn, args.terms, channel=args.channel, limit=args.limit, offset=args.offset
            )
        else:
            output = search.channel_stats(conn)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _sync(args: argparse.Namespace) -> int:
    if args.proxy_insecure_tls and not args.proxy:
        sys.exit("Error: --proxy-insecure-tls is only allowed together with --proxy.")
    client = YouTubeClient(FetchSettings(args.proxy, args.proxy_insecure_tls))
    with closing(connect(args.db)) as conn:
        channel_id = ingest.discover(conn, client, args.channel_url)
        if args.recheck_missing:
            ingest.requeue_missing(conn, channel_id)
        result = ingest.process_queue(
            conn,
            client,
            LocalEmbedder(),
            channel_id,
            ingest.SyncOptions(limit=args.limit, delay_s=args.delay),
        )
    print(
        f"Done: {result.done} transcripts, {result.no_transcript} without transcript, "
        f"{result.failed} failed, {result.not_ready} not yet available.",
        file=sys.stderr,
    )
    return 1 if result.aborted else 0


if __name__ == "__main__":
    main()
