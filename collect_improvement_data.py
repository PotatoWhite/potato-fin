#!/usr/bin/env python3
"""
자기개선용 데이터 수집 (Improvement Data Collector)

최근 보고서/로그/테제/검증결과를 분석하여 개선 포인트를 도출할 데이터를 수집한다.
run_improve.sh에서 호출되어 Claude에게 전달할 컨텍스트를 생성한다.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STOCK_DIR = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
LOG_DIR = Path.home() / "logs" / "stock-monitor"


def collect_prediction_accuracy() -> str:
    """투자 테제에서 예측 정확도 추출."""
    thesis_path = STOCK_DIR / "investment_thesis.json"
    if not thesis_path.exists():
        return "투자 테제 파일 없음"

    thesis = json.loads(thesis_path.read_text())
    acc = thesis.get('accuracy', {})
    lines = [
        "=== 예측 정확도 ===",
        f"총 예측: {acc.get('total_predictions', 0)}건",
        f"방향 적중률: {acc.get('direction_rate', 0):.1f}%",
        f"평균 오차: {acc.get('avg_error_pct', 0):.1f}%",
        f"체계적 편향: {acc.get('systematic_bias', 'unknown')}",
        f"최악 종목: {acc.get('worst_tickers', [])}",
        f"최고 종목: {acc.get('best_tickers', [])}",
    ]

    # 종목별 확신도 분포
    tickers = thesis.get('tickers', {})
    conv_dist = {}
    for t, td in tickers.items():
        conv = td.get('conviction', 5)
        conv_dist[t] = conv
    lines.append(f"\n종목별 확신도: {json.dumps(conv_dist, indent=2)}")

    # 최근 변경 로그
    rev_log = thesis.get('revision_log', [])[-10:]
    if rev_log:
        lines.append("\n최근 테제 변경:")
        for r in rev_log:
            lines.append(f"  {r.get('date')} {r.get('ticker')} {r.get('field')}: "
                         f"{r.get('old')} → {r.get('new')} ({r.get('reason', '')})")

    return '\n'.join(lines)


def collect_recent_validation() -> str:
    """최근 보고서 검증 결과 수집."""
    lines = ["=== 최근 보고서 검증 결과 ==="]

    # 로그에서 검증 결과 추출
    for log_pattern in ["report_*.log", "korea_report_*.log"]:
        log_files = sorted(LOG_DIR.glob(log_pattern))[-5:]
        for lf in log_files:
            try:
                content = lf.read_text(errors='ignore')
                for m in re.finditer(r'\[보고서 검증\].*', content):
                    lines.append(f"  {lf.name}: {m.group()}")
                for m in re.finditer(r'\[가격 검증\].*', content):
                    lines.append(f"  {lf.name}: {m.group()}")
            except Exception:
                pass

    return '\n'.join(lines) if len(lines) > 1 else "검증 결과 없음"


def collect_error_logs() -> str:
    """최근 로그에서 에러 수집."""
    lines = ["=== 최근 에러 로그 ==="]
    error_count = 0

    for log_file in sorted(LOG_DIR.glob("*.log")):
        # 최근 3일 이내 로그만
        try:
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime, tz=KST)
            if mtime < datetime.now(KST) - timedelta(days=3):
                continue
        except Exception:
            continue

        try:
            content = log_file.read_text(errors='ignore')
            for line in content.split('\n'):
                lower = line.lower()
                if any(kw in lower for kw in ['error', 'traceback', 'exception', 'fail']):
                    if 'not found' not in lower or '$STOCK_DIR' in line:
                        lines.append(f"  [{log_file.name}] {line.strip()[:200]}")
                        error_count += 1
                        if error_count >= 30:
                            break
        except Exception:
            pass
        if error_count >= 30:
            break

    if error_count == 0:
        lines.append("  에러 없음")

    return '\n'.join(lines)


def collect_report_quality() -> str:
    """최근 보고서 품질 분석."""
    lines = ["=== 최근 보고서 품질 ==="]

    # 최근 5개 보고서
    reports = sorted((STOCK_DIR / "보고서").glob("20*.md"))[-5:]
    kr_reports = sorted((STOCK_DIR / "보고서" / "한국").glob("20*.md"))[-3:] \
        if (STOCK_DIR / "보고서" / "한국").exists() else []

    for rp in reports + kr_reports:
        text = rp.read_text(encoding='utf-8')
        word_count = len(text)
        price_count = len(re.findall(r'[$₩€¥]\s*[\d,]+\.?\d*', text))
        has_forecast = bool(re.search(r'종목.*현재가.*예상.*종가', text))
        has_retrospective = bool(re.search(r'예측 회고', text))
        section_count = len(re.findall(r'^## ', text, re.MULTILINE))

        lines.append(f"\n  {rp.name}:")
        lines.append(f"    길이: {word_count:,}자 | 섹션: {section_count}개 | "
                     f"가격데이터: {price_count}개")
        lines.append(f"    5일전망: {'O' if has_forecast else 'X'} | "
                     f"예측회고: {'O' if has_retrospective else 'X'}")

        # 가격 보정 공지 확인
        if '가격 자동 보정' in text:
            corrections = re.findall(r'> - (.+: 현재가.+)', text)
            lines.append(f"    ⚠️ 가격 보정: {len(corrections)}건")

    return '\n'.join(lines)


def collect_price_accuracy() -> str:
    """보고서 가격 정확도 분석 — 보정 전 오차 패턴."""
    lines = ["=== 가격 오차 패턴 ==="]

    reports = sorted((STOCK_DIR / "보고서").glob("20*.md"))[-5:]
    ticker_errors = {}

    for rp in reports:
        text = rp.read_text(encoding='utf-8')
        # 보정 공지에서 오차 추출
        for m in re.finditer(r'> - (\S+): 현재가.+오차 ([\d.]+)%', text):
            ticker = m.group(1)
            err = float(m.group(2))
            if ticker not in ticker_errors:
                ticker_errors[ticker] = []
            ticker_errors[ticker].append({'report': rp.name, 'error_pct': err})

    if ticker_errors:
        for ticker, errors in sorted(ticker_errors.items(),
                                      key=lambda x: max(e['error_pct'] for e in x[1]),
                                      reverse=True):
            avg_err = sum(e['error_pct'] for e in errors) / len(errors)
            max_err = max(e['error_pct'] for e in errors)
            lines.append(f"  {ticker}: 평균 {avg_err:.1f}% / 최대 {max_err:.1f}% "
                         f"({len(errors)}건)")
    else:
        lines.append("  가격 보정 이력 없음 (첫 실행)")

    return '\n'.join(lines)


def collect_crontab_health() -> str:
    """크론탭 실행 상태 확인 + 24시간 이상 미업데이트 시 텔레그램 알림."""
    lines = ["=== 크론탭 실행 상태 ==="]
    now = datetime.now(KST)
    alerts = []

    checks = {
        'monitor.log': ('뉴스 감시', 6),  # (설명, 알림 임계값 시간)
        'premarket.log': ('장전 브리핑', 30),
        'midcheck.log': ('장중 체크', 30),
        'korea_report.log': ('한국 보고서', 30),
        'us_report.log': ('US 보고서', 30),
        'alerts.log': ('가격 알림', 6),
        'schedule.log': ('스케줄링', 30),
    }

    for logname, (desc, threshold_hours) in checks.items():
        logpath = LOG_DIR / logname
        if logpath.exists():
            mtime = datetime.fromtimestamp(logpath.stat().st_mtime, tz=KST)
            age = now - mtime
            size = logpath.stat().st_size
            status = "✅" if age < timedelta(days=2) else "⚠️ 오래됨"
            # 에러 체크
            try:
                tail = logpath.read_text(errors='ignore')[-2000:]
                if 'not found' in tail or 'Error' in tail:
                    status = "❌ 에러"
                    alerts.append(f"{desc} 에러 발생")
            except Exception:
                pass

            # 임계값 초과 체크
            if age > timedelta(hours=threshold_hours):
                alerts.append(f"{desc} {threshold_hours}시간 이상 미업데이트 ({age.days}일 {age.seconds//3600}시간)")

            lines.append(f"  {status} {desc} ({logname}): "
                         f"최근 {age.days}일 {age.seconds//3600}시간 전, {size:,}B")
        else:
            lines.append(f"  ❌ {desc} ({logname}): 파일 없음")
            alerts.append(f"{desc} 로그 파일 없음")

    # 텔레그램 알림
    if alerts:
        _send_telegram_alert(alerts)

    return '\n'.join(lines)


def _send_telegram_alert(alerts: list[str]):
    """텔레그램으로 알림 전송."""
    try:
        import subprocess
        message = "⚠️ **운영 루프 중단 감지**\n\n" + "\n".join(f"• {a}" for a in alerts)
        subprocess.run(
            ['python3', str(STOCK_DIR / 'telegram_bot.py'), '--send', message],
            capture_output=True,
            timeout=10
        )
    except Exception as e:
        print(f"[WARN] 텔레그램 알림 실패: {e}", file=sys.stderr)


def collect_file_inventory() -> str:
    """주요 파일 목록 + 최근 수정일."""
    lines = ["=== 주요 파일 현황 ==="]

    key_files = [
        'run_report.sh', 'run_korea_report.sh', 'run_premarket.sh', 'run_midcheck.sh',
        'event_flash.sh', 'news_monitor.py', 'price_alerts.py', 'price_verify.py',
        'validate_report.py', 'update_thesis.py', 'portfolio_tracker.py',
        'market_data.py', 'technical_analysis.py', 'telegram_bot.py', 'telegram_notify.sh',
        'alert_config.json', 'investment_thesis.json', 'CLAUDE.md',
    ]

    for fname in key_files:
        fpath = STOCK_DIR / fname
        if fpath.exists():
            mtime = datetime.fromtimestamp(fpath.stat().st_mtime, tz=KST)
            size = fpath.stat().st_size
            lines.append(f"  {fname}: {mtime.strftime('%m/%d %H:%M')} ({size:,}B)")
        else:
            lines.append(f"  {fname}: 없음")

    return '\n'.join(lines)


def main():
    """전체 개선 데이터 수집 및 출력."""
    now = datetime.now(KST)
    print(f"=== 자기개선 데이터 수집 ({now.strftime('%Y-%m-%d %H:%M KST')}) ===\n")

    sections = [
        collect_prediction_accuracy,
        collect_recent_validation,
        collect_price_accuracy,
        collect_report_quality,
        collect_error_logs,
        collect_crontab_health,
        collect_file_inventory,
    ]

    for fn in sections:
        try:
            print(fn())
        except Exception as e:
            print(f"[{fn.__name__}] 수집 실패: {e}")
        print()


if __name__ == '__main__':
    main()
