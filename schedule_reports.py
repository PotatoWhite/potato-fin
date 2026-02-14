#!/usr/bin/env python3
"""경제 지표 발표 일정에 맞춰 run_report.sh를 자동 스케줄링.

20:30 기본 보고서 실행 후 이 스크립트가 호출되면:
1. 향후 7일 내 주요 경제 지표 발표 확인
2. 발표 30분 후 run_report.sh를 실행하는 crontab 항목 추가
3. 지난 항목 자동 정리

사용법:
  python3 schedule_reports.py          # crontab 업데이트
  python3 schedule_reports.py --show   # 이번 주 일정만 표시
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_SCRIPT = os.path.join(BASE_DIR, "run_report.sh")
OVERRIDE_FILE = os.path.join(BASE_DIR, "schedule_override.json")
CRONTAB_TAG = "# auto-econ-report"
BUFFER_MINUTES = 30  # 발표 후 30분 뒤 보고서 실행

# ─── 2026 경제 지표 발표 일정 (KST) ───
# BLS: https://www.bls.gov/schedule/2026/home.htm
# Fed: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# 시간: ET → KST 변환 (EST: +14h, EDT: +13h)
# EDT: 2026-03-08 ~ 2026-11-01
#
# 대부분 8:30 AM ET → 22:30 KST(EST) / 21:30 KST(EDT)
# FOMC 2:00 PM ET → 04:00+1 KST(EST) / 03:00+1 KST(EDT)

ECONOMIC_CALENDAR_2026 = [
    # (날짜 KST, 시:분 KST, 지표명, 영향도)
    # ── 2월 ──
    ("2026-02-13", "22:30", "CPI (1월)", "HIGH"),
    ("2026-02-14", "22:30", "PPI (1월)", "HIGH"),
    ("2026-02-14", "22:30", "소매판매 (1월)", "MED"),
    ("2026-02-20", "22:30", "신규실업수당", "MED"),
    ("2026-02-21", "23:45", "PMI 속보 (2월)", "MED"),
    ("2026-02-28", "22:30", "GDP 2차 (Q4)", "HIGH"),
    ("2026-02-28", "22:30", "PCE 물가 (1월)", "HIGH"),
    # ── 3월 ──
    ("2026-03-06", "22:30", "고용보고서 NFP (2월)", "HIGH"),
    ("2026-03-11", "21:30", "CPI (2월)", "HIGH"),  # EDT 시작 3/8
    ("2026-03-12", "21:30", "PPI (2월)", "HIGH"),
    ("2026-03-17", "21:30", "소매판매 (2월)", "MED"),
    ("2026-03-19", "03:00", "FOMC 금리결정", "CRITICAL"),  # 3/19 2PM ET = 3/20 03:00 KST
    ("2026-03-26", "21:30", "GDP 3차 (Q4)", "MED"),
    ("2026-03-27", "21:30", "PCE 물가 (2월)", "HIGH"),
    # ── 4월 ──
    ("2026-04-03", "21:30", "고용보고서 NFP (3월)", "HIGH"),
    ("2026-04-08", "21:30", "CPI (3월)", "HIGH"),
    ("2026-04-09", "21:30", "PPI (3월)", "HIGH"),
    ("2026-04-15", "21:30", "소매판매 (3월)", "MED"),
    ("2026-04-29", "21:30", "GDP 1차 (Q1)", "HIGH"),
    ("2026-04-30", "21:30", "PCE 물가 (3월)", "HIGH"),
    # ── 5월 ──
    ("2026-05-01", "21:30", "고용보고서 NFP (4월)", "HIGH"),
    ("2026-05-07", "03:00", "FOMC 금리결정", "CRITICAL"),  # 5/7 2PM ET = 5/8 03:00 KST
    ("2026-05-13", "21:30", "CPI (4월)", "HIGH"),
    ("2026-05-14", "21:30", "PPI (4월)", "HIGH"),
    ("2026-05-15", "21:30", "소매판매 (4월)", "MED"),
    ("2026-05-28", "21:30", "GDP 2차 (Q1)", "MED"),
    ("2026-05-29", "21:30", "PCE 물가 (4월)", "HIGH"),
    # ── 6월 ──
    ("2026-06-05", "21:30", "고용보고서 NFP (5월)", "HIGH"),
    ("2026-06-10", "21:30", "CPI (5월)", "HIGH"),
    ("2026-06-11", "21:30", "PPI (5월)", "HIGH"),
    ("2026-06-18", "03:00", "FOMC 금리결정 + 점도표", "CRITICAL"),
    ("2026-06-25", "21:30", "GDP 3차 (Q1)", "MED"),
    ("2026-06-26", "21:30", "PCE 물가 (5월)", "HIGH"),
    # ── 7월 ──
    ("2026-07-02", "21:30", "고용보고서 NFP (6월)", "HIGH"),
    ("2026-07-15", "21:30", "CPI (6월)", "HIGH"),
    ("2026-07-16", "21:30", "PPI (6월)", "HIGH"),
    ("2026-07-16", "21:30", "소매판매 (6월)", "MED"),
    ("2026-07-29", "21:30", "GDP 1차 (Q2)", "HIGH"),
    ("2026-07-30", "03:00", "FOMC 금리결정", "CRITICAL"),
    ("2026-07-31", "21:30", "PCE 물가 (6월)", "HIGH"),
    # ── 8월 ──
    ("2026-08-07", "21:30", "고용보고서 NFP (7월)", "HIGH"),
    ("2026-08-12", "21:30", "CPI (7월)", "HIGH"),
    ("2026-08-13", "21:30", "PPI (7월)", "HIGH"),
    ("2026-08-14", "21:30", "소매판매 (7월)", "MED"),
    ("2026-08-27", "21:30", "GDP 2차 (Q2)", "MED"),
    ("2026-08-28", "21:30", "PCE 물가 (7월)", "HIGH"),
    # ── 9월 ──
    ("2026-09-04", "21:30", "고용보고서 NFP (8월)", "HIGH"),
    ("2026-09-09", "21:30", "CPI (8월)", "HIGH"),
    ("2026-09-10", "21:30", "PPI (8월)", "HIGH"),
    ("2026-09-17", "03:00", "FOMC 금리결정 + 점도표", "CRITICAL"),
    ("2026-09-25", "21:30", "GDP 3차 (Q2)", "MED"),
    ("2026-09-26", "21:30", "PCE 물가 (8월)", "HIGH"),
    # ── 10월 ──
    ("2026-10-02", "21:30", "고용보고서 NFP (9월)", "HIGH"),
    ("2026-10-14", "21:30", "CPI (9월)", "HIGH"),
    ("2026-10-15", "21:30", "PPI (9월)", "HIGH"),
    ("2026-10-16", "21:30", "소매판매 (9월)", "MED"),
    ("2026-10-29", "21:30", "GDP 1차 (Q3)", "HIGH"),
    ("2026-10-30", "21:30", "PCE 물가 (9월)", "HIGH"),
    # ── 11월 ── (11/1부터 EST)
    ("2026-11-05", "03:00", "FOMC 금리결정", "CRITICAL"),
    ("2026-11-06", "22:30", "고용보고서 NFP (10월)", "HIGH"),  # EST 복귀
    ("2026-11-12", "22:30", "CPI (10월)", "HIGH"),
    ("2026-11-13", "22:30", "PPI (10월)", "HIGH"),
    ("2026-11-17", "22:30", "소매판매 (10월)", "MED"),
    ("2026-11-25", "22:30", "GDP 2차 (Q3)", "MED"),
    ("2026-11-25", "22:30", "PCE 물가 (10월)", "HIGH"),
    # ── 12월 ──
    ("2026-12-04", "22:30", "고용보고서 NFP (11월)", "HIGH"),
    ("2026-12-09", "22:30", "CPI (11월)", "HIGH"),
    ("2026-12-10", "22:30", "PPI (11월)", "HIGH"),
    ("2026-12-16", "22:30", "소매판매 (11월)", "MED"),
    ("2026-12-17", "04:00", "FOMC 금리결정 + 점도표", "CRITICAL"),
    ("2026-12-23", "22:30", "GDP 3차 (Q3)", "MED"),
    ("2026-12-23", "22:30", "PCE 물가 (11월)", "HIGH"),
]


def load_overrides():
    """schedule_override.json에서 일정 변경사항 로드.

    보고서 생성 시 Claude가 WebSearch로 감지한 일정 변경을 반영.
    구조:
    {
        "overrides": [{"original_date": "...", "new_date": "...", "new_time": "...",
                        "name": "...", "impact": "...", "reason": "..."}],
        "additions": [{"date": "...", "time": "...", "name": "...",
                        "impact": "...", "reason": "..."}],
        "cancellations": [{"date": "...", "name": "...", "reason": "..."}]
    }
    """
    if not os.path.exists(OVERRIDE_FILE):
        return {"overrides": [], "additions": [], "cancellations": []}
    try:
        with open(OVERRIDE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "overrides": data.get("overrides", []),
            "additions": data.get("additions", []),
            "cancellations": data.get("cancellations", []),
        }
    except Exception:
        return {"overrides": [], "additions": [], "cancellations": []}


def get_upcoming_events(days=7, min_impact="HIGH"):
    """향후 N일 내 주요 경제 지표 발표 목록 (오버라이드 반영)."""
    now = datetime.now()
    cutoff = now + timedelta(days=days)
    impact_order = {"CRITICAL": 0, "HIGH": 1, "MED": 2, "LOW": 3}
    min_level = impact_order.get(min_impact, 2)

    overrides = load_overrides()

    # 취소된 이벤트 세트: (날짜, 지표명)
    cancelled = set()
    for c in overrides["cancellations"]:
        cancelled.add((c.get("date", ""), c.get("name", "")))

    # 변경된 이벤트 맵: (원래날짜, 지표명) → (새날짜, 새시간, 새영향도)
    changed = {}
    for o in overrides["overrides"]:
        key = (o.get("original_date", ""), o.get("name", ""))
        changed[key] = {
            "date": o.get("new_date", o.get("original_date", "")),
            "time": o.get("new_time", "22:30"),
            "impact": o.get("impact", "HIGH"),
            "reason": o.get("reason", ""),
        }

    events = []

    # 정적 캘린더 (취소/변경 반영)
    for date_str, time_str, name, impact in ECONOMIC_CALENDAR_2026:
        key = (date_str, name)

        # 취소된 이벤트 건너뜀
        if key in cancelled:
            continue

        # 변경된 이벤트 적용
        if key in changed:
            ch = changed[key]
            date_str = ch["date"]
            time_str = ch["time"]
            impact = ch["impact"]

        if impact_order.get(impact, 3) > min_level:
            continue
        event_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        if now < event_dt <= cutoff:
            events.append({
                "datetime": event_dt,
                "date": date_str,
                "time": time_str,
                "name": name,
                "impact": impact,
            })

    # 추가된 이벤트
    for a in overrides["additions"]:
        impact = a.get("impact", "HIGH")
        if impact_order.get(impact, 3) > min_level:
            continue
        try:
            date_str = a["date"]
            time_str = a.get("time", "22:30")
            event_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if now < event_dt <= cutoff:
                events.append({
                    "datetime": event_dt,
                    "date": date_str,
                    "time": time_str,
                    "name": a.get("name", "추가 지표"),
                    "impact": impact,
                })
        except (KeyError, ValueError):
            continue

    events.sort(key=lambda e: e["datetime"])
    return events


def calc_report_time(event_dt):
    """발표 시간 + 버퍼 → 보고서 실행 시간 계산."""
    report_dt = event_dt + timedelta(minutes=BUFFER_MINUTES)
    return report_dt


def get_current_crontab():
    """현재 crontab 내용 읽기."""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def update_crontab(events):
    """crontab에 경제 지표 보고서 스케줄 추가/갱신."""
    current = get_current_crontab()

    # 기존 auto-econ 항목 제거
    lines = [l for l in current.splitlines() if CRONTAB_TAG not in l]

    # 새 항목 추가
    added = []
    for event in events:
        report_dt = calc_report_time(event["datetime"])
        # 이미 지난 시간이면 건너뜀
        if report_dt < datetime.now():
            continue
        minute = report_dt.minute
        hour = report_dt.hour
        day = report_dt.day
        month = report_dt.month
        dow = "*"  # 요일 무관 (날짜로 특정)

        cron_line = (
            f"{minute} {hour} {day} {month} {dow} "
            f"{REPORT_SCRIPT} "
            f"{CRONTAB_TAG} {event['name']} ({event['impact']})"
        )
        lines.append(cron_line)
        added.append((report_dt, event["name"], event["impact"]))

    # crontab 저장
    new_crontab = "\n".join(lines) + "\n"
    proc = subprocess.run(
        ["crontab", "-"],
        input=new_crontab,
        capture_output=True,
        text=True,
    )

    if proc.returncode != 0:
        print(f"  crontab 업데이트 실패: {proc.stderr}")
        return []

    return added


def show_schedule(days=7):
    """이번 주 경제 지표 일정 표시."""
    events = get_upcoming_events(days=days, min_impact="MED")
    if not events:
        print("  향후 7일 내 주요 경제 지표 발표 없음")
        return

    print(f"  {'날짜':12s} {'시간':6s} {'영향':10s} {'지표'}")
    print(f"  {'─' * 55}")
    for e in events:
        report_dt = calc_report_time(e["datetime"])
        print(f"  {e['date']}  {e['time']}  {e['impact']:10s} {e['name']}")
        print(f"  {'':12s} → 보고서: {report_dt.strftime('%H:%M')} 자동 실행")


def main():
    print("=" * 55)
    print("경제 지표 기반 보고서 자동 스케줄링")
    print("=" * 55)

    # 오버라이드 상태 표시
    ov = load_overrides()
    n_ov = len(ov["overrides"]) + len(ov["additions"]) + len(ov["cancellations"])
    if n_ov > 0:
        print(f"\n[schedule_override.json 반영: {n_ov}건]")
        for o in ov["overrides"]:
            print(f"  변경: {o.get('name','')} {o.get('original_date','')} → {o.get('new_date','')} {o.get('new_time','')} ({o.get('reason','')})")
        for a in ov["additions"]:
            print(f"  추가: {a.get('name','')} {a.get('date','')} {a.get('time','')} ({a.get('reason','')})")
        for c in ov["cancellations"]:
            print(f"  취소: {c.get('name','')} {c.get('date','')} ({c.get('reason','')})")

    if "--show" in sys.argv:
        print("\n[이번 주 경제 지표 일정]")
        show_schedule(days=7)
        return

    # 1. 이번 주 이벤트 확인
    events = get_upcoming_events(days=7, min_impact="HIGH")
    print(f"\n[향후 7일 HIGH+ 이벤트: {len(events)}건]")
    show_schedule(days=7)

    # 2. crontab 업데이트
    if events:
        print(f"\n[crontab 업데이트]")
        added = update_crontab(events)
        for dt, name, impact in added:
            print(f"  + {dt.strftime('%m/%d %H:%M')} {name} ({impact})")
        if not added:
            print("  추가할 새 항목 없음 (이미 지난 이벤트)")
    else:
        # 이벤트 없어도 지난 항목 정리
        current = get_current_crontab()
        lines = [l for l in current.splitlines() if CRONTAB_TAG not in l]
        new_crontab = "\n".join(lines) + "\n"
        subprocess.run(["crontab", "-"], input=new_crontab, capture_output=True, text=True)
        print("\n  이번 주 HIGH+ 이벤트 없음. 지난 항목 정리 완료.")

    # 3. 현재 crontab 확인
    print(f"\n[현재 crontab]")
    current = get_current_crontab()
    for line in current.splitlines():
        if line.strip() and not line.startswith("#"):
            print(f"  {line}")


if __name__ == "__main__":
    main()
