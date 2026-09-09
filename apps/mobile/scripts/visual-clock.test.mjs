import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { expect, it } from "vitest";

it("freezes only wall time while preserving explicit dates and native timers", async () => {
  const sandbox = vm.createContext({ setTimeout, performance });
  vm.runInContext(
    await readFile(
      new URL("../visual/harness/clock.js", import.meta.url),
      "utf8",
    ),
    sandbox,
  );
  expect(vm.runInContext("new Date().toISOString()", sandbox)).toBe(
    "2026-08-01T09:41:00.000Z",
  );
  expect(vm.runInContext("Date.now()", sandbox)).toBe(1785577260000);
  expect(
    vm.runInContext("new Date('2020-01-01').getUTCFullYear()", sandbox),
  ).toBe(2020);
  expect(vm.runInContext("new Date() instanceof Date", sandbox)).toBe(true);
  expect(vm.runInContext("setTimeout", sandbox)).toBe(setTimeout);
  expect(vm.runInContext("performance", sandbox)).toBe(performance);
});
