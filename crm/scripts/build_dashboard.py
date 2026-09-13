#!/usr/bin/env python3
"""summary.json → 읽기용 대시보드(HTML, 개인정보 없음).

    python3 crm/scripts/build_dashboard.py   # crm/output/dashboard.html 생성
build_crm.py 를 돌린 뒤 실행하면 최신 집계로 다시 만들어진다.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = json.loads((ROOT / "output" / "summary.json").read_text(encoding="utf-8"))
OUT = ROOT / "output" / "dashboard.html"

o = S["overview"]; hs = S.get("history") or {}; ss = S.get("sends") or {}; rp = S.get("recipient_profile") or {}
tm = S.get("timing") or {}; tg = S.get("targets") or []; py = S.get("payments") or {}
E = html.escape


def bars(items, value_key="전환율%", label_key=None, n_key="발송", c_key="전환자", hollow=None, unit="%"):
    """가로 막대 차트 (단일 계열, 직접 라벨, 호버 툴팁). items: list of (label, dict)."""
    rows = [(k, v) for k, v in items]
    vmax = max([v[value_key] for _, v in rows] + [1])
    h = 26; gap = 8; pad_l = 118; w = 560; pad_r = 64
    height = len(rows) * (h + gap) + 8
    out = [f'<svg class="bar" viewBox="0 0 {w} {height}" role="img" aria-label="막대 차트">']
    for i, (k, v) in enumerate(rows):
        y = 4 + i * (h + gap)
        val = v[value_key]
        bw = max(2, (w - pad_l - pad_r) * val / vmax)
        cls = "hollow" if hollow and hollow(k, v) else ""
        tip = f"{k}: {v.get(n_key, '')}명 중 {v.get(c_key, '')}명 · {val}{unit}"
        out.append(f'<g class="row" tabindex="0"><title>{E(tip)}</title>')
        out.append(f'<text class="lbl" x="{pad_l - 10}" y="{y + h * 0.68}" text-anchor="end">{E(str(k))}</text>')
        out.append(f'<rect class="mark {cls}" x="{pad_l}" y="{y}" width="{bw:.1f}" height="{h}" rx="0" />')
        out.append(f'<text class="val" x="{pad_l + bw + 8:.1f}" y="{y + h * 0.68}">{val}{unit}<tspan class="sub"> · {v.get(n_key, "")}명</tspan></text>')
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)


def kpi(label, value, note):
    return f'<div class="kpi"><div class="k-label">{E(label)}</div><div class="k-value">{value}</div><div class="k-note">{E(note)}</div></div>'


# ---- 데이터 정리 ----
dim = rp.get("by_dimension", {})
def dim_items(name, order=None, drop=("미상",)):
    d = {k: v for k, v in dim.get(name, {}).items() if k not in drop}
    keys = [k for k in (order or []) if k in d] + [k for k in d if k not in (order or [])]
    return [(k, d[k]) for k in keys]

stage = dim_items("생애단계", ["활성", "휴면", "미이용", "이탈위험"])
pref = dim_items("시간성향", ["심야형", "낮형", "저녁형", "새벽·오전형"])
genre = dim_items("취향장르")
genre = sorted(genre, key=lambda kv: -kv[1]["전환율%"])
cc = dim_items("이력_최대배기량", ["미들급", "리터급", "쿼터급", "소형"])
consent = dim_items("마케팅상태", ["동의", "미응답", "미동의"])
branch = dim_items("주지점")
branch = [(k.replace("Yongsan", "용산").replace("Incheon", "인천").replace("Bundang", "분당").replace("Daegu", "대구").replace("Jeju", "제주").replace("Jinju", "진주"), v) for k, v in branch if v["발송"] >= 10]

slot_items = [(f"{r['발송요일']} {r['발송시간대'].split('(')[0]}", {"전환율%": r["전환율%"], "발송": r["발송"], "전환자": r["전환자"], "회차": r["회차"]}) for r in tm.get("slot", [])]
elapsed = tm.get("elapsed", [])
conv_hour = {int(k): v for k, v in tm.get("conv_hour", {}).items()}
pref_slot = tm.get("pref_x_slot", [])

camps = [r for r in ss.get("campaigns", []) if r["발송"] is not None and r["발송"] == r["발송"]]
by_round = {}
for r in camps:
    key = (r["발송일"], r["캠페인"])
    b = by_round.setdefault(key, {"발송": 0, "전환자": 0, "매출": 0, "근거": r["근거"], "타겟": []})
    if "대조군" in r["근거"]:
        continue
    b["발송"] += int(r["발송"]); b["전환자"] += int(r["전환자"]); b["매출"] += int(r["전환매출"]); b["타겟"].append(r["타겟"])
send_times = {r["발송일시"][:10]: (r["발송일시"][11:], r["요일"], r["시각근거"]) for r in tm.get("by_round", [])}

# 시간성향×슬롯 표 (pivot)
slots = ["오전(~12시)", "점심(12~15시)", "오후(15~18시)"]
prefs = ["낮형", "저녁형", "심야형"]
pv = {p: {s: None for s in slots} for p in prefs}
for r in pref_slot:
    if r["시간성향"] in pv and r["발송시간대"] in slots:
        pv[r["시간성향"]][r["발송시간대"]] = r

# ---- HTML ----
css = """
:root{color-scheme:light;
 --page:#f4f5f3;--surface:#ffffff;--ink:#15181b;--ink-2:#5b6168;--muted:#8a8f95;--hair:#e3e5e1;--rule:#c9cdc8;
 --accent:#1f5f8b;--accent-ink:#ffffff;--bar:#2a78d6;--bar-hollow:#2a78d6;
 --chip-a:#dcecd6;--chip-b:#fbefc9;--chip-c:#e8e9e6;--chip-x:#f6d2c6;--chip-ink:#15181b;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
 --page:#0f1113;--surface:#1a1d20;--ink:#f2f3f0;--ink-2:#b9bdb5;--muted:#8f948f;--hair:#2c3034;--rule:#3a3f44;
 --accent:#6fa8dc;--accent-ink:#0f1113;--bar:#3987e5;--bar-hollow:#3987e5;
 --chip-a:#2f4a2a;--chip-b:#4d4020;--chip-c:#2c3034;--chip-x:#5a2f28;--chip-ink:#f2f3f0;}}
:root[data-theme="dark"]{color-scheme:dark;
 --page:#0f1113;--surface:#1a1d20;--ink:#f2f3f0;--ink-2:#b9bdb5;--muted:#8f948f;--hair:#2c3034;--rule:#3a3f44;
 --accent:#6fa8dc;--accent-ink:#0f1113;--bar:#3987e5;--bar-hollow:#3987e5;
 --chip-a:#2f4a2a;--chip-b:#4d4020;--chip-c:#2c3034;--chip-x:#5a2f28;--chip-ink:#f2f3f0;}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font-family:"IBM Plex Sans KR","IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;font-size:15px;line-height:1.55;padding-block:0 48px;padding-inline:20px}
.mono{font-family:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;font-variant-numeric:tabular-nums}
.wrap{max-width:1120px;margin:0 auto}
header{padding-block:28px 18px;border-bottom:1px solid var(--rule);margin-bottom:24px}
.eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-2)}
h1{font-size:28px;line-height:1.2;margin:6px 0 8px;font-weight:600;text-wrap:balance}
.basis{color:var(--ink-2);font-size:14px;display:flex;flex-wrap:wrap;gap:6px 18px}
h2{font-size:19px;font-weight:600;margin:36px 0 6px;text-wrap:balance}
h2 + p.lead{margin:0 0 14px;color:var(--ink-2);max-width:68ch}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.kpi{background:var(--surface);border:1px solid var(--hair);padding:14px 16px}
.k-label{font-size:12px;color:var(--ink-2);letter-spacing:.04em}
.k-value{font-size:30px;font-weight:600;line-height:1.15;margin:4px 0 2px}
.k-value small{font-size:15px;font-weight:500;color:var(--ink-2);margin-left:4px}
.k-note{font-size:12.5px;color:var(--muted)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.grid2.two{grid-template-columns:repeat(auto-fit,minmax(420px,1fr))}
.panel{background:var(--surface);border:1px solid var(--hair);padding:14px 16px 10px}
.panel h3{font-size:14.5px;font-weight:600;margin:0 0 2px}
.panel .sub{font-size:12.5px;color:var(--muted);margin:0 0 8px}
svg.bar{width:100%;height:auto;display:block;overflow:visible}
svg.bar .lbl{font-size:12.5px;fill:var(--ink-2);font-family:inherit}
svg.bar .val{font-size:12.5px;fill:var(--ink);font-family:"IBM Plex Mono",ui-monospace,monospace;font-weight:600}
svg.bar .val .sub{fill:var(--muted);font-weight:400}
svg.bar .mark{fill:var(--bar)}
svg.bar .mark.hollow{fill:none;stroke:var(--bar-hollow);stroke-width:1.5;stroke-dasharray:4 3}
svg.bar .row:hover .mark,svg.bar .row:focus .mark{opacity:.8}
svg.bar .row:focus{outline:none}
.tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--page);font-size:12.5px;padding:6px 9px;border-radius:2px;opacity:0;transition:opacity .12s;z-index:9;max-width:280px}
table{border-collapse:collapse;width:100%;font-size:13.5px;background:var(--surface)}
.tablewrap{overflow-x:auto;border:1px solid var(--hair)}
th{text-align:left;font-weight:600;font-size:12px;letter-spacing:.04em;color:var(--ink-2);border-bottom:1px solid var(--rule);padding:9px 10px;white-space:nowrap;background:var(--surface);position:sticky;top:0}
td{padding:8px 10px;border-bottom:1px solid var(--hair);vertical-align:top}
td.num,th.num{text-align:right;font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.dim td{color:var(--muted)}
.chip{display:inline-block;font-size:11.5px;font-weight:600;padding:1px 7px;border-radius:2px;color:var(--chip-ink);letter-spacing:.03em}
.chip.A{background:var(--chip-a)}.chip.B{background:var(--chip-b)}.chip.C{background:var(--chip-c)}.chip.X{background:var(--chip-x)}
.callouts{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.call{border-left:3px solid var(--accent);background:var(--surface);padding:12px 14px}
.call b{display:block;margin-bottom:3px}
.call p{margin:0;color:var(--ink-2);font-size:14px}
.elapsed{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;align-items:end;height:120px;margin-top:6px}
.elapsed .col{display:flex;flex-direction:column;justify-content:flex-end;height:100%;gap:4px}
.elapsed .bar-v{background:var(--bar);min-height:2px}
.elapsed .cap{font-size:11px;color:var(--muted);text-align:center;line-height:1.2}
.elapsed .n{font-size:12px;text-align:center;font-family:"IBM Plex Mono",monospace}
.hours{display:grid;grid-template-columns:repeat(24,1fr);gap:2px;align-items:end;height:70px;margin-top:6px}
.hours .h{background:var(--bar);min-height:1px}
.hours .h.peak{background:var(--accent)}
.hourlab{display:grid;grid-template-columns:repeat(24,1fr);font-size:10px;color:var(--muted);font-family:"IBM Plex Mono",monospace;text-align:center}
.pivot td{text-align:right;font-family:"IBM Plex Mono",monospace}
.pivot td.best{font-weight:700;color:var(--accent)}
.foot{margin-top:36px;padding-top:14px;border-top:1px solid var(--rule);font-size:12.5px;color:var(--muted);max-width:80ch}
.foot p{margin:4px 0}
@media (prefers-reduced-motion:reduce){.tip{transition:none}}
@media (max-width:480px){h1{font-size:23px}.k-value{font-size:26px}}
"""

def num(x):
    return f"{int(x):,}"

kpis = [
    kpi("발송 가능 풀", f"{num(o.get('sendable_policy', 0))}<small>명</small>", "동의 + 설문 도입 전 미응답 · 미동의·수신거부·직원 제외"),
    kpi("발송 시점 활성 고객 전환율", f"{dim.get('생애단계', {}).get('활성', {}).get('전환율%', 0)}<small>%</small>", f"미이용 {dim.get('생애단계', {}).get('미이용', {}).get('전환율%', 0)}% · 휴면 {dim.get('생애단계', {}).get('휴면', {}).get('전환율%', 0)}% (완전 측정 {rp.get('measurable_sends', 0):,}건)"),
    kpi("문자 → 첫 결제 중앙값", f"{tm.get('elapsed_median_h', 0) / 24:.1f}<small>일</small>", f"24시간 내 {tm.get('within_24h_pct', 0)}% · 성과 판정은 D+14"),
    kpi("가장 반응 좋은 발송 슬롯", f"{slot_items[0][0] + ' 발송' if slot_items else '-'}", f"{slot_items[0][1]['전환율%'] if slot_items else 0}% · {slot_items[0][1]['회차'] if slot_items else ''} (명단 효과 포함)"),
]

round_rows = []
for (d, camp), b in sorted(by_round.items()):
    t, wd, src = send_times.get(d, ("", "", ""))
    rate = f"{b['전환자'] / b['발송'] * 100:.1f}%" if b["발송"] else "-"
    dim_cls = " class=\"dim\"" if "측정 불가" in b["근거"] else ""
    note = b["근거"].replace("명단 전수 대조 (발송 후 14일 내 유효 결제)", "완전 측정")
    round_rows.append(f"<tr{dim_cls}><td class=\"mono\">{d} {wd} {t}</td><td>{E(camp)}</td><td>{E(', '.join(b['타겟'][:4]))}{'…' if len(b['타겟']) > 4 else ''}</td><td class=\"num\">{num(b['발송'])}</td><td class=\"num\">{b['전환자']}</td><td class=\"num\">{rate}</td><td class=\"num\">{num(b['매출'])}</td><td>{E(note)}{' · 시각 ' + src if src else ''}</td></tr>")

target_rows = []
for t in tg:
    target_rows.append(f"<tr><td><span class=\"chip {t['우선순위']}\">{t['우선순위']}</span></td><td><b>{E(t['코드'])}</b> {E(t['타겟'])}</td><td class=\"num\">{num(t['인원'])}</td><td class=\"num\">{num(t['동의'])}</td><td>{E(t['실측 근거'])}</td><td>{E(t['권장 오퍼·문안'])}</td><td>{E(t['권장 발송 시점'])}</td></tr>")

el_max = max([r["전환자"] for r in elapsed] + [1])
el_cols = "".join(f'<div class="col"><div class="n">{r["전환자"]}</div><div class="bar-v" style="height:{r["전환자"] / el_max * 78:.0f}px"></div><div class="cap">{E(r["경과시간"])}</div></div>' for r in elapsed)
hmax = max(list(conv_hour.values()) + [1])
peak = sorted(conv_hour.items(), key=lambda kv: -kv[1])[:3]
peak_h = {k for k, _ in peak}
hour_cols = "".join(f'<div class="h{" peak" if h in peak_h else ""}" style="height:{conv_hour.get(h, 0) / hmax * 66:.0f}px" title="{h}시 {conv_hour.get(h, 0)}명"></div>' for h in range(24))
hour_lab = "".join(f"<div>{h if h % 3 == 0 else ''}</div>" for h in range(24))

pivot_rows = []
for p in prefs:
    cells = []
    best = max((pv[p][s]["전환율%"] for s in slots if pv[p][s]), default=None)
    for s_ in slots:
        r = pv[p][s_]
        if r is None:
            cells.append("<td>-</td>")
        else:
            cells.append(f"<td class=\"{'best' if r['전환율%'] == best else ''}\">{r['전환율%']}%<br><span style=\"color:var(--muted);font-size:11px\">{r['발송']}명</span></td>")
    pivot_rows.append(f"<tr><td style=\"text-align:left;font-family:inherit\">{p}</td>{''.join(cells)}</tr>")

page = f"""<title>아르테파인 CRM 대시보드</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600&family=IBM+Plex+Mono:wght@400;600&display=swap">
<style>{css}</style>
<div class="wrap">
<header>
  <div class="eyebrow">ARTEFINE · CRM 문자 캠페인</div>
  <h1>누구에게, 언제 보내면 결제로 이어지나</h1>
  <div class="basis">
    <span>회원 {num(o['total_members'])}명 · 설문 {num(o['survey_done'])} · 동의 {num(o['consent_yes'])}</span>
    <span>결제 이력 {E(hs.get('period', ''))} · 이용 고객 {num(hs.get('customers', 0))}</span>
    <span>문자 {num(ss.get('sends', 0))}건 · 수신자 {num(ss.get('recipients', 0))}명 · 대조군 {ss.get('holdout', 0)}</span>
    <span>갱신 {E(S['meta']['generated_at'])}</span>
  </div>
</header>

<div class="kpis">{''.join(kpis)}</div>

<h2>누구에게 보내면 반응하나</h2>
<p class="lead">전환 = 문자 발송 후 14일 안에 유효 결제. 생애단계는 발송 시점 기준. 결제 데이터가 14일 창을 완전히 덮는 회차({E(', '.join(rp.get('measurable_campaigns', [])))})만 집계.</p>
<div class="grid2">
  <div class="panel"><h3>발송 시점 생애단계</h3><p class="sub">활성 = 최근 30일 이용 · 이탈위험 = 2회 이상 & 31~90일 · 그 외 휴면</p>{bars(stage)}</div>
  <div class="panel"><h3>고객 시간성향</h3><p class="sub">결제 이력의 예약 시작 시각으로 판정 (심야 21~05시, 저녁 17~20시, 낮 10~16시)</p>{bars(pref)}</div>
  <div class="panel"><h3>취향 장르</h3><p class="sub">이용 차종의 장르 (가장 많이 탄 장르)</p>{bars(genre)}</div>
  <div class="panel"><h3>최대 이용 배기량</h3><p class="sub">스텝업 소구는 미들급 이용자에게</p>{bars(cc)}</div>
  <div class="panel"><h3>마케팅 수신 상태</h3><p class="sub">동의자가 미응답보다 2배 이상 반응</p>{bars(consent)}</div>
  <div class="panel"><h3>주 이용 지점</h3><p class="sub">발송 10명 이상 지점만</p>{bars(branch)}</div>
</div>

<h2>언제 보내면 반응하나</h2>
<p class="lead">발송 시각은 보고서 기록(7/25 토 10:00, 7/31·8/7 금 17:00, 8/22 토 14:28)과 추정(8/14, 9/4)을 함께 썼다. 슬롯 비교는 회차마다 명단이 달라 명단 효과가 섞여 있다.</p>
<div class="grid2 two">
  <div class="panel"><h3>발송 요일·시간대별 전환율</h3><p class="sub">같은 명단을 시각만 바꿔 나눠 보내는 A/B로 확인 필요</p>{bars(slot_items)}</div>
  <div class="panel"><h3>고객 시간성향 × 발송 시간대</h3><p class="sub">결제 이력이 있는 수신자만. 세 성향 모두 오후 발송이 가장 낮다</p>
    <div class="tablewrap"><table class="pivot"><thead><tr><th>시간성향</th>{''.join(f'<th class="num">{E(s)}</th>' for s in slots)}</tr></thead><tbody>{''.join(pivot_rows)}</tbody></table></div></div>
  <div class="panel"><h3>문자 받고 결제까지 걸린 시간</h3><p class="sub">전환자 {tm.get('n_conv_measured', 0)}명 · 중앙값 {tm.get('elapsed_median_h', 0)}시간 · 40%가 7일 이후</p><div class="elapsed">{el_cols}</div></div>
  <div class="panel"><h3>전환자의 첫 결제 시각</h3><p class="sub">낮 13~16시에 몰린다. 진한 막대가 상위 3개 시각</p><div class="hours">{hour_cols}</div><div class="hourlab">{hour_lab}</div></div>
</div>

<h2>회차별 성과</h2>
<p class="lead">명단 전수 대조 기준. 회색 행은 결제 데이터가 아직 14일 창을 덮지 못한 회차.</p>
<div class="tablewrap"><table><thead><tr><th>발송 일시</th><th>캠페인</th><th>타겟</th><th class="num">발송</th><th class="num">전환</th><th class="num">전환율</th><th class="num">전환 매출(원)</th><th>측정</th></tr></thead><tbody>{''.join(round_rows)}</tbody></table></div>

<h2>다음 회차 타겟</h2>
<p class="lead">명단은 발송용 엑셀(CRM_발송용)의 같은 코드 시트에 있다. 한 사람이 여러 타겟에 들어가면 우선순위 높은 한 곳에서만 보낸다(월 2통 상한).</p>
<div class="tablewrap"><table><thead><tr><th></th><th>타겟</th><th class="num">인원</th><th class="num">동의</th><th>왜</th><th>무엇을</th><th>언제</th></tr></thead><tbody>{''.join(target_rows)}</tbody></table></div>

<h2>다음 회차 설계 원칙</h2>
<div class="callouts">
  <div class="call"><b>최근 30일 내 이용자부터</b><p>활성 {dim.get('생애단계', {}).get('활성', {}).get('전환율%', 0)}% vs 미이용 {dim.get('생애단계', {}).get('미이용', {}).get('전환율%', 0)}%. 휴면·이탈위험은 문자보다 전화나 라인업 교체 명분이 필요하다.</p></div>
  <div class="call"><b>오전~점심 발송을 시험</b><p>낮형·저녁형·심야형 모두 오후 15~18시 발송이 가장 낮았다. 같은 명단을 반으로 나눠 토 10:00 vs 금 17:00으로 비교한다.</p></div>
  <div class="call"><b>성과 판정은 D+14</b><p>결제의 60%가 발송 3일 이후, 40%가 7일 이후. D+7 집계는 전환을 절반 가까이 놓친다.</p></div>
  <div class="call"><b>투어러 취향은 신차 입고 때만</b><p>투어러 {dim.get('취향장르', {}).get('투어러', {}).get('전환율%', 0)}%. 현재 라인업에 BMW 투어러가 없다. 스포츠·네이키드·크루저·어드벤처에 집중.</p></div>
  <div class="call"><b>대조군 10%를 매 회차</b><p>9/4에 처음 둔 홀드아웃 112명이 네 층 모두 발송 쪽보다 낮았다. 3~4회 쌓이면 순효과가 안정된다.</p></div>
  <div class="call"><b>규정</b><p>(광고) 표기, 080 수신거부, 08~20시 발송. 미동의·수신거부는 명단에서 자동 제외되어 있다.</p></div>
</div>

<div class="foot">
  <p>데이터: 회원 설문 내보내기 {E(S['meta']['source_file'])}, 결제상세 {E(hs.get('period', ''))} (예약이력으로 5/19~6/21 보강), 문자 발송 명단 6회 + 홀드아웃, 레인조아카데미 회원 DB, 방문통계 월별 리포트.</p>
  <p>개인정보는 이 페이지에 없다. 명단은 CRM_발송용 / CRM_타겟통합 엑셀에만 있다. 새 파일을 넣고 build_crm.py → build_dashboard.py 를 실행하면 갱신된다.</p>
</div>
</div>
<div class="tip" id="tip" aria-hidden="true"></div>
<script>
(function(){{
  var tip=document.getElementById('tip');
  document.querySelectorAll('svg.bar .row').forEach(function(g){{
    var t=g.querySelector('title'); if(!t) return; var text=t.textContent; t.remove();
    g.addEventListener('mousemove',function(e){{tip.textContent=text;tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY+12)+'px';tip.style.opacity=1;}});
    g.addEventListener('mouseleave',function(){{tip.style.opacity=0;}});
    g.addEventListener('focus',function(){{var r=g.getBoundingClientRect();tip.textContent=text;tip.style.left=(r.left+120)+'px';tip.style.top=(r.top-30)+'px';tip.style.opacity=1;}});
    g.addEventListener('blur',function(){{tip.style.opacity=0;}});
  }});
}})();
</script>
"""
OUT.write_text(page, encoding="utf-8")
print(f"dashboard: {OUT} ({OUT.stat().st_size:,} bytes)")
