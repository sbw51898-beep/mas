import fs from "node:fs/promises";

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  throw new Error("usage: node build_dual_blind_review_pack_artifact.mjs <input.json> <output.xlsx>");
}
if (!process.env.CODEX_ARTIFACT_TOOL_MODULE) {
  throw new Error("CODEX_ARTIFACT_TOOL_MODULE is required");
}

const { Workbook, SpreadsheetFile } = await import(
  process.env.CODEX_ARTIFACT_TOOL_MODULE,
);
const spec = JSON.parse(await fs.readFile(inputPath, "utf8"));
if (!Array.isArray(spec.rows) || spec.rows.length === 0) {
  throw new Error("review pack needs at least one row");
}

function messageBlock(messages) {
  return messages
    .map((message) => `[${message.message_id}] ${message.content}`)
    .join("\n\n");
}

function setColumnWidth(sheet, column, width, lastRow) {
  sheet.getRange(`${column}1:${column}${lastRow}`).format.columnWidth = width;
}

const workbook = Workbook.create();
const guide = workbook.worksheets.add("填写说明");
guide.showGridLines = false;
guide.getRange("A1").values = [[`HiddenBench 私有信息披露双人盲审签核表（${spec.reviewer_label}）`]];
guide.getRange("A1").format = {
  fill: "#D9EAF7",
  font: { bold: true, color: "#17365D", size: 16 },
  verticalAlignment: "center",
  wrapText: true,
};
guide.getRange("A1").format.rowHeight = 28;
guide.getRange("A3:B6").values = [
  ["填写项目", "内容"],
  ["审阅者姓名（真实姓名）", ""],
  ["审阅日期（YYYY-MM-DD）", ""],
  ["签核确认", ""],
];
guide.getRange("A3:B3").format = {
  fill: "#D9EAF7",
  font: { bold: true, color: "#17365D" },
  horizontalAlignment: "center",
};
guide.getRange("A4:A6").format = {
  fill: "#F2F2F2",
  font: { bold: true },
  wrapText: true,
};
guide.getRange("B4:B6").format = {
  fill: "#FFF2CC",
  wrapText: true,
};
guide.getRange("A8").values = [["判定规则"]];
guide.getRange("A8").format = {
  fill: "#D9EAD3",
  font: { bold: true, color: "#274E13" },
};
guide.getRange("A9:A16").values = [
  ["1. 仅当信息拥有者本人公开说出原事实，或作出保留决策关键含义的忠实转述时，才判为“是”。"],
  ["2. 与原事实相矛盾、极性反转、仅提到话题、或明显弱化关键含义时，判为“否”。"],
  ["3. 判“是”时，必须填写拥有者消息 ID，并从该消息复制一段连续原文作为证据。"],
  ["4. 判“否”时，证据消息 ID 和原文引句必须留空。"],
  ["5. 请逐行独立判断；不要根据其他条目推断，也不要使用外部资料。"],
  ["6. 填写姓名、日期，并在签核确认栏填写：“我确认以上为本人独立判断”。"],
  ["7. 表内不展示任何既有判断标签；完成后请保留原始文件，以便双人合并程序核验。"],
  ["8. 若无法判断，请仍选择“是”或“否”，并在理由列写明不确定点；不要留空。"],
];
guide.getRange("A9:A16").format = { wrapText: true, verticalAlignment: "top" };
setColumnWidth(guide, "A", 105, 16);
setColumnWidth(guide, "B", 36, 16);
guide.getRange("A3:B6").format.borders = { preset: "all", style: "thin", color: "#B7C9D6" };

const review = workbook.worksheets.add("盲审签核");
review.showGridLines = false;
const headers = [
  "序号",
  "盲审编号",
  "私有信息包（待判断内容）",
  "信息拥有者",
  "拥有者公开发言（含消息ID）",
  "是否披露（是/否）",
  "证据消息ID（判“是”必填）",
  "证据原文引句（判“是”必填）",
  "理由（可选）",
];
const values = [
  headers,
  ...spec.rows.map((row, index) => [
    index + 1,
    row.blind_id,
    row.fact,
    row.owner_agent_id,
    messageBlock(row.owner_messages),
    "",
    "",
    "",
    "",
  ]),
];
const lastRow = values.length;
review.getRange(`A1:I${lastRow}`).values = values;
review.getRange("A1:I1").format = {
  fill: "#17365D",
  font: { bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
review.getRange(`A2:I${lastRow}`).format = {
  verticalAlignment: "top",
  wrapText: true,
};
review.getRange(`F2:I${lastRow}`).format = { fill: "#FFF2CC", wrapText: true, verticalAlignment: "top" };
review.getRange(`A1:I${lastRow}`).format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
review.getRange(`F2:F${lastRow}`).dataValidation = {
  rule: { type: "list", values: ["是", "否"] },
};
review.freezePanes.freezeRows(1);
setColumnWidth(review, "A", 7, lastRow);
setColumnWidth(review, "B", 19, lastRow);
setColumnWidth(review, "C", 50, lastRow);
setColumnWidth(review, "D", 14, lastRow);
setColumnWidth(review, "E", 85, lastRow);
setColumnWidth(review, "F", 16, lastRow);
setColumnWidth(review, "G", 31, lastRow);
setColumnWidth(review, "H", 50, lastRow);
setColumnWidth(review, "I", 40, lastRow);
review.getRange("A1:I1").format.rowHeight = 36;
review.getRange(`A2:I${lastRow}`).format.rowHeight = 105;

const inspection = await workbook.inspect({
  kind: "table",
  sheetId: "盲审签核",
  range: "A1:I4",
  tableMaxRows: 4,
  tableMaxCols: 9,
  maxChars: 2500,
});
if (!inspection.ndjson.includes("盲审编号")) {
  throw new Error("artifact workbook inspection did not contain expected header");
}
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
