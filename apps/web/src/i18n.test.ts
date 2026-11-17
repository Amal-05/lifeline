import { describe, expect, it } from "vitest";
import { resources } from "./i18n.js";

describe("field translations", () => {
  it("provides every English UI string in all required languages", () => {
    const keys = Object.keys(resources.en.translation).sort();
    for (const language of ["ml", "hi", "ta"] as const) {
      expect(Object.keys(resources[language].translation).sort()).toEqual(keys);
    }
  });
});
