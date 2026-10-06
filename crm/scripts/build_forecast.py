#!/usr/bin/env python3
"""아르테파인 주간 매출·예약 예측 + 주의 필요 예약/고객 플래그.

crm/data/raw/ 의
  - 결제내역_<날짜>_전체.xlsx  (시트 '결제상세', 선택: '기본 데이터')   ← 예약 단위 원장
  - 웹분석_<시작>_<끝>.xlsx     (시트 '기본 데이터' 일별 방문자·예약시작) ← 퍼널
를 읽어
  1) 지점×일 예측 (이미 잡힌 예약의 실현 기대치 + 앞으로 더 들어올 예약)
  2) 확보 예약 파이프라인 (취소율 반영 실현 매출)
  3) 방문 → 예약시작 → 결제 퍼널 추이와 다음 주 기대치
  4) 주의 필요: 취소 위험 예약 · 이탈 위험 단골 · 지점/퍼널 이상 신호
  5) 지난 예측 vs 실적 (예측 정확도)
를 만든다. 모델 설명은 crm/docs/주간예측_자동화_설계.md.

사용법:
    python3 crm/scripts/build_forecast.py [--asof 2026-10-06T12:00]

--asof 를 생략하면 결제상세의 마지막 결제 시각을 기준 시각으로 쓴다.
출력: output/주간예측_<기준일>.xlsx (개인정보 포함, git 미추적), output/주간예측_<기준일>.md (개인정보 없음),
      output/forecast_history.json (매 실행의 지점×일 예측 기록, 개인정보 없음)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_crm as bc  # noqa: E402  (결제상세 로더·전화번호 정규화 재사용)

RAW_DIR = bc.RAW_DIR
OUT_DIR = bc.OUT_DIR
HISTORY_FILE = OUT_DIR / "forecast_history.json"

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]
BRANCH_KO = {"Yongsan": "용산", "Incheon": "인천", "Bundang": "분당", "Jinju": "진주", "Daegu": "대구", "Jeju": "제주"}

# ---------------------------------------------------------------------------
# 모델·플래그 기준 (운영하며 조정하는 값)
# ---------------------------------------------------------------------------
HORIZON_DAYS = 14          # 기준일부터 며칠을 예측할지 (이번 주 잔여 + 다음 주)
BASELINE_WEEKS = 4         # 기준선 = 최근 N주 같은 요일 평균
SHRINK_K = 10              # 취소율 축소 추정 강도 (표본이 K건이면 전체 평균과 반반)
LEAD_BUCKETS = [(-1, 1, "당일·익일"), (1, 7, "2~7일 전"), (7, 10_000, "8일 이상 전")]

RISK_MIN_SCORE = 3         # 취소 위험 점수 이 이상이면 플래그
RISK_WINDOW_DAYS = 7       # 앞으로 며칠 안의 예약만 취소 위험 점검
HIGH_VALUE_Q = 0.75        # 결제금액 상위 25% = 고액

LAPSE_MIN_RENTALS = 2      # 단골 = 완료 이용 N회 이상
LAPSE_MIN_DAYS = 21        # 마지막 이용 후 최소 경과일
LAPSE_INTERVAL_X = 2.0     # 본인 평균 이용 간격의 N배 지나면 이탈 위험
LAPSE_MIN_HISTORY_DAYS = 60  # 결제 이력이 이 기간 미만이면 이탈 판정 보류

PACE_ALERT = 0.6           # 다음 7일 확보분이 '이맘때 평소 확보분'의 60% 미만이면 부진
CANCEL_SPIKE_X = 2.0       # 최근 7일 취소율이 평소의 2배 이상 (최소 3건)
FUNNEL_DROP = 0.2          # 최근 7일 방문·전환이 직전 3주 평균보다 20% 이상 하락


# ---------------------------------------------------------------------------
# 로드
# ---------------------------------------------------------------------------
def load_bookings() -> pd.DataFrame:
    P = bc.load_payments()
    if P is None or P.empty:
        sys.exit(f"결제내역_*.xlsx 가 없습니다: {RAW_DIR}")
    P = P[P["예약시작"].notna()].copy()
    P["지점"] = P["예약 지점"].fillna("미상").str.strip()
    P["예약일자"] = P["예약시작"].dt.normalize()
    P["리드일"] = (P["예약일자"] - P["결제일시"].dt.normalize()).dt.days
    P["고객"] = P["연락처_정규화"].fillna(P["이메일_소문자"]).fillna(P["고객명"])
    return P


def load_daily_totals() -> pd.DataFrame | None:
    """결제내역 파일의 '기본 데이터'(관리자 화면 일별 합계: 결제 건수·금액). 연도는 파일명 날짜에서."""
    rows = []
    for f in sorted(RAW_DIR.glob("결제내역_*.xlsx")):
        try:
            d = pd.read_excel(f, sheet_name="기본 데이터")
        except ValueError:
            continue
        m = re.search(r"(\d{4})-\d{2}-\d{2}", f.name)
        if not m or "기간" not in d.columns:
            continue
        d["날짜"] = pd.to_datetime(m.group(1) + "-" + d["기간"].astype(str), errors="coerce")
        rows.append(d.dropna(subset=["날짜"]))
    if not rows:
        return None
    D = pd.concat(rows).drop_duplicates("날짜", keep="last").set_index("날짜").sort_index()
    return D[["결제 건수", "결제 금액"]].rename(columns={"결제 건수": "결제건수", "결제 금액": "결제금액"})


def load_web_daily() -> pd.DataFrame | None:
    """웹분석 '기본 데이터' 가 일별(날짜 컬럼)인 내보내기만 사용. 겹치는 날은 마지막 파일 값."""
    rows = []
    for f in sorted(RAW_DIR.glob("웹분석_*.xlsx")):
        d = pd.read_excel(f, sheet_name="기본 데이터")
        if "날짜" not in d.columns:
            continue
        d["날짜"] = pd.to_datetime(d["날짜"], errors="coerce")
        rows.append(d.dropna(subset=["날짜"]))
    if not rows:
        return None
    W = pd.concat(rows).drop_duplicates("날짜", keep="last").set_index("날짜").sort_index()
    return W[["방문자수", "예약시작"]]


# ---------------------------------------------------------------------------
# 모델 구성 요소
# ---------------------------------------------------------------------------
def coverage_start(P: pd.DataFrame, DT: pd.DataFrame | None) -> pd.Timestamp:
    """결제 내보내기가 실제로 덮는 첫 결제일. 몇 건 섞여 들어오는 오래된 결제(변경·취소 건)는 무시한다."""
    if DT is not None and len(DT):
        return DT.index.min()
    return P["결제일시"].quantile(0.02).normalize()


def lead_bucket(days: float) -> str:
    for lo, hi, name in LEAD_BUCKETS:
        if lo < days <= hi:
            return name
    return LEAD_BUCKETS[0][2]


def shrink(k_events: float, n: float, prior: float, k: float = SHRINK_K) -> float:
    return (k_events + k * prior) / (n + k)


def cancel_model(P: pd.DataFrame, asof: pd.Timestamp) -> tuple[dict, pd.DataFrame]:
    """예약일이 지난(결과가 확정된) 예약으로 취소율을 추정: 전체 → 지점 → 지점×리드구간 순으로 축소 추정."""
    R = P[P["예약시작"] < asof].copy()
    R["리드구간"] = R["리드일"].map(lead_bucket)
    overall = R["취소"].mean() if len(R) else 0.2
    br = {b: shrink(g["취소"].sum(), len(g), overall) for b, g in R.groupby("지점")}
    cell = {(b, l): shrink(g["취소"].sum(), len(g), br[b]) for (b, l), g in R.groupby(["지점", "리드구간"])}
    tbl = (R.groupby(["지점", "리드구간"]).agg(예약=("취소", "size"), 취소=("취소", "sum")).reset_index())
    tbl["원취소율%"] = (tbl["취소"] / tbl["예약"] * 100).round(1)
    tbl["적용취소율%"] = [round(cell[(b, l)] * 100, 1) for b, l in zip(tbl["지점"], tbl["리드구간"])]
    return {"overall": overall, "branch": br, "cell": cell, "n": len(R)}, tbl


def cancel_prob(cm: dict, branch: str, lead_days: float) -> float:
    return cm["cell"].get((branch, lead_bucket(lead_days)), cm["branch"].get(branch, cm["overall"]))


def booking_curve(P: pd.DataFrame, asof: pd.Timestamp, cov: pd.Timestamp) -> tuple[pd.Series, bool]:
    """완료된 예약의 순매출 중 '예약일 L일 전까지 결제된' 비율. index=L(0~HORIZON).
    예약일이 내보내기 시작 + HORIZON 이후인 예약만 쓴다(그 전 예약은 일찍 결제된 건이 빠져 있어 곡선이 짧아진다).
    그런 예약이 30건 미만이면 전체로 계산하고 biased=True."""
    R = P[(P["예약시작"] < asof) & ~P["취소"]]
    full = R[R["예약일자"] >= cov + pd.Timedelta(days=HORIZON_DAYS)]
    biased = len(full) < 30
    R = R if biased else full
    tot = R["순결제"].sum()
    if tot <= 0:
        return pd.Series(0.0, index=range(HORIZON_DAYS + 1)), biased
    return pd.Series({L: R.loc[R["리드일"] >= L, "순결제"].sum() / tot for L in range(HORIZON_DAYS + 1)}), biased


def realized_daily(P: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """지점×예약일 실현 순매출(취소분 제외, 위약금 포함 = 결제−환불). 완료된 날만."""
    R = P[P["예약시작"] < asof.normalize()]
    return R.groupby(["지점", "예약일자"]).agg(실현매출=("순결제", "sum"), 이용건수=("취소", lambda s: int((~s).sum()))).reset_index()


def baseline(RD: pd.DataFrame, branch: str, day: pd.Timestamp, asof: pd.Timestamp, first_day: pd.Timestamp) -> tuple[float, str]:
    """최근 BASELINE_WEEKS주 같은 요일 평균. 같은 요일 이력이 없으면 지점 일평균 × 요일지수."""
    lo = max(asof.normalize() - pd.Timedelta(weeks=BASELINE_WEEKS), first_day)
    days = pd.date_range(lo, asof.normalize() - pd.Timedelta(days=1))
    if len(days) == 0:
        return 0.0, "이력없음"
    s = RD[RD["지점"] == branch].set_index("예약일자")["실현매출"].reindex(days, fill_value=0)
    same = s[s.index.dayofweek == day.dayofweek]
    if len(same) >= 2:
        return float(same.mean()), f"같은요일 {len(same)}주 평균"
    allb = RD.groupby("예약일자")["실현매출"].sum().reindex(days, fill_value=0)
    idx = allb.groupby(allb.index.dayofweek).mean() / allb.mean() if allb.mean() > 0 else pd.Series(dtype=float)
    return float(s.mean() * idx.get(day.dayofweek, 1.0)), f"일평균×요일지수({len(days)}일)"


def forecast(P: pd.DataFrame, asof: pd.Timestamp, cm: dict, curve: pd.Series, first_day: pd.Timestamp) -> pd.DataFrame:
    RD = realized_daily(P, asof)
    branches = sorted(P["지점"].unique())
    today = asof.normalize()
    act = P[~P["취소"]].copy()
    act["취소확률"] = [cancel_prob(cm, b, (d - asof).days) for b, d in zip(act["지점"], act["예약시작"])]
    rows = []
    for d in pd.date_range(today, today + pd.Timedelta(days=HORIZON_DAYS - 1)):
        L = (d - today).days
        share = float(curve.get(L, curve.iloc[-1]))
        if L == 0:  # 오늘은 이미 지난 시간만큼만 확보됐다고 본다
            elapsed = (asof - today).total_seconds() / 86400
            share = float(curve.get(1, 1.0)) + (1 - float(curve.get(1, 1.0))) * elapsed
        for b in branches:
            bk = act[(act["지점"] == b) & (act["예약일자"] == d)]
            booked = float(bk["순결제"].sum())
            booked_exp = float((bk["순결제"] * (1 - bk["취소확률"])).sum())
            base, how = baseline(RD, b, d, asof, first_day)
            if base > 0:
                pickup, method = base * (1 - share), f"기준선×(1−확보비율) · {how}"
            elif share > 0.15 and booked > 0:
                pickup, method = booked_exp * (1 / share - 1), "확보분÷확보비율"
            else:
                pickup, method = 0.0, "추가분 추정 불가(이력없음)"
            rows.append({"날짜": d, "요일": WEEKDAY_KO[d.dayofweek], "지점": b, "확보건수": len(bk), "확보매출": booked,
                         "확보_실현기대": booked_exp, "추가예상": pickup, "예측매출": booked_exp + pickup,
                         "기준선": base, "확보비율(L일전)": round(share, 2), "방법": method})
    F = pd.DataFrame(rows)
    for c in ["확보매출", "확보_실현기대", "추가예상", "예측매출", "기준선"]:
        F[c] = F[c].round(-2)
    return F


def confidence(asof: pd.Timestamp, cm: dict, cov: pd.Timestamp) -> tuple[str, int]:
    days = (asof.normalize() - cov).days
    if days >= 28 and cm["n"] >= 150:
        return "높음", days
    if days >= 14 and cm["n"] >= 60:
        return "보통", days
    return "낮음", days


# ---------------------------------------------------------------------------
# 퍼널
# ---------------------------------------------------------------------------
def funnel(W: pd.DataFrame | None, DT: pd.DataFrame | None, P: pd.DataFrame, asof: pd.Timestamp) -> tuple[pd.DataFrame | None, dict]:
    if W is None:
        return None, {}
    pays = DT["결제건수"] if DT is not None else P.groupby(P["결제일시"].dt.normalize()).size()
    end = asof.normalize() - pd.Timedelta(days=1)
    idx = pd.date_range(W.index.min(), min(end, W.index.max()))
    D = W.reindex(idx).join(pays.rename("결제건수").reindex(idx))
    D["주"] = D.index - pd.to_timedelta(D.index.dayofweek, unit="D")
    wk = D.groupby("주").agg(일수=("방문자수", "size"), 방문자=("방문자수", "sum"), 예약시작=("예약시작", "sum"),
                            결제건수=("결제건수", lambda s: s.sum(min_count=1)), 결제_일수=("결제건수", "count")).reset_index()
    wk["방문당예약시작"] = (wk["예약시작"] / wk["방문자"]).round(2)
    wk["방문당결제%"] = (wk["결제건수"] / wk["방문자"] * 100).where(wk["결제_일수"] == wk["일수"]).round(2)
    # 다음 주 방문자 기대치 = 최근 4주 같은 요일 평균
    last28 = D[D.index > end - pd.Timedelta(days=28)]
    dow = last28.groupby(last28.index.dayofweek)["방문자수"].mean()
    nxt_visitors = float(dow.reindex(range(7)).fillna(last28["방문자수"].mean()).sum())
    paid = D.dropna(subset=["결제건수"])
    conv = float(paid["결제건수"].sum() / paid["방문자수"].sum()) if len(paid) and paid["방문자수"].sum() else None
    # 최근 7일 vs 직전 21일
    l7, p21 = D[D.index > end - pd.Timedelta(days=7)], D[(D.index <= end - pd.Timedelta(days=7)) & (D.index > end - pd.Timedelta(days=28))]
    info = {"next_week_visitors": round(nxt_visitors), "visit_to_pay": conv,
            "next_week_payments": round(nxt_visitors * conv, 1) if conv else None,
            "conv_days": int(len(paid)),
            "l7_visitors_per_day": float(l7["방문자수"].mean()) if len(l7) else None,
            "p21_visitors_per_day": float(p21["방문자수"].mean()) if len(p21) else None,
            "l7_start_rate": float(l7["예약시작"].sum() / l7["방문자수"].sum()) if len(l7) else None,
            "p21_start_rate": float(p21["예약시작"].sum() / p21["방문자수"].sum()) if len(p21) else None}
    return wk, info


# ---------------------------------------------------------------------------
# 주의 필요 플래그
# ---------------------------------------------------------------------------
def flag_cancel_risk(P: pd.DataFrame, asof: pd.Timestamp, cm: dict) -> pd.DataFrame:
    up = P[~P["취소"] & (P["예약시작"] >= asof) & (P["예약시작"] < asof + pd.Timedelta(days=RISK_WINDOW_DAYS))].copy()
    past = P[P["예약시작"] < asof]
    cancelled_before = set(P.loc[P["취소"], "고객"])
    completed = set(past.loc[~past["취소"], "고객"])
    hi = P["결제금액"].quantile(HIGH_VALUE_Q)
    out = []
    for _, r in up.iterrows():
        reasons, s = [], 0
        if r["고객"] in cancelled_before:
            s += 2; reasons.append("과거 취소 이력")
        if r["리드일"] >= 7:
            s += 1; reasons.append(f"{int(r['리드일'])}일 전 결제")
        if r["결제금액"] >= hi:
            s += 1; reasons.append(f"고액(상위25%, {int(r['결제금액']):,}원)")
        if r["이용시간"] >= 24:
            s += 1; reasons.append(f"장기 {r['이용시간'] / 24:.1f}일")
        if r["고객"] not in completed:
            s += 1; reasons.append("첫 이용")
        p = cancel_prob(cm, r["지점"], (r["예약시작"] - asof).days)
        if s >= RISK_MIN_SCORE:
            out.append({"위험점수": s, "예약시작": r["예약시작"], "지점": r["지점"], "고객명": r["고객명"], "연락처": r["연락처"],
                        "차종": r["차종"], "결제금액": r["결제금액"], "이용시간(h)": round(r["이용시간"], 1),
                        "결제일시": r["결제일시"], "기본취소확률%": round(p * 100, 1), "사유": ", ".join(reasons),
                        "권장조치": "D-2 리마인드 문자 + 전일 확인 전화" + (" · 대체 차량/일정 변경 제안" if "과거 취소 이력" in reasons else "")})
    return pd.DataFrame(out).sort_values(["위험점수", "예약시작"], ascending=[False, True]) if out else pd.DataFrame(
        columns=["위험점수", "예약시작", "지점", "고객명", "연락처", "차종", "결제금액", "사유", "권장조치"])


def flag_lapsing(P: pd.DataFrame, asof: pd.Timestamp) -> tuple[pd.DataFrame, str | None]:
    span = (asof.normalize() - P["결제일시"].min().normalize()).days
    if span < LAPSE_MIN_HISTORY_DAYS:
        return pd.DataFrame(), f"결제 이력이 {span}일뿐이라 판정 보류(최소 {LAPSE_MIN_HISTORY_DAYS}일). 이전 결제내역 파일을 raw/ 에 넣으면 자동으로 켜진다."
    C = P[~P["취소"]]
    has_future = set(C.loc[C["예약시작"] >= asof, "고객"])
    done = C[C["예약시작"] < asof].sort_values("예약시작")
    out = []
    for cust, g in done.groupby("고객"):
        if len(g) < LAPSE_MIN_RENTALS or cust in has_future:
            continue
        days = g["예약일자"].drop_duplicates()
        if len(days) < LAPSE_MIN_RENTALS:
            continue
        gap = float(days.diff().dt.days.dropna().mean())
        since = (asof.normalize() - days.iloc[-1]).days
        if since >= max(LAPSE_MIN_DAYS, LAPSE_INTERVAL_X * gap):
            last = g.iloc[-1]
            out.append({"고객명": last["고객명"], "연락처": last["연락처"], "주이용지점": g["지점"].mode().iloc[0], "이용횟수": len(days),
                        "누적순매출": g["순결제"].sum(), "평균간격(일)": round(gap, 1), "마지막이용": days.iloc[-1].date(),
                        "경과일": since, "최근차종": last["모델"], "권장조치": "최근 차종 기반 재방문 제안 문자(단골 전용 혜택)"})
    return (pd.DataFrame(out).sort_values("누적순매출", ascending=False) if out else pd.DataFrame()), None


def flag_signals(P: pd.DataFrame, asof: pd.Timestamp, F: pd.DataFrame, curve: pd.Series, fi: dict) -> pd.DataFrame:
    out = []
    today = asof.normalize()
    nxt7 = F[F["날짜"] < today + pd.Timedelta(days=7)]
    for b, g in nxt7.groupby("지점"):
        expected_at_lead = float((g["기준선"] * g["확보비율(L일전)"]).sum())
        have = float(g["확보_실현기대"].sum())
        if expected_at_lead >= 100_000 and have < PACE_ALERT * expected_at_lead:
            out.append({"구분": "예약 페이스 부진", "대상": b, "수치": f"확보 {have:,.0f}원 / 평소 이맘때 {expected_at_lead:,.0f}원 ({have / expected_at_lead:.0%})",
                        "권장조치": "해당 지점 다음 7일 빈 슬롯 대상 타깃 문자·SNS 노출"})
    R = P[P["예약시작"] < asof]
    base = R["취소"].mean() if len(R) else 0
    last7 = R[R["예약시작"] >= asof - pd.Timedelta(days=7)]
    for b, g in last7.groupby("지점"):
        br = R[R["지점"] == b]["취소"].mean()
        ref = max(br, base)
        if g["취소"].sum() >= 3 and ref > 0 and g["취소"].mean() >= CANCEL_SPIKE_X * ref:
            out.append({"구분": "취소 급증", "대상": b, "수치": f"최근 7일 {g['취소'].mean():.0%} ({int(g['취소'].sum())}/{len(g)}) vs 평소 {ref:.0%}",
                        "권장조치": "취소 사유 확인(날씨·차량 상태·일정) 후 리마인드 강화"})
    if fi.get("l7_visitors_per_day") and fi.get("p21_visitors_per_day"):
        ch = fi["l7_visitors_per_day"] / fi["p21_visitors_per_day"] - 1
        if ch <= -FUNNEL_DROP:
            out.append({"구분": "방문자 감소", "대상": "웹사이트", "수치": f"일평균 {fi['l7_visitors_per_day']:.0f} vs 직전3주 {fi['p21_visitors_per_day']:.0f} ({ch:+.0%})",
                        "권장조치": "유입 채널별(IG·SMS·검색) 감소분 확인, 콘텐츠·발송 일정 점검"})
    if fi.get("l7_start_rate") and fi.get("p21_start_rate"):
        ch = fi["l7_start_rate"] / fi["p21_start_rate"] - 1
        if ch <= -FUNNEL_DROP:
            out.append({"구분": "예약시작 전환 하락", "대상": "웹사이트", "수치": f"방문당 {fi['l7_start_rate']:.2f} vs 직전3주 {fi['p21_start_rate']:.2f} ({ch:+.0%})",
                        "권장조치": "예약 페이지·차량 가용성·가격 노출 점검"})
    return pd.DataFrame(out, columns=["구분", "대상", "수치", "권장조치"])


# ---------------------------------------------------------------------------
# 예측 기록 · 정확도
# ---------------------------------------------------------------------------
def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def save_history(hist: list[dict], F: pd.DataFrame, asof: pd.Timestamp) -> list[dict]:
    run = asof.strftime("%Y-%m-%d")
    hist = [h for h in hist if h["run"] != run]
    hist += [{"run": run, "date": r["날짜"].strftime("%Y-%m-%d"), "branch": r["지점"], "forecast": float(r["예측매출"]),
              "booked_exp": float(r["확보_실현기대"])} for _, r in F.iterrows()]
    HISTORY_FILE.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    return hist


def accuracy(hist: list[dict], P: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """과거 실행의 예측(예측일 기준 7일 이내 분)과 지금 확정된 실적 비교. 주×지점 단위."""
    if not hist:
        return pd.DataFrame()
    H = pd.DataFrame(hist)
    H["date"] = pd.to_datetime(H["date"])
    H["run"] = pd.to_datetime(H["run"])
    H = H[(H["date"] < asof.normalize()) & (H["date"] < H["run"] + pd.Timedelta(days=7))]
    if H.empty:
        return pd.DataFrame()
    RD = realized_daily(P, asof).rename(columns={"예약일자": "date", "지점": "branch"})
    M = H.merge(RD, on=["date", "branch"], how="left").fillna({"실현매출": 0})
    A = M.groupby(["run", "branch"]).agg(예측=("forecast", "sum"), 실적=("실현매출", "sum")).reset_index()
    A["오차%"] = ((A["예측"] - A["실적"]) / A["실적"].where(A["실적"] > 0) * 100).round(1)
    return A.rename(columns={"run": "예측실행일", "branch": "지점"})


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def week_start(d: pd.Timestamp) -> pd.Timestamp:
    return d.normalize() - pd.Timedelta(days=d.dayofweek)


def week_table(P: pd.DataFrame, F: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """지점별: 지난 주 실적 · 이번 주(실적+잔여 예측) · 다음 주 예측."""
    ws = week_start(asof)
    RD = realized_daily(P, asof)
    rows = []
    for b in sorted(P["지점"].unique()):
        r = RD[RD["지점"] == b]
        f = F[F["지점"] == b]
        last = r[(r["예약일자"] >= ws - pd.Timedelta(days=7)) & (r["예약일자"] < ws)]["실현매출"].sum()
        this_act = r[r["예약일자"] >= ws]["실현매출"].sum()
        this_fc = f[f["날짜"] < ws + pd.Timedelta(days=7)]["예측매출"].sum()
        nxt = f[(f["날짜"] >= ws + pd.Timedelta(days=7)) & (f["날짜"] < ws + pd.Timedelta(days=14))]
        rows.append({"지점": b, "지난주_실적": last, "이번주_실적(지금까지)": this_act, "이번주_잔여예측": this_fc,
                     "이번주_예상합계": this_act + this_fc, "다음주_확보": nxt["확보매출"].sum(),
                     "다음주_확보_실현기대": nxt["확보_실현기대"].sum(), "다음주_예측": nxt["예측매출"].sum()})
    T = pd.DataFrame(rows)
    tot = T.drop(columns="지점").sum()
    tot["지점"] = "합계"
    T = pd.concat([T, tot.to_frame().T], ignore_index=True)
    for c in T.columns[1:]:
        T[c] = T[c].astype(float).round(-3)
    return T


def won(v) -> str:
    return f"{v / 10_000:,.0f}만원" if abs(v) >= 10_000 else f"{v:,.0f}원"


def data_warnings(asof: pd.Timestamp, cov: pd.Timestamp, conf: tuple[str, int], curve_biased: bool, last_week: pd.Timestamp) -> list[str]:
    w = []
    if conf[1] < 28:
        w.append(f"결제 내보내기가 {cov:%m/%d} 결제분부터라 이력이 {conf[1]}일뿐이다. 결제일 기준 최근 90일 이상을 내보내 raw/ 에 넣으면 기준선·취소율이 안정된다.")
    if curve_biased:
        w.append("예약 곡선(며칠 전에 결제되는지)이 내보내기 시작 직후 예약으로만 계산돼 '당일 결제' 쪽으로 치우쳐 있다 → 앞으로 들어올 추가분이 과소/과대 추정될 수 있다.")
    if cov > last_week:
        w.append(f"지난주 실적은 {cov:%m/%d} 이후 결제분만 반영된 부분 값이다(그 전에 결제된 예약 누락).")
    return w


def write_markdown(path: Path, asof, conf, WT, F, cm, CR, LP, lapse_note, SG, wk, fi, ACC, cancel_tbl, warns) -> None:
    ws = week_start(asof)
    tot = WT[WT["지점"] == "합계"].iloc[0]
    L = [f"# 주간 예측 리포트 — 기준 {asof:%Y-%m-%d %H:%M}",
         "",
         f"이번 주 {ws:%m/%d}~{ws + pd.Timedelta(days=6):%m/%d} · 다음 주 {ws + pd.Timedelta(days=7):%m/%d}~{ws + pd.Timedelta(days=13):%m/%d} · "
         f"예측 신뢰도 **{conf[0]}** (완료 이력 {conf[1]}일, 취소율 표본 {cm['n']}건)",
         "",
         *([f"> ⚠️ {w}" for w in warns] + [""] if warns else []),
         "## 1. 한눈에",
         "",
         f"- 이번 주 예상 매출 **{won(tot['이번주_예상합계'])}** (지금까지 실적 {won(tot['이번주_실적(지금까지)'])} + 남은 날 예측 {won(tot['이번주_잔여예측'])})",
         f"- 다음 주 예측 **{won(tot['다음주_예측'])}** — 이미 잡힌 예약 {won(tot['다음주_확보'])} 중 취소 반영 실현 기대 {won(tot['다음주_확보_실현기대'])}, 나머지는 앞으로 들어올 예상분",
         f"- 주의 필요: 취소 위험 예약 **{len(CR)}건**, 이탈 위험 단골 **{len(LP) if lapse_note is None else '판정 보류'}**, 이상 신호 **{len(SG)}건**",
         "",
         "## 2. 지점별 주간 매출 (원, 천원 단위 반올림)",
         "",
         WT.to_markdown(index=False, floatfmt=",.0f"),
         "",
         "## 3. 다음 14일 일별 예측 (전 지점 합)",
         "",
         F.groupby(["날짜", "요일"]).agg(확보건수=("확보건수", "sum"), 확보매출=("확보매출", "sum"), 확보_실현기대=("확보_실현기대", "sum"),
                                        추가예상=("추가예상", "sum"), 예측매출=("예측매출", "sum")).reset_index()
          .assign(날짜=lambda d: d["날짜"].dt.strftime("%m/%d")).to_markdown(index=False, floatfmt=",.0f"),
         "",
         "## 4. 주의가 필요한 예약·고객",
         "",
         f"### 취소 위험 예약 (앞으로 {RISK_WINDOW_DAYS}일, 점수 {RISK_MIN_SCORE}점 이상) — {len(CR)}건",
         "",
         "명단(이름·연락처)은 xlsx `3_취소위험` 시트에만 있다.",
         ""]
    if len(CR):
        L += [CR[["위험점수", "예약시작", "지점", "결제금액", "사유"]].assign(예약시작=lambda d: d["예약시작"].dt.strftime("%m/%d %H:%M"))
              .to_markdown(index=False, floatfmt=",.0f"), ""]
    L += ["### 이탈 위험 단골", "", lapse_note or f"{len(LP)}명 — 명단은 xlsx `4_이탈위험단골` 시트.", "",
          "### 지점·퍼널 이상 신호", ""]
    L += [SG.to_markdown(index=False) if len(SG) else "없음", ""]
    L += ["## 5. 방문 → 예약시작 → 결제 퍼널 (주별)", ""]
    if wk is not None:
        L += [wk.assign(주=lambda d: d["주"].dt.strftime("%m/%d~")).drop(columns=["결제_일수"]).to_markdown(index=False, floatfmt=",.2f", missingval="-"), ""]
        if fi.get("visit_to_pay"):
            L += [f"다음 주 방문자 기대 {fi['next_week_visitors']:,}명 × 방문당 결제율 {fi['visit_to_pay']:.2%} (결제 집계 {fi['conv_days']}일 기준) "
                  f"→ 결제 약 **{fi['next_week_payments']:.0f}건** 예상.", ""]
    else:
        L += ["웹분석 일별 파일이 없어 생략.", ""]
    L += ["## 6. 지난 예측 정확도", ""]
    L += [ACC.assign(예측실행일=lambda d: d["예측실행일"].dt.strftime("%Y-%m-%d")).to_markdown(index=False, floatfmt=",.0f", missingval="-") if len(ACC)
          else "아직 비교할 과거 예측이 없다. 매주 실행하면 다음 주부터 쌓인다.", ""]
    L += ["## 7. 적용 취소율 (예약일이 지난 예약 기준)", "", cancel_tbl.to_markdown(index=False), "",
          "## 계산 방식", "",
          "- **예측매출 = 확보_실현기대 + 추가예상**",
          "- 확보_실현기대 = 이미 결제된 예약 순결제 × (1 − 지점·리드구간별 취소율). 취소율은 표본이 적으면 지점·전체 평균 쪽으로 당겨 쓴다.",
          f"- 추가예상 = 기준선(최근 {BASELINE_WEEKS}주 같은 요일 실현매출 평균) × (1 − 그 날짜까지 남은 일수 시점의 평소 확보비율).",
          "- 확보비율 = 완료된 예약 매출 중 예약일 L일 전까지 결제된 비율(예약 곡선).",
          "- 자세한 설명: `crm/docs/주간예측_자동화_설계.md`", ""]
    path.write_text("\n".join(L), encoding="utf-8")


def write_excel(path: Path, WT, F, P, asof, cm, CR, LP, lapse_note, SG, wk, ACC, cancel_tbl, curve) -> None:
    up = P[~P["취소"] & (P["예약시작"] >= asof) & (P["예약시작"] < asof + pd.Timedelta(days=HORIZON_DAYS))].copy()
    up["취소확률%"] = [round(cancel_prob(cm, b, (d - asof).days) * 100, 1) for b, d in zip(up["지점"], up["예약시작"])]
    up["실현기대"] = (up["순결제"] * (1 - up["취소확률%"] / 100)).round(-2)
    up = up.sort_values("예약시작")[["예약시작", "지점", "고객명", "연락처", "차종", "이용시간", "결제일시", "리드일", "결제금액", "순결제", "취소확률%", "실현기대"]]
    guide = pd.DataFrame({"항목": ["기준 시각", "예측매출", "확보_실현기대", "추가예상", "기준선", "확보비율(L일전)", "취소 위험 점수",
                                  "이탈 위험 단골", "예약 페이스 부진", "취소 급증", "퍼널 하락"],
                         "설명": [f"{asof:%Y-%m-%d %H:%M}",
                                "확보_실현기대 + 추가예상",
                                "이미 결제된 예약의 순결제 × (1 − 적용취소율)",
                                "기준선 × (1 − 확보비율). 기준선이 없으면 확보분÷확보비율",
                                f"최근 {BASELINE_WEEKS}주 같은 요일 실현매출 평균(2주 미만이면 지점 일평균×요일지수)",
                                "완료 예약 매출 중 예약일 L일 전까지 결제된 비율",
                                f"과거취소 +2, 7일 이상 전 결제 +1, 고액(상위 {int((1 - HIGH_VALUE_Q) * 100)}%) +1, 24h 이상 +1, 첫 이용 +1 → {RISK_MIN_SCORE}점 이상",
                                f"완료 {LAPSE_MIN_RENTALS}회 이상 · 예정 예약 없음 · 마지막 이용 후 max({LAPSE_MIN_DAYS}일, 평균간격×{LAPSE_INTERVAL_X})",
                                f"다음 7일 확보 실현기대 < 평소 이맘때 확보분 × {PACE_ALERT}",
                                f"최근 7일 취소율 ≥ 평소 × {CANCEL_SPIKE_X} (3건 이상)",
                                f"최근 7일 방문자/예약시작률이 직전 3주 대비 {int(FUNNEL_DROP * 100)}% 이상 하락"]})
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        WT.to_excel(xw, sheet_name="0_주간요약", index=False)
        F.assign(날짜=F["날짜"].dt.date).to_excel(xw, sheet_name="1_지점별일별예측", index=False)
        up.to_excel(xw, sheet_name="2_확보예약", index=False)
        CR.to_excel(xw, sheet_name="3_취소위험", index=False)
        (LP if len(LP) else pd.DataFrame({"안내": [lapse_note or "해당 없음"]})).to_excel(xw, sheet_name="4_이탈위험단골", index=False)
        (SG if len(SG) else pd.DataFrame({"안내": ["이상 신호 없음"]})).to_excel(xw, sheet_name="5_이상신호", index=False)
        (wk if wk is not None else pd.DataFrame({"안내": ["웹분석 일별 파일 없음"]})).to_excel(xw, sheet_name="6_퍼널", index=False)
        (ACC if len(ACC) else pd.DataFrame({"안내": ["비교할 과거 예측 없음"]})).to_excel(xw, sheet_name="7_예측정확도", index=False)
        cancel_tbl.to_excel(xw, sheet_name="8_취소율", index=False)
        curve.rename("확보비율").rename_axis("L일전").reset_index().to_excel(xw, sheet_name="9_예약곡선", index=False)
        guide.to_excel(xw, sheet_name="기준설명", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                w = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(10, w * 1.3), 60)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", help="기준 시각 (예: 2026-10-06T12:00). 생략 시 마지막 결제 시각")
    args = ap.parse_args()

    P = load_bookings()
    asof = pd.Timestamp(args.asof) if args.asof else P["결제일시"].max()
    P = P[P["결제일시"] <= asof]
    P["지점"] = P["지점"].map(lambda b: BRANCH_KO.get(b, b))

    DT = load_daily_totals()
    cov = coverage_start(P, DT)
    cm, cancel_tbl = cancel_model(P, asof)
    curve, curve_biased = booking_curve(P, asof, cov)
    F = forecast(P, asof, cm, curve, cov)
    conf = confidence(asof, cm, cov)
    WT = week_table(P, F, asof)
    wk, fi = funnel(load_web_daily(), DT, P, asof)
    warns = data_warnings(asof, cov, conf, curve_biased, week_start(asof) - pd.Timedelta(days=7))
    CR = flag_cancel_risk(P, asof, cm)
    LP, lapse_note = flag_lapsing(P, asof)
    SG = flag_signals(P, asof, F, curve, fi)
    hist = save_history(load_history(), F, asof)
    ACC = accuracy(hist, P, asof)

    tag = asof.strftime("%Y-%m-%d")
    xlsx, md = OUT_DIR / f"주간예측_{tag}.xlsx", OUT_DIR / f"주간예측_{tag}.md"
    write_excel(xlsx, WT, F, P, asof, cm, CR, LP, lapse_note, SG, wk, ACC, cancel_tbl, curve)
    write_markdown(md, asof, conf, WT, F, cm, CR, LP, lapse_note, SG, wk, fi, ACC, cancel_tbl, warns)
    for w in warns:
        print(f"주의     : {w}")

    tot = WT[WT["지점"] == "합계"].iloc[0]
    print(f"asof     : {asof}  (신뢰도 {conf[0]}, 이력 {conf[1]}일, 취소율 표본 {cm['n']}건, 전체 취소율 {cm['overall']:.1%})")
    print(f"this week: {tot['이번주_예상합계']:,.0f}  next week: {tot['다음주_예측']:,.0f} (확보 {tot['다음주_확보']:,.0f})")
    print(f"flags    : 취소위험 {len(CR)}  이탈단골 {len(LP) if lapse_note is None else '보류'}  이상신호 {len(SG)}")
    print(f"xlsx     : {xlsx}\nmd       : {md}")


if __name__ == "__main__":
    main()
