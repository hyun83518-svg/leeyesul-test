const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType,
  AlignmentType, HeadingLevel, BorderStyle, ShadingType, LevelFormat, PageBreak,
  TableLayoutType, VerticalAlign,
} = require("docx");

const FONT = "Malgun Gothic";
const CONTENT_W = 9600; // DXA
const GREY = "F2F3F5";
const HEAD = "1F2937";
const ACCENT = "0F766E";
const LIGHT = "E6F4F1";

// ---------- helpers ----------
const run = (text, opts = {}) => new TextRun({ text, font: FONT, size: 20, ...opts });

const p = (text, opts = {}) => {
  const { bold, italic, color, size, align, before = 60, after = 60, indent } = opts;
  const runs = Array.isArray(text)
    ? text.map((t) => (typeof t === "string" ? run(t, { size }) : run(t.text, { ...t, size: t.size || size })))
    : [run(text, { bold, italic, color, size })];
  return new Paragraph({ children: runs, alignment: align, spacing: { before, after }, indent });
};

const note = (text) => p(text, { italic: true, color: "555555", size: 18, before: 40, after: 80 });

const h1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  spacing: { before: 360, after: 140 },
  children: [new TextRun({ text, font: FONT, size: 30, bold: true, color: HEAD })],
});
const h2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  spacing: { before: 260, after: 100 },
  children: [new TextRun({ text, font: FONT, size: 24, bold: true, color: ACCENT })],
});
const h3 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_3,
  spacing: { before: 180, after: 80 },
  children: [new TextRun({ text, font: FONT, size: 21, bold: true, color: HEAD })],
});

const bullets = (items, ref = "bul") =>
  items.map((t) => new Paragraph({
    numbering: { reference: ref, level: 0 },
    spacing: { before: 30, after: 30 },
    children: Array.isArray(t)
      ? t.map((x) => (typeof x === "string" ? run(x) : run(x.text, x)))
      : [run(t)],
  }));

const numbered = (items) => bullets(items, "num");

const border = { style: BorderStyle.SINGLE, size: 4, color: "C9CDD3" };
const borders = { top: border, bottom: border, left: border, right: border };

const cell = (content, width, opts = {}) => {
  const { shade, bold, color, size = 18, align } = opts;
  const paras = (Array.isArray(content) ? content : [content]).map((line) =>
    new Paragraph({
      alignment: align,
      spacing: { before: 20, after: 20 },
      children: [run(String(line), { bold, color, size })],
    })
  );
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    borders,
    verticalAlign: VerticalAlign.TOP,
    shading: shade ? { type: ShadingType.CLEAR, fill: shade, color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: paras,
  });
};

// rows: [[c1,c2,...], ...], first row header. widths in DXA summing to CONTENT_W
const table = (header, rows, widths) => {
  const total = widths.reduce((a, b) => a + b, 0);
  if (total !== CONTENT_W) throw new Error("widths must sum to " + CONTENT_W + " got " + total);
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    layout: TableLayoutType.FIXED,
    rows: [
      new TableRow({
        tableHeader: true,
        children: header.map((h, i) => cell(h, widths[i], { shade: HEAD, bold: true, color: "FFFFFF" })),
      }),
      ...rows.map((r, ri) => new TableRow({
        cantSplit: true,
        children: r.map((c, i) => cell(c, widths[i], { shade: ri % 2 ? "FAFAFA" : undefined })),
      })),
    ],
  });
};

// copy-paste block: title line + lines, in a shaded single-cell table
const copy = (title, lines, meta) => {
  const paras = [];
  paras.push(new Paragraph({
    spacing: { before: 20, after: 80 },
    children: [run(title, { bold: true, size: 18, color: ACCENT })],
  }));
  lines.forEach((l) => {
    if (l === "") {
      paras.push(new Paragraph({ spacing: { before: 0, after: 0 }, children: [run(" ", { size: 12 })] }));
    } else if (l.startsWith("[[")) {
      // sticker / instruction line
      paras.push(new Paragraph({ spacing: { before: 20, after: 20 }, children: [run(l.replace(/^\[\[|\]\]$/g, ""), { italic: true, color: "6B7280", size: 17 })] }));
    } else {
      paras.push(new Paragraph({ spacing: { before: 20, after: 20 }, children: [run(l, { size: 19 })] }));
    }
  });
  if (meta) {
    const chars = lines.filter((l) => !l.startsWith("[[")).join("\n").length;
    paras.push(new Paragraph({
      spacing: { before: 80, after: 0 },
      children: [run(`${meta}${meta ? " · " : ""}${chars}자`, { italic: true, color: "6B7280", size: 16 })],
    }));
  }
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    layout: TableLayoutType.FIXED,
    rows: [new TableRow({
      children: [new TableCell({
        width: { size: CONTENT_W, type: WidthType.DXA },
        borders: { top: { style: BorderStyle.SINGLE, size: 6, color: ACCENT }, bottom: border, left: border, right: border },
        shading: { type: ShadingType.CLEAR, fill: GREY, color: "auto" },
        margins: { top: 120, bottom: 120, left: 180, right: 180 },
        children: paras,
      })],
    })],
  });
};

const gap = (n = 1) => Array.from({ length: n }, () => new Paragraph({ spacing: { before: 0, after: 0 }, children: [run(" ", { size: 8 })] }));
const pageBreak = () => new Paragraph({ children: [new PageBreak()] });

// ---------- content ----------
const BASE_TAGS = "#아르테파인 #아르테파인용산 #용산바이크 #바이크렌탈 #모터사이클렌탈 #바이크시승 #서울바이크렌탈";

const children = [];

// Title block
children.push(new Paragraph({
  spacing: { before: 0, after: 60 },
  children: [run("ARTEFINE · YONGSAN · INSTAGRAM", { bold: true, color: ACCENT, size: 18 })],
}));
children.push(new Paragraph({
  spacing: { before: 0, after: 80 },
  children: [run("아르테파인 용산 인스타그램 2주 운영 기획", { bold: true, size: 40, color: HEAD })],
}));
children.push(new Paragraph({
  spacing: { before: 0, after: 60 },
  children: [run("스토리 · 피드 · 릴스 — 9/15(화) ~ 9/28(월), 추석 연휴 포함", { size: 24, color: "374151" })],
}));
children.push(p("작성 2026-09-15 · 채널: 인스타그램만(스토리·피드·릴스) · 할인·시간 추가 혜택 없음 · 문자·카카오·쓰레드·쇼츠 제외", { size: 18, color: "6B7280", after: 40 }));
children.push(p("출처: SNS 콘텐츠 플랜(9/13), 발송계획 0918·0923(9/13), 추석 2배 위크 v2(9/13), 인천 리뉴얼 플랜(9/14), 마케팅 회의록(9/11)에서 용산 인스타그램 관련 내용만 추려 재구성. 오퍼·코드·문자 문안은 모두 제외했다.", { size: 18, color: "6B7280", after: 200 }));

// 0. 한 장 요약
children.push(h1("0. 한 장 요약"));
children.push(p("할인도, 시간 추가도 없다. 대신 세 가지를 매일 보여준다: 지금 용산에 있는 차, 열려 있는 시간, 처음이어도 되는 이유. 인스타그램은 '알리고 저장하게' 만드는 채널이고(3~9월 프로필 링크 유입 확정률 2.0%), 결제는 예약 페이지에서 일어난다. 그래서 피드는 저장되게, 릴스는 공유되게, 스토리는 오늘 움직이게 설계했다."));
children.push(...gap());
children.push(table(
  ["원칙", "실행"],
  [
    ["보유 대수를 말하지 않는다", "'용산, 차가 더 많아졌습니다' + 새 기종 이름만. 인천 이동·대수·숫자 언급 없음"],
    ["영업시간은 한 문구로 통일", "'일~목 자정 · 금·토 새벽 2시'. 프로필·하이라이트·피드·스토리 전부 같은 표현"],
    ["스토리는 하루 3장 고정 슬롯", "12:00 정보 / 18:00 오늘 예약 가능 차종 / 21:00 현장. 복붙 템플릿으로 3분 안에 올린다"],
    ["피드 주 3~4, 릴스 주 2", "피드 12:00(결제 피크 13~16시 직전), 릴스 19:00(저녁·심야형이 폰 보는 시간)"],
    ["참여는 보상 없이", "설문·질문·퀴즈 스티커, 인증샷 리그램, 키·경력 댓글 추천. 답글은 30분 안에"],
    ["차종은 '오늘 예약 가능'만", "정비 중 차량(800MT-X, 베스파 2종)은 어떤 콘텐츠에도 싣지 않는다"],
  ],
  [2800, 6800]
));
children.push(...gap());
children.push(h3("하루 운영 슬롯 (매일 반복)"));
children.push(table(
  ["시각", "포맷", "내용", "담당·소요"],
  [
    ["12:00", "스토리 1장 (+피드 있는 날 피드)", "정보: 오늘의 차 / FAQ / 코스 / 서비스. 피드 올린 날은 피드 리포스트 + '저장' 안내", "마케팅 · 5분"],
    ["18:00", "스토리 1장", "오늘 예약 가능 차종 (템플릿 A). 금·토는 '새벽 2시까지' 버전", "매장 매니저 · 3분"],
    ["19:00", "릴스 (주 2회)", "30초, 9:16, 자막 필수. 목·토 또는 화·목", "마케팅 · 사전 제작"],
    ["21:00", "스토리 1장", "현장: 출차·반납·매장 불 켜진 컷, 고객 리그램 (템플릿 F·G)", "매장 매니저 · 3분"],
    ["21:30", "점검", "당일 링크 탭·저장·설문 응답 확인. 댓글·DM 미답 처리", "마케팅 · 10분"],
  ],
  [1000, 2200, 4600, 1800]
));
children.push(...gap());
children.push(h3("2주 목표 (팔로워 수보다 행동 지표)"));
children.push(...bullets([
  "스토리 링크 스티커 탭: 하루 10회 이상 (18:00 잔여 차종 스토리 기준)",
  "피드 저장: 게시물당 30회 이상이면 다음 주 같은 형식 반복",
  "릴스: 게시 48시간 내 조회 3,000 미만이면 훅 자막 교체 후 재게시",
  "프로필 링크 유입 확정률: 방문통계 ?f=ig 파라미터로 측정, 3~9월 평균 2.0% 초과가 기준",
]));

// 1. 계정 세팅
children.push(h1("1. 계정 세팅 (9/15 화 당일 완료)"));
children.push(p("콘텐츠를 올리기 전에 프로필이 먼저 '매장 안내판' 역할을 해야 한다. 스토리를 보고 프로필에 들어온 사람이 3초 안에 어디·언제·얼마부터·예약 링크를 찾게 한다."));
children.push(h2("1-1. 프로필 문구 (복붙)"));
children.push(copy("프로필 이름 (검색 노출용)", ["아르테파인 용산 | 바이크 렌탈·시승"]));
children.push(...gap());
children.push(copy("소개 (150자 이내)", [
  "서울 용산 바이크 렌탈·시승",
  "일~목 자정 · 금·토 새벽 2시",
  "전 차량 자차·자손 보험 포함",
  "헬멧·장갑 무료, 몸만 오세요",
  "👇 예약 · 오늘 탈 수 있는 차",
], ""));
children.push(...gap());
children.push(p("프로필 링크: 예약 페이지 주소 뒤에 ?f=ig 를 붙인다. 할인 코드가 아니라 방문통계에서 인스타 유입을 구분하는 표시다. 스토리 링크 스티커는 ?f=ig-story, 릴스 캡션 안내는 ?f=ig-reels 로 나눠 두면 어느 포맷이 예약을 만드는지 10월에 바로 보인다.", { size: 19 }));
children.push(h2("1-2. 하이라이트 6개 (커버 이름은 6자 이내)"));
children.push(table(
  ["하이라이트", "들어가는 스토리", "첫 채우기"],
  [
    ["영업시간", "템플릿 B 영업시간·위치 1장, 오는 길(역 출구~매장) 1장", "9/15"],
    ["처음이세요?", "FAQ 1문1답 시리즈(템플릿 D) 8장. 9/21 질문 스티커 답변으로 계속 추가", "9/15~"],
    ["라인업", "오늘의 차 카드(템플릿 C) — 새 기종부터 1장씩. 정비·판매로 빠지면 삭제", "9/16~"],
    ["코스", "용산 출발 코스 카드(템플릿 E) 3장: 한강 야경 / 아침 강변 / 반나절", "9/18~"],
    ["고객사진", "리그램(템플릿 G). 동의 받은 것만", "9/19~"],
    ["연휴", "추석 연휴 영업 안내(템플릿 J). 9/29 이후 삭제", "9/23"],
  ],
  [1800, 6200, 1600]
));
children.push(h2("1-3. 고정 게시물 3개"));
children.push(...numbered([
  "9/15 피드 ① '영업시간·위치' — 항상 첫 칸. 연휴 기간엔 9/23 '연휴에도 엽니다'로 교체",
  "9/16 피드 ② '용산, 차가 더 많아졌습니다' 캐러셀 — 라인업 안내판",
  "9/22 피드 ⑤ '첫 라이딩 FAQ' 카드뉴스 — 처음 오는 사람용",
]));

// 2. 스토리 템플릿
children.push(pageBreak());
children.push(h1("2. 스토리 복붙 템플릿 라이브러리"));
children.push(p("스토리는 사진 위에 글자를 얹는 형식이라 문장이 짧아야 한다. 아래 템플릿은 [대괄호] 부분만 바꿔 그대로 붙인다. 글자는 한 화면 6줄 이내, 굵은 고딕, 사진이 어두우면 흰 글자 + 검정 외곽선. 스티커는 [[이중 대괄호]]로 표시했다."));
children.push(p("가장 중요한 건 A(18:00 오늘 예약 가능 차종)다. 용산 결제의 45%가 19~23시에 시작되므로, 저녁에 '오늘 뭐 타지'를 결정하는 사람에게 남은 차를 보여주는 것이 할인 없이 당일 예약을 만드는 가장 직접적인 방법이다.", { size: 19 }));

children.push(h2("A. 오늘 예약 가능 차종 — 매일 18:00 (매장 매니저)"));
children.push(copy("A-1 일~목 버전", [
  "오늘 [화요일] 용산",
  "자정까지 열어요",
  "",
  "지금 예약 가능",
  "🟢 [TIGER 900 GT PRO]",
  "🟢 [675SR-R]",
  "🟢 [REBEL 500]",
  "🟢 [슈퍼커브 110]",
  "",
  "[[링크 스티커: 지금 예약 → ?f=ig-story]]",
], "18:00"));
children.push(...gap());
children.push(copy("A-2 금·토 버전", [
  "오늘 [금요일] 용산",
  "새벽 2시까지 열어요 🌙",
  "",
  "지금 예약 가능",
  "🟢 [CBR1000RR-R]",
  "🟢 [Daytona 660]",
  "🟢 [450SR]",
  "🟢 [XSR900GP]",
  "",
  "[[링크 스티커: 지금 예약 → ?f=ig-story]]",
], "18:00"));
children.push(...gap());
children.push(...bullets([
  "게시 시점에 실제로 남은 차만. 4~6대, 소·중·대배기량 섞어서 최소 1대씩",
  "남은 차가 2대 이하면 '오늘 [차종] 2대 남았습니다'로 바꿔 올린다. 0대면 '오늘 마감. 내일 [요일] 예약 가능' 1장",
  "21:00 현장 스토리 때 바뀌었으면 A를 다시 올리지 말고 현장 스토리 하단에 '🟢 지금 [차종] 가능' 한 줄만",
  "배경 사진: 그날 매장에 서 있는 차 실사진. 같은 사진 3일 연속 금지",
]));

children.push(h2("B. 영업시간·위치 — 하이라이트 고정"));
children.push(copy("B-1 영업시간", [
  "아르테파인 용산",
  "일~목 10:00~24:00",
  "금·토 10:00~02:00",
  "",
  "헬멧·장갑 무료",
  "전 차량 자차·자손 보험 포함",
  "[[위치 스티커: 아르테파인 용산]] [[링크 스티커: 예약]]",
]));
children.push(...gap());
children.push(copy("B-2 오는 길", [
  "[역 이름] [n]번 출구",
  "도보 [n]분",
  "[랜드마크] 지나서 [좌/우]회전",
  "",
  "차 가져오시면 [주차 안내]",
  "[[위치 스티커]]",
]));

children.push(h2("C. 오늘의 차 — 12:00 시리즈 (하이라이트 '라인업')"));
children.push(copy("C 차종 카드", [
  "오늘의 차 · [TIGER 900 GT PRO]",
  "[888]cc · [어드벤처]",
  "면허: [2종 소형]",
  "이런 분께: [장거리·고속 편한 차 찾는 분]",
  "",
  "[[슬라이더 스티커: 타보고 싶은 정도 🔥]]",
  "또는 [[질문 스티커: 이 차 타봤어요? 한 줄 후기]]",
], "12:00"));
children.push(...gap());
children.push(p("2주 순서(새 기종부터): TIGER 900 GT PRO → Daytona 660 → REBEL 500 → SCRAMBLER 400X → VITPILEN 701 → SVARTPILEN 401 → NX500 → 675SR-R → CBR1000RR-R → T120 → XSR900GP → 450CL-C 바버 → 슈퍼커브 110. 질문 스티커에 달린 후기는 다음 날 같은 차 카드에 '어제 답변'으로 한 장 더 올린다.", { size: 19 }));

children.push(h2("D. 처음이세요? — FAQ 1문1답 (하이라이트)"));
children.push(copy("D-1 면허", [
  "처음이세요? Q1",
  "Q. 면허만 있으면 되나요?",
  "A. 2종 소형이면 전 차종.",
  "원동기(125cc 이하)면",
  "슈퍼커브 110 · VITPILEN 125 · LX 125.",
  "만 20세 이상.",
  "[[질문 스티커: 더 궁금한 거?]]",
]));
children.push(...gap());
children.push(copy("D-2 보험", [
  "처음이세요? Q2",
  "Q. 넘어지면요?",
  "A. 전 차량에 자차·자손 보험이",
  "들어 있습니다.",
  "국내 렌탈에서 드문 조건이라",
  "처음 타는 분이 제일 많이 오세요.",
]));
children.push(...gap());
children.push(copy("D-3 장비", [
  "처음이세요? Q3",
  "Q. 장비는요?",
  "A. 헬멧·장갑 무료 대여.",
  "사이즈 S~XL.",
  "본인 헬멧 가져오셔도 됩니다.",
  "'몸만 오세요'가 진짜입니다.",
]));
children.push(...gap());
children.push(copy("D-4 차 고르기", [
  "처음이세요? Q4",
  "Q. 처음이면 어떤 차?",
  "A. 키 165 이하 → 슈퍼커브 110 · 450CL-C 바버",
  "키 170 이상 → 450SR · 450NK",
  "매장에서 직접 앉아보고 바꿔도 됩니다.",
  "직원이 골라드려요.",
]));
children.push(...gap());
children.push(copy("D-5 당일 예약", [
  "처음이세요? Q5",
  "Q. 지금 가면 바로 탈 수 있어요?",
  "A. 전화보다 예약 페이지가 빠릅니다.",
  "남은 시간대가 실시간으로 보여요.",
  "오늘 남은 차는 매일 저녁 6시 스토리에.",
  "[[링크 스티커: 예약 페이지]]",
]));
children.push(...gap());
children.push(copy("D-6 밤", [
  "처음이세요? Q6",
  "Q. 밤에도 되나요?",
  "A. 일~목 자정, 금·토 새벽 2시까지.",
  "밤에 처음 타시면 출발 전에",
  "직원이 코스 설명드립니다.",
]));
children.push(...gap());
children.push(copy("D-7 둘이", [
  "처음이세요? Q7",
  "Q. 친구랑 같이 타도 되나요?",
  "A. 같은 시간에 2대 예약하시면 됩니다.",
  "초보 + 경험자 조합이면",
  "초보는 450, 경험자는 675 추천.",
]));
children.push(...gap());
children.push(copy("D-8 시간·가격", [
  "처음이세요? Q8",
  "Q. 최소 몇 시간부터예요?",
  "A. 1시간부터, 1시간 [23,000원]부터.",
  "보험 포함 가격입니다.",
  "처음이면 2시간이 제일 많아요.",
  "[[링크 스티커: 차종별 가격 보기]]",
]));

children.push(h2("E. 코스 카드 — 12:00 (하이라이트 '코스', 저장 유도)"));
children.push(copy("E-1 한강 야경 (밤)", [
  "용산 출발 코스 · 한강 야경 🌙",
  "용산 → 한강대로 → 남산 → 용산",
  "약 [1시간 30분] · 초보 OK",
  "",
  "저장해두고 반납 전에 한 번 보세요",
  "[[코스 지도 이미지 위에 올리기]]",
], "12:00"));
children.push(...gap());
children.push(copy("E-2 아침 강변 (낮)", [
  "용산 출발 코스 · 아침 강변 🌅",
  "용산 → [강변북로/올림픽대로] → [반환점] → 용산",
  "약 [1시간] · 평일 오전 도로가 비어 있어요",
  "",
  "저장 → 주말 아침에 꺼내 보기",
]));
children.push(...gap());
children.push(copy("E-3 반나절 (4시간)", [
  "용산 출발 코스 · 반나절 ☕",
  "용산 → [목적지 카페] → [경유] → 용산",
  "약 [4시간] · 점심 포함",
  "",
  "코스 짜드려요. 댓글에 '반나절'",
]));
children.push(note("코스 세부(경로·소요시간)는 매장에서 이미 쓰고 있는 한강 야경 코스 지도를 기준으로 담당자가 확정한다. 코스 지도는 '선물'이 아니라 콘텐츠다. 저장 수가 가장 잘 나오는 형식이므로 2주 후 코스 카드를 피드 캐러셀로 묶는다."));

children.push(h2("F. 현장 — 매일 21:00 (매장 매니저)"));
children.push(copy("F-1 출차", [
  "오늘 밤 용산",
  "[675SR-R] 출발했습니다",
  "[자정 / 새벽 2시]까지 열어요",
  "[[사진: 출차 장면. 번호판·얼굴 가림]]",
  "🟢 지금 [차종] 가능",
], "21:00"));
children.push(...gap());
children.push(copy("F-2 반납", [
  "반납 완료 🙌",
  "[REBEL 500] · [3]시간",
  "오늘 타주신 분들 감사합니다",
  "내일 [수요일]도 자정까지",
]));
children.push(...gap());
children.push(copy("F-3 매장 (손님 없을 때)", [
  "지금 용산 라운지",
  "불 켜져 있습니다",
  "[자정 / 새벽 2시]까지",
  "[[사진: 매장 외경 또는 라인업 와이드]]",
  "[[링크 스티커: 지금 예약]]",
]));

children.push(h2("G. 고객 리그램 (동의 후)"));
children.push(copy("G 리그램", [
  "@[계정] 님 사진",
  "[차종] · 용산",
  "허락받고 올립니다. 감사합니다 🙏",
  "",
  "#아르테파인용산 태그하면 리그램해요",
  "[[멘션 스티커: @계정]]",
]));
children.push(note("동의는 구두 + DM 기록. 번호판은 가린다. 보상은 없다. '리그램해요' 자체가 참여 이유다. 주말 사진은 모아서 9/26 피드 캐러셀로 묶는다."));

children.push(h2("H. 참여 스티커 (보상 없음)"));
children.push(copy("H-1 설문 — 9/15 화 19:30", [
  "당신은 어느 쪽?",
  "[[설문 스티커: 밤 라이딩 🌙 / 아침 라이딩 🌅]]",
  "결과는 금요일 점심에 공개",
]));
children.push(...gap());
children.push(copy("H-2 질문 — 9/21 월 19:00", [
  "첫 라이딩 전에 제일 궁금한 거?",
  "[[질문 스티커]]",
  "많이 나온 질문은 내일 카드뉴스로 정리해서 올립니다",
]));
children.push(...gap());
children.push(copy("H-3 퀴즈 — 9/27 일 12:00", [
  "이 계기판, 어느 차?",
  "[[퀴즈 스티커: ① 675SR-R ② CBR1000RR-R ③ Daytona 660 ④ TIGER 900]]",
  "[[사진: 계기판 클로즈업]]",
  "정답은 오늘 밤 9시 스토리에",
]));
children.push(...gap());
children.push(copy("H-4 슬라이더 — 오늘의 차 카드에 붙이기", [
  "[[슬라이더 스티커 🔥: 이 차 타보고 싶은 정도]]",
]));
children.push(...gap());
children.push(copy("H-5 공유 유도 — 금·토 12:00", [
  "이번 주말 같이 탈 사람한테",
  "이 스토리 보내기 →",
  "금·토 새벽 2시까지",
]));

children.push(h2("I. 금요일 12:00 — 밤 운영 예고"));
children.push(copy("I 금요일", [
  "오늘은 금요일",
  "용산 새벽 2시까지 🌙",
  "",
  "[[카운트다운 스티커: 밤 라이딩 시작 — 오늘 21:00]]",
  "[[설문 결과 카드 (9/18만): '밤 라이딩 __%가 골랐습니다']]",
], "12:00"));

children.push(h2("J. 추석 연휴 안내 — 9/23 수 12:10 이후 매일 변형"));
children.push(copy("J-1 연휴 전체", [
  "추석 연휴에도 엽니다",
  "9/24 목 ~ 9/28 월",
  "",
  "목·일·월 → 자정까지",
  "금·토 → 새벽 2시까지",
  "",
  "연휴 토요일 밤은 먼저 찹니다",
  "[[링크 스티커: 연휴 예약]]",
]));
children.push(...gap());
children.push(copy("J-2 연휴 당일 (매일 12:00)", [
  "연휴 [첫날 / 둘째 날 / 추석 당일 / 넷째 날 / 마지막 날]",
  "오늘 용산 [자정 / 새벽 2시]까지",
  "'오늘 뭐 하지' 싶으면 오세요",
  "[[링크 스티커: 오늘 예약]]",
]));

children.push(h2("K. 무상 케어 서비스 — 12:00 (9/17, 9/25)"));
children.push(copy("K 케어", [
  "내 바이크 타고 오셔도",
  "공기압 체크 · 배터리 충전 무상",
  "",
  "영업시간 내 언제든",
  "셀프 아니고, 말씀만 하세요",
  "[[위치 스티커]]",
]));
children.push(note("9/11 회의에서 확정된 상시 서비스(전 지점 공통). 할인이 아니라 매장에 들를 이유다. 라이더가 저장·공유할 만한 정보라 2주에 2번 올린다."));

children.push(h2("L. 날씨 연동 — 즉흥 (날 좋은 저녁)"));
children.push(copy("L 날씨", [
  "오늘 밤 용산 [18도 · 맑음]",
  "타기 좋은 날입니다",
  "[자정 / 새벽 2시]까지",
  "[[날씨 스티커 또는 캡처]]",
  "🟢 지금 [차종] 가능",
]));

children.push(h2("M. 피드·릴스 리포스트 — 게시 직후"));
children.push(copy("M 리포스트", [
  "[[피드/릴스 리포스트]]",
  "새 글 올렸어요",
  "저장해두고 나중에 보세요 🔖",
  "또는: 소리 켜고 보세요 🔊 (릴스 시동 소리)",
]));

// 3. 캘린더
children.push(pageBreak());
children.push(h1("3. 2주 캘린더 (9/15 화 ~ 9/28 월)"));
children.push(p("A·F·G 등 알파벳은 2절 스토리 템플릿, ①~⑧은 4절 피드, R1~R5는 5절 릴스를 가리킨다. 18:00 A와 21:00 F는 매일 고정이라 표에서 줄여 썼다."));
children.push(h2("3-1. 1주차 — 계정 세팅, 새 기종 알리기, 밤 운영 알리기"));
children.push(table(
  ["날짜", "12:00 (스토리 · 피드)", "18:00", "19:00 ~ 21:00", "제작·메모"],
  [
    ["9/15 화", "계정 세팅(프로필·링크·하이라이트 6개). 낮 촬영: 실차 정면·계기판·시동 영상", "A", "19:00 피드 ① 영업시간·위치 + M / 19:30 H-1 설문 밤 vs 아침 / 21:00 F", "첫날. 하이라이트 '영업시간'·'처음이세요?' B·D 8장 채우기"],
    ["9/16 수", "피드 ② 캐러셀 '용산, 차가 더 많아졌습니다' + M 저장 안내", "A", "21:00 F", "피드 ② 고정. 댓글 키·경력 추천 답글 30분 내"],
    ["9/17 목", "C 오늘의 차 TIGER 900 GT PRO / K 케어 서비스", "A", "19:00 R1 릴스 '시동 소리' + M 소리 켜고 / 21:00 F", "R1은 9/15 낮 촬영분"],
    ["9/18 금", "I 금요일 예고 + 설문 결과 / 피드 ③ '금요일 밤, 새벽 2시까지' + 코스 지도", "A-2", "21:00 F 첫 출차 / 22:00~02:00 야간 POV 촬영", "하이라이트 '코스'에 E-1 저장. 야간 촬영: 시동·한강대로·남산·새벽 반납·매장 외경"],
    ["9/19 토", "E-1 한강 야경 코스 카드 / H-5 공유 유도", "A-2", "19:00 R2 릴스 '서울에서 새벽 2시에 바이크 타는 곳' + M / 21:00 F + G 리그램", "R2는 9/18 밤 촬영분을 당일 편집. 첫 방문 고객 동의 받아 R3 촬영"],
    ["9/20 일", "피드 ④ 카드뉴스 '처음이면 어떤 차?' + M", "A", "21:00 F + '이번 주 감사' 리그램 모음 2장", "21:30 주간 리뷰(9절). 9/21 월 아침 결과 정리"],
    ["9/21 월", "C 오늘의 차 Daytona 660", "A", "19:00 H-2 질문 '첫 라이딩 전 궁금한 거?' / 21:00 F", "질문 답변 수집 → 9/22 카드뉴스. 카드 디자인은 당일 저녁"],
  ],
  [900, 3000, 700, 2900, 2100]
));
children.push(...gap());
children.push(h2("3-2. 2주차 — 첫 라이딩 FAQ, 연휴 영업, 인증샷"));
children.push(table(
  ["날짜", "12:00 (스토리 · 피드)", "18:00", "19:00 ~ 21:00", "제작·메모"],
  [
    ["9/22 화", "피드 ⑤ 카드뉴스 '첫 라이딩 FAQ' + M", "A", "19:00 R3 릴스 '도착부터 출발까지 3분' / 21:00 F", "피드 ⑤ 고정. 하이라이트 '처음이세요?'에 추가 답변 D로 저장"],
    ["9/23 수", "피드 ⑥ '연휴에도 엽니다' + J-1 연휴 안내(하이라이트 '연휴')", "A + '연휴 예약은 전날까지'", "21:00 F + '#아르테파인용산 태그하면 리그램' 안내", "고정 게시물 ①을 ⑥으로 교체. 연휴 영업시간 매장 내 확인"],
    ["9/24 목 (연휴 1)", "J-2 연휴 첫날, 자정까지 / C REBEL 500", "A", "19:00 R4 릴스 '늦게 생각나도 열려 있습니다' + M / 21:00 F", "R4는 9/18 밤 + 9/24 낮 현장 컷. 연휴 현장 사진 매일 5장 이상 확보"],
    ["9/25 금 (추석)", "J-2 추석 당일, 새벽 2시까지 / E-1 코스 재게시 / K 케어", "A-2", "21:00 F + G 리그램", "연휴 인증샷 동의 DM 보내기(9/26 캐러셀 재료)"],
    ["9/26 토 (연휴 3)", "피드 ⑦ 캐러셀 '연휴 인증샷 모음' + M / H-5 공유 유도", "A-2", "21:00 F + G 리그램", "고객 사진 4장 미만이면 직원 현장 컷 모음 '연휴 첫 이틀 용산 풍경'으로 대체"],
    ["9/27 일 (연휴 4)", "H-3 퀴즈 '이 계기판 어느 차?' / E-2 아침 강변 코스", "A", "21:00 F + 퀴즈 정답 / (예비) R5 릴스", "R5는 동의된 고객 리액션 확보 시에만"],
    ["9/28 월 (연휴 5)", "J-2 연휴 마지막 날, 자정까지 / C SCRAMBLER 400X", "A", "19:00 피드 ⑧ '연휴 TOP 3 + 10월 힌트' + M / 21:00 F '연휴 감사'", "21:30 2주 리뷰. 9/29 하이라이트 '연휴' 삭제, 고정 게시물 ① 복귀"],
  ],
  [900, 3000, 700, 2900, 2100]
));
children.push(note("9/28(월)은 추석 연휴 대체공휴일로 보고 '연휴 5일'로 썼다. 9/28 영업시간(자정)은 매장에서 확정한 뒤 9/23 피드 ⑥에 반영한다. 정식 연휴가 9/27까지면 '9/24~9/27, 4일'로 바꾸고 9/28 콘텐츠는 평일 월요일 형식으로 돌린다."));

// 4. 피드 문안
children.push(pageBreak());
children.push(h1("4. 피드 문안 전문"));
children.push(p("피드는 저장되는 글이다. 첫 줄이 '더 보기' 앞에 보이는 전부이므로 첫 줄에 결론을 쓴다. 해시태그는 8~12개, 기본 7개(#아르테파인 #아르테파인용산 #용산바이크 #바이크렌탈 #모터사이클렌탈 #바이크시승 #서울바이크렌탈)에 주제 태그 3~5개를 더한다. 가격은 기본 요금(1시간 23,000원부터)만 쓰고 할인·추가 혜택 문구는 쓰지 않는다."));

children.push(copy("피드 ① · 9/15 화 19:00 · 단일 이미지 '영업시간·위치' (고정 게시물)", [
  "용산 아르테파인, 오늘부터 매일 올립니다.",
  "오늘 탈 수 있는 차는 매일 저녁 6시 스토리에.",
  "",
  "영업시간",
  "일~목 10:00~24:00",
  "금·토 10:00~02:00",
  "",
  "전 차량 자차·자손 보험 포함. 헬멧·장갑 무료.",
  "[용산 주소] · [역] [n]번 출구 도보 [n]분",
  "예약은 프로필 링크.",
  "",
  BASE_TAGS,
], "이미지: 매장 외경(저녁, 불 켜진 상태) 또는 라인업 와이드 1장. 영업시간을 이미지에도 크게 넣는다"));
children.push(...gap());

children.push(copy("피드 ② · 9/16 수 12:00 · 캐러셀 9장 '용산, 차가 더 많아졌습니다' (고정 게시물)", [
  "용산, 차가 더 많아졌습니다.",
  "이번 주부터 용산에서 탈 수 있는 새 얼굴들. (슬라이드 →)",
  "",
  "TIGER 900 GT PRO · Daytona 660 · REBEL 500 · SCRAMBLER 400X · VITPILEN 701 · SVARTPILEN 401 · NX500",
  "그리고 원래 있던 CBR1000RR-R · 675SR-R · T120 · XSR900GP까지.",
  "",
  "1시간 23,000원부터, 전 차량 자차·자손 보험 포함. 헬멧·장갑 무료.",
  "뭐부터 타볼지 고민되면 댓글에 키·경력 적어주세요. 골라드립니다.",
  "일~목 자정, 금·토 새벽 2시. 예약은 프로필 링크.",
  "",
  BASE_TAGS + " #TIGER900 #Daytona660 #REBEL500 #SCRAMBLER400X #VITPILEN701",
], "슬라이드: 1 표지 '용산, 차가 더 많아졌습니다' / 2~8 새 기종 7대 각 1장(차종명·배기량·장르 자막) / 9 영업시간 + '예약은 프로필 링크'"));
children.push(note("대수·숫자·인천 언급 없음. 게시 당일 예약 가능 상태인 차만 싣는다. 9/16 기준 정비 중인 차가 있으면 슬라이드에서 뺀다. R 12 NineT 보유가 확인되면 슬라이드 추가."));
children.push(...gap());

children.push(copy("피드 ③ · 9/18 금 12:00 · 단일 이미지 '금요일 밤, 용산은 새벽 2시까지' (코스 지도)", [
  "다른 데가 문 닫는 시간에 용산은 엽니다.",
  "금·토는 새벽 2시까지.",
  "",
  "낮엔 덥고 길은 막히고, 밤엔 둘 다 비어 있습니다.",
  "용산 → 한강대로 → 남산 → 용산. 한강 야경 코스 지도를 그렸어요.",
  "저장해두고 반납 전에 한 번 보세요.",
  "",
  "밤에 처음 타시는 분은 출발 전에 직원이 코스 설명드립니다.",
  "예약은 프로필 링크.",
  "",
  "#밤바리 #야간라이딩 #한강야경 #남산라이딩 #심야라이딩 " + BASE_TAGS,
], "이미지: 코스 지도 1장(경로·주요 포인트·소요시간). 사진보다 지도가 저장을 만든다"));
children.push(...gap());

children.push(copy("피드 ④ · 9/20 일 12:00 · 카드뉴스 6장 '처음이면 어떤 차?'", [
  "처음이면 어떤 차? 제일 많이 받는 질문이라 정리했어요.",
  "키와 경력 두 가지만 알려주시면 매장에서 바로 골라드립니다. (슬라이드 →)",
  "",
  "댓글에 키·경력 적어주시면 여기서도 추천드려요.",
  "면허: 2종 소형은 전 차종, 원동기(125cc 이하)는 슈퍼커브 110 · VITPILEN 125 · LX 125.",
  "예약은 프로필 링크.",
  "",
  "#바이크입문 #첫라이딩 #바이크초보 #바이크추천 #슈퍼커브 " + BASE_TAGS,
], "카드: 1 표지 / 2 키 165 이하·첫 라이딩 → 슈퍼커브 110 · 450CL-C 바버 / 3 키 170 이상·첫 라이딩 → 450SR · 450NK · REBEL 500 / 4 경력 1년+ 미들급 → 675SR-R · 675NK · Daytona 660 · SCRAMBLER 400X / 5 경력 충분·대배기량 → CBR1000RR-R · TIGER 900 GT PRO · T120 · XSR900GP / 6 '고민되면 직원이 골라드립니다' + 영업시간"));
children.push(...gap());

children.push(copy("피드 ⑤ · 9/22 화 12:00 · 카드뉴스 6장 '첫 라이딩 FAQ' (고정 게시물)", [
  "첫 라이딩 전에 제일 많이 물어보신 것 5가지.",
  "어제 스토리 질문에 답해주신 분들 감사합니다. (슬라이드 →)",
  "",
  "더 궁금한 건 댓글에 남겨주세요. 하나씩 답드립니다.",
  "예약은 프로필 링크.",
  "",
  "#바이크입문 #첫라이딩 #모터사이클면허 #바이크초보 #바이크보험 " + BASE_TAGS,
], "카드: 1 표지 '9/21 스토리 질문 결과' / 2 면허 / 3 넘어지면(보험) / 4 장비 / 5 당일 예약 / 6 밤에도 되나요. 실제 질문 결과에 따라 2~6 교체. 문구는 2절 D-1~D-6 그대로"));
children.push(...gap());

children.push(copy("피드 ⑥ · 9/23 수 12:00 · 단일 이미지 '연휴에도 엽니다' (연휴 기간 고정 게시물)", [
  "추석 연휴에도 엽니다.",
  "9/24 목 ~ 9/28 월, 5일 내내.",
  "",
  "목·일·월은 자정까지, 금·토는 새벽 2시까지.",
  "'연휴인데 오늘 뭐 하지' 싶을 때 오세요. 늦게 생각나도 열려 있습니다.",
  "",
  "연휴 토요일 밤은 매번 먼저 찹니다. 예약은 전날까지 해두시는 게 안전해요.",
  "타고 나서 사진 올리실 땐 #아르테파인용산 태그해 주세요. 허락받고 리그램합니다.",
  "",
  "#추석연휴 #연휴놀거리 #서울연휴 #심야라이딩 " + BASE_TAGS,
], "이미지: 날짜·요일별 영업시간 표 1장. 글자 크게"));
children.push(...gap());

children.push(copy("피드 ⑦ · 9/26 토 12:00 · 캐러셀 6~8장 '연휴 인증샷 모음' (리그램)", [
  "연휴 이틀 동안 용산에서 나간 차들, 그리고 보내주신 사진들. 허락받고 모았어요.",
  "(슬라이드 →, 각 장에 @계정 태그)",
  "",
  "아직 연휴 3일 남았습니다. 오늘은 새벽 2시까지.",
  "#아르테파인용산 태그하면 다음 모음에 넣어드려요.",
  "",
  "#아르테파인용산 #인증샷 #라이딩사진 #추석연휴 #아르테파인 #용산바이크 #바이크렌탈 #모터사이클렌탈 #바이크시승",
], "고객 사진 4장 미만이면 제목을 '연휴 첫 이틀, 용산 풍경'으로 바꾸고 직원 현장 컷으로 채운다"));
children.push(...gap());

children.push(copy("피드 ⑧ · 9/28 월 19:00 · 단일 이미지 '연휴 TOP 3 + 10월 힌트'", [
  "연휴 5일 동안 가장 많이 나간 차 3대. 실제 예약 기준.",
  "1위 [차종] · 2위 [차종] · 3위 [차종]",
  "",
  "안전하게 반납해주신 모든 분 감사합니다.",
  "10월에 들어올 차 힌트: '[힌트 한 단어]'. 맞히신 분은 댓글에서 뵙겠습니다.",
  "10월 라인업은 10/1 공개.",
  "",
  "#이달의라인업 #10월라인업 " + BASE_TAGS,
], "순위는 게시 직전 예약 데이터로 교체. 힌트 퀴즈는 보상 없이 댓글 참여만"));

// 5. 릴스
children.push(pageBreak());
children.push(h1("5. 릴스 기획 (30초 · 9:16 · 자막 필수)"));
children.push(p("릴스는 공유되는 포맷이다. 첫 1초에 화면·자막·소리가 동시에 시작해야 하고, 소리 없이 봐도 이해돼야 한다. 자막은 한 화면 2줄, 줄당 3~5어절, 굵은 고딕 + 검정 외곽선. 마지막 3초는 항상 '일~목 자정 · 금·토 새벽 2시 / 예약은 프로필 링크'."));
children.push(table(
  ["릴스", "게시", "훅 (0~2초 자막)", "구성 (30초)", "마지막 자막", "촬영"],
  [
    ["R1 시동 소리", "9/17 목 19:00", "\"용산에 차가 더 많아졌습니다\" + 첫 시동 소리", "0~3 라인업 와이드 / 3~25 새 기종 6대 각 3~4초: 계기판 ON → 시동 → 배기음 (차종명 자막) / 25~30 영업시간 + 링크", "소리 켜고 들으세요 🔊 / 일~목 자정 · 금·토 새벽 2시", "9/15 낮. 원음 사용, BGM 없음"],
    ["R2 새벽 2시", "9/19 토 19:00", "\"서울에서 새벽 2시에 바이크 타는 곳\"", "0~5 시동·헤드라이트 / 5~20 한강대로·남산 POV / 20~27 새벽 반납, 불 켜진 매장 외경 / 27~30 로고", "금·토 새벽 2시까지 / 프로필 링크", "9/18 밤 22:00~02:00"],
    ["R3 3분", "9/22 화 19:00", "\"바이크 처음 빌리면 이렇게 됩니다\"", "0~3 매장 문 열고 들어오는 컷 / 3~10 면허 확인 / 10~17 헬멧·장갑 고르기 / 17~25 직원 차 설명(클러치·브레이크) / 25~30 시동·출발", "몸만 오세요 / 전 차량 보험 포함", "9/19~20 첫 방문 고객(동의) 또는 직원 연출"],
    ["R4 연휴 밤", "9/24 목 19:00", "\"늦게 생각나도 열려 있습니다\"", "0~5 밤 11시 매장 불 켜진 컷 / 5~20 출차, 한강 / 20~27 반납 / 27~30 연휴 영업시간", "연휴 5일 내내 / 목·일·월 자정 · 금·토 새벽 2시", "9/18 밤 + 9/24 낮 현장"],
    ["R5 예비", "9/27 일 19:00", "\"675 타던 사람이 1000 처음 탄 날\"", "0~5 675SR-R 계기판 / 5~20 CBR1000RR-R로 갈아타는 장면 / 20~27 고객 리액션(동의) / 로고", "다음 차가 궁금하면 / 프로필 링크", "해당 고객 동의 확보 시에만"],
  ],
  [1100, 1200, 1900, 2900, 1400, 1100]
));
children.push(...gap());
children.push(h3("릴스 캡션 (공통 틀, 복붙)"));
children.push(copy("릴스 캡션", [
  "[훅 문장 그대로 1줄]",
  "[내용 1줄: 어디서·언제·무엇]",
  "일~목 자정, 금·토 새벽 2시. 예약은 프로필 링크.",
  "",
  "[주제 태그 3~4개] " + BASE_TAGS,
]));
children.push(...gap());
children.push(...bullets([
  "R1 예: '용산에 차가 더 많아졌습니다. 이번 주부터 탈 수 있는 새 기종, 시동 소리로 먼저 들어보세요.' #바이크시동소리 #배기음 #TIGER900 #Daytona660",
  "R2 예: '서울에서 새벽 2시에 바이크 타는 곳. 금·토 용산은 새벽 2시까지 엽니다. 한강대로 → 남산 야경 코스.' #밤바리 #야간라이딩 #한강야경",
  "R3 예: '바이크 처음 빌리면 이렇게 됩니다. 면허 확인 → 헬멧 → 차 설명 → 출발, 3분.' #바이크입문 #첫라이딩 #바이크초보",
  "R4 예: '늦게 생각나도 열려 있습니다. 추석 연휴 5일 내내, 목·일·월 자정·금·토 새벽 2시.' #추석연휴 #연휴놀거리 #심야라이딩",
  "커버 이미지는 훅 자막이 그대로 보이는 프레임으로 고른다. 릴스 게시 직후 스토리 M으로 리포스트",
]));

// 6. 해시태그·응답
children.push(h1("6. 해시태그 세트와 댓글·DM 응답 규칙"));
children.push(h2("6-1. 해시태그 세트 (복붙)"));
children.push(table(
  ["세트", "태그", "쓰는 곳"],
  [
    ["기본 7 (모든 게시물)", BASE_TAGS, "모든 피드·릴스"],
    ["야간", "#밤바리 #야간라이딩 #한강야경 #심야라이딩 #남산라이딩", "금·토 콘텐츠, R2·R4"],
    ["입문", "#바이크입문 #첫라이딩 #바이크초보 #모터사이클면허 #바이크추천", "FAQ·차 고르기, R3"],
    ["차종", "#CBR1000RRR #675SRR #TIGER900 #Daytona660 #REBEL500 #SCRAMBLER400X #VITPILEN701 #슈퍼커브 #T120 #XSR900GP", "해당 차가 주인공인 게시물에 2~3개만"],
    ["연휴", "#추석연휴 #연휴놀거리 #서울연휴 #서울데이트", "9/23~9/28"],
    ["고객", "#아르테파인용산 #인증샷 #라이딩사진", "리그램. 고객에게 안내하는 태그는 #아르테파인용산 하나만"],
  ],
  [2000, 5600, 2000]
));
children.push(h2("6-2. 댓글 답글 규칙"));
children.push(...bullets([
  "질문 댓글은 30분 안에. 답을 모르면 '확인하고 답드릴게요' 먼저 달고 1시간 안에 답",
  "가격 질문은 숫자를 바로 쓴다. 'DM 주세요'로 넘기지 않는다",
  "키·경력 댓글에는 차종을 바로 추천한다: '키 [ ]·경력 [ ]이시면 [차종] 추천드려요. 매장에서 직접 앉아보고 바꾸셔도 됩니다.'",
  "부정 댓글(사고·가격 불만)은 사과 없이 사실만: 보험 조건, 환불 규정 링크. 논쟁은 하지 않는다",
  "자주 나온 질문은 그날 메모 → 하이라이트 '처음이세요?'에 D 카드로 추가",
]));
children.push(h2("6-3. DM 템플릿 (복붙)"));
children.push(copy("DM-1 예약 문의", [
  "안녕하세요, 아르테파인 용산입니다.",
  "예약은 링크에서 남은 시간대를 바로 보실 수 있어요 → [예약 링크 ?f=ig-dm]",
  "차종 고민되시면 키·경력 알려주세요. 추천드릴게요.",
]));
children.push(...gap());
children.push(copy("DM-2 리그램 동의 요청", [
  "안녕하세요, 아르테파인 용산입니다. 사진 너무 좋아서요.",
  "저희 계정 스토리(또는 피드)에 @계정 태그 달아 올려도 괜찮을까요?",
  "번호판은 가려서 올립니다. 괜찮으시면 '네' 한 글자만 보내주세요 🙏",
]));
children.push(...gap());
children.push(copy("DM-3 설문·질문 답변 감사", [
  "답해주셔서 감사합니다! 결과는 [금요일 점심] 스토리에 올릴게요.",
  "궁금한 거 있으면 언제든 여기로 주세요.",
]));

// 7. 제작 체크리스트
children.push(h1("7. 제작 체크리스트"));
children.push(table(
  ["언제", "촬영·제작", "쓰이는 곳"],
  [
    ["9/15 화 낮", "용산 실차 전 차종 정면·측면·계기판 사진, 새 기종 6대 시동·배기음 영상(각 10초)", "피드 ②, C 카드, R1, A 배경"],
    ["9/15 화 저녁", "매장 외경(불 켜진 상태), 라인업 와이드", "피드 ①, F-3"],
    ["9/15 화", "캔바 템플릿 3종: A(잔여 차종) · B/J(영업시간) · D(FAQ). 글자만 바꿔 쓰게", "스토리 전체"],
    ["9/17 목", "한강 야경 코스 지도 1장(경로·포인트·소요시간)", "피드 ③, E-1"],
    ["9/18 금 22:00~02:00", "야간 POV: 시동·헤드라이트 → 한강대로 → 남산 → 새벽 반납 → 매장 외경", "R2, R4"],
    ["9/19~20", "첫 방문 고객 프로세스(동의) 또는 직원 연출: 면허 확인 → 장비 → 설명 → 출발", "R3"],
    ["9/19 토", "카드뉴스 '처음이면 어떤 차?' 6장 디자인", "피드 ④"],
    ["9/21 월 저녁", "FAQ 카드뉴스 6장 (질문 결과 반영)", "피드 ⑤"],
    ["9/22 화", "연휴 영업시간 카드 1장", "피드 ⑥, J-1"],
    ["9/24~27", "연휴 현장 컷 매일 5장 이상, 고객 사진 동의 DM", "피드 ⑦, F, G"],
    ["매일", "18:00 전 그날 예약 가능 차종 확인, 배경 실사진 1장", "A"],
  ],
  [2000, 5000, 2600]
));
children.push(...gap());
children.push(...bullets([
  "모든 고객 사진·영상은 게시 전 동의(구두 + DM 기록). 번호판·얼굴은 가린다",
  "문안 속 차종은 게시 당일 '예약 가능'만. 정비 중 3대(800MT-X, GTS 125 SUPER, PRIMAVERA 125)는 어떤 콘텐츠에도 싣지 않는다",
  "인천·대수·'몇 대'는 쓰지 않는다. '더 많아졌습니다'와 차종 이름으로만 말한다",
  "할인·무료·추가 시간·코드 단어는 쓰지 않는다. 상시 무료인 것(헬멧·장갑·보험 포함·공기압·배터리)만 '무료'로 표기",
]));

// 8. 측정
children.push(h1("8. 측정과 리뷰"));
children.push(table(
  ["시점", "확인할 것", "판단·조치"],
  [
    ["매일 21:30", "스토리 A 링크 탭 수 · 설문/질문 응답 수 · 피드 저장·공유 · 릴스 조회·공유 · 미답 댓글/DM", "링크 탭 10 미만이 3일 이어지면 A 게시 시각을 17:30으로 당겨 비교"],
    ["9/21 월 (1주 리뷰)", "상위 3·하위 3 게시물, 릴스 R1·R2 조회, 프로필 방문 → 링크 탭 비율, 하이라이트 조회", "릴스 조회 3,000 미만이면 훅 자막 교체 후 재게시. 저장 30+ 형식은 2주차에 반복"],
    ["9/28 월 (2주 리뷰)", "연휴 5일 스토리 링크 탭 합계, 리그램 수, 해시태그 #아르테파인용산 게시물 수, 팔로워 증감", "연휴 데이터로 10월 요일별 게시 시각 확정. 코스 카드 저장 수가 높으면 10월 첫 피드를 '코스 모음' 캐러셀로"],
    ["10/7", "방문통계 ?f=ig / ig-story / ig-reels / ig-dm 별 방문 → 예약 확정률", "인스타 확정률 2.0%(3~9월 평균) 초과 여부. 포맷별로 갈라 10월 비중 조정"],
  ],
  [1800, 4200, 3600]
));

// 9. 확인 필요
children.push(h1("9. 게시 전 확인이 필요한 것"));
children.push(p("문서에 [대괄호]로 남긴 자리다. 9/15 세팅 때 한 번에 채운다."));
children.push(...numbered([
  "용산 라운지 주소, 가장 가까운 역·출구, 도보 시간, 주차 안내 (피드 ①, B-2)",
  "오픈 시각 10:00 확인 (문서에 따라 표기가 달라 10:00으로 가정)",
  "9/28(월) 대체공휴일 영업 여부와 마감 시각 (자정으로 가정). 연휴가 9/27까지면 피드 ⑥·J-1을 '4일'로 수정",
  "피드 ②에 실을 새 기종 7대가 9/16 기준 '예약 가능'인지. R 12 NineT 보유 여부(한 문서에만 언급)",
  "기본 요금 '1시간 23,000원부터' 표기 유지 여부 (피드 ②, D-8)",
  "한강 야경 코스의 실제 경로·소요시간 (피드 ③, E-1). 아침 강변·반나절 코스 경로 확정 (E-2, E-3)",
  "예약 링크에 ?f=ig 계열 파라미터를 붙였을 때 방문통계에 잡히는지 테스트",
  "헬멧 사이즈 범위 S~XL, 공기압·배터리 무상 서비스가 용산에서 상시 가능한지 (D-3, K)",
]));

// ---------- build ----------
const doc = new Document({
  creator: "ARTEFINE",
  title: "아르테파인 용산 인스타그램 2주 운영 기획",
  styles: {
    default: { document: { run: { font: FONT, size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 30, bold: true, color: HEAD }, paragraph: { spacing: { before: 360, after: 140 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 24, bold: true, color: ACCENT }, paragraph: { spacing: { before: 260, after: 100 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 21, bold: true, color: HEAD }, paragraph: { spacing: { before: 180, after: 80 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 240 } } } }] },
      { reference: "num", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 300 } } } }] },
    ],
  },
  sections: [{
    properties: { page: { margin: { top: 1100, bottom: 1100, left: 1153, right: 1153 } } },
    children,
  }],
});

const out = process.argv[2];
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(out, buf); console.log("wrote", out, buf.length); });
