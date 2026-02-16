"""
금융 에이전트 — 주식/포트폴리오/투자 (기존 telegram_bot.py 로직)

기존 슬래시 명령어와 금융 대화를 모두 처리한다.
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from agents import BaseAgent, register_agent

STOCK_DIR = Path(__file__).resolve().parent.parent
CLAUDE_PATH = "/home/linuxbrew/.linuxbrew/bin/claude"

# 실행 가능한 스크립트 작업 정의
EXECUTE_TASKS = {
    'update': {
        'cmd': [str(STOCK_DIR / '.venv/bin/python3'), str(STOCK_DIR / '주가_업데이트.py')],
        'name': '주가 업데이트',
        'timeout': 120,
        'bg': False,
    },
    'us_report': {
        'cmd': ['bash', str(STOCK_DIR / 'run_report.sh')],
        'name': 'US 보고서 생성',
        'timeout': 900,
        'bg': True,
        'cost': '$10-15 (Opus)',
    },
    'korea_report': {
        'cmd': ['bash', str(STOCK_DIR / 'run_korea_report.sh')],
        'name': '한국 보고서 생성',
        'timeout': 900,
        'bg': True,
        'cost': '$8-10 (Opus)',
    },
    'premarket': {
        'cmd': ['bash', str(STOCK_DIR / 'run_premarket.sh')],
        'name': '장전 브리핑',
        'timeout': 600,
        'bg': True,
        'cost': '$3-4 (Sonnet)',
    },
    'midcheck': {
        'cmd': ['bash', str(STOCK_DIR / 'run_midcheck.sh')],
        'name': '장중 체크',
        'timeout': 600,
        'bg': True,
        'cost': '$3-4 (Sonnet)',
    },
    'alert_run': {
        'cmd': [str(STOCK_DIR / '.venv/bin/python3'), str(STOCK_DIR / 'price_alerts.py')],
        'name': '알림 체크',
        'timeout': 60,
        'bg': False,
    },
    'monitor_run': {
        'cmd': [str(STOCK_DIR / '.venv/bin/python3'), str(STOCK_DIR / 'news_monitor.py')],
        'name': '뉴스 감시',
        'timeout': 120,
        'bg': False,
    },
}

# 한글 종목명 → 티커 별칭
ALIASES = {
    '삼성': '005930.KS', '삼전': '005930.KS', '삼성전자': '005930.KS',
    'sk': '000660.KS', 'sk하이닉스': '000660.KS', '하이닉스': '000660.KS',
    '네이버': '035420.KS', 'naver': '035420.KS',
    '이노엔': '195940.KQ', 'hk이노엔': '195940.KQ', '케이캡': '195940.KQ',
    '엔비디아': 'NVDA', '테슬라': 'TSLA', '구글': 'GOOGL', '마소': 'MSFT',
    '마이크로소프트': 'MSFT', '팔란티어': 'PLTR', '퀄컴': 'QCOM',
    '셰브론': 'CVX', '엑슨': 'XOM', '유나이티드': 'UNH', '바이엘': 'BAYN.DE',
    '사카타': '1377.T',
}


def _ensure_path():
    if str(STOCK_DIR) not in sys.path:
        sys.path.insert(0, str(STOCK_DIR))


# ── 금융 명령어 (기존 그대로) ──────────────────────────

def cmd_thesis() -> str:
    _ensure_path()
    from update_thesis import format_thesis_summary
    return format_thesis_summary()


def cmd_price(ticker: str = '') -> str:
    import yfinance as yf
    _ensure_path()
    from update_thesis import load_thesis, ALL_TICKERS, TICKER_NAMES

    thesis = load_thesis()
    tickers_data = thesis.get('tickers', {})

    if ticker:
        ticker = ticker.upper()
        matches = [t for t in ALL_TICKERS if ticker in t or ticker in t.split('.')[0]]
        if not matches:
            return f"종목을 찾을 수 없습니다: {ticker}"

        target = matches[0]
        try:
            data = yf.download([target], period='2d', progress=False, group_by='ticker')
            try:
                close = data[target]['Close'].dropna()
            except (KeyError, TypeError):
                close = data['Close'].dropna()
                if hasattr(close, 'columns'):
                    close = close[target].dropna()
            if len(close) >= 2:
                price = float(close.iloc[-1])
                prev = float(close.iloc[-2])
                change = price - prev
                change_pct = change / prev * 100
            elif len(close) == 1:
                price = float(close.iloc[-1])
                change = 0
                change_pct = 0
            else:
                return f"{target}: 가격 조회 실패"
        except Exception as e:
            return f"{target}: 가격 조회 실패 ({e})"

        sign = '+' if change >= 0 else ''
        name = TICKER_NAMES.get(target, target)

        lines = [f"*{name}* ({target})"]
        if '.KS' in target or '.KQ' in target:
            lines.append(f"현재가: ₩{price:,.0f} ({sign}{change:,.0f} / {sign}{change_pct:.1f}%)")
        elif '.T' in target:
            lines.append(f"현재가: ¥{price:,.0f} ({sign}{change:,.0f} / {sign}{change_pct:.1f}%)")
        elif '.DE' in target:
            lines.append(f"현재가: €{price:.2f} ({sign}{change:.2f} / {sign}{change_pct:.1f}%)")
        else:
            lines.append(f"현재가: ${price:.2f} ({sign}{change:.2f} / {sign}{change_pct:.1f}%)")

        tdata = tickers_data.get(target, {})
        if tdata:
            j = {'buy': '매수', 'sell': '매도', 'hold': '보유', 'watch': '관망'}.get(
                tdata.get('judgment', ''), '?')
            d = {'bullish': '강세', 'bearish': '약세', 'neutral': '중립',
                 'mild_bullish': '약강세', 'mild_bearish': '약약세'}.get(
                tdata.get('direction', ''), '?')
            conv = tdata.get('conviction', 5)
            score = tdata.get('scores', {}).get('total', 0)
            pred = tdata.get('predictions', {}).get('5d', {}).get('price', '?')
            stop = tdata.get('stop_loss', '?')
            target_p = tdata.get('target', '?')

            lines.append(f"테제: {j} / {d} (확신 {conv}/10)")
            lines.append(f"점수: {score:+.1f}")
            lines.append(f"5일 예측: {pred}")
            lines.append(f"손절: {stop} | 목표: {target_p}")
            labels = tdata.get('special_labels', [])
            if labels:
                lines.append(f"경고: {', '.join(labels)}")

        return '\n'.join(lines)

    else:
        try:
            _ensure_path()
            from update_thesis import ALL_TICKERS, TICKER_NAMES
            data = yf.download(ALL_TICKERS, period='2d', progress=False, group_by='ticker')
        except Exception as e:
            return f"가격 조회 실패: {e}"

        lines = ["*전 종목 현재가*", ""]
        for t in ALL_TICKERS:
            try:
                if len(ALL_TICKERS) == 1:
                    col = data['Close'].dropna()
                else:
                    col = data[t]['Close'].dropna()
                if len(col) >= 2:
                    price = float(col.iloc[-1])
                    prev = float(col.iloc[-2])
                    pct = (price - prev) / prev * 100
                elif len(col) == 1:
                    price = float(col.iloc[-1])
                    pct = 0
                else:
                    continue
            except Exception:
                continue

            sign = '+' if pct >= 0 else ''
            name = TICKER_NAMES.get(t, t)[:6]
            if '.KS' in t or '.KQ' in t:
                p_str = f"₩{price:>8,.0f}"
            elif '.T' in t:
                p_str = f"¥{price:>6,.0f}"
            elif '.DE' in t:
                p_str = f"€{price:>7.2f}"
            else:
                p_str = f"${price:>7.2f}"
            lines.append(f"`{name:<6} {p_str} {sign}{pct:.1f}%`")

        return '\n'.join(lines)


def cmd_portfolio() -> str:
    _ensure_path()
    from portfolio_tracker import format_summary
    return format_summary()


def cmd_weekly() -> str:
    _ensure_path()
    from update_thesis import weekly_retrospective
    return weekly_retrospective()


def cmd_validate() -> str:
    _ensure_path()
    from validate_report import validate_report, format_result
    report_dir = STOCK_DIR / "보고서"
    reports = sorted(report_dir.glob("20*.md"))
    if not reports:
        return "보고서 없음"
    latest = reports[-1]
    result = validate_report(str(latest))
    return format_result(result)


def cmd_report() -> str:
    report_dir = STOCK_DIR / "보고서"
    reports = sorted(report_dir.glob("20*.md"))
    if not reports:
        return "보고서 없음"

    latest = reports[-1]
    text = latest.read_text(encoding='utf-8')
    filename = latest.stem

    lines = [f"*최신 보고서* ({filename})", ""]
    for line in text.split('\n')[:5]:
        if '총 평가' in line or '총평가' in line or '총 손익' in line:
            lines.append(line.strip().lstrip('> '))
            break

    in_events = False
    event_count = 0
    for line in text.split('\n'):
        if '핵심 이벤트' in line:
            in_events = True
            lines.append("")
            lines.append("*핵심 이벤트:*")
            continue
        if in_events and '|' in line and '---' not in line and '시간' not in line:
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 3:
                lines.append(f"  {parts[0]} {parts[1]} {parts[3] if len(parts) > 3 else ''}")
                event_count += 1
                if event_count >= 5:
                    break

    in_action = False
    action_count = 0
    for line in text.split('\n'):
        if '액션 플랜' in line and '오늘' in line:
            in_action = True
            lines.append("")
            lines.append("*액션 플랜:*")
            continue
        if in_action and '|' in line and '---' not in line and '액션' not in line:
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 3:
                lines.append(f"  {parts[0]} {parts[1]} {parts[2]}")
                action_count += 1
                if action_count >= 5:
                    break

    if len(lines) <= 2:
        for line in text.split('\n')[:10]:
            if line.strip():
                lines.append(line.strip())

    return '\n'.join(lines)


def cmd_alert() -> str:
    config_path = STOCK_DIR / "alert_config.json"
    if not config_path.exists():
        return "alert_config.json 없음"

    config = json.loads(config_path.read_text(encoding='utf-8'))
    alerts = config.get('alerts', {})

    lines = ["*알림 설정 현황*", ""]
    lines.append("`종목     손절      목표     스윙`")
    lines.append("`" + "-" * 35 + "`")

    for ticker, cfg in sorted(alerts.items()):
        name = cfg.get('name', ticker)[:6]
        sl = cfg.get('stop_loss')
        tgt = cfg.get('target')
        swing = cfg.get('swing_pct', 3.0)

        if '.KS' in ticker or '.KQ' in ticker:
            sl_s = f"₩{sl:,.0f}" if sl else "미설정"
            tgt_s = f"₩{tgt:,.0f}" if tgt else "미설정"
        else:
            sl_s = f"${sl:.1f}" if sl else "미설정"
            tgt_s = f"${tgt:.1f}" if tgt else "미설정"

        lines.append(f"`{name:<6} {sl_s:>8} {tgt_s:>8} {swing:.0f}%`")

    updated = config.get('_updated', '?')
    lines.append(f"\n_업데이트: {updated}_")
    return '\n'.join(lines)


def cmd_snapshot() -> str:
    _ensure_path()
    from portfolio_tracker import take_snapshot

    snap = take_snapshot()
    total = snap['total_krw']
    pnl = snap['total_pnl_krw']
    pnl_pct = snap['total_pnl_pct']

    sign = '+' if pnl >= 0 else ''
    lines = [f"*포트폴리오 스냅샷* ({snap['date']} {snap['time']})"]
    lines.append(f"총 평가: ₩{total:,}")
    lines.append(f"손익: {sign}₩{pnl:,} ({sign}{pnl_pct}%)")

    fx = snap.get('fx', {})
    if fx.get('USD'):
        lines.append(f"환율: ${fx['USD']:,.0f}")

    tickers = snap.get('tickers', {})
    if tickers:
        sorted_t = sorted(tickers.items(), key=lambda x: x[1].get('pnl_pct', 0), reverse=True)
        lines.append("")
        lines.append("*상위:*")
        for t, d in sorted_t[:5]:
            s = '+' if d['pnl_pct'] >= 0 else ''
            lines.append(f"  {t}: {s}{d['pnl_pct']}%")
        lines.append("*하위:*")
        for t, d in sorted_t[-3:]:
            s = '+' if d['pnl_pct'] >= 0 else ''
            lines.append(f"  {t}: {s}{d['pnl_pct']}%")

    return '\n'.join(lines)


def cmd_monitor() -> str:
    data_dir = STOCK_DIR / "data" / "monitor"
    if not data_dir.exists():
        return "감시 데이터 없음"

    latest = data_dir / "latest.json"
    if not latest.exists():
        return "latest.json 없음"

    snap = json.loads(latest.read_text(encoding='utf-8'))
    lines = [f"*감시병 현황* ({snap.get('timestamp', '?')[:16]})"]

    triggers = snap.get('triggers', [])
    if triggers:
        lines.append(f"\n*긴급 {len(triggers)}건:*")
        for t in triggers[:5]:
            ticker = t.get('ticker', '?')
            detail = t.get('detail', '') or t.get('event', '') or t.get('type', '알림')
            lines.append(f"  {ticker}: {detail}")
    else:
        lines.append("긴급 이벤트 없음")

    prices = snap.get('prices', {})
    if prices:
        movers = []
        for ticker, pdata in prices.items():
            change = pdata.get('change_pct', 0)
            if abs(change) >= 1.0:
                movers.append((ticker, change))
        if movers:
            lines.append(f"\n*변동 종목:*")
            for t, c in sorted(movers, key=lambda x: abs(x[1]), reverse=True)[:5]:
                s = '+' if c >= 0 else ''
                lines.append(f"  {t}: {s}{c:.1f}%")

    events = snap.get('events', [])
    if events:
        lines.append(f"\n*예정 이벤트:*")
        for e in events[:3]:
            lines.append(f"  D-{e.get('days_until', '?')} {e.get('name', '?')}")

    return '\n'.join(lines)


def cmd_accuracy() -> str:
    thesis_path = STOCK_DIR / "investment_thesis.json"
    if not thesis_path.exists():
        return "투자 테제 파일 없음"

    thesis = json.loads(thesis_path.read_text(encoding='utf-8'))
    acc = thesis.get('accuracy', {})
    tickers_data = thesis.get('tickers', {})

    total = acc.get('total_predictions', 0)
    dir_rate = acc.get('direction_rate', 0)
    avg_err = acc.get('avg_error_pct', 0)
    bias = acc.get('systematic_bias', 'none')
    worst = acc.get('worst_tickers', [])
    best = acc.get('best_tickers', [])

    lines = ["*예측 정확도 대시보드*", ""]
    lines.append(f"총 예측: {total}건")
    lines.append(f"방향 적중률: {dir_rate:.1f}%")
    lines.append(f"평균 오차: {avg_err:.1f}%")
    lines.append(f"체계적 편향: {bias}")

    if best:
        lines.append(f"\n최고 종목: {', '.join(best[:3])}")
    if worst:
        lines.append(f"최악 종목: {', '.join(worst[:3])}")

    conv_list = [(t, td.get('conviction', 5)) for t, td in tickers_data.items()]
    conv_list.sort(key=lambda x: x[1], reverse=True)
    lines.append("\n*확신도 순위:*")
    for t, c in conv_list:
        bar = '█' * c + '░' * (10 - c)
        lines.append(f"`{t:<10} {bar} {c}/10`")

    weekly_rate = acc.get('weekly_direction_rate')
    if weekly_rate is not None:
        weekly_date = acc.get('weekly_date', '?')
        lines.append(f"\n주간 방향적중: {weekly_rate:.0f}% ({weekly_date})")

    return '\n'.join(lines)


# ── 실행/개발 명령 ─────────────────────────────────────

def detect_execute(text: str) -> str | None:
    """실행 명령 감지."""
    low = text.lower().strip()
    if ('한국' in low or 'kr' in low) and ('보고서' in low or '리포트' in low):
        if any(v in low for v in ['만들', '써', '생성', '돌려', '실행']):
            return 'korea_report'
    if ('보고서' in low or '리포트' in low):
        if any(v in low for v in ['만들', '써', '생성', '돌려', '실행']):
            return 'us_report'
    if any(kw in low for kw in ['장전 브리핑', '프리마켓 브리핑', '장전 분석']):
        return 'premarket'
    if any(kw in low for kw in ['장중 체크', '장중 점검', '미드체크']):
        return 'midcheck'
    if any(kw in low for kw in ['주가 업데이트', '주가 갱신', '가격 업데이트', '가격 갱신']):
        return 'update'
    if low.strip() in ['업데이트해', '업데이트 해', '갱신해', '업뎃해', '업데이트', '갱신']:
        return 'update'
    if ('알림' in low or '알럿' in low) and any(v in low for v in ['실행', '체크해', '확인해', '돌려']):
        return 'alert_run'
    if ('뉴스' in low or '감시' in low) and any(v in low for v in ['실행해', '수집해', '돌려']):
        return 'monitor_run'
    return None


def handle_execute(action: str, chat_id: str, send_fn) -> str | None:
    """스크립트 실행."""
    task = EXECUTE_TASKS.get(action)
    if not task:
        return f"알 수 없는 작업: {action}"

    name = task['name']
    cost = task.get('cost', '')
    cost_note = f" (예상 비용: {cost})" if cost else ""

    if task.get('bg'):
        send_fn(f"⏳ {name} 시작{cost_note}...\n완료되면 알려드리겠습니다.", chat_id)

        def _run():
            try:
                result = subprocess.run(
                    task['cmd'],
                    capture_output=True, text=True,
                    timeout=task['timeout'],
                    cwd=str(STOCK_DIR),
                    env={**os.environ,
                         'PATH': f"{STOCK_DIR / '.venv/bin'}:/home/linuxbrew/.linuxbrew/bin:{os.environ.get('PATH', '')}"}
                )
                if result.returncode == 0:
                    output = result.stdout.strip()
                    if len(output) > 2000:
                        output = output[-2000:]
                    send_fn(f"✅ {name} 완료\n\n{output}", chat_id)
                else:
                    err = result.stderr.strip()[-500:] if result.stderr else "알 수 없는 오류"
                    send_fn(f"❌ {name} 실패 (code {result.returncode})\n{err}", chat_id)
            except subprocess.TimeoutExpired:
                send_fn(f"⏰ {name} 시간 초과 ({task['timeout']//60}분)", chat_id)
            except Exception as e:
                send_fn(f"❌ {name} 오류: {e}", chat_id)

        threading.Thread(target=_run, daemon=True).start()
        return None
    else:
        try:
            result = subprocess.run(
                task['cmd'],
                capture_output=True, text=True,
                timeout=task['timeout'],
                cwd=str(STOCK_DIR),
                env={**os.environ,
                     'PATH': f"{STOCK_DIR / '.venv/bin'}:{os.environ.get('PATH', '')}"}
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                if len(output) > 3000:
                    output = output[-3000:]
                return f"✅ {name} 완료\n\n{output}"
            else:
                err = result.stderr.strip()[-500:] if result.stderr else "알 수 없는 오류"
                return f"❌ {name} 실패\n{err}"
        except subprocess.TimeoutExpired:
            return f"⏰ {name} 시간 초과"
        except Exception as e:
            return f"❌ {name} 오류: {e}"


def _build_portfolio_context() -> str:
    """포트폴리오 + 테제 + 감시 데이터 → 대화 컨텍스트."""
    parts = []
    _ensure_path()

    try:
        from portfolio_tracker import format_summary
        parts.append(format_summary())
    except Exception:
        pass

    try:
        from update_thesis import format_thesis_summary
        parts.append(format_thesis_summary())
    except Exception:
        pass

    latest = STOCK_DIR / "data" / "monitor" / "latest.json"
    if latest.exists():
        try:
            snap = json.loads(latest.read_text(encoding='utf-8'))
            triggers = snap.get('triggers', [])
            if triggers:
                parts.append(f"긴급 트리거: {json.dumps(triggers[:5], ensure_ascii=False)}")
            events = snap.get('events', [])
            if events:
                parts.append(f"예정 이벤트: {json.dumps(events[:5], ensure_ascii=False)}")
        except Exception:
            pass

    return '\n---\n'.join(parts)


def handle_conversation(text: str, chat_id: str, context: dict) -> str:
    """Claude Sonnet 금융 대화."""
    conversations = context.get('conversation', [])
    history_lines = []
    for m in conversations[-6:]:
        role = '사용자' if m.get('role') == 'user' else '관리자'
        history_lines.append(f"{role}: {m.get('content', '')}")
    history = '\n'.join(history_lines)

    pf_context = _build_portfolio_context()

    prompt = f"""당신은 사용자의 전담 금융자산 관리자다.
사용자와 텔레그램으로 자연스럽게 대화한다.

포트폴리오 현황:
{pf_context}

최근 대화:
{history}

사용자: {text}

규칙:
- 텔레그램이므로 3000자 이내, 핵심 위주로 답하라
- 포트폴리오 데이터와 수치를 기반으로 구체적으로 답하라
- 매수/매도 의견을 구할 때: 종목, 근거(기술적+펀더), 리스크, 구체적 가격대를 제시하라
- 시장 상황 질문: 최신 데이터 기반으로 답하되, 모르면 모른다고 하라
- 이전 대화 맥락을 유지하라
- "모니터링 중", "지켜보겠습니다" 같은 회피성 답변 금지. 판단을 내려라.
- 반말/존댓말은 사용자의 톤에 맞춰라
- 한국어로 답하라"""

    try:
        result = subprocess.run(
            [CLAUDE_PATH, '-p', prompt,
             '--model', 'sonnet',
             '--max-budget-usd', '1',
             '--permission-mode', 'bypassPermissions',
             '--allowedTools', ''],
            capture_output=True, text=True, timeout=90,
            cwd=str(STOCK_DIR),
            env={**os.environ, 'CLAUDECODE': ''}
        )
        response = result.stdout.strip()
        if response:
            return response
        if result.stderr:
            return f"처리 중 오류: {result.stderr[:200]}"
        return "메시지를 이해했지만 답을 생성하지 못했습니다."
    except subprocess.TimeoutExpired:
        return "응답 시간 초과. 다시 시도해 주세요."
    except Exception as e:
        return f"처리 실패: {e}"


# ── FinanceAgent 클래스 ────────────────────────────────

class FinanceAgent(BaseAgent):
    name = 'finance'
    description = '주식/포트폴리오/투자 분석'
    emoji = '💰'

    # 슬래시 명령어 매핑
    SLASH_COMMANDS = {
        '/t': lambda args: cmd_thesis(),
        '/thesis': lambda args: cmd_thesis(),
        '/p': lambda args: cmd_price(args),
        '/price': lambda args: cmd_price(args),
        '/pf': lambda args: cmd_portfolio(),
        '/portfolio': lambda args: cmd_portfolio(),
        '/s': lambda args: cmd_snapshot(),
        '/snapshot': lambda args: cmd_snapshot(),
        '/r': lambda args: cmd_report(),
        '/report': lambda args: cmd_report(),
        '/a': lambda args: cmd_alert(),
        '/alert': lambda args: cmd_alert(),
        '/m': lambda args: cmd_monitor(),
        '/monitor': lambda args: cmd_monitor(),
        '/ac': lambda args: cmd_accuracy(),
        '/accuracy': lambda args: cmd_accuracy(),
        '/w': lambda args: cmd_weekly(),
        '/weekly': lambda args: cmd_weekly(),
        '/v': lambda args: cmd_validate(),
        '/validate': lambda args: cmd_validate(),
    }

    def handle_slash(self, cmd: str, args: str) -> str | None:
        handler = self.SLASH_COMMANDS.get(cmd)
        if handler:
            return handler(args)
        return None

    def handle(self, text: str, chat_id: str, context: dict) -> str:
        low = text.lower().strip()
        send_fn = context.get('send_fn')

        # 실행 명령 감지
        action = detect_execute(low)
        if action:
            if not send_fn:
                send_fn = lambda msg, cid: print(msg)  # --once 모드 폴백
            result = handle_execute(action, chat_id, send_fn)
            return result if result else ''

        # 종목명/티커 매칭 → 가격 조회
        _ensure_path()
        from update_thesis import ALL_TICKERS, TICKER_NAMES
        name_to_ticker = {v: k for k, v in TICKER_NAMES.items()}

        matched_ticker = None

        for alias, ticker in ALIASES.items():
            if alias in low:
                matched_ticker = ticker
                break
        if not matched_ticker:
            for name, ticker in name_to_ticker.items():
                if name.lower() in low:
                    matched_ticker = ticker
                    break
        if not matched_ticker:
            for t in ALL_TICKERS:
                if t.lower() in low or t.split('.')[0].lower() in low:
                    matched_ticker = t
                    break

        if matched_ticker:
            return cmd_price(matched_ticker)

        # 키워드 → 기존 명령
        keyword_map = [
            (['보고서', '리포트', '분석'], cmd_report),
            (['포트폴리오', '평가', '총액', '자산', '얼마야'], lambda: cmd_snapshot()),
            (['스냅샷'], lambda: cmd_snapshot()),
            (['테제', '판단', '전략'], cmd_thesis),
            (['알림', '손절', '목표가', '알럿'], cmd_alert),
            (['감시', '모니터', '감시병'], cmd_monitor),
            (['정확도', '예측', '적중'], cmd_accuracy),
            (['주간', '회고', '리뷰'], cmd_weekly),
            (['검증', '밸리'], cmd_validate),
            (['전종목', '전체', '다보여', '종목들'], lambda: cmd_price('')),
        ]
        for keywords, func in keyword_map:
            if any(kw in low for kw in keywords):
                return func()

        # 금융 대화
        return handle_conversation(text, chat_id, context)

    def get_help(self) -> str:
        return """💰 *금융 에이전트*
/p — 전 종목 현재가
/p NVDA — 종목 상세
/pf — 포트폴리오 추이
/s — 실시간 스냅샷
/t — 투자 테제
/r — 최신 보고서
/a — 알림 설정
/m — 감시병 현황
/ac — 예측 정확도
/w — 주간 회고
/v — 보고서 검증"""


# 인스턴스 생성 & 등록
finance_agent = FinanceAgent()
register_agent(finance_agent)
