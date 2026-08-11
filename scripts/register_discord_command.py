#!/usr/bin/env python3
"""Register or replace the global Discord /최신 application command."""

from __future__ import annotations

import argparse
import os
import sys

import httpx


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"환경변수 {name}을(를) 설정하세요.")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guild-id", help="지정하면 테스트 서버용 guild command로 등록합니다.")
    args = parser.parse_args()
    application_id = required_env("DISCORD_APPLICATION_ID")
    bot_token = required_env("DISCORD_BOT_TOKEN")
    if args.guild_id:
        url = f"https://discord.com/api/v10/applications/{application_id}/guilds/{args.guild_id}/commands"
    else:
        url = f"https://discord.com/api/v10/applications/{application_id}/commands"

    payload = {"name": "최신", "description": "마지막 확인 이후 새 공모전을 확인합니다.", "type": 1}
    response = httpx.post(
        url,
        headers={"Authorization": f"Bot {bot_token}"},
        json=payload,
        timeout=15.0,
    )
    response.raise_for_status()
    print("/최신 명령 등록 완료")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.HTTPError as exc:
        print(f"Discord 명령 등록 실패: {exc}", file=sys.stderr)
        sys.exit(1)
