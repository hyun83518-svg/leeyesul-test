#!/usr/bin/env python3
"""아르테파인 CRM 데이터 파이프라인.

crm/data/raw/ 에 있는 '회원 설문' 내보내기 파일(xlsx)을 읽어
  1) 정규화 + 파생 컬럼 생성
  2) 연락처 기준 중복 회원 식별
  3) 리드 스코어 산출 및 세그먼트 분류
  4) 세그먼트별 시트가 담긴 CRM 마스터 xlsx 출력
  5) 개인정보가 없는 집계 요약(JSON/Markdown) 출력
을 수행한다.

사용법:
    python3 crm/scripts/build_crm.py [--master 파일경로]

--master 를 생략하면 crm/data/raw/ 에서 파일명에 '전체'가 들어간 가장 최신 파일을 사용한다.
추가 파일(예: 예약/렌탈 내역)이 들어오면 load_extra_sources() 에 병합 로직을 붙인다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "output"

# ---------------------------------------------------------------------------
# 컬럼 정의
# ---------------------------------------------------------------------------
COL = {
    "no": "번호",
    "name": "이름",
    "nick": "닉네임",
    "email": "이메일",
    "phone": "연락처",
    "platform": "가입플랫폼",
    "role": "권한",
    "branch": "소속지점",
    "fav_branch": "자주이용지점",
    "joined": "가입일",
    "consent": "마케팅수신",
    "consent_at": "마케팅응답일",
    "consent_src": "마케팅수집경로",
    "survey_done": "설문완료",
    "survey_at": "설문제출일",
    "q_source": "아르테파인을 알게 된 경로는?",
    "q_exp": "라이딩 경력은?",
    "q_own": "바이크를 보유하고 계신가요?",
    "q_purpose": "이번 렌탈의 목적은?",
    "q_reason": "해당 모델을 선택한 이유는?",
    "q_buy": "모터사이클 구매 계획이 있으신가요?",
    "q_when": "주로 언제 라이딩하시나요?",
    "q_factor": "바이크 선택 시 가장 중요한 요소는?",
    "q_next": "다음에 타보고 싶은 브랜드/모델은?",
    "q_wish": "아르테파인에 추가되었으면 하는 모델은?",
}

MULTI_SELECT_QS = [COL["q_source"], COL["q_purpose"], COL["q_reason"], COL["q_when"], COL["q_factor"]]

# 선택지 표준값 (자유입력은 '기타'로 묶는다)
CHOICES = {
    COL["q_source"]: ["인스타그램", "네이버 검색", "지인 추천", "유튜브", "레인조아카데미", "매장 방문", "구글 검색", "스레드"],
    COL["q_purpose"]: ["구매 전 시승·비교", "투어링 (당일/박투어)", "보유 바이크와 비교", "저비용으로 다양한 바이크 경험",
                       "오랜만에 라이딩 (재입문)", "도심 라이딩·데이트(텐덤)", "입문 전 연습"],
    COL["q_reason"]: ["성능 궁금", "구매 전 시승", "보유 바이크와 비교", "렌탈 가능 모델이라서", "디자인", "가성비", "유튜브·SNS 보고"],
    COL["q_when"]: ["평일 저녁", "주말 오후", "주말 오전", "평일 낮", "새벽"],
    COL["q_factor"]: ["디자인", "성능", "편안함", "가격", "브랜드", "연비"],
}
EXP_ORDER = ["3개월 미만", "1년 미만", "1~2년", "3~5년", "5~10년", "10년 이상"]
BUY_ORDER = ["3개월 내", "6개월 내", "1년 내", "없음"]
OWN_CLASSES = ["없음", "쿼터급", "미들급", "리터급"]


# ---------------------------------------------------------------------------
# 로드 / 정규화
# ---------------------------------------------------------------------------
def find_master_file() -> Path:
    cands = sorted(RAW_DIR.glob("*전체*.xlsx"))
    if not cands:
        cands = sorted(RAW_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_size)
    if not cands:
        sys.exit(f"raw 파일이 없습니다: {RAW_DIR}")
    return cands[-1]


def normalize_phone(v) -> str | None:
    if v is None or pd.isna(v):
        return None
    digits = re.sub(r"\D", "", str(v))
    if digits.startswith("82") and len(digits) in (11, 12):
        digits = "0" + digits[2:]
    if re.fullmatch(r"010\d{8}", digits):
        return digits
    return None


def split_multi(v) -> list[str]:
    if v is None or pd.isna(v):
        return []
    return [t.strip() for t in str(v).split(",") if t.strip()]


def canon_multi(v, choices: list[str]) -> list[str]:
    out = []
    for t in split_multi(v):
        out.append(t if t in choices else "기타")
    return sorted(set(out), key=lambda x: (x == "기타", x))


def own_class(v) -> str | None:
    if v is None or pd.isna(v):
        return None
    for c in OWN_CLASSES:
        if str(v).startswith(c):
            return c
    return "기타(급 미기재)"


def own_model(v) -> str | None:
    if v is None or pd.isna(v):
        return None
    parts = split_multi(v)
    if len(parts) >= 2 and parts[0] in OWN_CLASSES:
        return ", ".join(parts[1:])
    if parts and parts[0] not in OWN_CLASSES:
        return ", ".join(parts)
    return None


def load_master(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, dtype=str)
    df = df.replace({"-": pd.NA, "": pd.NA})
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in COL.values() if c not in df.columns]
    if missing:
        sys.exit(f"예상 컬럼이 없습니다: {missing}")

    df["연락처_원본"] = df[COL["phone"]]
    df["연락처_정규화"] = df[COL["phone"]].map(normalize_phone)
    df["연락처_유효"] = df["연락처_정규화"].notna()
    df["이메일_소문자"] = df[COL["email"]].str.strip().str.lower()
    df["가입월"] = df[COL["joined"]].str[:7]
    df["가입플랫폼_주"] = df[COL["platform"]].str.split(",").str[0].str.strip()
    df["설문완료_bool"] = df[COL["survey_done"]].eq("완료")
    df["마케팅상태"] = df[COL["consent"]].fillna("미응답")
    # 관리자/매니저/테스트 계정은 마케팅 대상에서 제외
    df["마케팅제외"] = (
        df[COL["role"]].fillna("USER").ne("USER")
        | df[COL["consent_src"]].eq("ADMIN_TEST_ACCOUNT")
        | df["이메일_소문자"].str.contains(r"test@|@test\.", regex=True, na=False)
    )

    for q in MULTI_SELECT_QS:
        df[q + "_list"] = df[q].map(lambda v: canon_multi(v, CHOICES[q]))
    df["보유바이크_급"] = df[COL["q_own"]].map(own_class)
    df["보유바이크_모델"] = df[COL["q_own"]].map(own_model)
    df["바이크보유"] = df["보유바이크_급"].map(lambda c: None if c is None else c != "없음")
    return df


def load_extra_sources() -> dict[str, pd.DataFrame]:
    """추후 업로드되는 예약/렌탈/결제 데이터 병합 지점. 현재는 비어 있다."""
    return {}


# ---------------------------------------------------------------------------
# 중복 식별
# ---------------------------------------------------------------------------
def mark_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["중복그룹"] = pd.NA
    df["대표계정"] = True
    grp_id = 0
    for phone, g in df[df["연락처_정규화"].notna()].groupby("연락처_정규화"):
        if len(g) < 2:
            continue
        grp_id += 1
        df.loc[g.index, "중복그룹"] = f"D{grp_id:03d}"
        # 대표계정: 설문완료 > 마케팅동의 > 최근 가입 순
        ranked = g.assign(
            _s=g["설문완료_bool"].astype(int),
            _c=g[COL["consent"]].eq("동의").astype(int),
        ).sort_values(["_s", "_c", COL["joined"]], ascending=[False, False, False])
        df.loc[ranked.index[1:], "대표계정"] = False
    return df


# ---------------------------------------------------------------------------
# 리드 스코어 / 세그먼트
# ---------------------------------------------------------------------------
BUY_SCORE = {"3개월 내": 40, "6개월 내": 25, "1년 내": 15, "없음": 0}


def lead_score(r: pd.Series) -> int:
    s = 0
    s += BUY_SCORE.get(r[COL["q_buy"]], 0) if pd.notna(r[COL["q_buy"]]) else 0
    s += 20 if r[COL["consent"]] == "동의" else 0
    s += 10 if r["연락처_유효"] else 0
    s += 10 if "구매 전 시승·비교" in r[COL["q_purpose"] + "_list"] else 0
    s += 10 if "구매 전 시승" in r[COL["q_reason"] + "_list"] else 0
    s += 5 if r["설문완료_bool"] else 0
    s += 5 if r["가입월"] == "2026-08" else 0
    return s


def lead_tier(r: pd.Series) -> str:
    if not r["설문완료_bool"]:
        return "미설문"
    if r["리드스코어"] >= 70:
        return "HOT"
    if r["리드스코어"] >= 40:
        return "WARM"
    return "COLD"


SEGMENT_DEFS = [
    # (코드, 이름, 설명/액션, 필터함수)
    ("S01", "HOT_구매3개월내_동의",
     "구매 계획 3개월 내 + 마케팅 동의. 즉시 세일즈 콜/시승 예약 제안.",
     lambda d: d[COL["q_buy"]].eq("3개월 내") & d[COL["consent"]].eq("동의")),
    ("S02", "구매3개월내_미동의",
     "구매 계획 3개월 내지만 광고 수신 미동의. 광고성 메시지 불가, 거래 관련 정보성 안내만. 매장 방문 시 동의 유도.",
     lambda d: d[COL["q_buy"]].eq("3개월 내") & d[COL["consent"]].ne("동의")),
    ("S03", "구매6개월내",
     "6개월 내 구매 의향. 시승 비교 프로그램/구매 연계 혜택 안내.",
     lambda d: d[COL["q_buy"]].eq("6개월 내")),
    ("S04", "구매1년내",
     "1년 내 구매 의향. 뉴스레터·신차 입고 소식으로 육성(nurture).",
     lambda d: d[COL["q_buy"]].eq("1년 내")),
    ("S05", "마케팅동의_전체",
     "광고성 메시지 발송 가능 풀. 모든 프로모션의 기본 발송 대상.",
     lambda d: d[COL["consent"]].eq("동의")),
    ("S06", "설문완료_미동의",
     "설문은 했지만 광고 미동의. 혜택 연계 동의 전환 캠페인(앱/매장 접점).",
     lambda d: d["설문완료_bool"] & d[COL["consent"]].eq("미동의")),
    ("S07", "입문자",
     "경력 1년 미만 + 바이크 미보유. 입문 연습·안전 교육·소배기량 렌탈 패키지.",
     lambda d: d[COL["q_exp"]].isin(["3개월 미만", "1년 미만"]) & d["보유바이크_급"].eq("없음")),
    ("S08", "투어링_경험형",
     "렌탈 목적이 투어링/다양한 바이크 경험. 재렌탈 쿠폰·멤버십·시즌 투어 코스 제안.",
     lambda d: d[COL["q_purpose"] + "_list"].map(
         lambda l: bool({"투어링 (당일/박투어)", "저비용으로 다양한 바이크 경험"} & set(l)))),
    ("S09", "보유자_기변검토",
     "바이크 보유 + 목적이 보유 바이크와 비교. 상위 배기량 시승·기변 상담 타깃.",
     lambda d: d["바이크보유"].eq(True) & d[COL["q_purpose"] + "_list"].map(lambda l: "보유 바이크와 비교" in l)),
    ("S10", "재입문",
     "오랜만에 라이딩(재입문). 리프레시 코스·안전 점검 안내.",
     lambda d: d[COL["q_purpose"] + "_list"].map(lambda l: "오랜만에 라이딩 (재입문)" in l)),
    ("S11", "지점이용자",
     "소속/자주이용 지점이 기록된 회원. 지점별 오프라인 이벤트 대상.",
     lambda d: d[COL["branch"]].notna() | d[COL["fav_branch"]].notna()),
    ("S12", "미설문_연락처보유",
     "설문 미완료 + 유효 연락처. 설문 참여 유도 + 마케팅 동의 요청(정보성 안내로만 접근).",
     lambda d: ~d["설문완료_bool"] & d["연락처_유효"]),
    ("S13", "미설문_이메일만",
     "설문 미완료 + 연락처 없음. 이메일 기반 설문 유도.",
     lambda d: ~d["설문완료_bool"] & ~d["연락처_유효"] & d[COL["email"]].notna()),
    ("S14", "데이터정리_중복계정",
     "동일 연락처 다중 계정. 계정 통합/대표계정 확정 필요.",
     lambda d: d["중복그룹"].notna()),
    ("S15", "데이터정리_연락처비정상",
     "연락처가 010 11자리 형식이 아님(해외번호·오입력). SMS 발송 전 검수.",
     lambda d: d["연락처_원본"].notna() & ~d["연락처_유효"]),
]

EXPORT_COLS = [
    COL["no"], COL["name"], COL["nick"], COL["email"], "연락처_정규화", "연락처_원본", COL["platform"], COL["role"],
    COL["branch"], COL["fav_branch"], COL["joined"], COL["consent"], COL["consent_at"], COL["consent_src"],
    COL["survey_done"], COL["survey_at"], "리드스코어", "리드등급", "세그먼트", "중복그룹", "대표계정", "마케팅제외",
    COL["q_source"], COL["q_exp"], "보유바이크_급", "보유바이크_모델", COL["q_purpose"], COL["q_reason"],
    COL["q_buy"], COL["q_when"], COL["q_factor"], COL["q_next"], COL["q_wish"],
]


def assign_segments(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    df = df.copy()
    df["리드스코어"] = df.apply(lead_score, axis=1)
    df["리드등급"] = df.apply(lead_tier, axis=1)
    seg_tags = [[] for _ in range(len(df))]
    masks: dict[str, pd.Series] = {}
    for code, name, _desc, fn in SEGMENT_DEFS:
        mask = fn(df).fillna(False).astype(bool)
        if not name.startswith("데이터정리"):
            mask = mask & ~df["마케팅제외"]
        masks[f"{code}_{name}"] = mask
        for pos in range(len(df)):
            if mask.iloc[pos]:
                seg_tags[pos].append(code)
    df["세그먼트"] = [",".join(t) for t in seg_tags]
    seg_frames = {k: df[m] for k, m in masks.items()}
    return df, seg_frames


# ---------------------------------------------------------------------------
# 집계 요약 (개인정보 없음)
# ---------------------------------------------------------------------------
def pct(n, d) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def multi_counts(series_of_lists) -> dict[str, int]:
    c: Counter = Counter()
    for l in series_of_lists:
        c.update(l)
    return dict(c.most_common())


def build_summary(df: pd.DataFrame, seg_frames: dict[str, pd.DataFrame], src: Path) -> dict:
    total = len(df)
    s = df[df["설문완료_bool"]]
    asked = df[df["마케팅상태"] != "미응답"]
    consent = df[df[COL["consent"]] == "동의"]

    by_month = df.groupby("가입월").agg(
        가입=("번호", "size"),
        설문완료=("설문완료_bool", "sum"),
        마케팅동의=(COL["consent"], lambda x: (x == "동의").sum()),
    ).reset_index()
    by_platform = df.groupby("가입플랫폼_주").agg(
        가입=("번호", "size"),
        설문완료=("설문완료_bool", "sum"),
        마케팅동의=(COL["consent"], lambda x: (x == "동의").sum()),
        연락처보유=("연락처_유효", "sum"),
    ).reset_index()
    by_platform["설문완료율"] = (by_platform["설문완료"] / by_platform["가입"] * 100).round(1)
    by_platform["연락처보유율"] = (by_platform["연락처보유"] / by_platform["가입"] * 100).round(1)

    # 8월 가입자만 놓고 본 플랫폼별 설문 완료율 (설문 기능이 8월에 열렸으므로 공정 비교)
    aug = df[df["가입월"] == "2026-08"]
    aug_platform = aug.groupby("가입플랫폼_주").agg(
        가입=("번호", "size"), 설문완료=("설문완료_bool", "sum")).reset_index()
    aug_platform["설문완료율"] = (aug_platform["설문완료"] / aug_platform["가입"] * 100).round(1)

    def crosstab(a, b, order_a=None, order_b=None):
        ct = pd.crosstab(s[a], s[b])
        if order_a:
            ct = ct.reindex([o for o in order_a if o in ct.index])
        if order_b:
            ct = ct[[o for o in order_b if o in ct.columns]]
        return ct

    source_x_buy = pd.crosstab(
        s[COL["q_source"] + "_list"].explode(), s[COL["q_buy"]].reindex(s[COL["q_source"] + "_list"].explode().index)
    )
    source_x_buy = source_x_buy[[o for o in BUY_ORDER if o in source_x_buy.columns]]
    source_x_buy["합계"] = source_x_buy.sum(axis=1)
    source_x_buy["3개월내_비율"] = (source_x_buy["3개월 내"] / source_x_buy["합계"] * 100).round(1)
    source_x_buy = source_x_buy.sort_values("합계", ascending=False)

    # 유입경로별 마케팅 동의율 (설문 완료자 기준)
    src_expl = s[[COL["q_source"] + "_list", COL["consent"]]].explode(COL["q_source"] + "_list")
    source_x_consent = pd.crosstab(src_expl[COL["q_source"] + "_list"], src_expl[COL["consent"]])
    source_x_consent["동의율"] = (source_x_consent.get("동의", 0) / source_x_consent.sum(axis=1) * 100).round(1)
    source_x_consent = source_x_consent.sort_values("동의율", ascending=False)

    summary = {
        "meta": {
            "source_file": src.name,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "data_cutoff": df[COL["joined"]].max(),
        },
        "overview": {
            "total_members": total,
            "unique_members_after_phone_dedup": int(df["대표계정"].sum()),
            "duplicate_groups": int(df["중복그룹"].nunique()),
            "email_present": int(df[COL["email"]].notna().sum()),
            "phone_present_raw": int(df["연락처_원본"].notna().sum()),
            "phone_valid": int(df["연락처_유효"].sum()),
            "phone_invalid_format": int((df["연락처_원본"].notna() & ~df["연락처_유효"]).sum()),
            "survey_done": int(len(s)),
            "survey_done_pct_all": pct(len(s), total),
            "survey_done_pct_aug_joiners": pct(int(aug["설문완료_bool"].sum()), len(aug)),
            "consent_asked": int(len(asked)),
            "consent_yes": int(len(consent)),
            "consent_no": int((df[COL["consent"]] == "미동의").sum()),
            "consent_unasked": int((df["마케팅상태"] == "미응답").sum()),
            "consent_rate_among_asked": pct(len(consent), len(asked)),
            "consent_yes_with_valid_phone": int((consent["연락처_유효"]).sum()),
            "first_survey_date": s[COL["survey_at"]].min(),
            "first_consent_date": df[COL["consent_at"]].dropna().min(),
            "roles": df[COL["role"]].value_counts().to_dict(),
            "marketing_excluded_accounts": int(df["마케팅제외"].sum()),
        },
        "by_month": by_month.to_dict(orient="records"),
        "by_platform": by_platform.to_dict(orient="records"),
        "aug_joiners_by_platform": aug_platform.to_dict(orient="records"),
        "consent_source": df[COL["consent_src"]].value_counts().to_dict(),
        "lead_tiers": df["리드등급"].value_counts().to_dict(),
        "survey": {
            "n": int(len(s)),
            "source": multi_counts(s[COL["q_source"] + "_list"]),
            "experience": {k: int(v) for k, v in s[COL["q_exp"]].value_counts().reindex(EXP_ORDER).fillna(0).items()},
            "own_class": s["보유바이크_급"].value_counts().to_dict(),
            "purpose": multi_counts(s[COL["q_purpose"] + "_list"]),
            "reason": multi_counts(s[COL["q_reason"] + "_list"]),
            "buy_plan": {k: int(v) for k, v in s[COL["q_buy"]].value_counts().reindex(BUY_ORDER).fillna(0).items()},
            "ride_when": multi_counts(s[COL["q_when"] + "_list"]),
            "factor": multi_counts(s[COL["q_factor"] + "_list"]),
            "next_models_top": s[COL["q_next"]].dropna().str.strip().str.lower().value_counts().head(20).to_dict(),
            "wish_models_top": s[COL["q_wish"]].dropna().str.strip().str.lower().value_counts().head(20).to_dict(),
        },
        "crosstabs": {
            "buy_x_consent": crosstab(COL["q_buy"], COL["consent"], BUY_ORDER).to_dict(orient="index"),
            "exp_x_buy": crosstab(COL["q_exp"], COL["q_buy"], EXP_ORDER, BUY_ORDER).to_dict(orient="index"),
            "own_x_buy": crosstab("보유바이크_급", COL["q_buy"], OWN_CLASSES, BUY_ORDER).to_dict(orient="index"),
            "source_x_buy": source_x_buy.to_dict(orient="index"),
            "source_x_consent": source_x_consent.to_dict(orient="index"),
            "factor_x_exp": pd.crosstab(
                s[COL["q_factor"] + "_list"].explode(),
                s[COL["q_exp"]].reindex(s[COL["q_factor"] + "_list"].explode().index),
            ).reindex(columns=EXP_ORDER).fillna(0).astype(int).to_dict(orient="index"),
        },
        "segments": [
            {"code": code, "name": name, "description": desc, "count": int(len(seg_frames[f"{code}_{name}"])),
             "with_valid_phone": int(seg_frames[f"{code}_{name}"]["연락처_유효"].sum()),
             "with_consent": int((seg_frames[f"{code}_{name}"][COL["consent"]] == "동의").sum())}
            for code, name, desc, _ in SEGMENT_DEFS
        ],
    }
    return summary


def write_markdown(summary: dict, path: Path) -> None:
    o = summary["overview"]
    sv = summary["survey"]
    L: list[str] = []
    L.append(f"# 아르테파인 CRM 데이터 분석 요약")
    L.append(f"\n기준 파일: `{summary['meta']['source_file']}` · 데이터 기준일: {summary['meta']['data_cutoff']} · 생성: {summary['meta']['generated_at']}\n")
    L.append("## 1. 전체 현황\n")
    L.append("| 항목 | 값 |\n|---|---|")
    L.append(f"| 전체 회원 수 | {o['total_members']:,} |")
    L.append(f"| 연락처 기준 중복 제거 후 | {o['unique_members_after_phone_dedup']:,} (중복 그룹 {o['duplicate_groups']}개) |")
    L.append(f"| 유효 연락처(010 11자리) 보유 | {o['phone_valid']:,} (형식 오류 {o['phone_invalid_format']}건) |")
    L.append(f"| 설문 완료 | {o['survey_done']:,} ({o['survey_done_pct_all']}% / 8월 가입자 기준 {o['survey_done_pct_aug_joiners']}%) |")
    L.append(f"| 마케팅 수신 질문 응답 | {o['consent_asked']:,} (동의 {o['consent_yes']:,} · 미동의 {o['consent_no']:,}) |")
    L.append(f"| 응답자 중 동의율 | {o['consent_rate_among_asked']}% |")
    L.append(f"| 마케팅 미응답(질문 전 가입) | {o['consent_unasked']:,} |")
    L.append(f"| 동의 + 유효 연락처 (SMS 발송 가능 풀) | {o['consent_yes_with_valid_phone']:,} |")
    L.append(f"| 설문/동의 최초 수집일 | {o['first_survey_date']} / {o['first_consent_date']} |")
    L.append(f"| 마케팅 제외 계정(관리자·매니저·테스트) | {o['marketing_excluded_accounts']} |")
    L.append("\n## 2. 월별 가입 추이\n")
    L.append("| 가입월 | 가입 | 설문완료 | 마케팅동의 |\n|---|---|---|---|")
    for r in summary["by_month"]:
        L.append(f"| {r['가입월']} | {r['가입']:,} | {r['설문완료']} | {r['마케팅동의']} |")
    L.append("\n## 3. 가입 플랫폼별\n")
    L.append("| 플랫폼 | 가입 | 연락처보유율 | 설문완료 | 설문완료율 | 마케팅동의 |\n|---|---|---|---|---|---|")
    for r in summary["by_platform"]:
        L.append(f"| {r['가입플랫폼_주']} | {r['가입']:,} | {r['연락처보유율']}% | {r['설문완료']} | {r['설문완료율']}% | {r['마케팅동의']} |")
    L.append("\n8월 가입자만 놓고 본 플랫폼별 설문 완료율:\n")
    L.append("| 플랫폼 | 8월 가입 | 설문완료 | 완료율 |\n|---|---|---|---|")
    for r in summary["aug_joiners_by_platform"]:
        L.append(f"| {r['가입플랫폼_주']} | {r['가입']} | {r['설문완료']} | {r['설문완료율']}% |")
    L.append("\n## 4. 설문 응답 분포 (완료자 {n}명, 복수응답 문항은 응답 건수)\n".format(n=sv["n"]))

    def block(title, d):
        L.append(f"### {title}\n")
        L.append("| 응답 | 건수 | 비율 |\n|---|---|---|")
        for k, v in d.items():
            L.append(f"| {k} | {v} | {pct(v, sv['n'])}% |")
        L.append("")

    block("알게 된 경로", sv["source"])
    block("라이딩 경력", sv["experience"])
    block("보유 바이크 급", sv["own_class"])
    block("렌탈 목적", sv["purpose"])
    block("모델 선택 이유", sv["reason"])
    block("구매 계획", sv["buy_plan"])
    block("주 라이딩 시간대", sv["ride_when"])
    block("바이크 선택 요소", sv["factor"])
    L.append("### 다음에 타보고 싶은 모델 (상위)\n")
    L.append(", ".join(f"{k}({v})" for k, v in sv["next_models_top"].items() if k not in (".", "없음")))
    L.append("\n### 추가 희망 모델 (상위)\n")
    L.append(", ".join(f"{k}({v})" for k, v in sv["wish_models_top"].items() if k not in (".", "없음", "없습니다")))

    L.append("\n## 5. 교차 분석\n")

    def ct_block(title, d, cols=None):
        L.append(f"### {title}\n")
        rows = list(d.items())
        if not rows:
            return
        cols = cols or list(rows[0][1].keys())
        L.append("| | " + " | ".join(str(c) for c in cols) + " |")
        L.append("|---|" + "---|" * len(cols))
        for k, v in rows:
            L.append(f"| {k} | " + " | ".join(str(v.get(c, 0)) for c in cols) + " |")
        L.append("")

    ct = summary["crosstabs"]
    ct_block("구매 계획 × 마케팅 동의", ct["buy_x_consent"])
    ct_block("라이딩 경력 × 구매 계획", ct["exp_x_buy"])
    ct_block("보유 바이크 급 × 구매 계획", ct["own_x_buy"])
    ct_block("유입 경로 × 구매 계획", ct["source_x_buy"])
    ct_block("유입 경로 × 마케팅 동의", ct["source_x_consent"])
    ct_block("선택 요소 × 라이딩 경력", ct["factor_x_exp"])

    L.append("## 6. 리드 등급\n")
    L.append("| 등급 | 인원 |\n|---|---|")
    for k in ["HOT", "WARM", "COLD", "미설문"]:
        L.append(f"| {k} | {summary['lead_tiers'].get(k, 0):,} |")
    L.append("\n스코어: 구매계획(3개월 40 / 6개월 25 / 1년 15) + 마케팅동의 20 + 유효연락처 10 + 목적 '구매 전 시승·비교' 10 + 이유 '구매 전 시승' 10 + 설문완료 5 + 8월 가입 5. HOT ≥70, WARM 40~69, COLD <40.\n")
    L.append("## 7. 세그먼트\n")
    L.append("| 코드 | 세그먼트 | 인원 | 유효연락처 | 마케팅동의 | 액션 |\n|---|---|---|---|---|---|")
    for sg in summary["segments"]:
        L.append(f"| {sg['code']} | {sg['name']} | {sg['count']:,} | {sg['with_valid_phone']:,} | {sg['with_consent']:,} | {sg['description']} |")
    L.append("\n세그먼트별 명단은 `crm/output/CRM_마스터_*.xlsx` 의 각 시트에 있다(개인정보 포함, git 미추적).\n")
    path.write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def write_excel(df: pd.DataFrame, seg_frames: dict[str, pd.DataFrame], summary: dict, path: Path) -> None:
    def prep(d: pd.DataFrame) -> pd.DataFrame:
        out = d[EXPORT_COLS].copy()
        out["대표계정"] = out["대표계정"].map({True: "Y", False: "N"})
        out["마케팅제외"] = out["마케팅제외"].map({True: "Y", False: ""})
        return out.sort_values(["리드스코어", COL["joined"]], ascending=[False, False])

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        seg_tbl = pd.DataFrame(summary["segments"]).rename(columns={
            "code": "코드", "name": "세그먼트", "description": "설명/액션", "count": "인원",
            "with_valid_phone": "유효연락처", "with_consent": "마케팅동의"})
        seg_tbl.to_excel(xw, sheet_name="세그먼트요약", index=False)
        prep(df).to_excel(xw, sheet_name="회원마스터", index=False)
        for name, d in seg_frames.items():
            prep(d).to_excel(xw, sheet_name=name[:31], index=False)

        # 열 너비 보정
        for ws in xw.book.worksheets:
            for col_cells in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col_cells[:200])
                ws.column_dimensions[col_cells[0].column_letter].width = min(max(10, width * 1.4), 50)
            ws.freeze_panes = "A2"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", type=Path, help="기준 회원 설문 xlsx (생략 시 raw/ 최신 '전체' 파일)")
    args = ap.parse_args()
    src = args.master or find_master_file()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = load_master(src)
    df = mark_duplicates(df)
    df, seg_frames = assign_segments(df)
    summary = build_summary(df, seg_frames, src)

    cutoff = summary["meta"]["data_cutoff"]
    xlsx = OUT_DIR / f"CRM_마스터_{cutoff}.xlsx"
    write_excel(df, seg_frames, summary, xlsx)
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=int), encoding="utf-8")
    write_markdown(summary, OUT_DIR / "분석요약.md")

    print(f"source : {src}")
    print(f"members: {len(df):,}  survey: {summary['overview']['survey_done']}  consent: {summary['overview']['consent_yes']}")
    print(f"xlsx   : {xlsx}")
    print(f"summary: {OUT_DIR / 'summary.json'}, {OUT_DIR / '분석요약.md'}")
    for sg in summary["segments"]:
        print(f"  {sg['code']} {sg['name']:<20} {sg['count']:>5}  phone={sg['with_valid_phone']:>5}  consent={sg['with_consent']:>4}")


if __name__ == "__main__":
    main()
