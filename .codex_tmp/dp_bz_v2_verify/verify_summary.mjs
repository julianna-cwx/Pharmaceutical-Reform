import fs from "node:fs/promises";
import { Workbook } from "@oai/artifact-tool";

const sourcePath =
  "D:\\Hospital_Pharmacy program\\data\\hospital\\hosp_dp\\diff_dp_bz\\v2\\dp_bz_year_v2_summary.csv";
const csvText = await fs.readFile(sourcePath, "utf8");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "V2 Summary" });

const inspection = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 8000,
  tableMaxRows: 10,
  tableMaxCols: 12,
  tableMaxCellChars: 100,
});
console.log(inspection.ndjson);

const preview = await workbook.render({
  sheetName: "V2 Summary",
  range: "A1:L10",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  "D:\\Hospital_Pharmacy program\\.codex_tmp\\dp_bz_v2_verify\\summary_preview.png",
  new Uint8Array(await preview.arrayBuffer()),
);
console.log("ARTIFACT_TOOL_VERIFY_OK");
process.exit(0);
