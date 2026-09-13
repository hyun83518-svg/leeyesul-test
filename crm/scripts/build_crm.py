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
    df["탈퇴"] = df[COL["name"]].eq("탈퇴한 사용자") | (df[COL["email"]].isna() & df[COL["phone"]].isna())
    df["마케팅제외"] = (
        df["탈퇴"]
        | df[COL["role"]].fillna("USER").ne("USER")
        | df[COL["consent_src"]].eq("ADMIN_TEST_ACCOUNT")
        | df["이메일_소문자"].str.contains(r"test@|@test\.", regex=True, na=False)
    )

    for q in MULTI_SELECT_QS:
        df[q + "_list"] = df[q].map(lambda v: canon_multi(v, CHOICES[q]))
    df["보유바이크_급"] = df[COL["q_own"]].map(own_class)
    df["보유바이크_모델"] = df[COL["q_own"]].map(own_model)
    df["바이크보유"] = df["보유바이크_급"].map(lambda c: None if c is None else c != "없음")
    return df


def load_member_admin() -> pd.DataFrame | None:
    """'회원 관리' 내보내기(번호/이름=닉네임/실명/이메일/연락처/권한/소속지점/가입일) 페이지 파일을 모두 합친다."""
    files = sorted(RAW_DIR.glob("회원관리_*.xlsx"))
    if not files:
        return None
    frames = []
    for f in files:
        d = pd.read_excel(f, dtype=str).replace({"-": pd.NA, "": pd.NA})
        d.columns = [c.strip() for c in d.columns]
        if "실명" in d.columns:            # 07-24 레이아웃: 이름=닉네임, 실명=본명
            d = d.rename(columns={"이름": "닉네임"})
        elif "닉네임" in d.columns:        # 07-30 레이아웃: 이름=본명, 닉네임
            d = d.rename(columns={"이름": "실명"})
        d["_src"] = f.name
        frames.append(d)
    m = pd.concat(frames, ignore_index=True)
    m["이메일_소문자"] = m["이메일"].str.strip().str.lower()
    m = m.drop_duplicates("이메일_소문자", keep="last")
    return m.rename(columns={"번호": "회원관리_번호", "닉네임": "회원관리_닉네임", "실명": "회원관리_실명",
                             "연락처": "회원관리_연락처", "가입일": "회원관리_가입일"})[
        ["이메일_소문자", "회원관리_번호", "회원관리_닉네임", "회원관리_실명", "회원관리_연락처", "회원관리_가입일"]]


def merge_member_admin(df: pd.DataFrame, m: pd.DataFrame | None) -> pd.DataFrame:
    if m is None:
        df["회원관리_실명"] = pd.NA
        df["회원관리_번호"] = pd.NA
        return df
    df = df.merge(m, on="이메일_소문자", how="left")
    # 설문 파일의 '이름'이 비어 있거나 다르면 회원관리 실명으로 보강
    df["실명"] = df["회원관리_실명"].fillna(df[COL["name"]])
    # 설문 파일에 연락처가 없고 회원관리에 있으면 보강
    fill = df["연락처_정규화"].isna() & df["회원관리_연락처"].notna()
    df.loc[fill, "연락처_정규화"] = df.loc[fill, "회원관리_연락처"].map(normalize_phone)
    df["연락처_유효"] = df["연락처_정규화"].notna()
    return df


def survey_snapshots() -> list[dict]:
    """raw/ 의 회원설문_<날짜>_전체 파일들을 읽어 날짜별 설문·동의 누적 추이를 만든다."""
    rows = []
    for f in sorted(RAW_DIR.glob("회원설문_*_전체.xlsx")):
        d = pd.read_excel(f, dtype=str, usecols=["가입일", "마케팅수신", "설문완료"]).replace({"-": pd.NA})
        m = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
        rows.append({
            "snapshot": m.group(1) if m else f.name,
            "members": int(len(d)),
            "survey_done": int(d["설문완료"].eq("완료").sum()),
            "consent_yes": int(d["마케팅수신"].eq("동의").sum()),
            "consent_no": int(d["마케팅수신"].eq("미동의").sum()),
        })
    for i in range(1, len(rows)):
        rows[i]["members_delta"] = rows[i]["members"] - rows[i - 1]["members"]
        rows[i]["survey_delta"] = rows[i]["survey_done"] - rows[i - 1]["survey_done"]
        rows[i]["consent_delta"] = rows[i]["consent_yes"] - rows[i - 1]["consent_yes"]
    return rows


RCA_HEAVY_MIN = 3   # R1 헤비 기준 수강 횟수 (문서의 267명은 다른 기준/시점일 수 있어 조정 가능)


def load_rca() -> pd.DataFrame | None:
    """레인조아카데미(RCA) 회원 DB: No/회원등급/이름/이메일/휴대전화/가입일/이메일인증/보유포인트/수강횟수."""
    files = sorted(RAW_DIR.glob("레인조_*.xlsx"))
    if not files:
        return None
    frames = [pd.read_excel(f, dtype=str) for f in files]
    r = pd.concat(frames, ignore_index=True).dropna(axis=1, how="all")
    r.columns = [c.strip() for c in r.columns]
    r["RCA_수강횟수"] = pd.to_numeric(r["수강횟수"], errors="coerce").fillna(0).astype(int)
    r["RCA_포인트"] = pd.to_numeric(r["보유포인트"], errors="coerce").fillna(0).astype(int)
    r["RCA_등급"] = r["회원등급"]
    r["RCA_가입일"] = r["가입일"].str[:10]
    r["RCA_이름"] = r["이름"]
    r["RCA_이메일"] = r["이메일"].str.strip().str.lower()
    r["RCA_연락처"] = r["휴대전화"].map(lambda v: normalize_phone("0" + str(v)) if pd.notna(v) and str(v).startswith("10") else normalize_phone(v))
    r["RCA구분"] = pd.cut(r["RCA_수강횟수"], bins=[-1, 0, RCA_HEAVY_MIN - 1, 10**6],
                          labels=["R3_미수강", "R2_수강경험", "R1_헤비"]).astype(str)
    # 한 사람이 여러 계정이면 수강횟수 많은 쪽을 대표로
    r = r.sort_values("RCA_수강횟수", ascending=False)
    return r[["RCA_이름", "RCA_이메일", "RCA_연락처", "RCA_등급", "RCA_가입일", "RCA_수강횟수", "RCA_포인트", "RCA구분"]]


def merge_rca(df: pd.DataFrame, r: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """연락처 → 이메일 순으로 매칭. 반환: (마스터, 회원여부가 표시된 RCA 전체)"""
    cols = ["RCA_등급", "RCA_가입일", "RCA_수강횟수", "RCA_포인트", "RCA구분"]
    for c in cols:
        df[c] = pd.NA
    df["RCA회원"] = False
    if r is None:
        return df, None
    by_phone = r.dropna(subset=["RCA_연락처"]).drop_duplicates("RCA_연락처").set_index("RCA_연락처")
    by_email = r.dropna(subset=["RCA_이메일"]).drop_duplicates("RCA_이메일").set_index("RCA_이메일")
    matched_keys_phone, matched_keys_email = set(), set()
    for i in df.index:
        ph, em = df.at[i, "연락처_정규화"], df.at[i, "이메일_소문자"]
        row = None
        if pd.notna(ph) and ph in by_phone.index:
            row = by_phone.loc[ph]; matched_keys_phone.add(ph)
        elif pd.notna(em) and em in by_email.index:
            row = by_email.loc[em]; matched_keys_email.add(em)
        if row is not None:
            for c in cols:
                df.at[i, c] = row[c]
            df.at[i, "RCA회원"] = True
    r = r.copy()
    r["아르테파인회원"] = r["RCA_연락처"].isin(matched_keys_phone) | r["RCA_이메일"].isin(matched_keys_email)
    return df, r


# ---------------------------------------------------------------------------
# 결제(렌탈) 내역
# ---------------------------------------------------------------------------
# 차종 → (장르, 배기량대). 새 차종이 나오면 여기에 추가한다. 없는 차종은 ('기타', '미상').
MODEL_INFO = {
    "675SR-R": ("스포츠", "미들급"), "675NK": ("네이키드", "미들급"), "450SR": ("스포츠", "쿼터급"),
    "450CL-C BOBBER": ("크루저", "쿼터급"), "450CL-C": ("크루저", "쿼터급"), "450MT": ("어드벤처", "쿼터급"),
    "800MT-X": ("어드벤처", "미들급"), "450NK": ("네이키드", "쿼터급"),
    "R 1300 RT": ("투어러", "리터급"), "R 12 NineT": ("클래식", "리터급"), "M 1000 RR": ("슈퍼스포츠", "리터급"),
    "F 900XR": ("어드벤처", "미들급"), "R 12 GS": ("어드벤처", "리터급"), "K 1600 B": ("투어러", "리터급"),
    "R 18 Transcontinental": ("투어러", "리터급"), "R 1250 GS ADV": ("어드벤처", "리터급"),
    "Bonneville T120": ("클래식", "리터급"), "SCRAMBLER 400X": ("클래식", "쿼터급"),
    "TIGER 900 GT PRO": ("어드벤처", "미들급"), "Daytona660": ("스포츠", "미들급"),
    "CBR1000RR-R": ("슈퍼스포츠", "리터급"), "CBR600RR": ("슈퍼스포츠", "미들급"), "CBR650R E-Clutch": ("스포츠", "미들급"),
    "Super cub 110": ("커브", "소형"), "CT125A 헌터커브": ("커브", "소형"), "REBEL500": ("크루저", "미들급"),
    "NX500": ("어드벤처", "미들급"), "NT1100 DCT": ("투어러", "리터급"), "GB350C": ("클래식", "쿼터급"),
    "CB1000SP": ("네이키드", "리터급"), "CB300NA": ("네이키드", "쿼터급"),
    "VITPILEN 125": ("네이키드", "소형"), "VITPILEN 701": ("네이키드", "미들급"),
    "SVARTPILEN125": ("네이키드", "소형"), "SVARTPILEN 401": ("네이키드", "쿼터급"),
    "XSR900GP(ABS)": ("클래식", "미들급"), "Guerrilla 450": ("네이키드", "쿼터급"),
}
CC_ORDER = ["소형", "쿼터급", "미들급", "리터급"]


def time_pref(hour: float) -> str | None:
    if pd.isna(hour):
        return None
    h = int(hour)
    if 17 <= h <= 20:
        return "저녁형"
    if h >= 21 or h <= 5:
        return "심야형"
    if 6 <= h <= 9:
        return "새벽·오전형"
    return "낮형"


def load_payments() -> pd.DataFrame | None:
    """결제내역_<날짜>_전체.xlsx 의 '결제상세' 시트. 여러 파일이면 합치고 (결제일, 고객명, 예약일, 차종)로 중복 제거."""
    files = sorted(RAW_DIR.glob("결제내역_*_전체.xlsx"))
    if not files:
        return None
    frames = [pd.read_excel(f, sheet_name="결제상세", dtype=str) for f in files]
    P = pd.concat(frames, ignore_index=True)
    P.columns = [c.strip() for c in P.columns]
    P = P.drop_duplicates(["결제일", "고객명", "예약일", "차종"])
    P["결제일시"] = pd.to_datetime(P["결제일"], format="%Y.%m.%d %H:%M", errors="coerce")
    P["예약시작"] = pd.to_datetime(P["예약일"] + " " + P["예약시작시간"], format="%Y.%m.%d %H:%M", errors="coerce")
    P["반납예정"] = pd.to_datetime(P["반납예정일"] + " " + P["반납예정시간"], format="%Y.%m.%d %H:%M", errors="coerce")
    for c in ["결제금액", "취소금액", "환불금액", "위약금액", "시작주행거리", "반납주행거리"]:
        P[c] = pd.to_numeric(P[c], errors="coerce")
    P["순결제"] = P["결제금액"].fillna(0) - P["환불금액"].fillna(0)
    P["취소"] = P["취소금액"].fillna(0) > 0
    P["이용시간"] = (P["반납예정"] - P["예약시작"]).dt.total_seconds() / 3600
    P["주행거리"] = P["반납주행거리"] - P["시작주행거리"]
    P["모델"] = P["차종"].str.split(" / ").str[0].str.strip()
    P["장르"] = P["모델"].map(lambda m: MODEL_INFO.get(m, ("기타", "미상"))[0])
    P["배기량대"] = P["모델"].map(lambda m: MODEL_INFO.get(m, ("기타", "미상"))[1])
    P["시작시"] = P["예약시작"].dt.hour
    P["주말"] = P["예약시작"].dt.dayofweek >= 5
    P["연락처_정규화"] = P["연락처"].map(normalize_phone)
    P["이메일_소문자"] = P["이메일"].str.strip().str.lower()
    P["프로모"] = P["프로모코드"].notna()
    return P


def customer_aggregates(P: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """고객 키(연락처 → 이메일 → 고객명)별 이용 집계."""
    P = P.copy()
    P["고객키"] = P["연락처_정규화"].fillna(P["이메일_소문자"]).fillna(P["고객명"])
    V = P[~P["취소"]]

    def mode(x):
        x = x.dropna()
        return x.mode().iloc[0] if len(x) else None

    g = V.groupby("고객키")
    A = pd.DataFrame({
        "결제횟수": g.size(),
        "순결제금액": g["순결제"].sum().round(0),
        "첫예약일": g["예약시작"].min().dt.date,
        "최근예약일": g["예약시작"].max().dt.date,
        "주지점": g["예약 지점"].agg(mode),
        "이용지점수": g["예약 지점"].nunique(),
        "취향브랜드": g["브랜드"].agg(mode),
        "취향장르": g["장르"].agg(mode),
        "이용장르": g["장르"].agg(lambda x: ",".join(sorted(set(x.dropna())))),
        "이용모델": g["모델"].agg(lambda x: ",".join(sorted(set(x.dropna())))),
        "최대배기량": g["배기량대"].agg(lambda x: max((c for c in x if c in CC_ORDER), key=CC_ORDER.index, default=None)),
        "평균이용시간": g["이용시간"].mean().round(1),
        "주말비율": g["주말"].mean().round(2),
        "시간성향": g["시작시"].agg(lambda x: time_pref(x.mode().iloc[0]) if len(x.dropna()) else None),
        "유입경로_결제": g["유입경로"].agg(mode),
        "프로모사용": g["프로모"].any(),
    })
    C = P.groupby("고객키").agg(취소횟수=("취소", "sum"))
    A = A.join(C, how="outer")
    A["결제횟수"] = A["결제횟수"].fillna(0).astype(int)
    A["취소횟수"] = A["취소횟수"].fillna(0).astype(int)
    A["최근성_일"] = (cutoff - pd.to_datetime(A["최근예약일"])).dt.days
    A["첫이용_경과일"] = (cutoff - pd.to_datetime(A["첫예약일"])).dt.days
    A["주말성향"] = A["주말비율"].map(lambda v: None if pd.isna(v) else ("Y" if v >= 0.5 else "N"))
    A["리터급경험"] = A["이용장르"].notna() & A["최대배기량"].eq("리터급")
    return A.reset_index()


def merge_payments(df: pd.DataFrame, A: pd.DataFrame | None) -> pd.DataFrame:
    cols = [c for c in A.columns if c != "고객키"] if A is not None else []
    if A is None:
        df["결제회원"] = False
        return df
    by_phone = A.set_index("고객키")
    df["_key"] = df["연락처_정규화"]
    df.loc[df["_key"].isna() | ~df["_key"].isin(by_phone.index), "_key"] = df["이메일_소문자"]
    df = df.merge(A, left_on="_key", right_on="고객키", how="left").drop(columns=["_key", "고객키"])
    df["결제회원"] = df["결제횟수"].fillna(0).gt(0)
    df["결제횟수"] = df["결제횟수"].fillna(0).astype(int)
    df["취소횟수"] = df["취소횟수"].fillna(0).astype(int)
    return df


def payment_summary(P: pd.DataFrame | None, A: pd.DataFrame | None, df: pd.DataFrame) -> dict | None:
    if P is None:
        return None
    V = P[~P["취소"]]
    paying = df[df["결제회원"]]
    matched_keys = set(paying["연락처_정규화"].dropna()) | set(paying["이메일_소문자"].dropna())
    return {
        "period": f"{P['결제일시'].min():%Y-%m-%d} ~ {P['결제일시'].max():%Y-%m-%d}",
        "rows": int(len(P)), "valid_rows": int(len(V)), "cancel_rows": int(P["취소"].sum()),
        "cancel_rate_pct": round(P["취소"].mean() * 100, 1),
        "gross": int(P["결제금액"].sum()), "refund": int(P["환불금액"].sum()), "penalty": int(P["위약금액"].sum()),
        "net": int(P["순결제"].sum()),
        "customers": int(A["고객키"].nunique()), "repeat_2plus": int((A["결제횟수"] >= 2).sum()),
        "repeat_3plus": int((A["결제횟수"] >= 3).sum()),
        "median_net_per_customer": float(A["순결제금액"].median()),
        "by_branch": V.groupby("예약 지점").agg(건수=("순결제", "size"), 순매출=("순결제", "sum")).astype(int).to_dict(orient="index"),
        "by_brand": V["브랜드"].value_counts().to_dict(),
        "by_genre": V["장르"].value_counts().to_dict(),
        "by_cc": V["배기량대"].value_counts().to_dict(),
        "by_model_top": V["모델"].value_counts().head(15).to_dict(),
        "by_source": V["유입경로"].value_counts().to_dict(),
        "promo_rows": int(V["프로모"].sum()), "promo_codes": V["프로모코드"].value_counts().to_dict(),
        "by_hour": {int(k): int(v) for k, v in V["시작시"].value_counts().sort_index().items()},
        "by_weekday": {int(k): int(v) for k, v in V["예약시작"].dt.dayofweek.value_counts().sort_index().items()},
        "time_pref": A["시간성향"].value_counts().to_dict(),
        "weekend_pref": A["주말성향"].value_counts().to_dict(),
        "duration_quantiles": {str(k): round(v, 1) for k, v in V["이용시간"].quantile([.25, .5, .75, .9]).items()},
        "members_paying": int(len(paying)),
        "paying_survey_done": int(paying["설문완료_bool"].sum()),
        "paying_consent_yes": int((paying[COL["consent"]] == "동의").sum()),
        "paying_consent_no": int((paying[COL["consent"]] == "미동의").sum()),
        "paying_consent_unasked": int((paying["마케팅상태"] == "미응답").sum()),
        "paying_rca": int(paying["RCA회원"].sum()),
        "members_not_paying": int((~df["결제회원"] & ~df["마케팅제외"]).sum()),
    }


def load_extra_sources() -> dict[str, pd.DataFrame]:
    """추후 업로드되는 예약/렌탈/결제(세분화_기준표적용.xlsx 등) 병합 지점. 현재는 비어 있다."""
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


# 전략 문서(고객세분화_타겟팅 2026-07, 광고문자 운영뼈대 v2) 체계에 맞춘 페르소나 태그.
# 설문 응답으로 추정 가능한 것만 정의한다. 렌탈 이용 데이터가 붙으면 조건을 실측 기반으로 교체한다.
def _has(col, val):
    return lambda d: d[col + "_list"].map(lambda l: val in l)


def _pay(col):
    return lambda d: d[col] if col in d.columns else pd.Series(pd.NA, index=d.index)


PERSONA_DEFS = [
    ("P01_퇴근후직장인", "문자 페르소나 ① 퇴근 후 직장인 (실측)",
     "결제 고객 중 시간성향 저녁형(17~20시). 결제 이력 없으면 설문 '평일 저녁'",
     lambda d: _pay("시간성향")(d).eq("저녁형") | (~d["결제회원"] & _has(COL["q_when"], "평일 저녁")(d))),
    ("P02_주말애아빠후보", "문자 페르소나 ② 주말 짬내는 애아빠 (연령 제외 실측)",
     "결제 고객 중 주말성향 Y + 평균이용 2~4시간. 결제 없으면 설문 '주말 오전'",
     lambda d: (_pay("주말성향")(d).eq("Y") & _pay("평균이용시간")(d).between(2, 4))
               | (~d["결제회원"] & _has(COL["q_when"], "주말 오전")(d))),
    ("P03_교육수료실전파", "문자 페르소나 ③ 교육 수료 실전파 (실측)",
     "RCA 수강 1회 이상 + 렌탈 미결제",
     lambda d: pd.to_numeric(d["RCA_수강횟수"], errors="coerce").fillna(0).ge(1) & ~d["결제회원"]),
    ("P04_야간라이딩족", "문자 페르소나 ④ 야간 라이딩족 (실측)",
     "결제 고객 중 시간성향 심야형(21시~05시)",
     lambda d: _pay("시간성향")(d).eq("심야형")),
    ("P05_얼리버드", "문자 페르소나 ⑤ 얼리버드 아침형 (실측)",
     "결제 고객 중 시간성향 새벽·오전형(06~09시). 결제 없으면 설문 '새벽'",
     lambda d: _pay("시간성향")(d).eq("새벽·오전형") | (~d["결제회원"] & _has(COL["q_when"], "새벽")(d))),
    ("P06_복귀라이더", "문자 페르소나 ⑥ 복귀 라이더 (설문 기반)",
     "렌탈 목적 '오랜만에 라이딩(재입문)'. 휴면+과거 2회 이상은 이용 이력이 길어져야 판정 가능",
     _has(COL["q_purpose"], "오랜만에 라이딩 (재입문)")),
    ("P07_투어러", "문자 페르소나 ⑦ 중장년 투어러 (연령 제외)",
     "결제 취향장르 투어러/클래식, 또는 설문 목적 '투어링'",
     lambda d: _pay("취향장르")(d).isin(["투어러", "클래식"]) | _has(COL["q_purpose"], "투어링 (당일/박투어)")(d)),
    ("P08_스텝업", "문자 페르소나 ⑧ 스텝업 지망생 (실측)",
     "결제 고객 중 최대 이용 배기량 쿼터·미들급(리터급 미경험). 결제 없으면 설문 보유 쿼터·미들급",
     lambda d: (d["결제회원"] & _pay("최대배기량")(d).isin(["쿼터급", "미들급"]))
               | (~d["결제회원"] & d["보유바이크_급"].isin(["쿼터급", "미들급"]))),
    ("L_첫이용30일", "생애주기 CP011 첫이용 30일 재방문",
     "결제 1회 + 첫 이용 후 27~35일 경과 (기준일 대비)",
     lambda d: d["결제회원"] & d["결제횟수"].eq(1) & _pay("첫이용_경과일")(d).between(27, 35)),
    ("L_프로모전환자", "생애주기 CP009 전환자 재방문 쿠폰",
     "프로모코드로 결제한 고객 (동일 할인 재발송 금지 그룹)",
     lambda d: d["결제회원"] & _pay("프로모사용")(d).eq(True)),
    ("L_단골2회이상", "생애주기 CP008 이탈위험 win-back 후보",
     "결제 2회 이상. 최근성 30일 넘으면 win-back 대상",
     lambda d: d["결제회원"] & d["결제횟수"].ge(2)),
    ("L_회원_미결제", "퍼널: 회원이지만 결제 이력 없음",
     "회원 + 결제 0회 (조회 기간 07-01~08-13 기준)",
     lambda d: ~d["결제회원"]),
    # (태그, 전략문서 명칭, 근거 조건 설명, 필터)
    ("S05_장롱면허입문", "세그먼트 ⑤ 장롱면허 / 보험 소구 1순위",
     "경력 3개월 미만 + 바이크 없음, 또는 목적 '입문 전 연습'",
     lambda d: (d[COL["q_exp"]].eq("3개월 미만") & d["보유바이크_급"].eq("없음")) | _has(COL["q_purpose"], "입문 전 연습")(d)),
    ("S06_기변기추예정", "세그먼트 ⑥ 기변·기추 예정자 / 우선순위 5점",
     "바이크 보유 + 구매 계획 1년 내", lambda d: d["바이크보유"].eq(True) & d[COL["q_buy"]].isin(["3개월 내", "6개월 내", "1년 내"])),
    ("S10_커플데이트", "세그먼트 ⑩ 커플 / '특별한 경험' 동기그룹",
     "렌탈 목적에 '도심 라이딩·데이트(텐덤)' 포함", _has(COL["q_purpose"], "도심 라이딩·데이트(텐덤)")),
    ("S13_평일휴무", "세그먼트 ⑬ 평일 휴무 고객",
     "라이딩 시간대가 평일 낮만(주말 미선택)",
     lambda d: d[COL["q_when"] + "_list"].map(lambda l: "평일 낮" in l and not ({"주말 오전", "주말 오후"} & set(l)))),
    ("X_유튜브시청자", "확장 타깃 '유튜브 시청자'",
     "알게 된 경로 유튜브 또는 모델 선택 이유 '유튜브·SNS 보고'",
     lambda d: _has(COL["q_source"], "유튜브")(d) | _has(COL["q_reason"], "유튜브·SNS 보고")(d)),
    ("X_구매직전", "확장 타깃 '구매 직전 고객' / 동기 '사기 전에 확인하고 싶다'",
     "구매 계획 3개월 내", lambda d: d[COL["q_buy"]].eq("3개월 내")),
    ("X_고가기종시승", "보험 소구 '기변·고가 기종 시승'",
     "보유 리터급 또는 희망 모델에 리터급 슈퍼스포츠 언급",
     lambda d: d["보유바이크_급"].eq("리터급") | d[COL["q_next"]].fillna("").str.lower().str.contains(
         r"s1000|m1000|v4|r1\b|zx.?10|파니갈레|1300", regex=True)),
]

MOTIVE_GROUPS = {
    "다시 시작하고 싶다": ["P06_복귀라이더", "S05_장롱면허입문"],
    "사기 전에 확인하고 싶다": ["S06_기변기추예정", "X_구매직전"],
    "시간이 부족하다": ["P01_퇴근후직장인", "P02_주말애아빠후보"],
    "새로운 취미를 찾는다": ["S05_장롱면허입문"],
    "특별한 경험을 원한다": ["S10_커플데이트", "P07_투어러"],
    "불안해서 망설인다": ["S05_장롱면허입문", "P06_복귀라이더", "X_고가기종시승"],
}


def assign_personas(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    tags = [[] for _ in range(len(df))]
    masks: dict[str, pd.Series] = {}
    for tag, _name, _why, fn in PERSONA_DEFS:
        m = fn(df).fillna(False).astype(bool) & ~df["마케팅제외"]
        if tag.startswith(("P03", "P04", "L_")) or (tag.startswith("P") and "결제회원" in df.columns):
            pass  # 실측 기반 태그는 설문 완료 여부와 무관
        else:
            m = m & df["설문완료_bool"]
        masks[tag] = m
        for pos in range(len(df)):
            if m.iloc[pos]:
                tags[pos].append(tag)
    df["페르소나"] = [",".join(t) for t in tags]
    motive = []
    for t in tags:
        ts = set(t)
        motive.append(",".join(g for g, members in MOTIVE_GROUPS.items() if ts & set(members)))
    df["동기그룹"] = motive
    return df, masks


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
    ("S16", "RCA교차_수강경험",
     "레인조 수강 1회 이상 + 아르테파인 회원. RCA 브릿지 캠페인(경험 소구만, 가격 소구 금지). 렌탈 결제 이력 붙으면 '미결제'로 좁힌다.",
     lambda d: d["RCA회원"] & pd.to_numeric(d["RCA_수강횟수"], errors="coerce").fillna(0).ge(1)),
    ("S17", "RCA교차_미수강",
     "레인조 가입만 하고 미수강 + 아르테파인 회원. 문서 규칙(R3)대로 렌탈 광고 중단, 교육 모집만.",
     lambda d: d["RCA회원"] & pd.to_numeric(d["RCA_수강횟수"], errors="coerce").fillna(0).eq(0)),
    ("S18", "결제고객_전체",
     "조회 기간 내 유효 결제 1회 이상. 거래 관계가 있어 정보성 안내 가능. 광고는 동의자만.",
     lambda d: d["결제회원"]),
    ("S19", "결제고객_동의미응답",
     "결제 고객인데 마케팅 동의를 물어본 적 없음. 앱 로그인 시 동의 모달 1순위 노출 대상.",
     lambda d: d["결제회원"] & d["마케팅상태"].eq("미응답")),
    ("S20", "결제고객_재이용2회이상",
     "단골. 멤버십·로테이션 안내·LTV 상위는 지점 전화.",
     lambda d: d["결제회원"] & d["결제횟수"].ge(2)),
    ("S21", "결제고객_취소만",
     "결제했지만 전부 취소된 고객. 취소 사유 확인·재예약 유도.",
     lambda d: ~d["결제회원"] & d["취소횟수"].ge(1)),
    ("S14", "데이터정리_중복계정",
     "동일 연락처 다중 계정. 계정 통합/대표계정 확정 필요.",
     lambda d: d["중복그룹"].notna()),
    ("S15", "데이터정리_연락처비정상",
     "연락처가 010 11자리 형식이 아님(해외번호·오입력). SMS 발송 전 검수.",
     lambda d: d["연락처_원본"].notna() & ~d["연락처_유효"]),
]

EXPORT_COLS = [
    COL["no"], COL["name"], "실명", COL["nick"], COL["email"], "연락처_정규화", "연락처_원본", COL["platform"], COL["role"],
    COL["branch"], COL["fav_branch"], COL["joined"], COL["consent"], COL["consent_at"], COL["consent_src"],
    COL["survey_done"], COL["survey_at"], "리드스코어", "리드등급", "세그먼트", "페르소나", "동기그룹", "중복그룹", "대표계정", "마케팅제외", "탈퇴", "회원관리_번호", "RCA회원", "RCA구분", "RCA_수강횟수", "RCA_등급",
    "결제회원", "결제횟수", "취소횟수", "순결제금액", "첫예약일", "최근예약일", "최근성_일", "주지점", "취향브랜드", "취향장르", "이용모델",
    "최대배기량", "평균이용시간", "주말성향", "시간성향", "유입경로_결제", "프로모사용",
    COL["q_source"], COL["q_exp"], "보유바이크_급", "보유바이크_모델", COL["q_purpose"], COL["q_reason"],
    COL["q_buy"], COL["q_when"], COL["q_factor"], COL["q_next"], COL["q_wish"],
]


def assign_segments(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
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
    return df, masks


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
        "snapshots": survey_snapshots(),
        "member_admin": {
            "matched": int(df["회원관리_번호"].notna().sum()),
            "unmatched": int(df["회원관리_번호"].isna().sum()),
            "withdrawn": int(df["탈퇴"].sum()),
        },
        "personas": [
            {"tag": tag, "framework_name": name, "condition": why,
             "count": int(len(seg_frames[tag])), "with_consent": int((seg_frames[tag][COL["consent"]] == "동의").sum())}
            for tag, name, why, _ in PERSONA_DEFS
        ],
        "motive_groups": {g: int(df["동기그룹"].str.contains(g, regex=False).sum()) for g in MOTIVE_GROUPS},
        "segments": [
            {"code": code, "name": name, "description": desc, "count": int(len(seg_frames[f"{code}_{name}"])),
             "with_valid_phone": int(seg_frames[f"{code}_{name}"]["연락처_유효"].sum()),
             "with_consent": int((seg_frames[f"{code}_{name}"][COL["consent"]] == "동의").sum())}
            for code, name, desc, _ in SEGMENT_DEFS
        ],
    }
    return summary


def rca_summary(df: pd.DataFrame, rca: pd.DataFrame | None) -> dict | None:
    if rca is None:
        return None
    cross = df[df["RCA회원"]]
    return {
        "rca_total": int(len(rca)),
        "rca_by_group": rca["RCA구분"].value_counts().to_dict(),
        "rca_vip": int((rca["RCA_등급"] == "VIP").sum()),
        "rca_by_year": rca["RCA_가입일"].str[:4].value_counts().sort_index().to_dict(),
        "rca_valid_phone": int(rca["RCA_연락처"].notna().sum()),
        "cross_members": int(len(cross)),
        "cross_by_group": cross["RCA구분"].value_counts().to_dict(),
        "cross_survey_done": int(cross["설문완료_bool"].sum()),
        "cross_consent_yes": int((cross[COL["consent"]] == "동의").sum()),
        "cross_consent_no": int((cross[COL["consent"]] == "미동의").sum()),
        "rca_only_by_group": rca[~rca["아르테파인회원"]]["RCA구분"].value_counts().to_dict(),
        "heavy_min_courses": RCA_HEAVY_MIN,
    }


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
    if len(summary["snapshots"]) > 1:
        L.append("\n## 7-1. 스냅샷 추이 (회원 설문 내보내기 날짜별 누적)\n")
        L.append("| 기준일 | 회원 | 설문완료 | 동의 | 미동의 | 회원 증가 | 설문 증가 | 동의 증가 |\n|---|---|---|---|---|---|---|---|")
        for r in summary["snapshots"]:
            L.append(f"| {r['snapshot']} | {r['members']:,} | {r['survey_done']} | {r['consent_yes']} | {r['consent_no']} | "
                     f"{r.get('members_delta', '')} | {r.get('survey_delta', '')} | {r.get('consent_delta', '')} |")
    L.append("\n## 8. 전략 문서 페르소나 매핑 (설문 완료자 기준)\n")
    L.append("| 태그 | 전략 문서 명칭 | 데이터 조건 | 인원 | 마케팅동의 |\n|---|---|---|---|---|")
    for p in summary["personas"]:
        L.append(f"| {p['tag']} | {p['framework_name']} | {p['condition']} | {p['count']} | {p['with_consent']} |")
    L.append("\n동기 그룹별 인원(중복 포함): " + ", ".join(f"{g} {n}명" for g, n in summary["motive_groups"].items()))
    rc = summary.get("rca")
    if rc:
        L.append("\n## 9. 레인조아카데미(RCA) DB 교차\n")
        L.append("| 항목 | 값 |\n|---|---|")
        L.append(f"| RCA 회원 전체 | {rc['rca_total']:,} (VIP {rc['rca_vip']}) |")
        L.append(f"| RCA 구분 (R1 헤비 = {rc['heavy_min_courses']}회 이상) | " + ", ".join(f"{k} {v:,}" for k, v in sorted(rc['rca_by_group'].items())) + " |")
        L.append(f"| RCA 가입 연도 | " + ", ".join(f"{k} {v:,}" for k, v in rc['rca_by_year'].items()) + " |")
        L.append(f"| 아르테파인 회원과 교차 | {rc['cross_members']:,} (" + ", ".join(f"{k} {v}" for k, v in sorted(rc['cross_by_group'].items())) + ") |")
        L.append(f"| 교차 회원의 설문 완료 / 동의 / 미동의 | {rc['cross_survey_done']} / {rc['cross_consent_yes']} / {rc['cross_consent_no']} |")
        L.append(f"| RCA 전용(아르테파인 비회원) | " + ", ".join(f"{k} {v:,}" for k, v in sorted(rc['rca_only_by_group'].items())) + " |")
        L.append("\nRCA DB에는 광고 수신 동의 컬럼이 없다. RCA 명단으로 광고 문자를 보내려면 레인조 측 동의 근거를 별도로 확인해야 한다.\n")
    py = summary.get("payments")
    if py:
        L.append("\n## 10. 결제(렌탈) 내역 요약\n")
        L.append("| 항목 | 값 |\n|---|---|")
        L.append(f"| 결제일 범위 | {py['period']} |")
        L.append(f"| 결제 건수 / 유효 / 취소 | {py['rows']} / {py['valid_rows']} / {py['cancel_rows']} (취소율 {py['cancel_rate_pct']}%) |")
        L.append(f"| 결제금액 / 환불 / 위약금 / 순매출 | {py['gross']:,} / {py['refund']:,} / {py['penalty']:,} / {py['net']:,} |")
        L.append(f"| 유효 결제 고객 / 2회 이상 / 3회 이상 | {py['customers']} / {py['repeat_2plus']} / {py['repeat_3plus']} |")
        L.append(f"| 고객당 순결제 중앙값 | {py['median_net_per_customer']:,.0f} |")
        L.append(f"| 결제 고객 중 회원 매칭 | {py['members_paying']} (설문 {py['paying_survey_done']}, 동의 {py['paying_consent_yes']}, 미동의 {py['paying_consent_no']}, 미응답 {py['paying_consent_unasked']}, RCA 교차 {py['paying_rca']}) |")
        L.append(f"| 회원 중 결제 이력 없음 | {py['members_not_paying']:,} |")
        L.append(f"| 프로모코드 결제 | {py['promo_rows']} ({', '.join(f'{k} {v}' for k, v in py['promo_codes'].items())}) |")
        L.append(f"| 이용시간 분위(25/50/75/90%) | {' / '.join(f'{v}h' for v in py['duration_quantiles'].values())} |")
        L.append("\n지점별 유효 건수·순매출: " + ", ".join(f"{k} {v['건수']}건 {v['순매출']:,}원" for k, v in py['by_branch'].items()))
        L.append("\n브랜드: " + ", ".join(f"{k} {v}" for k, v in py['by_brand'].items()))
        L.append("\n장르: " + ", ".join(f"{k} {v}" for k, v in py['by_genre'].items()))
        L.append("\n배기량대: " + ", ".join(f"{k} {v}" for k, v in py['by_cc'].items()))
        L.append("\n모델 상위: " + ", ".join(f"{k} {v}" for k, v in py['by_model_top'].items()))
        L.append("\n유입경로(결제 시): " + ", ".join(f"{k} {v}" for k, v in py['by_source'].items()))
        L.append("\n예약 시작 시각별 건수: " + ", ".join(f"{k}시 {v}" for k, v in py['by_hour'].items()))
        L.append("\n요일별 건수(0=월): " + ", ".join(f"{k} {v}" for k, v in py['by_weekday'].items()))
        L.append("\n고객 시간성향: " + ", ".join(f"{k} {v}" for k, v in py['time_pref'].items()) + " · 주말성향: " + ", ".join(f"{k} {v}" for k, v in py['weekend_pref'].items()))
        L.append("")
    ma = summary["member_admin"]
    L.append(f"\n회원관리 파일 매칭: {ma['matched']:,}명 실명 확인 / 미매칭 {ma['unmatched']:,}명 / 탈퇴 {ma['withdrawn']}명\n")
    L.append("\n세그먼트별 명단은 `crm/output/CRM_마스터_*.xlsx` 의 각 시트에 있다(개인정보 포함, git 미추적).\n")
    path.write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def write_excel(df: pd.DataFrame, seg_frames: dict[str, pd.DataFrame], summary: dict, path: Path,
                rca: pd.DataFrame | None = None) -> None:
    def prep(d: pd.DataFrame) -> pd.DataFrame:
        out = d[EXPORT_COLS].copy()
        out["대표계정"] = out["대표계정"].map({True: "Y", False: "N"})
        out["마케팅제외"] = out["마케팅제외"].map({True: "Y", False: ""})
        out["탈퇴"] = out["탈퇴"].map({True: "Y", False: ""})
        return out.sort_values(["리드스코어", COL["joined"]], ascending=[False, False])

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        seg_tbl = pd.DataFrame(summary["segments"]).rename(columns={
            "code": "코드", "name": "세그먼트", "description": "설명/액션", "count": "인원",
            "with_valid_phone": "유효연락처", "with_consent": "마케팅동의"})
        seg_tbl.to_excel(xw, sheet_name="세그먼트요약", index=False)
        prep(df).to_excel(xw, sheet_name="회원마스터", index=False)
        for name, d in seg_frames.items():
            prep(d).to_excel(xw, sheet_name=name[:31], index=False)
        if rca is not None:
            rc = rca.rename(columns={"아르테파인회원": "아르테파인회원"}).copy()
            rc["아르테파인회원"] = rc["아르테파인회원"].map({True: "Y", False: ""})
            rc.sort_values(["RCA_수강횟수", "RCA_가입일"], ascending=[False, False]).to_excel(xw, sheet_name="RCA_전체", index=False)
            for g in ["R1_헤비", "R2_수강경험", "R3_미수강"]:
                rc[rc["RCA구분"] == g].to_excel(xw, sheet_name=f"RCA_{g}"[:31], index=False)

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
    df = merge_member_admin(df, load_member_admin())
    df, rca = merge_rca(df, load_rca())
    P = load_payments()
    cutoff_ts = pd.Timestamp(df[COL["joined"]].max())
    A = customer_aggregates(P, cutoff_ts) if P is not None else None
    df = merge_payments(df, A)
    df = mark_duplicates(df)
    df, seg_masks = assign_segments(df)
    df, persona_masks = assign_personas(df)
    seg_frames = {k: df[m] for k, m in seg_masks.items()}
    for tag, _n, _w, _f in PERSONA_DEFS:
        seg_frames[tag] = df[persona_masks[tag]]
    summary = build_summary(df, seg_frames, src)
    summary["rca"] = rca_summary(df, rca)
    summary["payments"] = payment_summary(P, A, df)

    cutoff = summary["meta"]["data_cutoff"]
    xlsx = OUT_DIR / f"CRM_마스터_{cutoff}.xlsx"
    write_excel(df, seg_frames, summary, xlsx, rca)
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
