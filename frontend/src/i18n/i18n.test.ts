// 中英切换守门：源码里每条中文都经 T()，每个 T() 都有英文、占位一致；词典没有死条目。
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import { afterEach, describe, expect, it } from "vitest";
import { EN } from "./en";
import { __setLangForTest, T } from "./index";

const SRC = path.resolve(__dirname, "..");
const CJK = /[　-〿一-鿿＀-￯]/;

function sourceFiles(dir: string): string[] {
  return fs.readdirSync(dir).flatMap((f) => {
    const p = path.join(dir, f);
    if (fs.statSync(p).isDirectory()) return f === "test" || f === "i18n" ? [] : sourceFiles(p);
    return /\.(ts|tsx)$/.test(f) && !/\.test\.tsx?$/.test(f) && !f.endsWith(".d.ts") ? [p] : [];
  });
}

interface Scan { keys: Set<string>; raw: string[] }

function scan(): Scan {
  const keys = new Set<string>();
  const raw: string[] = [];
  for (const file of sourceFiles(SRC)) {
    const text = fs.readFileSync(file, "utf8");
    const lines = text.split("\n");
    const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const where = (n: ts.Node) => `${path.relative(SRC, file)}:${sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1}`;
    const exempt = (n: ts.Node) => /i18n-exempt/.test(lines[sf.getLineAndCharacterOfPosition(n.getStart(sf)).line] ?? "");
    const visit = (n: ts.Node): void => {
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "T") {
        const a = n.arguments[0];
        if (a && ts.isStringLiteral(a)) keys.add(a.text);
        n.arguments.slice(1).forEach(visit);
        return;
      }
      const isText = ts.isJsxText(n) || ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n) || ts.isTemplateHead(n)
        || ts.isTemplateMiddle(n) || ts.isTemplateTail(n);
      if (isText && CJK.test((n as ts.LiteralLikeNode).text) && !exempt(n)) raw.push(`${where(n)} ${(n as ts.LiteralLikeNode).text.trim().slice(0, 40)}`);
      ts.forEachChild(n, visit);
    };
    visit(sf);
  }
  return { keys, raw };
}

const placeholders = (s: string) => [...s.matchAll(/\{(\d+)\}/g)].map((m) => m[1]).sort();

describe("中英切换", () => {
  afterEach(() => __setLangForTest("zh"));
  const { keys, raw } = scan();

  it("源码里没有绕过 T() 的中文（注释与 i18n-exempt 标注除外）", () => {
    expect(raw).toEqual([]);
  });
  it("每个 T() 键都有英文，且词典没有死条目", () => {
    expect([...keys].filter((k) => !(k in EN))).toEqual([]);
    expect(Object.keys(EN).filter((k) => !keys.has(k))).toEqual([]);
  });
  it("英文值不含中文、占位与中文键一致", () => {
    expect(Object.entries(EN).filter(([, v]) => CJK.test(v))).toEqual([]);
    expect(Object.entries(EN).filter(([k, v]) => placeholders(k).join() !== placeholders(v).join())).toEqual([]);
  });
  it("T()：中文原样、英文查词典并替换占位", () => {
    expect(T("第 {0} 年", [3])).toBe("第 3 年");
    __setLangForTest("en");
    expect(T("第 {0} 年", [3])).toBe("Year 3");
    expect(T("保存为新版本")).toBe("Save as new version");
    expect(T("词典里没有的话")).toBe("词典里没有的话");  // i18n-exempt：缺词回退原文
  });
});
