#!/usr/bin/env python3
"""한글날 '한 시간 더' 문자 발송 명단 (10/7 1차 · 10/8 2차). 단골은 같은 명단 안에 표시한다.

입력: crm/data/raw/발송명단_2026-10-01_1000_week-1001.xlsx (10/1 회차 명단: 거래고객·수강생·신규동의·제외)
      crm/data/raw/회원설문_<날짜>_전체.xlsx (최신 회원: 10월 신규 동의 추가, 수신동의 상태 갱신)
      crm/data/raw/결제내역_*.xlsx (10/7~10/11 예약 보유자 제외용)
출력: crm/output/발송명단_2026-10-07_1000_1009hangul.xlsx (개인정보 포함, git 미추적)
2차(10/8) 발송 직전에는 최신 결제내역을 raw/ 에 넣고 다시 실행하면 그 사이 예약한 사람이 빠진다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_crm as bc  # noqa: E402

SRC = bc.RAW_DIR / "발송명단_2026-10-01_1000_week-1001.xlsx"
OTHER_BRANCHES = {"Bundang", "Jinju", "Daegu", "Jeju"}  # 용산 오퍼와 무관한 지점만 이용한 사람은 뺀다
OUT = bc.OUT_DIR / "발송명단_2026-10-07_1000_1009hangul.xlsx"
WINDOW = (pd.Timestamp("2026-10-07"), pd.Timestamp("2026-10-12"))
PROMO = "hangul1009"  # 할인 신청 때 정한 전용 링크 코드. 다르면 여기만 바꾼다
# 문자 앱이 한글 주소를 링크로 인식하지 못하는 경우가 있어 코드를 URL 인코딩해 넣는다
LINK = f"https://www.artefine.co.kr/?promo={quote(PROMO)}&utm_source=sms&utm_medium=lms&utm_campaign=1009hangul"
COLS = ["구분", "이름", "연락처", "마케팅수신", "비고"]

SMS1 = f"""(광고) 아르테파인 용산
[한글날엔 한 시간 더]

3시간 이상 시승하면 1시간 무료.
3시간 69,000원 → 46,000원

연휴 10/9(금)~10/11(일), 서울 한 바퀴 돌기 딱 좋은 3시간.
평일(10/7~10/8)도 적용됩니다.

▶ 한 시간 더 받고 예약하기
{LINK}

※ 10/7~10/11 시승분, 3시간 이상, 1인 1일 1회
※ 링크로 예약 시 적용, 다른 할인과 중복 불가
무료수신거부 080-881-1293"""

SMS2 = f"""(광고) 아르테파인 용산
오늘이 평일 40% 마지막 날입니다.

· 오늘 밤 24시간 대여 → 40% (week-1001)
· 연휴 3시간 시승 → 1시간 무료

연휴 남은 시간대가 줄고 있어요.
▶ {LINK}
무료수신거부 080-881-1293"""


def euckr_bytes(s: str) -> int:
    return len(s.encode("euc-kr", errors="replace"))


def main() -> None:
    S = pd.read_excel(SRC, sheet_name="0_발송_통합", dtype=str)
    G = pd.read_excel(SRC, sheet_name="1_일반_week-1001", dtype=str)
    A = pd.read_excel(SRC, sheet_name="2_수강생_acad-1001", dtype=str)
    E = pd.read_excel(SRC, sheet_name="4_제외", dtype=str)

    # 수강생은 10/1 통합 시트에 없어서 거래고객으로 합친다
    A2 = A.rename(columns={"고객명": "이름"}).assign(구분="수강생", 비고=lambda d: "최근 " + d["최근 예약일"] + " · " + d["이용 차종"])
    base = pd.concat([S[COLS], A2[COLS]], ignore_index=True)
    base["ph"] = base["연락처"].map(bc.normalize_phone)
    branch = G.assign(ph=G["연락처"].map(bc.normalize_phone)).set_index("ph")["이용지점"]
    base["이용지점"] = base["ph"].map(branch).fillna(base["구분"].map({"수강생": "Yongsan", "신규동의": "-"}))

    # 최신 회원 내보내기: 10/1 이후 가입한 동의 회원 추가 + 현재 수신동의 상태로 갱신
    mfile = bc.find_master_file()
    M = pd.read_excel(mfile, dtype=str)
    M["ph"] = M["연락처"].map(bc.normalize_phone)
    M["가입"] = pd.to_datetime(M["가입일"], errors="coerce")
    Mu = M.dropna(subset=["ph"]).sort_values("가입").drop_duplicates("ph", keep="last")
    new = Mu[(Mu["가입"] >= "2026-10-01") & Mu["마케팅수신"].eq("동의") & ~Mu["ph"].isin(base["ph"])]
    new = new.assign(구분="신규동의(10월)", 이름=new["이름"], 마케팅수신="동의", 비고="가입 " + new["가입일"].str[:10],
                     이용지점=new["자주이용지점"].replace("-", "-"))
    base = pd.concat([base, new[COLS + ["ph", "이용지점"]]], ignore_index=True)
    status = Mu.set_index("ph")["마케팅수신"]
    base["마케팅수신"] = base["ph"].map(status).fillna(base["마케팅수신"])
    older = Mu[Mu["마케팅수신"].eq("동의") & (Mu["가입"] < "2026-10-01") & ~Mu["ph"].isin(base["ph"])]
    # 10/6 결정: 이전 가입 동의 회원도 1차 대상에 포함
    base = pd.concat([base, older.assign(구분="이전 동의회원", 비고="가입 " + older["가입일"].str[:10],
                                         이용지점=older["자주이용지점"])[COLS + ["ph", "이용지점"]]], ignore_index=True)

    P = bc.load_payments()
    paid_br = P.dropna(subset=["연락처_정규화"]).groupby("연락처_정규화")["예약 지점"].agg(lambda x: set(x.str.strip()))
    up = P[~P["취소"] & (P["예약시작"] >= WINDOW[0]) & (P["예약시작"] < WINDOW[1])]
    booked = set(up["연락처_정규화"].dropna())
    ad_no = set(E["연락처"].map(bc.normalize_phone).dropna())

    excl = []
    def drop(mask, why):
        nonlocal base
        excl.append(base[mask].assign(제외사유=why))
        base = base[~mask]
    drop(base["ph"].isna(), "연락처 형식 오류")
    drop(base["ph"].duplicated(), "중복 연락처")
    drop(base["ph"].isin(ad_no) | base["마케팅수신"].eq("미동의"), "광고 미동의")
    other_only = base["ph"].map(lambda ph: bool(paid_br.get(ph)) and paid_br.get(ph) <= OTHER_BRANCHES) | \
        base["이용지점"].isin(["아르테파인 대구 라운지", "아르테파인 분당 라운지", "아르테파인 진주 라운지", "아르테파인 제주 라운지"])
    drop(other_only, "다른 지점(분당·진주·대구·제주)만 이용")
    drop(base["마케팅수신"].eq("비회원"), "비회원(수신동의 확인 불가)")
    drop(base["ph"].isin(booked), "10/7~10/11 예약 보유")
    X = pd.concat(excl, ignore_index=True)

    # 10/6 결정: 수신동의 미응답(설문 도입 전 가입이라 동의를 받은 적 없음)은 광고 문자에서 뺀다
    yes = base[base["마케팅수신"].eq("동의")]
    unasked = base[base["마케팅수신"].eq("미응답")]

    # 단골 표시: 용산 이용, 2회 이상 · 1박 이상 · 누적 20만원 이상 중 하나 (직접 연락은 하지 않고 같은 문자를 받는다)
    g = G.assign(ph=G["연락처"].map(bc.normalize_phone))
    for c in ["결제건수(8/28~9/30)", "순결제금액", "1박이상 건수"]:
        g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0)
    vip_ph = set(g.loc[g["이용지점"].str.contains("Yongsan") & ((g["결제건수(8/28~9/30)"] >= 2) | (g["1박이상 건수"] >= 1)
                                                         | (g["순결제금액"] >= 200000)), "ph"])
    yes = yes.assign(단골=yes["ph"].isin(vip_ph).map({True: "단골", False: ""}))
    yes = yes.sort_values(["단골", "구분"], ascending=[False, True])

    summary = pd.DataFrame([
        ["1차 발송 (10/7 10:00) — 전체", len(yes), "1_문자1차 시트를 문자 툴에 그대로 붙여 넣는다"],
        ["  └ 거래고객·수강생 (동의)", int(yes["구분"].isin(["거래고객", "수강생"]).sum()), "용산 중심 + 인천 고객(인천 리뉴얼로 차량이 용산에 있음)"],
        ["제외 — 수신동의 미응답 거래고객", len(unasked), "설문 도입 전 가입이라 동의를 받은 적 없음 → 광고 문자 제외. 참고_미응답_동의받기 시트: 다음 방문·반납 때 현장에서 수신동의를 받는다"],
        ["  └ 신규 동의 회원(9월 가입)", int((yes["구분"] == "신규동의").sum()), ""],
        ["  └ 신규 동의 회원(10/1~10/6 가입)", int((yes["구분"] == "신규동의(10월)").sum()), f"{mfile.name} 기준"],
        ["  └ 이전 가입 동의 회원", int((yes["구분"] == "이전 동의회원").sum()), "9/30 이전 가입, 이전 회차에서 받은 사람 포함"],
        ["2차 발송 (10/8 12:00)", "1차 대상 − 그 사이 예약자", "10/8 오전 최신 결제내역을 raw/ 에 넣고 이 스크립트를 다시 실행 → 1_문자1차 시트를 2차 명단으로 사용"],
        ["  (그중 단골 표시)", int((yes["단골"] == "단골").sum()), "용산 2회 이상·1박 이상·누적 20만원 이상. 직접 연락 없이 같은 문자를 받는다"],
        ["제외", len(X), "9_제외 시트 (사유별)"],
        ["1차 문안 바이트(EUC-KR)", euckr_bytes(SMS1), "LMS(2,000바이트 이하)"],
        ["2차 문안 바이트(EUC-KR)", euckr_bytes(SMS2), "LMS"],
        ["주의", "", f"문안 링크의 promo={PROMO} 는 할인 등록 때 정한 코드와 같아야 한다. 발송 직전 최신 회원 설문을 raw/ 에 넣고 다시 실행하면 새 가입자·수신거부가 반영된다."],
    ], columns=["항목", "인원", "설명"])
    reasons = X["제외사유"].value_counts().rename_axis("제외사유").reset_index(name="인원")

    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="0_요약", index=False)
        yes[["단골"] + COLS + ["이용지점"]].to_excel(xw, sheet_name="1_문자1차", index=False)
        unasked[COLS + ["이용지점"]].to_excel(xw, sheet_name="참고_미응답_동의받기", index=False)
        pd.DataFrame({"회차": ["1차 10/7 10:00", "2차 10/8 12:00"], "문안": [SMS1, SMS2],
                      "바이트(EUC-KR)": [euckr_bytes(SMS1), euckr_bytes(SMS2)]}).to_excel(xw, sheet_name="문안", index=False)
        pd.concat([reasons, pd.DataFrame([{}]), X[COLS + ["제외사유"]]]).to_excel(xw, sheet_name="9_제외", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                w = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(10, w * 1.4), 70)
    print(summary.to_string(index=False))
    print(reasons.to_string(index=False))
    print(OUT)


if __name__ == "__main__":
    main()
