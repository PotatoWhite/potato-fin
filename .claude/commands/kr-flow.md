---
description: 한국 5종목 즉시 수급 조회 (외인/기관/개인 + 거래원 TOP5 + 외국인 보유율)
---

# 한국 수급 실측 (즉시)

```python
from pathlib import Path
import sys
sys.path.insert(0, '/home/bravopotato/Spaces/finspace/potato-fin')
import naver_finance as nf
import naver_broker as nb

TICKERS = [
    ("005930.KS", "삼성전자"),
    ("000660.KS", "SK하이닉스"),
    ("035420.KS", "NAVER"),
    ("195940.KQ", "HK이노엔"),
    ("429760.KS", "PLUS 미국S&P500"),
]

for tk, name in TICKERS:
    print(f"\n### {tk} {name}")
    # 3일 수급
    flow = nf.get_kr_investor_flow(tk, days=3)
    if flow:
        s = flow["summary"]
        verdict = "🚨 분배" if (s["foreign_net_total"]<0 and s["organ_net_total"]<0 and s["individual_net_total"]>0) \
            else "✅ 최강매수" if (s["foreign_net_total"]>0 and s["organ_net_total"]>0 and s["individual_net_total"]<0) \
            else "🟢 외인매수" if s["foreign_net_total"]>0 else "🔴 외인매도" if s["foreign_net_total"]<0 else "🟡 혼재"
        print(f"  3일 수급: 외 {s['foreign_net_total']:+,} / 기 {s['organ_net_total']:+,} / 개 {s['individual_net_total']:+,}")
        print(f"  외인 보유율 {s['foreign_hold_latest']}% ({s['foreign_hold_change']:+.3f}%p 3일)")
        print(f"  판정: {verdict}")

    # 거래원 TOP5 (당일)
    brokers = nb.get_brokers(tk, trader_day=1)
    if brokers:
        b = brokers["summary"]
        print(f"  거래원: 외국계 {b['foreign_net']:+,}주 / 국내 {b['domestic_net']:+,}주")

    # 펀더멘탈
    f = nf.get_kr_fundamentals(tk)
    if f:
        print(f"  PER {f.get('per')} / PBR {f.get('pbr')} / 외인소진율 {f.get('foreign_rate_pct')}%")
```

## 판정 기준 (CLAUDE.md)

| 외인 | 기관 | 개인 | 판정 |
|------|------|------|------|
| - | - | + | 🚨 **분배 위험** — 추격 금지 |
| + | + | - | ✅ **최강 매수 신호** |
| + | ± | | 🟢 외인 매수 |
| - | ± | | 🔴 외인 매도 |

## 출력

Terminal 즉시. Notion 업로드 안 함 (단순 조회용).

※ 정기 분석은 `/report-kr` 또는 `/deep-dive` 사용.
