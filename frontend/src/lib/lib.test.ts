import { describe, expect, it } from "vitest";
import { DASH, fmt, fmtCell, fmtDate, fmtShort, isNeg, parseNum, unitSuffix } from "./format";
import { matches } from "./hotkeys";
import { getPath, scaleNum, setPath, updateWild } from "./paths";
import { href, parse } from "./router";

describe("format：未知保持未知、负数括号、单位规则", () => {
  it("未知显示 —，绝不显示 0", () => {
    for (const v of [null, undefined, Number.NaN, Infinity, ""]) { expect(fmt(v, "usd")).toBe(DASH); expect(fmtCell(v, "pct")).toBe(DASH); }
  });
  it("金额千分位、负数括号", () => {
    expect(fmt(1234567.4, "usd")).toBe("$1,234,567");
    expect(fmt(-12084000, "usd")).toBe("($12,084,000)");
    expect(fmtCell(-5, "usd")).toBe("(5)");
  });
  it("百分比按百分比数（6.5 = 6.5%），倍数带 ×，评分为分", () => {
    expect(fmt(6.5, "pct")).toBe("6.50%");
    expect(fmt(-13.83, "pct")).toBe("(13.83%)");
    expect(fmt(1.3378, "x")).toBe("1.34×");
    expect(fmt(91.1, "pts")).toBe("91.1");
    expect(fmt(90, "pts")).toBe("90");
    expect(unitSuffix("usd_month")).toBe("$/月");
  });
  it("紧凑金额与日期", () => {
    expect(fmtShort(37979400)).toBe("$37.98M");
    expect(fmtShort(-1500)).toBe("($1.5K)");
    expect(fmtShort(2.5e9)).toBe("$2.50B");
    expect(fmtShort(null)).toBe(DASH);
    expect(fmtDate("2026-10-22T08:05:00Z").length).toBe(10);
    expect(fmtDate("garbage")).toBe(DASH);
    expect(fmtDate(null)).toBe(DASH);
    expect(isNeg(-1)).toBe(true);
    expect(isNeg("x")).toBe(false);
  });
  it("parseNum：千分位、$、括号负数、空串为未知", () => {
    expect(parseNum("4,200,000")).toBe(4200000);
    expect(parseNum("$1,500")).toBe(1500);
    expect(parseNum("(250)")).toBe(-250);
    expect(parseNum("-3.5")).toBe(-3.5);
    expect(parseNum("6.5%")).toBe(6.5);
    expect(parseNum("")).toBeNull();
    expect(parseNum("abc")).toBeNull();
  });
});

describe("paths：与后端同语义", () => {
  const d = { a: { b: 1 }, t: [{ r: 10 }, { r: 20 }] };
  it("读写且不可变", () => {
    expect(getPath(d, "a.b")).toBe(1);
    expect(getPath(d, "t.1.r")).toBe(20);
    expect(getPath(d, "x.y")).toBeUndefined();
    const d2 = setPath(d, "a.b", 2);
    expect(getPath(d2, "a.b")).toBe(2);
    expect(d.a.b).toBe(1);
    expect(getPath(setPath({}, "n.0.m", 5), "n.0.m")).toBe(5);
  });
  it("通配 * 对每一项生效", () => {
    const d3 = updateWild(d, "t.*.r", (v) => scaleNum(v, 1.1));
    expect(getPath(d3, "t.0.r")).toBeCloseTo(11);
    expect(getPath(d3, "t.1.r")).toBeCloseTo(22);
    expect(updateWild({ t: "no" }, "t.*.r", (v) => v)).toEqual({ t: "no" });
    expect(updateWild(d, "a.b", (v) => scaleNum(v, 3))).toEqual({ ...d, a: { b: 3 } });
    expect(scaleNum("x", 2)).toBe("x");
  });
});

describe("router", () => {
  it("解析与生成互逆", () => {
    expect(parse("#/")).toEqual({ name: "pipeline" });
    expect(parse("#/deals/12/model")).toEqual({ name: "deal", id: 12, tab: "model" });
    expect(parse("#/deals/12/nope")).toEqual({ name: "deal", id: 12, tab: "overview" });
    expect(parse("#/compare?ids=1,2,x")).toEqual({ name: "compare", ids: [1, 2] });
    expect(parse("#/settings")).toEqual({ name: "settings", section: "templates" });
    expect(parse("#/zzz").name).toBe("notfound");
    expect(href({ name: "deal", id: 3, tab: "overview" })).toBe("#/deals/3");
    expect(href({ name: "deal", id: 3, tab: "risk" })).toBe("#/deals/3/risk");
    expect(href({ name: "compare", ids: [1, 2] })).toBe("#/compare?ids=1,2");
    expect(href({ name: "settings", section: "users" })).toBe("#/settings/users");
  });
});

describe("hotkeys.matches", () => {
  const ev = (key: string, mods: Partial<KeyboardEvent> = {}) => ({ key, metaKey: false, ctrlKey: false, shiftKey: false, ...mods }) as KeyboardEvent;
  it("⌘/Ctrl 组合与单键", () => {
    expect(matches(ev("k", { metaKey: true }), "mod+k")).toBe(true);
    expect(matches(ev("k", { ctrlKey: true }), "mod+k")).toBe(true);
    expect(matches(ev("k"), "mod+k")).toBe(false);
    expect(matches(ev("j"), "j")).toBe(true);
    expect(matches(ev("j", { metaKey: true }), "j")).toBe(false);
    expect(matches(ev("S", { metaKey: true }), "mod+s")).toBe(true);
  });
});
