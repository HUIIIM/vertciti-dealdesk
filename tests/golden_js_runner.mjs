// 黄金样本对照 · JS 引擎抽取运行器（台账第 13 项）
// 用法：node golden_js_runner.mjs <uw-commercial.js 路径> <jobs.json 路径>
// 从 static/uw-commercial.js 抽取纯计算段（const EXPENSES … computeAll，
// 止于 state 段落标记），在 Node 里求值后对 fixture 逐个跑 computeAll，
// 并跑 helper 网格（amortPayment / remainingBal）。结果 JSON 打到 stdout
// （NaN 经 JSON.stringify 自动变 null，与后端 None 同判）。
import fs from "node:fs";

const [jsPath, jobsPath] = process.argv.slice(2);
const src = fs.readFileSync(jsPath, "utf8");
const start = src.indexOf("const EXPENSES");
const end = src.indexOf("/* ---------------- state");
if (start < 0 || end < 0 || end <= start) {
  console.error("compute section markers not found");
  process.exit(2);
}
const section = src.slice(start, end);
const factory = new Function(
  section +
  "\nreturn { computeAll, computeAnalysis, computeExit, amortPayment, remainingBal, irrOf };"
);
const api = factory();
const jobs = JSON.parse(fs.readFileSync(jobsPath, "utf8"));
const results = {};
for (const [name, data] of Object.entries(jobs.fixtures || {})) {
  results[name] = api.computeAll(JSON.parse(JSON.stringify(data)));
}
const grid = (jobs.grid || []).map((g) => {
  const annual = api.amortPayment(g.loan, g.rate_dec, g.years);
  const balance = api.remainingBal(g.loan, g.rate_dec, g.years, annual, g.after);
  return { annual, monthly: annual / 12, balance };
});
process.stdout.write(JSON.stringify({ results, grid }));
