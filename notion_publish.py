#!/usr/bin/env python3
"""
Notion publish — Markdown 보고서를 Notion DB에 업로드.

의존성: requests (이미 설치됨 가정)
환경변수 (.env):
  NOTION_TOKEN       — Notion Integration secret (ntn_...)
  NOTION_DATABASE_ID — 대상 DB ID (UUID with dashes)

Fallback:
  NOTION_TOKEN 누락 시 warning 로그 + exit 0 (non-fatal).
  telegram_notify.sh가 이 동작을 가정하고 Notion 업로드 없이도 진행하도록.

사용:
  python3 notion_publish.py <md_file> <type> [--title=<title>] [--summary=<1-liner>]

Type: US | KR | DeepDive | Premarket | Midcheck | Findings | Round1 | Round2 | Scout
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("[notion_publish] ERROR: requests 미설치. `.venv/bin/pip install requests`", file=sys.stderr)
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────────
# 환경 로드
# ──────────────────────────────────────────────────────────────────────

STOCK_DIR = Path(os.environ.get("STOCK_DIR", "/home/bravopotato/Spaces/finspace/potato-fin"))


def load_env() -> dict[str, str]:
    env: dict[str, str] = dict(os.environ)
    dotenv = STOCK_DIR / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip().strip('"').strip("'")
            env.setdefault(k.strip(), v)
    return env


# ──────────────────────────────────────────────────────────────────────
# 메타 추출 (보고서 헤더에서)
# ──────────────────────────────────────────────────────────────────────

NAV_RE = re.compile(r"총\s*평가금액[\s*]*₩([\d,]+)")
RETURN_RE = re.compile(r"총\s*손익[\s*]*\+?₩([\d,\-]+)\s*\(([+\-]?[\d.]+%)\)")
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def extract_metadata(md_text: str, md_path: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "title": md_path.stem,
        "nav": None,
        "total_return": None,
        "return_pct": None,
        "date": None,
    }

    first_100 = "\n".join(md_text.splitlines()[:30])

    m = NAV_RE.search(first_100)
    if m:
        meta["nav"] = int(m.group(1).replace(",", ""))

    m = RETURN_RE.search(first_100)
    if m:
        meta["total_return"] = int(m.group(1).replace(",", "").replace("-", ""))
        meta["return_pct"] = m.group(2)

    # 파일명 또는 내용에서 날짜 추출
    m = DATE_RE.search(md_path.name) or DATE_RE.search(first_100)
    if m:
        meta["date"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # 제목: H1 첫 줄
    for line in md_text.splitlines()[:5]:
        if line.startswith("# "):
            meta["title"] = line[2:].strip()
            break

    return meta


# ──────────────────────────────────────────────────────────────────────
# Markdown → Notion blocks (간소화)
# ──────────────────────────────────────────────────────────────────────

NOTION_MAX_CHARS = 1900  # rich_text 블록당 2000자 제한 (약간 여유)
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def chunk_text(text: str, limit: int = NOTION_MAX_CHARS) -> list[str]:
    """긴 텍스트를 Notion rich_text 제한 이하로 쪼갠다."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks


def paragraph_block(text: str) -> list[dict[str, Any]]:
    """긴 문단 1개를 여러 paragraph block으로 쪼개서 반환."""
    blocks: list[dict[str, Any]] = []
    for chunk in chunk_text(text):
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
        })
    return blocks


def heading_block(text: str, level: int) -> dict[str, Any]:
    level = min(max(level, 1), 3)
    key = f"heading_{level}"
    return {
        "object": "block",
        "type": key,
        key: {"rich_text": [{"type": "text", "text": {"content": text[:NOTION_MAX_CHARS]}}]},
    }


def code_block(code: str, language: str = "markdown") -> list[dict[str, Any]]:
    """코드 블록 1개 (긴 코드는 여러 블록으로 쪼갬)."""
    blocks = []
    for chunk in chunk_text(code):
        blocks.append({
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}],
                "language": language,
            },
        })
    return blocks


def md_to_blocks(md_text: str) -> list[dict[str, Any]]:
    """
    간소화된 MD→Notion 변환:
      - # / ## / ### → heading_1/2/3
      - 빈 줄로 구분된 단락 → paragraph
      - ``` 코드 블록 → code block
      - 그 외 (리스트/테이블 등)은 paragraph로 fallback
    """
    blocks: list[dict[str, Any]] = []
    lines = md_text.splitlines()
    buf: list[str] = []
    in_code = False
    code_lang = "markdown"
    code_buf: list[str] = []

    def flush_buf() -> None:
        if buf:
            text = "\n".join(buf).strip()
            if text:
                blocks.extend(paragraph_block(text))
            buf.clear()

    for line in lines:
        if line.startswith("```"):
            if in_code:
                # 코드 블록 종료
                blocks.extend(code_block("\n".join(code_buf), code_lang))
                code_buf.clear()
                in_code = False
            else:
                flush_buf()
                in_code = True
                code_lang = line[3:].strip() or "plain text"
            continue

        if in_code:
            code_buf.append(line)
            continue

        if line.startswith("# "):
            flush_buf()
            blocks.append(heading_block(line[2:].strip(), 1))
        elif line.startswith("## "):
            flush_buf()
            blocks.append(heading_block(line[3:].strip(), 2))
        elif line.startswith("### "):
            flush_buf()
            blocks.append(heading_block(line[4:].strip(), 3))
        elif line.strip() == "---":
            flush_buf()
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif line.strip() == "":
            flush_buf()
        else:
            buf.append(line)

    flush_buf()
    if in_code and code_buf:
        blocks.extend(code_block("\n".join(code_buf), code_lang))

    return blocks


# ──────────────────────────────────────────────────────────────────────
# Notion API POST
# ──────────────────────────────────────────────────────────────────────

def publish(
    md_file: Path,
    report_type: str,
    summary: str | None,
    token: str,
    database_id: str,
) -> str | None:
    md_text = md_file.read_text(encoding="utf-8")
    meta = extract_metadata(md_text, md_file)
    blocks = md_to_blocks(md_text)

    # Notion API는 한 번에 최대 100 children 까지 허용.
    # 초과분은 create 후 append 필요. 일단 100 cap 적용 (넘치면 나중 append).
    first_batch = blocks[:100]
    rest = blocks[100:]

    # DB 타입별 properties (스키마 다름)
    origin_path = str(md_file.relative_to(STOCK_DIR)) if md_file.is_relative_to(STOCK_DIR) else str(md_file)

    if report_type == "Scout":
        # 💎 스카우트 Watchlist DB 스키마
        properties = {
            "제목": {"title": [{"text": {"content": meta["title"][:2000]}}]},
            "유형": {"select": {"name": "주간리포트"}},
            "원본 파일": {"rich_text": [{"text": {"content": origin_path}}]},
            "상태": {"select": {"name": "신규"}},
        }
        if meta["date"]:
            properties["발굴일"] = {"date": {"start": meta["date"]}}
        if summary:
            properties["한 줄 요약"] = {"rich_text": [{"text": {"content": summary[:2000]}}]}
    elif report_type == "Earnings":
        # 📈 Earnings Preview DB 스키마
        # 실적일은 meta["date"]가 아니라 파일명에서 추출 필요 (실적일 != 작성일)
        # 임시로 meta["date"]를 실적일로 사용 (run_earnings_preview.sh가 파일명에 날짜 포함)
        properties = {
            "제목": {"title": [{"text": {"content": meta["title"][:2000]}}]},
            "원본 파일": {"rich_text": [{"text": {"content": origin_path}}]},
            "상태": {"select": {"name": "프리뷰"}},
        }
        # 파일명에서 실적일 추출 (예: NVDA_preview_2026-05-21.md)
        import re as _re
        m = _re.search(r"_(\d{4}-\d{2}-\d{2})\.md$", md_file.name)
        if m:
            properties["실적일"] = {"date": {"start": m.group(1)}}
        # 파일명에서 티커 추출
        m = _re.match(r"^([A-Za-z0-9._]+)_preview_", md_file.name)
        if m:
            properties["티커"] = {"rich_text": [{"text": {"content": m.group(1)}}]}
        if summary:
            properties["한 줄 요약"] = {"rich_text": [{"text": {"content": summary[:2000]}}]}
    else:
        # 보고서 DB (기본) 스키마
        properties = {
            "제목": {"title": [{"text": {"content": meta["title"][:2000]}}]},
            "종류": {"select": {"name": report_type}},
            "원본 파일": {"rich_text": [{"text": {"content": origin_path}}]},
            "상태": {"select": {"name": "생성"}},
        }
        if meta["date"]:
            properties["날짜"] = {"date": {"start": meta["date"]}}
        if meta["nav"]:
            properties["NAV"] = {"number": meta["nav"]}
        if summary:
            properties["한 줄 요약"] = {"rich_text": [{"text": {"content": summary[:2000]}}]}

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "parent": {"database_id": database_id},
        "icon": {"type": "emoji", "emoji": _icon_for(report_type)},
        "properties": properties,
        "children": first_batch,
    }

    r = requests.post(f"{NOTION_API}/pages", headers=headers, json=payload, timeout=30)
    if r.status_code >= 400:
        print(f"[notion_publish] ERROR {r.status_code}: {r.text[:500]}", file=sys.stderr)
        return None

    page = r.json()
    page_id = page["id"]
    page_url = page.get("url", f"https://www.notion.so/{page_id.replace('-', '')}")

    # 100+ 블록 append
    while rest:
        chunk = rest[:100]
        rest = rest[100:]
        ar = requests.patch(
            f"{NOTION_API}/blocks/{page_id}/children",
            headers=headers,
            json={"children": chunk},
            timeout=30,
        )
        if ar.status_code >= 400:
            print(f"[notion_publish] WARN append {ar.status_code}: {ar.text[:200]}", file=sys.stderr)
            break

    return page_url


def _icon_for(report_type: str) -> str:
    return {
        "US": "📊",
        "KR": "🇰🇷",
        "DeepDive": "🎯",
        "Premarket": "🌅",
        "Midcheck": "🕑",
        "Findings": "🔍",
        "Round1": "🔍",
        "Round2": "📊",
        "Scout": "💎",
        "Earnings": "📈",
    }.get(report_type, "📄")


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Upload MD report to Notion DB.")
    p.add_argument("md_file", type=Path, help="Markdown 보고서 파일 경로")
    p.add_argument("report_type", choices=["US", "KR", "DeepDive", "Premarket", "Midcheck", "Findings", "Round1", "Round2", "Scout", "Earnings"])
    p.add_argument("--summary", help="한 줄 요약 (생략 시 빈 값)")
    args = p.parse_args()

    if not args.md_file.exists():
        print(f"[notion_publish] 파일 없음: {args.md_file}", file=sys.stderr)
        return 1

    env = load_env()
    token = env.get("NOTION_TOKEN")

    # Type별 DB 라우팅 — 향후 확장 가능
    type_to_db_key = {
        "Scout": "NOTION_SCOUT_DATABASE_ID",
        "Earnings": "NOTION_EARNINGS_DATABASE_ID",
    }
    db_key = type_to_db_key.get(args.report_type, "NOTION_DATABASE_ID")
    db_id = env.get(db_key) or env.get("NOTION_DATABASE_ID")

    if not token or not db_id:
        print("[notion_publish] NOTION_TOKEN / NOTION_DATABASE_ID 미설정 — 업로드 스킵 (non-fatal).", file=sys.stderr)
        print("  설정 방법: https://www.notion.so/my-integrations 에서 integration 생성 →")
        print("  DB 'Connections'에 추가 → .env에 NOTION_TOKEN, NOTION_DATABASE_ID 추가")
        return 0

    url = publish(args.md_file, args.report_type, args.summary, token, db_id)
    if url:
        print(url)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
