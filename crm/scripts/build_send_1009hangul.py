#!/usr/bin/env python3
"""한글날 '한 시간 더' 문자 발송 명단 (10/7 1차 · 10/8 2차) + 단골 직접 연락 명단.

입력: crm/data/raw/발송명단_2026-10-01_1000_week-1001.xlsx (10/1 회차 명단: 거래고객·수강생·신규동의·제외)
      crm/data/raw/결제내역_*.xlsx (10/7~10/11 예약 보유자 제외용)
출력: crm/output/발송명단_2026-10-07_1000_1009hangul.xlsx (개인정보 포함, git 미추적)
2차(10/8) 발송 직전에는 최신 결제내역을 raw/ 에 넣고 다시 실행하면 그 사이 예약한 사람이 빠진다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_crm as bc  # noqa: E402

SRC = bc.RAW_DIR / "발송명단_2026-10-01_1000_week-1001.xlsx"
OUT = bc.OUT_DIR / "발송명단_2026-10-07_1000_1009hangul.xlsx"
WINDOW = (pd.Timestamp("2026-10-07"), pd.Timestamp("2026-10-12"))
LINK = "{전용 링크}?utm_source=sms&utm_campaign=1009hangul"
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

    P = bc.load_payments()
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
    drop(base["ph"].isin(ad_no), "광고 미동의(10/1 제외 명단)")
    drop(base["마케팅수신"].eq("비회원"), "비회원(수신동의 확인 불가)")
    drop(base["ph"].isin(booked), "10/7~10/11 예약 보유")
    X = pd.concat(excl, ignore_index=True)

    yes = base[base["마케팅수신"].eq("동의")]
    unasked = base[base["마케팅수신"].eq("미응답")]

    # 단골 직접 연락: 용산 이용, 2회 이상 · 1박 이상 · 누적 20만원 이상 중 하나, 예약 없는 사람
    g = G.assign(ph=G["연락처"].map(bc.normalize_phone))
    for c in ["결제건수(8/28~9/30)", "순결제금액", "1박이상 건수"]:
        g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0)
    vip = g[g["이용지점"].str.contains("Yongsan") & ((g["결제건수(8/28~9/30)"] >= 2) | (g["1박이상 건수"] >= 1) | (g["순결제금액"] >= 200000))
            & ~g["ph"].isin(booked) & ~g["ph"].isin(ad_no)].sort_values("순결제금액", ascending=False)
    vip = vip.assign(연락일=[["10/6", "10/7", "10/8"][min(i // 25, 2)] for i in range(len(vip))], 결과="", 예약여부="")
    vip = vip[["연락일", "고객명", "연락처", "마케팅수신", "결제건수(8/28~9/30)", "1박이상 건수", "순결제금액", "최근 예약일", "이용 차종", "결과", "예약여부"]]
    vip_script = "안녕하세요, 아르테파인 용산입니다. 지난번 {차종} 타셨던 거 기억하시죠? 이번 한글날 연휴(10/9~10/11)에 3시간 이상 시승하시면 1시간을 무료로 드려요. 연휴 차량이 빨리 차서 먼저 연락드렸습니다. 링크 드릴까요?"

    summary = pd.DataFrame([
        ["1차 발송 (10/7 10:00) — 동의", len(yes), "1_문자1차_동의 시트를 문자 툴에 그대로 붙여 넣는다"],
        ["  └ 거래고객·수강생", int((yes["구분"] != "신규동의").sum()), "용산 중심 + 인천 고객(인천 리뉴얼로 차량이 용산에 있음)"],
        ["  └ 신규 동의 회원(9월 가입)", int((yes["구분"] == "신규동의").sum()), ""],
        ["1차 발송 — 미응답 (선택)", len(unasked), "수신동의 미응답 거래고객. 9/13 운영 결정(SEND_TO_UNASKED)대로 보내려면 포함, 보수적으로 가려면 제외"],
        ["2차 발송 (10/8 12:00)", "1차 대상 − 그 사이 예약자", "10/8 오전 최신 결제내역을 raw/ 에 넣고 이 스크립트를 다시 실행 → 1_문자1차 시트를 2차 명단으로 사용"],
        ["단골 직접 연락 (10/6~10/8)", len(vip), "참고_단골직접연락 시트. 하루 25명씩, 결과·예약여부 칸을 채운다"],
        ["제외", len(X), "9_제외 시트 (사유별)"],
        ["1차 문안 바이트(EUC-KR)", euckr_bytes(SMS1), "LMS(2,000바이트 이하)"],
        ["2차 문안 바이트(EUC-KR)", euckr_bytes(SMS2), "LMS"],
        ["주의", "", "{전용 링크}를 할인 등록 후 받은 실제 링크로 바꾼다. 9월 30일 이후 가입자는 이 명단에 없다(회원 설문 최신 내보내기가 필요)."],
    ], columns=["항목", "인원", "설명"])
    reasons = X["제외사유"].value_counts().rename_axis("제외사유").reset_index(name="인원")

    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="0_요약", index=False)
        yes[COLS + ["이용지점"]].to_excel(xw, sheet_name="1_문자1차_동의", index=False)
        unasked[COLS + ["이용지점"]].to_excel(xw, sheet_name="2_문자1차_미응답_선택", index=False)
        vip.to_excel(xw, sheet_name="참고_단골직접연락", index=False)
        pd.DataFrame({"직접 연락 스크립트": [vip_script]}).to_excel(xw, sheet_name="참고_연락스크립트", index=False)
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
