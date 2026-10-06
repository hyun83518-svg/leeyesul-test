// 마크다운 계획서(제목·표·목록·코드블록·인용·굵게)를 워드로 변환한다.
// 사용법: node crm/scripts/build_md_docx.js <입력.md> <출력.docx> [삽입이미지.png ...]
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, ImageRun,
  WidthType, AlignmentType, ShadingType, BorderStyle, LevelFormat,
} = require("docx");

const FONT = "Malgun Gothic";
const ACCENT = "C2410C";
const PAGE_W = 9360;

const [, , src, out, ...images] = process.argv;
const md = fs.readFileSync(src, "utf8").split("\n");

// **굵게**, `코드` 를 TextRun 으로
function runs(text, base = {}) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return parts.map((p) => {
    if (p.startsWith("**")) return new TextRun({ text: p.slice(2, -2), font: FONT, size: 20, bold: true, ...base });
    if (p.startsWith("`")) return new TextRun({ text: p.slice(1, -1), font: "Consolas", size: 18, color: "7C2D12", ...base });
    return new TextRun({ text: p, font: FONT, size: 20, ...base });
  });
}

function table(lines) {
  const rows = lines.filter((l) => !/^\|\s*:?-+/.test(l)).map((l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
  const n = rows[0].length;
  const lens = rows[0].map((_, i) => Math.max(...rows.map((r) => (r[i] || "").length), 2));
  const sum = lens.reduce((a, b) => a + Math.min(b, 40), 0);
  const widths = lens.map((l) => Math.round((Math.min(l, 40) / sum) * PAGE_W));
  const cell = (text, w, head) => new TableCell({
    width: { size: w, type: WidthType.DXA }, margins: { top: 60, bottom: 60, left: 90, right: 90 },
    shading: head ? { type: ShadingType.CLEAR, fill: "1C1917", color: "auto" } : undefined,
    children: [new Paragraph({ spacing: { after: 0 }, children: runs(text || "", { size: 17, ...(head ? { bold: true, color: "FFFFFF" } : {}) }) })],
  });
  return new Table({
    width: { size: PAGE_W, type: WidthType.DXA }, columnWidths: widths,
    rows: rows.map((r, ri) => new TableRow({ tableHeader: ri === 0, children: Array.from({ length: n }, (_, i) => cell(r[i], widths[i], ri === 0)) })),
  });
}

function codeBox(lines) {
  return new Table({
    width: { size: PAGE_W, type: WidthType.DXA }, columnWidths: [PAGE_W],
    rows: [new TableRow({ children: [new TableCell({
      width: { size: PAGE_W, type: WidthType.DXA }, margins: { top: 120, bottom: 120, left: 180, right: 180 },
      shading: { type: ShadingType.CLEAR, fill: "FFF4EC", color: "auto" },
      children: lines.map((l) => new Paragraph({ spacing: { after: 30 }, children: [new TextRun({ text: l || " ", font: FONT, size: 19 })] })),
    })] })],
  });
}

const body = [];
const gap = () => body.push(new Paragraph({ spacing: { after: 80 }, children: [] }));
for (let i = 0; i < md.length; i++) {
  const l = md[i];
  if (l.startsWith("```")) {
    const buf = [];
    for (i++; i < md.length && !md[i].startsWith("```"); i++) buf.push(md[i]);
    body.push(codeBox(buf)); gap(); continue;
  }
  if (l.startsWith("|")) {
    const buf = [];
    for (; i < md.length && md[i].startsWith("|"); i++) buf.push(md[i]);
    i--; body.push(table(buf)); gap(); continue;
  }
  if (l.startsWith("# ")) {
    body.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: "ARTEFINE · 용산", font: FONT, size: 18, bold: true, color: ACCENT })] }));
    body.push(new Paragraph({ spacing: { after: 160 }, border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: ACCENT, space: 6 } }, children: runs(l.slice(2), { size: 34, bold: true }) }));
    continue;
  }
  if (l.startsWith("## ")) { body.push(new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 320, after: 140 }, children: runs(l.slice(3), { size: 28, bold: true, color: "1C1917" }) })); continue; }
  if (l.startsWith("### ")) { body.push(new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 220, after: 100 }, children: runs(l.slice(4), { size: 23, bold: true, color: ACCENT }) })); continue; }
  if (l.startsWith("> ")) { body.push(new Paragraph({ spacing: { after: 100 }, indent: { left: 240 }, border: { left: { style: BorderStyle.SINGLE, size: 18, color: ACCENT, space: 8 } }, children: runs(l.slice(2), { size: 19, color: "44403C" }) })); continue; }
  if (/^\s*- /.test(l)) { const lvl = l.match(/^\s*/)[0].length >= 2 ? 1 : 0; body.push(new Paragraph({ numbering: { reference: "bul", level: lvl }, spacing: { after: 50 }, children: runs(l.replace(/^\s*- /, "")) })); continue; }
  if (/^\d+\. /.test(l)) { body.push(new Paragraph({ numbering: { reference: "num", level: 0 }, spacing: { after: 50 }, children: runs(l.replace(/^\d+\. /, "")) })); continue; }
  if (l.trim() === "---") continue;
  if (l.trim() === "") continue;
  body.push(new Paragraph({ spacing: { after: 100 }, children: runs(l) }));
}

if (images.length) {
  body.push(new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 320, after: 140 }, children: runs("첨부 — 인스타그램·광고 소재", { size: 28, bold: true }) }));
  for (const img of images) {
    body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 }, children: [new ImageRun({ type: "png", data: fs.readFileSync(img), transformation: { width: 360, height: 450 } })] }));
    body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 }, children: [new TextRun({ text: path.basename(img), font: FONT, size: 16, color: "78716C" })] }));
  }
}

const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: 20 } } } },
  numbering: { config: [
    { reference: "bul", levels: [
      { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 240 } } } },
      { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 240 } } } }] },
    { reference: "num", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 300 } } } }] },
  ] },
  sections: [{ properties: { page: { margin: { top: 1100, bottom: 1100, left: 1300, right: 1300 } } }, children: body }],
});
Packer.toBuffer(doc).then((b) => { fs.writeFileSync(out, b); console.log(out); });
