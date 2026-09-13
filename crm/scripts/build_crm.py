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


SEND_TO_UNASKED = True   # 설문(수신동의 문항) 도입 전 가입자(미응답)에게도 CRM 문자를 보낸다는 운영 결정 (2026-09-13)
RCA_HEAVY_MIN = 4   # R1 헤비 = 4회 이상 (최종세분화명단의 정의와 일치)


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
    # 3~6월 라인업 (BMW 중심)
    "S 1000 RR": ("슈퍼스포츠", "리터급"), "S 1000 R": ("네이키드", "리터급"), "S 1000 XR": ("어드벤처", "리터급"),
    "M 1000 XR": ("어드벤처", "리터급"), "R 1300 GS": ("어드벤처", "리터급"), "R 1300 GS ADV": ("어드벤처", "리터급"),
    "R 1300 RS": ("투어러", "리터급"), "R 1300 R": ("네이키드", "리터급"), "R 1250 RT": ("투어러", "리터급"),
    "R NineT": ("클래식", "리터급"), "R 12 nineT": ("클래식", "리터급"), "R 12 G/S": ("어드벤처", "리터급"), "R 12 G": ("어드벤처", "리터급"),
    "F 900 GS ADV": ("어드벤처", "미들급"), "F 900 R": ("네이키드", "미들급"), "G 310 R": ("네이키드", "쿼터급"), "G 310 GS": ("어드벤처", "쿼터급"),
    "CL500A": ("클래식", "미들급"), "CB500X": ("어드벤처", "미들급"), "XL750 TRANSALP": ("어드벤처", "미들급"),
    "SVARTPILEN401": ("네이키드", "쿼터급"), "MSX125": ("커브", "소형"),
    "GTS125 SUPER": ("스쿠터", "소형"), "PRIMAVERA 125": ("스쿠터", "소형"), "LX 125": ("스쿠터", "소형"),
    "800MT-ES": ("어드벤처", "미들급"), "R NineT SCRAMBLER": ("클래식", "리터급"), "XSR900": ("클래식", "미들급"),
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
    files = sorted(RAW_DIR.glob("결제내역_*.xlsx"))
    if not files:
        return None
    frames = []
    for f in files:
        d = pd.read_excel(f, sheet_name="결제상세", dtype=str)
        d.columns = [c.strip() for c in d.columns]
        if "이메일" not in d.columns:      # 07-24 지점별 구버전(연락처 없음)은 전체 파일에 포함되므로 건너뜀
            continue
        d["_파일"] = f.name
        frames.append(d)
    P = pd.concat(frames, ignore_index=True)
    P["결제일"] = P["결제일"].str.strip()
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


def merge_by_key(df: pd.DataFrame, A: pd.DataFrame | None, cols: list[str], key: str = "고객키") -> pd.DataFrame:
    """고객키(연락처 → 이메일) 또는 지정 키로 집계 테이블을 마스터에 붙인다."""
    if A is None:
        for c in cols:
            df[c] = pd.NA
        return df
    if key == "고객키":
        idx = A.set_index("고객키")
        k = df["연락처_정규화"].where(df["연락처_정규화"].isin(idx.index), df["이메일_소문자"])
        return df.join(idx[cols], on=k.rename("_k")).drop(columns=["_k"], errors="ignore")
    return df.merge(A[[key] + cols], on=key, how="left")


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


# ---------------------------------------------------------------------------
# 웹 방문·캠페인 유입 리포트
# ---------------------------------------------------------------------------
def load_web_analytics() -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """웹분석_<시작>_<끝>.xlsx: '기본 데이터'(월별 방문자/PV/예약시작/문의)와 '캠페인 유입'.
    같은 월이 여러 파일에 있으면 종료일이 가장 늦은 파일의 값을 쓴다(더 완전한 집계)."""
    files = sorted(RAW_DIR.glob("웹분석_*.xlsx"))
    if not files:
        return None, None
    basics, camps = [], []
    for f in files:
        m = re.findall(r"(\d{4}-\d{2}-\d{2})", f.name)
        end = m[-1] if m else f.name
        b = pd.read_excel(f, sheet_name="기본 데이터", dtype=str)
        b["월"] = b["년/월"].str.extract(r"(\d{4})년\s*(\d{1,2})월").apply(lambda r: f"{r[0]}-{int(r[1]):02d}", axis=1)
        b["_end"] = end
        basics.append(b)
        c = pd.read_excel(f, sheet_name="캠페인 유입", dtype=str).rename(columns={"년/월": "월"})
        c["_end"] = end
        camps.append(c)
    # 같은 월이 여러 내보내기에 있으면 방문자 합이 가장 큰(=그 월을 온전히 담은) 내보내기를 채택
    B = pd.concat(basics, ignore_index=True)
    for c in ["방문자수", "페이지뷰(PV)", "예약시작", "문의제출"]:
        B[c] = pd.to_numeric(B[c], errors="coerce").fillna(0).astype(int)
    B = B.sort_values(["월", "방문자수"]).drop_duplicates("월", keep="last")
    B = B.sort_values("월")[["월", "방문자수", "페이지뷰(PV)", "예약시작", "문의제출"]]

    C = pd.concat(camps, ignore_index=True)
    for c in ["방문자수", "세션", "예약시작", "예약확정", "결제금액", "취소건수", "환불금액"]:
        C[c] = pd.to_numeric(C[c], errors="coerce").fillna(0).astype(int)
    tot = C.groupby(["월", "_end"])["방문자수"].sum().reset_index()
    best = tot.sort_values(["월", "방문자수"]).drop_duplicates("월", keep="last").set_index("월")["_end"]
    C = C[C["_end"] == C["월"].map(best)].copy()
    C["순결제"] = C["결제금액"] - C["환불금액"]
    C["확정율%"] = (C["예약확정"] / C["방문자수"].replace(0, pd.NA) * 100).astype(float).round(1)
    C["방문자당매출"] = (C["순결제"] / C["방문자수"].replace(0, pd.NA)).astype(float).round(0)
    C = C.sort_values(["월", "순결제"], ascending=[False, False])[
        ["월", "소스", "매체", "캠페인", "콘텐츠", "방문자수", "세션", "예약시작", "예약확정", "결제금액", "취소건수", "환불금액", "순결제", "확정율%", "방문자당매출"]]
    return B, C


def web_summary(B: pd.DataFrame | None, C: pd.DataFrame | None) -> dict | None:
    if B is None:
        return None
    by_medium = C.groupby(["소스", "매체"]).agg(방문자=("방문자수", "sum"), 예약시작=("예약시작", "sum"), 예약확정=("예약확정", "sum"),
                                              순결제=("순결제", "sum")).reset_index()
    by_medium["확정율%"] = (by_medium["예약확정"] / by_medium["방문자"].replace(0, pd.NA) * 100).astype(float).round(1)
    by_medium = by_medium.sort_values("순결제", ascending=False)
    by_camp = C[C["캠페인"].ne("-")].groupby("캠페인").agg(월=("월", lambda x: ",".join(sorted(set(x)))), 방문자=("방문자수", "sum"),
                                                     예약시작=("예약시작", "sum"), 예약확정=("예약확정", "sum"), 순결제=("순결제", "sum")).reset_index()
    by_camp["확정율%"] = (by_camp["예약확정"] / by_camp["방문자"].replace(0, pd.NA) * 100).astype(float).round(1)
    by_camp = by_camp.sort_values("순결제", ascending=False)
    return {
        "monthly": B.to_dict(orient="records"),
        "by_medium": by_medium.to_dict(orient="records"),
        "by_campaign": by_camp.to_dict(orient="records"),
        "campaign_rows": int(len(C)),
    }


# ---------------------------------------------------------------------------
# 세분화_기준표적용.xlsx (고객마스터 660 + 예약이력 3월~) → 결제상세 이전 기간 보강
# ---------------------------------------------------------------------------
GENRE_ALIAS = {"레플리카": "슈퍼스포츠", "스포츠투어러": "투어러", "스쿠터": "커브", "헤리티지": "클래식", "모던클래식": "클래식"}


def load_reservation_history() -> pd.DataFrame | None:
    files = sorted(RAW_DIR.glob("세분화_기준표적용_*.xlsx"))
    if not files:
        return None
    f = files[-1]
    M = pd.read_excel(f, sheet_name="고객마스터", dtype=str)
    H = pd.read_excel(f, sheet_name="예약이력", dtype=str)
    M["연락처_정규화"] = M["연락처"].map(normalize_phone)
    M["이메일_소문자"] = M["이메일"].str.strip().str.lower()
    idmap = M.set_index("고객ID")[["연락처_정규화", "이메일_소문자"]]
    H = H.join(idmap, on="고객ID")
    H["접수"] = pd.to_datetime(H["접수일"], errors="coerce")
    H["예약시작"] = pd.to_datetime(H["이용시작일"].str.replace(r"\.(\d)(?=\.|$)", r".0\1", regex=True), format="%Y.%m.%d", errors="coerce")
    H["순결제"] = pd.to_numeric(H["이용금액"], errors="coerce").fillna(0)
    H["취소"] = H["예약상태"].ne("이용완료")
    H["모델"] = H["기종"].str.strip()
    H["장르"] = H["모델"].map(lambda m: MODEL_INFO.get(m, (None, None))[0]).fillna(H["장르"].map(lambda g: GENRE_ALIAS.get(g, g)))
    H["배기량대"] = H["모델"].map(lambda m: MODEL_INFO.get(m, (None, "미상"))[1])
    H["예약 지점"] = H["지점"].map({"용산": "Yongsan", "인천": "Incheon", "분당": "Bundang", "대구": "Daegu", "제주": "Jeju"}).fillna(H["지점"])
    H["브랜드"] = pd.NA
    H["출처"] = "예약이력"
    return H[["접수", "예약시작", "순결제", "취소", "모델", "장르", "배기량대", "예약 지점", "브랜드", "연락처_정규화", "이메일_소문자", "출처"]]


def unify_history(P: pd.DataFrame | None, H: pd.DataFrame | None) -> pd.DataFrame | None:
    """결제상세(P)가 시작되기 전 기간은 예약이력(H)로 보강해 3월부터의 이용 이벤트를 만든다."""
    if P is None and H is None:
        return None
    parts = []
    if P is not None:
        Pp = P.rename(columns={"결제일시": "접수"})[["접수", "예약시작", "순결제", "취소", "모델", "장르", "배기량대", "예약 지점", "브랜드", "연락처_정규화", "이메일_소문자"]].copy()
        Pp["출처"] = "결제상세"
        parts.append(Pp)
        if H is not None:
            # 결제상세 파일별 (최소~최대 결제일) 구간 밖의 예약이력만 보강
            covered = pd.Series(False, index=H.index)
            for a, b in P.groupby("_파일")["결제일시"].agg(["min", "max"]).itertuples(index=False):
                covered |= (H["접수"] >= a.normalize()) & (H["접수"] <= b.normalize() + pd.Timedelta(days=1))
            parts.append(H[~covered])
    else:
        parts.append(H)
    E = pd.concat(parts, ignore_index=True)
    E["고객키"] = E["연락처_정규화"].fillna(E["이메일_소문자"])
    return E[E["고객키"].notna()]


def history_aggregates(E: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    V = E[~E["취소"]]
    g = V.groupby("고객키")
    A = pd.DataFrame({
        "이력_이용횟수": g.size(),
        "이력_이용금액": g["순결제"].sum().round(0),
        "이력_첫이용일": g["예약시작"].min().dt.date,
        "이력_최근이용일": g["예약시작"].max().dt.date,
        "이력_이용지점수": g["예약 지점"].nunique(),
        "이력_최대배기량": g["배기량대"].agg(lambda x: max((c for c in x if c in CC_ORDER), key=CC_ORDER.index, default=None)),
        "이력_이용장르": g["장르"].agg(lambda x: ",".join(sorted(set(x.dropna())))),
    })
    A["이력_취소횟수"] = E[E["취소"]].groupby("고객키").size().reindex(A.index).fillna(0).astype(int)
    A["이력_최근성_일"] = (cutoff - pd.to_datetime(A["이력_최근이용일"])).dt.days

    def stage(r):
        if r["이력_최근성_일"] <= 30:
            return "활성"
        if r["이력_이용횟수"] >= 2 and r["이력_최근성_일"] <= 90:
            return "이탈위험"
        return "휴면"
    A["생애단계"] = A.apply(stage, axis=1)
    return A.reset_index()


def load_suppression() -> set[str]:
    """최종세분화명단_*.xlsx 의 수신거부_차단기록 시트 → 연락처 집합."""
    out = set()
    for f in list(RAW_DIR.glob("최종세분화명단_*.xlsx")) + list(RAW_DIR.glob("발송용명단_*.xlsx")):
        try:
            for h in range(0, 4):
                d = pd.read_excel(f, sheet_name="수신거부_차단기록", dtype=str, header=h)
                if "연락처" in d.columns:
                    break
        except ValueError:
            continue
        if "연락처" in d.columns:
            out |= set(d["연락처"].map(normalize_phone).dropna())
    return out


def load_prior_vip() -> pd.DataFrame | None:
    """최종세분화명단의 VIP 표기와 세그먼트를 가져온다(기존 작업 보존용)."""
    files = sorted(RAW_DIR.glob("최종세분화명단_*.xlsx"))
    if not files:
        return None
    d = pd.read_excel(files[-1], sheet_name="아르테파인_명단", dtype=str)
    d["연락처_정규화"] = d["연락처"].map(normalize_phone)
    d = d.dropna(subset=["연락처_정규화"]).drop_duplicates("연락처_정규화")
    return d.rename(columns={"VIP": "기존VIP", "세그먼트": "기존세그먼트"})[["연락처_정규화", "기존VIP", "기존세그먼트"]]


# ---------------------------------------------------------------------------
# 발송 이력 (문자 캠페인) + 명단 전수 대조 전환
# ---------------------------------------------------------------------------
def load_send_log() -> pd.DataFrame | None:
    rows = []
    # (a) 세분화_기준표적용 발송이력 시트 (07-25 T1~T3A)
    for f in sorted(RAW_DIR.glob("세분화_기준표적용_*.xlsx")):
        S = pd.read_excel(f, sheet_name="발송이력", dtype=str)
        M = pd.read_excel(f, sheet_name="고객마스터", dtype=str)
        S = S.join(M.set_index("고객ID")[["연락처"]], on="고객ID")
        cp2promo = {"CP016": "20260724_promo", "CP017": "20260724_promo", "CP018": "20260724_promo",
                    "CP013": "202607_promo", "CP014": "202607_promo", "CP015": "202607_promo"}
        for _, r in S.iterrows():
            rows.append({"발송일": pd.to_datetime(r["발송일"]), "캠페인": cp2promo.get(r["캠페인ID"], r["캠페인ID"]),
                         "캠페인명": r["캠페인명(자동)"], "채널": r["채널"],
                         "연락처_정규화": normalize_phone(r["연락처"]), "타겟": r["캠페인명(자동)"][:3].strip()})
    # (b) 발송명단_<날짜>_*.xlsx: 시트마다 명단 (이름/연락처/…)
    # 발송일 → (캠페인 코드, 설명, 사용할 시트 목록(None=자동), 홀드아웃 시트)
    meta = {"2026-07-25": ("20260724_promo", "토요발송 T1~T3A", None, None),
            "2026-07-31": ("20260731_promo", "금요저녁 용산밤바리/인천오션라이딩", None, None),
            "2026-08-07": ("20260807_promo", "금요 17시 지점별 발송 (용산 밤바리/인천/분당 얼리버드, ys·ic·bd_promo)", None, None),
            "2026-08-14": ("20260814_연휴", "연휴 심야 LMS 500명 (거래관계/수신동의/미응답)", None, None),
            "2026-08-22": ("20260822RENT_promo", "토요 14시 용산 정가 찍먹 3종 / 인천 반값위크 (RENT-YS/IC)", ["02_명단_용산", "03_명단_인천"], None),
            "2026-09-04": ("20260904RENT_promo", "금요 2시간 무료 (ys-return/ys-new/ic-0904)", ["02_용산_재방문", "03_용산_신규", "04_인천"], "06_홀드아웃_발송금지")}
    for f in sorted(RAW_DIR.glob("발송명단_*.xlsx")):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
        day = m.group(1) if m else None
        # 등록된 회차가 없으면 파일명 규칙으로 자동 인식: 발송명단_<YYYY-MM-DD>_<캠페인코드>.xlsx
        #  - '연락처'/'전화번호' 컬럼이 있는 시트 = 수신자 명단 (단, 시트명에 제외·보류·참고·요약·문안·설명·라인업·차종·체크·자동화·검증·KPI 가 있으면 건너뜀)
        #  - 시트명에 '홀드아웃' 이 있으면 대조군
        auto_code = f.stem.split("_", 2)[2] if f.stem.count("_") >= 2 else f.stem
        camp, cname, sheets, holdout = meta.get(day, (auto_code, f"{day} {auto_code}", None, None))
        skip_words = ("제외", "보류", "참고", "요약", "문안", "설명", "라인업", "차종", "체크", "자동화", "검증", "KPI", "기존예약")
        xl = pd.ExcelFile(f)
        for sh in xl.sheet_names:
            is_holdout = (holdout is not None and sh == holdout) or (holdout is None and "홀드아웃" in sh)
            if sheets is not None and sh not in sheets and not is_holdout:
                continue
            if sheets is None and not is_holdout and (any(w in sh for w in skip_words) or sh.startswith(("①", "②", "④"))):
                continue
            d = pd.read_excel(f, sheet_name=sh, dtype=str)
            if "전화번호" in d.columns:
                d = d.rename(columns={"전화번호": "연락처"})
            if "연락처" not in d.columns:      # 제목 행이 있는 레이아웃(연휴 명단 ③)
                for h in range(1, 6):
                    d = pd.read_excel(f, sheet_name=sh, dtype=str, header=h)
                    if "연락처" in d.columns:
                        break
            if "연락처" not in d.columns:
                continue
            tgt_col = next((c for c in ["발송근거", "구분", "세그먼트"] if c in d.columns), None)
            for _, r in d.iterrows():
                tgt = r[tgt_col] if tgt_col else sh
                if tgt_col == "세그먼트" and not is_holdout:
                    prefix = re.sub(r"^\d+_", "", sh).split("(")[0]
                    tgt = f"{prefix} {tgt}"
                if is_holdout:
                    tgt = f"홀드아웃 {tgt}"
                rows.append({"발송일": pd.to_datetime(day), "캠페인": camp, "캠페인명": cname,
                             "채널": "미발송(대조군)" if is_holdout else "SMS",
                             "연락처_정규화": normalize_phone(r["연락처"]), "타겟": tgt})
    if not rows:
        return None
    L = pd.DataFrame(rows).dropna(subset=["연락처_정규화"])
    # 같은 날 같은 사람에게 같은 캠페인이 발송이력 시트와 발송명단 파일 양쪽에 있으면 한 건으로
    L = L.drop_duplicates(["발송일", "연락처_정규화"], keep="first")
    L["홀드아웃"] = L["채널"].eq("미발송(대조군)")
    return L


def attach_conversions(L: pd.DataFrame, E: pd.DataFrame | None, window_days: int = 14) -> pd.DataFrame:
    """발송 후 window_days 안에 유효 결제(예약이력/결제상세 기준)가 있으면 전환으로 본다(명단 전수 대조 방식)."""
    L = L.copy()
    L["전환"] = False
    L["전환금액"] = 0.0
    L["전환예약일"] = pd.NaT
    L["발송시_이용횟수"] = 0
    L["발송시_최근성_일"] = pd.NA
    L["발송시_생애단계"] = "미이용"
    if E is None:
        return L
    V = E[~E["취소"] & E["연락처_정규화"].notna()]
    byp = {k: g.sort_values("접수") for k, g in V.groupby("연락처_정규화")}
    for i, r in L.iterrows():
        g = byp.get(r["연락처_정규화"])
        if g is None:
            continue
        before = g[g["접수"] < r["발송일"]]
        n_before = len(before)
        L.at[i, "발송시_이용횟수"] = n_before
        if n_before:
            rec = (r["발송일"] - before["예약시작"].max()).days
            L.at[i, "발송시_최근성_일"] = rec
            L.at[i, "발송시_생애단계"] = "활성" if rec <= 30 else ("이탈위험" if (n_before >= 2 and rec <= 90) else "휴면")
        w = g[(g["접수"] >= r["발송일"]) & (g["접수"] < r["발송일"] + pd.Timedelta(days=window_days))]
        if len(w):
            L.at[i, "전환"] = True
            L.at[i, "전환금액"] = float(w["순결제"].sum())
            L.at[i, "전환예약일"] = w["예약시작"].min()
    return L


def send_aggregates(L: pd.DataFrame) -> pd.DataFrame:
    L = L[~L["홀드아웃"]]
    g = L.groupby("연락처_정규화")
    A = pd.DataFrame({
        "발송횟수": g.size(),
        "최근발송일": g["발송일"].max().dt.date,
        "발송캠페인": g["캠페인"].agg(lambda x: ",".join(sorted(set(x)))),
        "발송후전환": g["전환"].any(),
        "발송전환금액": g["전환금액"].sum(),
    })
    for ym, sub in L.groupby(L["발송일"].dt.strftime("%Y-%m")):
        A[f"발송_{ym}"] = sub.groupby("연락처_정규화").size().reindex(A.index).fillna(0).astype(int)
    return A.reset_index()


# 개인 명단이 없는 대량 발송: 세분화 v2 캠페인마스터 메모 + 웹분석 캠페인 유입 기준 (방문/확정/순매출)
MASS_CAMPAIGNS = [
    {"발송일": "2026-07-11", "캠페인": "202607_promo", "캠페인명": "0711 상시 프로모 최대30% — 회원 문자(sms_01)", "타겟": "회원 전체(대량)", "발송": 3517, "전환자": 24, "전환매출": 1310000, "근거": "웹분석 확정 24·순매출 131만원 (캠페인마스터 메모)"},
    {"발송일": "2026-07-11", "캠페인": "202607_promo", "캠페인명": "0711 상시 프로모 — RCA 교육생(raincho)", "타겟": "RCA 전체(대량)", "발송": 5005, "전환자": 3, "전환매출": 30000, "근거": "웹분석 확정 3·순매출 3만원. 수신자 40%가 미수강"},
    {"발송일": "2026-07-11", "캠페인": "202607_promo", "캠페인명": "0711 상시 프로모 — 카카오 친구톡(kakao_01)", "타겟": "카카오 구독자(대량)", "발송": None, "전환자": 5, "전환매출": 330000, "근거": "웹분석 확정 5·순매출 33만원"},
]


PAY_MAX: pd.Timestamp | None = None   # main()에서 결제상세 최대 결제일로 설정


def coverage_note(send_day: pd.Timestamp, window_days: int = 14) -> str:
    if PAY_MAX is None:
        return "측정 불가: 결제 데이터 없음"
    days = (PAY_MAX - send_day).days
    if days >= window_days:
        return "명단 전수 대조 (발송 후 14일 내 유효 결제)"
    if days < 1:
        return f"측정 불가: 결제 데이터 {PAY_MAX:%m-%d}까지"
    return f"부분 측정({days}일치): 결제 데이터 {PAY_MAX:%m-%d}까지"


def campaign_performance(L: pd.DataFrame) -> pd.DataFrame:
    g = L.groupby(["발송일", "캠페인", "캠페인명", "타겟", "채널"])
    C = pd.DataFrame({"발송": g.size(), "전환자": g["전환"].sum(), "전환매출": g["전환금액"].sum()}).reset_index()
    C["근거"] = [("대조군(미발송) 동일 창 결제 · " if ch.startswith("미발송") else "") + coverage_note(d)
               for d, ch in zip(C["발송일"], C["채널"])]
    C["발송일"] = C["발송일"].dt.strftime("%Y-%m-%d")
    C = C.drop(columns=["채널"])
    C = pd.concat([pd.DataFrame(MASS_CAMPAIGNS), C], ignore_index=True)
    C["전환율%"] = (C["전환자"] / C["발송"] * 100).round(1)
    return C.sort_values(["발송일", "타겟"])[["발송일", "캠페인", "캠페인명", "타겟", "발송", "전환자", "전환율%", "전환매출", "근거"]]


def recipient_profile(df: pd.DataFrame, L: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """문자 수신자의 성격(생애단계·시간성향·주말성향·취향장르·지점·동의상태·설문 페르소나)을 캠페인/타겟별로 집계."""
    L = L[~L["홀드아웃"]].copy()
    L["측정가능"] = L["발송일"].map(lambda d: PAY_MAX is not None and (PAY_MAX - d).days >= 14)
    rec = L.merge(df.drop_duplicates("연락처_정규화")[[
        "연락처_정규화", "시간성향", "주말성향", "취향장르", "주지점", "마케팅상태", "이력_이용횟수", "이력_최대배기량",
        "RCA회원", "VIP산정", "설문완료_bool", COL["q_buy"], COL["q_exp"], "가입월"]], on="연락처_정규화", how="left")
    rec["매칭"] = rec["마케팅상태"].notna()
    rec["생애단계"] = rec["발송시_생애단계"]
    dims = ["생애단계", "시간성향", "주말성향", "취향장르", "주지점", "마케팅상태", "이력_최대배기량", COL["q_buy"]]
    tables = []
    for (camp, tgt), g in rec.groupby(["캠페인", "타겟"]):
        n = len(g)
        row = {"캠페인": camp, "타겟": tgt, "발송": n, "회원매칭": int(g["매칭"].sum()), "이력고객": int(g["이력_이용횟수"].fillna(0).gt(0).sum()),
               "RCA회원": int(g["RCA회원"].fillna(False).sum()), "VIP": int(g["VIP산정"].fillna(False).sum()),
               "설문완료": int(g["설문완료_bool"].fillna(False).sum()), "전환자": int(g["전환"].sum()), "전환율%": round(g["전환"].mean() * 100, 1)}
        for dcol in dims:
            vc = g[dcol].fillna("미상").value_counts()
            row[dcol] = ", ".join(f"{k} {v}" for k, v in vc.head(6).items())
        # 전환자 vs 비전환자의 특징 차이
        conv = g[g["전환"]]
        row["전환자_시간성향"] = ", ".join(f"{k} {v}" for k, v in conv["시간성향"].fillna("미상").value_counts().items())
        row["전환자_생애단계"] = ", ".join(f"{k} {v}" for k, v in conv["생애단계"].fillna("미상").value_counts().items())
        row["전환자_취향장르"] = ", ".join(f"{k} {v}" for k, v in conv["취향장르"].fillna("미상").value_counts().items())
        tables.append(row)
    T = pd.DataFrame(tables)
    # 전체 수신자 기준 차원별 전환율
    overall = {}
    recm = rec[rec["측정가능"]]
    for dcol in ["생애단계", "시간성향", "주말성향", "취향장르", "주지점", "마케팅상태", "이력_최대배기량"]:
        ct = recm.groupby(recm[dcol].fillna("미상"))["전환"].agg(["size", "sum"])
        ct["전환율%"] = (ct["sum"] / ct["size"] * 100).round(1)
        overall[dcol] = ct.rename(columns={"size": "발송", "sum": "전환자"}).sort_values("발송", ascending=False).head(8).to_dict(orient="index")
    return {"by_target": T.to_dict(orient="records"), "by_dimension": overall,
            "recipients_total": int(rec["연락처_정규화"].nunique()), "recipients_matched": int(rec[rec["매칭"]]["연락처_정규화"].nunique()),
            "measurable_sends": int(recm.shape[0]), "measurable_campaigns": sorted(set(recm["캠페인"])),
            "pay_max": PAY_MAX.strftime("%Y-%m-%d") if PAY_MAX is not None else None}, T


LINEUP_SOURCES = [("발송명단_2026-09-04_2시간무료.xlsx", "07_차종현황", 2, "2026-09-02"),
                  ("발송명단_2026-08-22_지점별.xlsx", "05_라인업", 3, "2026-08-22")]


def load_lineup() -> pd.DataFrame | None:
    frames = []
    for fname, sh, h, asof in LINEUP_SOURCES:
        f = RAW_DIR / fname
        if not f.exists():
            continue
        d = pd.read_excel(f, sheet_name=sh, header=h, dtype=str)
        d = d[d.iloc[:, 0].isin(["용산", "인천", "분당", "대구", "제주"])]
        d.insert(0, "기준일", asof)
        frames.append(d)
    return pd.concat(frames, ignore_index=True) if frames else None


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
    ("P06_복귀라이더", "문자 페르소나 ⑥ 복귀 라이더 (실측)",
     "휴면 + 과거 이용 2회 이상. 이력 없으면 설문 '오랜만에 라이딩(재입문)'",
     lambda d: (d["생애단계"].eq("휴면") & d["이력_이용횟수"].ge(2)) | (~d["이력고객"] & _has(COL["q_purpose"], "오랜만에 라이딩 (재입문)")(d))),
    ("P07_투어러", "문자 페르소나 ⑦ 중장년 투어러 (연령 제외)",
     "결제 취향장르 투어러/클래식, 또는 설문 목적 '투어링'",
     lambda d: _pay("취향장르")(d).isin(["투어러", "클래식"]) | _has(COL["q_purpose"], "투어링 (당일/박투어)")(d)),
    ("P08_스텝업", "문자 페르소나 ⑧ 스텝업 지망생 (실측)",
     "결제 고객 중 최대 이용 배기량 쿼터·미들급(리터급 미경험). 결제 없으면 설문 보유 쿼터·미들급",
     lambda d: (d["이력고객"] & d["이력_최대배기량"].isin(["쿼터급", "미들급"]))
               | (~d["이력고객"] & d["보유바이크_급"].isin(["쿼터급", "미들급"]))),
    ("L_첫이용30일", "생애주기 CP011 첫이용 30일 재방문",
     "결제 1회 + 첫 이용 후 27~35일 경과 (기준일 대비)",
     lambda d: d["결제회원"] & d["결제횟수"].eq(1) & _pay("첫이용_경과일")(d).between(27, 35)),
    ("L_프로모전환자", "생애주기 CP009 전환자 재방문 쿠폰",
     "프로모코드로 결제한 고객 (동일 할인 재발송 금지 그룹)",
     lambda d: d["결제회원"] & _pay("프로모사용")(d).eq(True)),
    ("L_단골2회이상", "생애주기 CP008 이탈위험 win-back 후보",
     "결제 2회 이상. 최근성 30일 넘으면 win-back 대상",
     lambda d: d["이력고객"] & d["이력_이용횟수"].ge(2)),
    ("L_회원_미결제", "퍼널: 회원이지만 이용 이력 없음",
     "회원 + 3월 이후 유효 이용 0회",
     lambda d: ~d["이력고객"]),
    ("L_활성", "생애단계 활성", "최근 이용 30일 이내", lambda d: d["생애단계"].eq("활성")),
    ("L_이탈위험", "생애주기 CP008 이탈위험 win-back", "이용 2회 이상 + 최근 이용 31~90일", lambda d: d["생애단계"].eq("이탈위험")),
    ("L_휴면", "휴면 고객 (가을 시즌 각성 캠페인 풀)", "이용 이력 있음 + 활성/이탈위험 아님", lambda d: d["생애단계"].eq("휴면")),
    ("VIP_산정", "VIP (최종세분화명단 정의 재산정)", "3월 이후 이용 3회+ 또는 순결제 20만+ 또는 RCA교차+결제", lambda d: d["VIP산정"]),
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
        if tag.startswith(("P03", "P04", "L_", "VIP")) or (tag.startswith("P") and "결제회원" in df.columns):
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
    ("S22", "발송가능_전체",
     "운영 정책상 CRM 문자 발송 가능 풀: 동의자 + 설문 도입 전 미응답자 (미동의·수신거부·제외 계정 제외, 유효 연락처).",
     lambda d: d["발송가능"]),
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
    "이력고객", "이력_이용횟수", "이력_이용금액", "이력_첫이용일", "이력_최근이용일", "이력_최근성_일", "이력_최대배기량", "이력_이용장르", "생애단계",
    "VIP산정", "기존VIP", "기존세그먼트", "수신거부", "발송가능", "발송횟수", "최근발송일", "발송캠페인", "발송후전환", "발송전환금액",
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
            "sendable_policy": int(df["발송가능"].sum()) if "발송가능" in df.columns else None,
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


def history_summary(df: pd.DataFrame, E: pd.DataFrame | None) -> dict | None:
    if E is None:
        return None
    V = E[~E["취소"]]
    hist = df[df["이력고객"]]
    return {
        "period": f"{E['접수'].min():%Y-%m-%d} ~ {E['접수'].max():%Y-%m-%d}",
        "events": int(len(E)), "valid_events": int(len(V)),
        "by_source": E["출처"].value_counts().to_dict(),
        "monthly_net": {str(k): int(v) for k, v in V.groupby(V["접수"].dt.to_period("M"))["순결제"].sum().items()},
        "monthly_customers": {str(k): int(v) for k, v in V.groupby(V["접수"].dt.to_period("M"))["고객키"].nunique().items()},
        "customers": int(V["고객키"].nunique()),
        "members_with_history": int(len(hist)),
        "stage": hist["생애단계"].value_counts().to_dict(),
        "stage_x_consent": pd.crosstab(hist["생애단계"], hist["마케팅상태"]).to_dict(orient="index"),
        "visits_dist": hist["이력_이용횟수"].clip(upper=5).value_counts().sort_index().to_dict(),
        "vip_calc": int(hist["VIP산정"].sum()),
        "vip_prior": df["기존VIP"].value_counts().to_dict(),
        "suppressed": int(df["수신거부"].sum()),
        "monthly_new_customers": {str(k): int(v) for k, v in V.groupby("고객키")["접수"].min().dt.to_period("M").value_counts().sort_index().items()},
    }


def send_summary(L: pd.DataFrame) -> dict:
    C = campaign_performance(L)
    Ls = L[~L["홀드아웃"]]
    per = Ls.groupby("연락처_정규화").size()
    monthly = Ls.groupby([Ls["발송일"].dt.strftime("%Y-%m"), "연락처_정규화"]).size()
    return {
        "sends": int(len(Ls)), "recipients": int(per.size), "holdout": int(L["홀드아웃"].sum()),
        "campaigns": C.to_dict(orient="records"),
        "conversion_window_days": 14,
        "over_cap_month": int((monthly > 2).sum()),
        "recipients_2plus": int((per >= 2).sum()),
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
    L.append(f"| 마케팅 제외 계정(관리자·매니저·테스트·탈퇴·수신거부) | {o['marketing_excluded_accounts']} |")
    L.append(f"| 발송 가능(동의 + 설문 도입 전 미응답, 유효 연락처) | {o['sendable_policy']:,} |")
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
    wb = summary.get("web")
    if wb:
        L.append("\n## 11. 웹 방문·캠페인 유입 (월별 최신 내보내기 기준)\n")
        L.append("| 월 | 방문자 | PV | 예약시작 | 문의 |\n|---|---|---|---|---|")
        for r in wb["monthly"]:
            L.append(f"| {r['월']} | {r['방문자수']:,} | {r['페이지뷰(PV)']:,} | {r['예약시작']:,} | {r['문의제출']} |")
        L.append("\n소스·매체별 (캠페인 유입 시트 합계, 2026-07~09):\n")
        L.append("| 소스 | 매체 | 방문자 | 예약시작 | 예약확정 | 순결제 | 확정율 |\n|---|---|---|---|---|---|---|")
        for r in wb["by_medium"]:
            L.append(f"| {r['소스']} | {r['매체']} | {r['방문자']:,} | {r['예약시작']:,} | {r['예약확정']} | {r['순결제']:,} | {r['확정율%']}% |")
        L.append("\n캠페인별:\n")
        L.append("| 캠페인 | 월 | 방문자 | 예약시작 | 예약확정 | 순결제 | 확정율 |\n|---|---|---|---|---|---|---|")
        for r in wb["by_campaign"]:
            L.append(f"| {r['캠페인']} | {r['월']} | {r['방문자']:,} | {r['예약시작']:,} | {r['예약확정']} | {r['순결제']:,} | {r['확정율%']}% |")
        L.append("")
    hs = summary.get("history")
    if hs:
        L.append("\n## 12. 이용 이력 통합 (예약이력 3월~ + 결제상세)\n")
        L.append("| 항목 | 값 |\n|---|---|")
        L.append(f"| 기간 | {hs['period']} |")
        L.append(f"| 이벤트 / 유효 | {hs['events']:,} / {hs['valid_events']:,} ({', '.join(f'{k} {v}' for k, v in hs['by_source'].items())}) |")
        L.append(f"| 유효 이용 고객 | {hs['customers']:,} (회원 매칭 {hs['members_with_history']:,}) |")
        L.append(f"| 생애단계 (활성 ≤30일, 이탈위험 2회+ & 31~90일, 그 외 휴면) | " + ", ".join(f"{k} {v}" for k, v in hs['stage'].items()) + " |")
        L.append(f"| 이용횟수 분포 (5+는 합산) | " + ", ".join(f"{k}회 {v}" for k, v in hs['visits_dist'].items()) + " |")
        L.append(f"| VIP 재산정(3회+ / 20만+ / RCA교차+결제) | {hs['vip_calc']} (기존 명단 표기: " + ", ".join(f"{k} {v}" for k, v in hs['vip_prior'].items()) + ") |")
        L.append(f"| 수신거부 반영 | {hs['suppressed']}명 마케팅 제외 |")
        L.append("\n월별 순매출: " + ", ".join(f"{k} {v:,}" for k, v in hs['monthly_net'].items()))
        L.append("\n월별 이용 고객: " + ", ".join(f"{k} {v}" for k, v in hs['monthly_customers'].items()))
        L.append("\n월별 첫 이용 고객(신규): " + ", ".join(f"{k} {v}" for k, v in hs['monthly_new_customers'].items()))
        L.append("\n생애단계 × 마케팅 상태:\n")
        L.append("| 단계 | 동의 | 미동의 | 미응답 |\n|---|---|---|---|")
        for k, v in hs["stage_x_consent"].items():
            L.append(f"| {k} | {v.get('동의', 0)} | {v.get('미동의', 0)} | {v.get('미응답', 0)} |")
    ss = summary.get("sends")
    if ss:
        L.append(f"\n## 13. 문자 발송 이력과 명단 전수 대조 전환 (발송 후 {ss['conversion_window_days']}일 내 유효 결제)\n")
        L.append(f"발송 {ss['sends']}건 / 수신자 {ss['recipients']}명 / 2회 이상 수신 {ss['recipients_2plus']}명 / 월 2통 상한 초과 {ss['over_cap_month']}명 / 홀드아웃 대조군 {ss.get('holdout', 0)}명\n")
        L.append("| 발송일 | 캠페인 | 타겟 | 발송 | 전환자 | 전환율 | 전환매출 | 근거 |\n|---|---|---|---|---|---|---|---|")
        for r in ss["campaigns"]:
            n = f"{int(r['발송']):,}" if r['발송'] == r['발송'] and r['발송'] is not None else "-"
            rate = f"{r['전환율%']}%" if r['전환율%'] == r['전환율%'] else "-"
            L.append(f"| {r['발송일']} | {r['캠페인']} | {r['타겟']} | {n} | {r['전환자']} | {rate} | {int(r['전환매출']):,} | {r['근거']} |")
        L.append("")
    rp = summary.get("recipient_profile")
    if rp:
        L.append(f"\n## 14. 문자 수신자 프로필 (수신자 {rp['recipients_total']}명, 회원 매칭 {rp['recipients_matched']}명)\n")
        L.append(f"차원별 전환율 — 결제 데이터({rp['pay_max']}까지)로 14일 창이 완전히 덮이는 발송만 집계: {', '.join(rp['measurable_campaigns'])} ({rp['measurable_sends']}건). 생애단계는 발송 시점 상태, 시간성향·장르는 전체 이력 기준:\n")
        for dcol, tbl in rp["by_dimension"].items():
            L.append(f"- **{dcol}**: " + ", ".join(f"{k} {v['발송']}명→{v['전환자']}명({v['전환율%']}%)" for k, v in tbl.items()))
        L.append("\n타겟별 구성(상위 값)과 전환자 특징:\n")
        L.append("| 캠페인 | 타겟 | 발송 | 이력고객 | 전환 | 생애단계 | 시간성향 | 취향장르 | 마케팅상태 | 전환자 시간성향 |\n|---|---|---|---|---|---|---|---|---|---|")
        for r in rp["by_target"]:
            L.append(f"| {r['캠페인']} | {r['타겟']} | {r['발송']} | {r['이력고객']} | {r['전환자']} ({r['전환율%']}%) | {r['생애단계']} | {r['시간성향']} | {r['취향장르']} | {r['마케팅상태']} | {r['전환자_시간성향']} |")
        L.append("")
    ma = summary["member_admin"]
    L.append(f"\n회원관리 파일 매칭: {ma['matched']:,}명 실명 확인 / 미매칭 {ma['unmatched']:,}명 / 탈퇴 {ma['withdrawn']}명\n")
    L.append("\n세그먼트별 명단은 `crm/output/CRM_마스터_*.xlsx` 의 각 시트에 있다(개인정보 포함, git 미추적).\n")
    path.write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def write_excel(df: pd.DataFrame, seg_frames: dict[str, pd.DataFrame], summary: dict, path: Path,
                rca: pd.DataFrame | None = None, WB: pd.DataFrame | None = None, WC: pd.DataFrame | None = None,
                L: pd.DataFrame | None = None, CP: pd.DataFrame | None = None, RPT: pd.DataFrame | None = None) -> None:
    def prep(d: pd.DataFrame) -> pd.DataFrame:
        out = d[EXPORT_COLS].copy()
        out["대표계정"] = out["대표계정"].map({True: "Y", False: "N"})
        out["마케팅제외"] = out["마케팅제외"].map({True: "Y", False: ""})
        out["탈퇴"] = out["탈퇴"].map({True: "Y", False: ""})
        for c in ["이력고객", "VIP산정", "수신거부", "발송후전환", "발송가능"]:
            out[c] = out[c].map({True: "Y", False: ""})
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

        if L is not None:
            CP.to_excel(xw, sheet_name="캠페인성과_명단대조", index=False)
            Lx = L.copy(); Lx["발송일"] = Lx["발송일"].dt.date
            Lx.to_excel(xw, sheet_name="발송이력", index=False)
            if RPT is not None:
                RPT.to_excel(xw, sheet_name="발송수신자_프로필", index=False)
        lineup = load_lineup()
        if lineup is not None:
            lineup.to_excel(xw, sheet_name="라인업_현황", index=False)
        if WB is not None:
            WB.to_excel(xw, sheet_name="웹_월별", index=False)
            WC.to_excel(xw, sheet_name="웹_캠페인유입", index=False)
        # 열 너비 보정
        for ws in xw.book.worksheets:
            for col_cells in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col_cells[:200])
                ws.column_dimensions[col_cells[0].column_letter].width = min(max(10, width * 1.4), 50)
            ws.freeze_panes = "A2"


# ---------------------------------------------------------------------------
# 타겟 통합본 (한 파일에 타겟별 시트)
# ---------------------------------------------------------------------------
TARGET_COLS = [
    "실명", COL["nick"], "연락처_정규화", COL["email"], "주지점", "마케팅상태", "발송가능", "생애단계",
    "이력_이용횟수", "이력_이용금액", "이력_최근이용일", "이력_최근성_일", "시간성향", "주말성향", "취향장르", "취향브랜드", "이용모델",
    "이력_최대배기량", "평균이용시간", "VIP산정", "RCA구분", "발송횟수", "최근발송일", "발송캠페인", "발송후전환",
    COL["q_buy"], COL["q_exp"], COL["q_when"], COL["q_purpose"], "페르소나", "세그먼트", COL["joined"],
]

_ACT = "활성"; _DOR = "휴면"; _RISK = "이탈위험"


def _genre_in(vals):
    return lambda d: d["취향장르"].isin(vals)


# (코드, 이름, 우선순위, 근거(실측), 권장 오퍼/문안 방향, 권장 발송 시점, 필터)
TARGET_DEFS = [
    ("A1", "활성_야간형", "A",
     "심야형 전환 11.3%(최고), 9/4 용산 야간경험 8.6%(9일치)", "금·토 심야 연장·야간 라이딩 소구", "발송 당일 18:30~19:30 (목·금)",
     lambda d: d["생애단계"].eq(_ACT) & d["시간성향"].eq("심야형")),
    ("A2", "활성_최근30일이용", "A",
     "발송 시점 활성 9.7% vs 휴면 2.5%·미이용 1.6%", "이달의 라인업·재방문 오퍼(2시간 무료 등)", "토 10:00 또는 목·금 16:00",
     lambda d: d["생애단계"].eq(_ACT)),
    ("A3", "활성_미들급_스텝업", "A",
     "미들급 이용자 10.9% > 리터급 6.5% > 쿼터급 4.7%", "\"다음 단계\" 리터급 시승 제안 (현재 라인업 CBR1000RR-R·TIGER 900)", "토 10:00",
     lambda d: d["생애단계"].isin([_ACT, _RISK]) & d["이력_최대배기량"].eq("미들급")),
    ("A4", "동의신규_미거래", "A",
     "9/4 D그룹 439명 1.8%(128만 원, 9일치), 8/22 동의 신규 2.2%. 동의자 전환 5.3% vs 미응답 2.2%", "첫 시승 오퍼(첫라이딩 9,900·시간 추가)", "금 15:00 / 토 10:00",
     lambda d: d["마케팅상태"].eq("동의") & ~d["이력고객"]),
    ("A5", "활성휴면_스포츠네이키드크루저어드벤처", "A",
     "장르별 전환 스포츠 12.6%·크루저 11.4%·네이키드 10.4%·어드벤처 8.8%", "장르 동일 현재 차종으로 소구 (675SR-R·450CL-C·450MT·TIGER 900)", "토 10:00",
     lambda d: d["생애단계"].isin([_ACT, _DOR]) & _genre_in(["스포츠", "네이키드", "크루저", "어드벤처", "슈퍼스포츠"])(d)),
    ("A6", "지점_분당_결제고객", "A",
     "분당 14.3%(56명 중 8명) 지점 최고", "분당 얼리버드·CFMOTO 라인 (평일 아침)", "목·금 10:00",
     lambda d: d["이력고객"] & d["주지점"].eq("Bundang")),
    ("A7", "지점_대구진주제주_결제고객", "A",
     "소규모 지점 회차용. 제주 5명 중 3명 전환", "지점별 라인업 안내", "토 10:00",
     lambda d: d["이력고객"] & d["주지점"].isin(["Daegu", "Jinju", "Jeju"])),
    ("B1", "휴면_반응장르", "B",
     "휴면 전체 2.5%. 반응 장르(스포츠·네이키드·크루저·어드벤처·슈퍼스포츠)만 추림", "라인업 교체·신차 입고 명분 + 정액 오퍼", "월 1회 대량 회차",
     lambda d: d["생애단계"].eq(_DOR) & _genre_in(["스포츠", "네이키드", "크루저", "어드벤처", "슈퍼스포츠"])(d)),
    ("B2", "휴면_투어러클래식", "B",
     "투어러 0.8%·클래식 6.8%. 문자 저반응, BMW 투어러 부재 영향", "신차(투어러·클래식) 입고 시에만 발송. 평소엔 제외", "입고 시",
     lambda d: d["생애단계"].eq(_DOR) & _genre_in(["투어러", "클래식"])(d)),
    ("B3", "이탈위험_단골", "B",
     "이탈위험 0.6%. 문자로는 안 돌아옴", "지점 전화·개인 메시지(LTV 상위부터)", "문자 대신 전화",
     lambda d: d["생애단계"].eq(_RISK)),
    ("B4", "첫이용_30일_자동화", "B",
     "CP011. 첫 이용 27~35일 경과 1회 이용자", "\"다음은 같은 장르의 [현재 차종]\" 재방문 안내", "상시 자동(이용 D+27~30)",
     lambda d: d["이력고객"] & d["이력_이용횟수"].eq(1) & pd.to_numeric(d["이력_최근성_일"], errors="coerce").between(27, 35)),
    ("B5", "프로모전환자_재발송금지", "B",
     "CP009. 프로모코드로 결제한 고객. 동일 할인 광고 재발송 금지 그룹", "감사 + 재방문 혜택(다른 오퍼)", "회차 후 1주",
     lambda d: d["프로모사용"].fillna(False).astype(bool) if "프로모사용" in d.columns else pd.Series(False, index=d.index)),
    ("B6", "VIP", "B",
     "3회+ / 순결제 20만+ / RCA교차+결제 (최종세분화명단 정의)", "서킷데이·신차 우선 시승 초대, 친구 소개 프로그램", "회차별 우선 포함",
     lambda d: d["VIP산정"]),
    ("B7", "RCA교차_수강경험", "B",
     "레인조 수강 1회+ & 아르테파인 회원. 문서 규칙: 경험 소구만, 가격 소구 금지", "\"배운 그 감각, 도로에서\" + 같은 장르 현재 차종", "수료 후 D+3~7 오전 10:00",
     lambda d: d["RCA회원"] & pd.to_numeric(d["RCA_수강횟수"], errors="coerce").fillna(0).ge(1)),
    ("C1", "미이용_회원_발송가능", "C",
     "이력 없는 회원 1.6%. 대량 회차·지점 미상. 최근 가입순 정렬", "첫 시승·초회 혜택. 지점 링크로 지점 분류 겸함", "월 1회 대량 (동의자 우선)",
     lambda d: ~d["이력고객"]),
    ("X1", "참고_미동의_단골_발송불가", "X",
     "미동의자 26명 중 9명 결제(34.6%)했지만 광고 발송 불가", "예약 확인·반납 안내 등 거래 메시지에 재방문 정보만", "발송 금지",
     lambda d: d["마케팅상태"].eq("미동의") & d["이력고객"]),
]


def write_target_book(df: pd.DataFrame, summary: dict, path: Path,
                      L: pd.DataFrame | None, CP: pd.DataFrame | None, lineup: pd.DataFrame | None) -> None:
    base = df[df["대표계정"] & ~df["마케팅제외"]].copy()
    base["연락처_정규화"] = base["연락처_정규화"].fillna("")
    base["_sortkey"] = pd.to_numeric(base["이력_최근성_일"], errors="coerce").fillna(10**6)

    def prep(d: pd.DataFrame) -> pd.DataFrame:
        out = d.sort_values(["발송가능", "_sortkey", COL["joined"]], ascending=[False, True, False])[TARGET_COLS].copy()
        for c in ["발송가능", "VIP산정", "발송후전환"]:
            out[c] = out[c].map({True: "Y", False: ""})
        return out.rename(columns={"연락처_정규화": "연락처", COL["nick"]: "닉네임"})

    catalog = []
    frames = {}
    for code, name, pri, why, offer, when, fn in TARGET_DEFS:
        mask = fn(base).fillna(False).astype(bool)
        if code != "X1":
            mask = mask & base["발송가능"]
        d = base[mask]
        frames[f"{code}_{name}"] = prep(d)
        catalog.append({"우선순위": pri, "코드": code, "타겟": name, "인원": int(len(d)),
                        "동의": int((d["마케팅상태"] == "동의").sum()), "미응답": int((d["마케팅상태"] == "미응답").sum()),
                        "이력고객": int(d["이력고객"].sum()), "9월 발송 이력 있음": int(d.get("발송_2026-09", pd.Series(0, index=d.index)).fillna(0).gt(0).sum()),
                        "실측 근거": why, "권장 오퍼·문안": offer, "권장 발송 시점": when})
    cat = pd.DataFrame(catalog)

    o = summary["overview"]; hs = summary.get("history") or {}; ss = summary.get("sends") or {}
    header = [
        ["아르테파인 CRM 타겟 통합본", ""],
        ["생성", summary["meta"]["generated_at"]],
        ["회원 기준", f"회원설문 {summary['meta']['source_file']} · 회원 {o['total_members']:,} · 설문 {o['survey_done']:,} · 동의 {o['consent_yes']:,}"],
        ["이용 이력", f"{hs.get('period', '-')} · 유효 이벤트 {hs.get('valid_events', 0):,} · 이용 고객 {hs.get('customers', 0):,}"],
        ["발송 이력", f"정밀 타겟 {ss.get('sends', 0):,}건 · 수신자 {ss.get('recipients', 0):,}명 · 홀드아웃 {ss.get('holdout', 0)}명 · 대량(7/11) 회원 3,517·RCA 5,005"],
        ["발송 정책", "동의자 + 설문 도입(8/2) 전 가입한 미응답자 발송. 미동의·수신거부·직원/테스트/탈퇴 제외. (광고) 표기·080 수신거부·08~20시 준수"],
        ["발송 가능 풀", f"{o.get('sendable_policy', 0):,}명 (대표계정·유효 연락처 기준)"],
        ["전환 정의", "발송 후 14일 내 유효 결제. 생애단계는 발송 시점 기준. 활성 ≤30일 / 이탈위험 2회+ & 31~90일 / 그 외 휴면"],
        ["시트 안내", "각 타겟 시트는 발송가능 → 최근 이용순 정렬. 같은 사람이 여러 타겟에 들어갈 수 있으니 회차 배정 시 상위 우선순위 1통만 (월 2통 상한)"],
        ["", ""],
    ]
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame(header).to_excel(xw, sheet_name="0_요약", index=False, header=False)
        cat.to_excel(xw, sheet_name="0_요약", index=False, startrow=len(header))
        for name, d in frames.items():
            d.to_excel(xw, sheet_name=name[:31], index=False)
        prep(base).to_excel(xw, sheet_name="Z_고객마스터_발송가능순", index=False)
        excl = df[df["마케팅제외"] | df["마케팅상태"].eq("미동의")][["실명", "연락처_정규화", COL["email"], "마케팅상태", "수신거부", "탈퇴", COL["role"]]].copy()
        excl["사유"] = excl.apply(lambda r: "수신거부" if r["수신거부"] else ("탈퇴" if r["탈퇴"] else ("미동의" if r["마케팅상태"] == "미동의" else "직원/테스트")), axis=1)
        excl.rename(columns={"연락처_정규화": "연락처"}).drop(columns=["수신거부", "탈퇴"]).to_excel(xw, sheet_name="Z_제외명단", index=False)
        if CP is not None:
            CP.to_excel(xw, sheet_name="Z_캠페인성과", index=False)
        if L is not None:
            Lx = L.copy(); Lx["발송일"] = Lx["발송일"].dt.date
            Lx.to_excel(xw, sheet_name="Z_발송이력", index=False)
        rp = summary.get("recipient_profile")
        if rp:
            rows = []
            for dcol, tbl in rp["by_dimension"].items():
                for k, v in tbl.items():
                    rows.append({"차원": dcol, "값": k, "발송": v["발송"], "전환자": v["전환자"], "전환율%": v["전환율%"]})
            pd.DataFrame(rows).to_excel(xw, sheet_name="Z_실측_차원별전환율", index=False)
        if lineup is not None:
            lineup.to_excel(xw, sheet_name="Z_라인업", index=False)
        for ws in xw.book.worksheets:
            for col_cells in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col_cells[:300])
                ws.column_dimensions[col_cells[0].column_letter].width = min(max(8, width * 1.3), 60)
            ws.freeze_panes = "A2" if not ws.title.startswith("0_") else None
    print(f"target : {path}")
    for r in catalog:
        print(f"  {r['우선순위']} {r['코드']} {r['타겟']:<28} {r['인원']:>5}  동의={r['동의']:>4} 미응답={r['미응답']:>4} 이력고객={r['이력고객']:>4}")


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
    global PAY_MAX
    cutoff_ts = pd.Timestamp(df[COL["joined"]].max())
    if P is not None:
        PAY_MAX = P["결제일시"].max().normalize()
        cutoff_ts = PAY_MAX   # 최근성·생애단계는 결제 데이터가 있는 마지막 날 기준
    A = customer_aggregates(P, cutoff_ts) if P is not None else None
    df = merge_payments(df, A)
    # 3월부터의 이용 이력(예약이력 + 결제상세)
    E = unify_history(P, load_reservation_history())
    HA = history_aggregates(E, cutoff_ts) if E is not None else None
    df = merge_by_key(df, HA, ["이력_이용횟수", "이력_이용금액", "이력_첫이용일", "이력_최근이용일", "이력_이용지점수",
                                "이력_최대배기량", "이력_이용장르", "이력_취소횟수", "이력_최근성_일", "생애단계"])
    df["이력_이용횟수"] = df["이력_이용횟수"].fillna(0).astype(int)
    df["이력고객"] = df["이력_이용횟수"].gt(0)
    df["생애단계"] = df["생애단계"].fillna("미이용")
    # 기존 명단의 VIP·세그먼트, 수신거부
    df = df.merge(load_prior_vip(), on="연락처_정규화", how="left") if load_prior_vip() is not None else df.assign(기존VIP=pd.NA, 기존세그먼트=pd.NA)
    sup = load_suppression()
    df["수신거부"] = df["연락처_정규화"].isin(sup)
    df["마케팅제외"] = df["마케팅제외"] | df["수신거부"]
    # 발송 정책: 동의자 + (설문 도입 전 가입한 미응답자, SEND_TO_UNASKED=True) 발송. 미동의·수신거부·제외 계정은 불가.
    df["발송가능"] = ~df["마케팅제외"] & df["연락처_유효"] & (
        df["마케팅상태"].eq("동의") | (SEND_TO_UNASKED & df["마케팅상태"].eq("미응답")))
    # VIP 재산정: 결제 3건+ / 순결제 20만+ / RCA 교차 + 결제 (최종세분화명단 정의)
    df["VIP산정"] = df["이력_이용횟수"].ge(3) | df["이력_이용금액"].fillna(0).ge(200000) | (df["RCA회원"] & df["이력고객"])
    # 발송 이력
    L = load_send_log()
    if L is not None:
        L = attach_conversions(L, E)
        SA = send_aggregates(L)
        df = merge_by_key(df, SA, [c for c in SA.columns if c != "연락처_정규화"], key="연락처_정규화")
        df["발송횟수"] = df["발송횟수"].fillna(0).astype(int)
        df["발송후전환"] = df["발송후전환"].fillna(False).astype(bool)
    else:
        df["발송횟수"] = 0
        df["발송후전환"] = False
    df = mark_duplicates(df)
    df, seg_masks = assign_segments(df)
    df, persona_masks = assign_personas(df)
    seg_frames = {k: df[m] for k, m in seg_masks.items()}
    for tag, _n, _w, _f in PERSONA_DEFS:
        seg_frames[tag] = df[persona_masks[tag]]
    summary = build_summary(df, seg_frames, src)
    summary["rca"] = rca_summary(df, rca)
    summary["payments"] = payment_summary(P, A, df)
    summary["history"] = history_summary(df, E)
    summary["sends"] = send_summary(L) if L is not None else None
    CP = campaign_performance(L) if L is not None else None
    RP, RPT = (recipient_profile(df, L) if L is not None else (None, None))
    summary["recipient_profile"] = RP
    WB, WC = load_web_analytics()
    summary["web"] = web_summary(WB, WC)

    cutoff = summary["meta"]["data_cutoff"]
    xlsx = OUT_DIR / f"CRM_마스터_{cutoff}.xlsx"
    write_excel(df, seg_frames, summary, xlsx, rca, WB, WC, L, CP, RPT)
    write_target_book(df, summary, OUT_DIR / f"CRM_타겟통합_{cutoff}.xlsx", L, CP, load_lineup())
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else int(o)), encoding="utf-8")
    write_markdown(summary, OUT_DIR / "분석요약.md")

    print(f"source : {src}")
    print(f"members: {len(df):,}  survey: {summary['overview']['survey_done']}  consent: {summary['overview']['consent_yes']}")
    print(f"xlsx   : {xlsx}")
    print(f"summary: {OUT_DIR / 'summary.json'}, {OUT_DIR / '분석요약.md'}")
    for sg in summary["segments"]:
        print(f"  {sg['code']} {sg['name']:<20} {sg['count']:>5}  phone={sg['with_valid_phone']:>5}  consent={sg['with_consent']:>4}")


if __name__ == "__main__":
    main()
