#!/usr/bin/env python3
"""종목별 뉴스 리포트 생성 (방향 전환 감지 시)

news_monitor.py에서 방향 전환이 감지되면 호출된다.
Claude Haiku로 뉴스 분석 후 상세 MD 리포트 생성 → PDF → 텔레그램 전송.

비용: ~$0.10/리포트 (Haiku)

Usage:
    python3 news_report.py <trigger_file.json>
"""

import json
import logging
import os
import subprocess
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

# ─── 설정 ───

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.join(BASE_DIR, "보고서", "뉴스")
THESIS_FILE = os.path.join(BASE_DIR, "investment_thesis.json")
ALERT_CONFIG_FILE = os.path.join(BASE_DIR, "alert_config.json")
LOG_DIR = os.path.expanduser("~/logs/stock-monitor")
CLAUDE_BIN = "/home/linuxbrew/.linuxbrew/bin/claude"
PYTHON_BIN = os.path.join(BASE_DIR, ".venv", "bin", "python3")

os.makedirs(REPORT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "news_report.log")),
        logging.StreamHandler(),
    ],
)


# ─── .env 로드 ───

def _load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_env()


# ─── 유틸리티 ───

def naver_search_url(ticker_name, keyword=""):
    """한글 관련 기사 검색 URL 생성 (API 호출 없이 링크만)"""
    query = f"{ticker_name} {keyword}".strip()
    return f"https://search.naver.com/search.naver?where=news&query={urllib.parse.quote(query)}"


def load_thesis():
    """investment_thesis.json 로드"""
    if os.path.exists(THESIS_FILE):
        with open(THESIS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"tickers": {}}


def load_alert_config():
    """alert_config.json 로드"""
    if os.path.exists(ALERT_CONFIG_FILE):
        with open(ALERT_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def send_telegram(message, parse_mode="Markdown"):
    """텔레그램 메시지 전송"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logging.warning("텔레그램 설정 없음")
        return
    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode,
        }).encode()
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logging.error(f"텔레그램 전송 실패: {e}")


# ─── 리포트 생성 ───

def build_news_table(trigger_data):
    """뉴스 테이블 문자열 생성"""
    lines = []
    lines.append("| # | 호/악재 | 제목 | 출처 | 링크 |")
    lines.append("|---|---------|------|------|------|")

    idx = 1
    for item in trigger_data.get("urgent", []):
        headline = item.get("headline", "")[:60]
        source = item.get("source", "")
        url = item.get("url", "")
        link = f"[기사]({url})" if url else "-"
        lines.append(f"| {idx} | 🔴 악재 | {headline} | {source} | {link} |")
        idx += 1

    for item in trigger_data.get("positive", []):
        headline = item.get("headline", "")[:60]
        source = item.get("source", "")
        url = item.get("url", "")
        link = f"[기사]({url})" if url else "-"
        lines.append(f"| {idx} | 🟢 호재 | {headline} | {source} | {link} |")
        idx += 1

    # top_headlines 중 urgent/positive에 없는 것
    seen = set()
    for item in trigger_data.get("urgent", []) + trigger_data.get("positive", []):
        seen.add(item.get("headline", ""))

    for item in trigger_data.get("top_headlines", []):
        if item.get("headline", "") in seen:
            continue
        headline = item.get("headline", "")[:60]
        source = item.get("source", "")
        url = item.get("url", "")
        link = f"[기사]({url})" if url else "-"
        lines.append(f"| {idx} | ⚪ 중립 | {headline} | {source} | {link} |")
        idx += 1
        if idx > 10:
            break

    return "\n".join(lines)


def generate_report(trigger_data):
    """Claude Haiku로 뉴스 분석 리포트 생성

    Args:
        trigger_data: dict with keys: ticker, name, prev_direction, new_direction,
                      news_score, change_pct, urgent, positive, top_headlines, price, timestamp

    Returns:
        str: 리포트 파일 경로 (or None on failure)
    """
    ticker = trigger_data["ticker"]
    name = trigger_data["name"]
    prev_dir = trigger_data["prev_direction"]
    new_dir = trigger_data["new_direction"]
    score = trigger_data["news_score"]
    change_pct = trigger_data["change_pct"]
    price = trigger_data.get("price", 0)
    ts = trigger_data.get("timestamp", "")

    # 기존 테제 정보
    thesis = load_thesis()
    ticker_thesis = thesis.get("tickers", {}).get(ticker, {})

    # 알림 설정
    alert_config = load_alert_config()
    ticker_alert = alert_config.get(ticker, {})

    # 뉴스 테이블
    news_table = build_news_table(trigger_data)

    # Naver 검색 URL
    naver_url = naver_search_url(name)

    # 뉴스 상세 (Haiku에 전달할 데이터)
    urgent_text = "\n".join(
        f"- [{u.get('keyword')}] {u.get('headline', '')} ({u.get('source', '')})"
        for u in trigger_data.get("urgent", [])
    )
    positive_text = "\n".join(
        f"- [{p.get('keyword')}] {p.get('headline', '')} ({p.get('source', '')})"
        for p in trigger_data.get("positive", [])
    )

    # Claude Haiku 프롬프트
    prompt = f"""종목 뉴스 분석 리포트를 작성하라. 한국어로 작성.

=== 종목 정보 ===
종목: {name} ({ticker})
현재가: {price}
가격 변동: {change_pct:+.1f}%
뉴스 점수: {score:+.1f}
방향 전환: {prev_dir} → {new_dir}

=== 기존 테제 ===
판단: {ticker_thesis.get('judgment', 'N/A')}
확신도: {ticker_thesis.get('conviction', 'N/A')}
손절선: {ticker_thesis.get('stop_loss', 'N/A')}
목표가: {ticker_thesis.get('target', 'N/A')}
종합점수: {ticker_thesis.get('scores', {}).get('total', 'N/A')}

=== 악재 뉴스 ===
{urgent_text or '없음'}

=== 호재 뉴스 ===
{positive_text or '없음'}

=== 알림 설정 ===
손절선: {ticker_alert.get('stop_loss', 'N/A')}
목표가: {ticker_alert.get('target', 'N/A')}

아래 형식으로 분석을 작성하라. 각 섹션을 빠짐없이 채워라.

### 악재 분석
각 악재 뉴스에 대해:
1. **제목 요약** — 1줄 설명
   - 영향: 단기 주가에 미치는 영향 (구체적 % 추정)
   - 심각도: ★~★★★ (★ 노이즈, ★★ 단기 영향, ★★★ 구조적 변화)
   - 지속성: 1일/1주/1개월+ (가격 영향 지속 기간)

### 호재 분석
각 호재 뉴스에 대해:
1. **제목 요약** — 1줄 설명
   - 영향: 단기 주가에 미치는 영향
   - 심각도: ★~★★★
   - 지속성: 1일/1주/1개월+

### 종합 판정
- 전체 뉴스 톤: (강한 악재 / 약한 악재 / 혼조 / 약한 호재 / 강한 호재)
- 방향 전환 적절성: (적절 / 과잉반응 / 시기상조)
- 기존 테제 변경 필요성: (유지 / 수정 / 전면 재검토)

### 대응 제안
- **즉시**: (구체적 액션 1개 — 가격 조건 포함)
- **관망**: (추가 확인 필요 사항, 시간 프레임)
- **이전 판단 유지 항목**: (변경 불필요한 장기 테제)"""

    logging.info(f"Haiku 분석 시작: {ticker}")

    try:
        result = subprocess.run(
            [
                CLAUDE_BIN, "-p", prompt,
                "--allowedTools", "Read",
                "--permission-mode", "bypassPermissions",
                "--model", "haiku",
                "--max-budget-usd", "0.50",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "CLAUDECODE": ""},
        )
        analysis = result.stdout.strip()
        if result.returncode != 0:
            logging.error(f"Haiku 분석 실패: {result.stderr}")
            analysis = "(Haiku 분석 실패 — 수동 확인 필요)"
    except subprocess.TimeoutExpired:
        logging.error(f"Haiku 분석 타임아웃: {ticker}")
        analysis = "(Haiku 분석 타임아웃 — 수동 확인 필요)"
    except Exception as e:
        logging.error(f"Haiku 호출 실패: {e}")
        analysis = f"(Haiku 호출 실패: {e})"

    # ─── MD 리포트 조립 ───

    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    report_date = now.strftime("%Y-%m-%d")
    report_time = now.strftime("%H:%M")

    report = f"""# {name} ({ticker}) 뉴스 리포트

> 방향 전환: {prev_dir} → {new_dir}
> 작성: {report_date} {report_time} KST

---

## 핵심 뉴스

{news_table}

🔍 [네이버 관련 뉴스 검색]({naver_url})

## 호재/악재 분석

{analysis}

## 방향 전환 판정

| 항목 | 이전 | 현재 |
|------|------|------|
| 방향 | {prev_dir} | {new_dir} |
| 뉴스 점수 | - | {score:+.1f} |
| 가격 변동 | - | {change_pct:+.1f}% |
| 현재가 | - | {price} |
| 손절선 | {ticker_thesis.get('stop_loss', '-')} | {ticker_alert.get('stop_loss', ticker_thesis.get('stop_loss', '-'))} |
| 목표가 | {ticker_thesis.get('target', '-')} | {ticker_alert.get('target', ticker_thesis.get('target', '-'))} |
| 판단 | {ticker_thesis.get('judgment', '-')} | (리포트 참조) |

---

*이 리포트는 news_monitor.py 방향 전환 감지에 의해 자동 생성되었습니다.*
"""

    # ─── 파일 저장 ───
    report_filename = f"{report_date}_{ticker}.md"
    report_path = os.path.join(REPORT_DIR, report_filename)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    logging.info(f"리포트 저장: {report_path}")
    return report_path


def send_report(report_path, ticker, name):
    """리포트를 PDF로 변환하고 텔레그램 전송"""
    notify_script = os.path.join(BASE_DIR, "telegram_notify.sh")
    label = f"{name} 방향전환 리포트"

    if os.path.exists(notify_script):
        try:
            subprocess.run(
                ["bash", notify_script, report_path, label],
                timeout=60,
                capture_output=True,
            )
            logging.info(f"텔레그램 전송 완료: {report_path}")
        except subprocess.TimeoutExpired:
            logging.error("텔레그램 전송 타임아웃")
            # 폴백: MD 파일 직접 전송 시도
            send_telegram(
                f"📋 *{label}*\n방향 전환 리포트가 생성되었습니다.\n"
                f"파일: `{os.path.basename(report_path)}`\n"
                f"(PDF 변환 타임아웃)"
            )
        except Exception as e:
            logging.error(f"텔레그램 전송 실패: {e}")
    else:
        # telegram_notify.sh가 없으면 간단 메시지만
        send_telegram(
            f"📋 *{label}*\n리포트 파일: `{os.path.basename(report_path)}`"
        )


# ─── CLI ───

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 news_report.py <trigger_file.json>")
        sys.exit(1)

    trigger_file = sys.argv[1]
    if not os.path.exists(trigger_file):
        logging.error(f"트리거 파일 없음: {trigger_file}")
        sys.exit(1)

    with open(trigger_file, "r", encoding="utf-8") as f:
        trigger_data = json.load(f)

    ticker = trigger_data.get("ticker", "?")
    name = trigger_data.get("name", ticker)
    logging.info(f"=== 뉴스 리포트 생성 시작: {name} ({ticker}) ===")

    report_path = generate_report(trigger_data)
    if report_path:
        send_report(report_path, ticker, name)
        logging.info(f"=== 뉴스 리포트 완료: {report_path} ===")
    else:
        logging.error("리포트 생성 실패")
        sys.exit(1)


if __name__ == "__main__":
    main()
