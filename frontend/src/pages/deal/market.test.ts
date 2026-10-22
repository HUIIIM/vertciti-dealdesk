import { describe, expect, it } from "vitest";
import { guessArea } from "./MarketTab";

describe("guessArea (EchoWatch query area from a deal address)", () => {
  it("takes the city segment of a comma address", () => {
    expect(guessArea("123 Main St, Tampa, FL 33602")).toBe("Tampa");
  });
  it("takes the word before STATE ZIP in a comma-less address", () => {
    expect(guessArea("39-09 Main St Flushing NY 11354")).toBe("Flushing");
  });
  it("returns empty when it cannot tell (user types the area)", () => {
    expect(guessArea("")).toBe("");
    expect(guessArea("somewhere")).toBe("");
  });
});
