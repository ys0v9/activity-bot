#!/usr/bin/env python3
"""Run one real public ContestKorea crawl and print a safe JSON summary."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import fields
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.http_client import HttpClient
from src.crawler.contestkorea import ContestKoreaCrawler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=100, help="Maximum list pages to inspect (default: 100)")
    args = parser.parse_args()
    started = time.perf_counter()
    client = HttpClient()
    crawler = ContestKoreaCrawler(client, max_pages=args.max_pages)
    try:
        contests = crawler.crawl()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "http_request_count": client.metrics.request_count,
                    "total_duration_ms": int((time.perf_counter() - started) * 1000),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    finally:
        client.close()

    field_names = [field.name for field in fields(contests[0])] if contests else []
    missing_fields = {
        field: sum(1 for contest in contests if getattr(contest, field) is None)
        for field in field_names
        if any(getattr(contest, field) is None for contest in contests)
    }
    summary = {
        "success": True,
        "contest_count": len(contests),
        "sample_contests": [contest.to_item() for contest in contests[:3]],
        "missing_fields": missing_fields,
        "http_request_count": client.metrics.request_count,
        "list_request_count": client.metrics.list_request_count,
        "detail_request_count": client.metrics.detail_request_count,
        "list_fetch_duration_ms": crawler.metrics.list_fetch_duration_ms,
        "detail_fetch_duration_ms": crawler.metrics.detail_fetch_duration_ms,
        "total_duration_ms": int((time.perf_counter() - started) * 1000),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
