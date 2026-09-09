import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { expect, it, vi } from "vitest";

it("keeps the native input and its API, hiding only the nondeterministic caret", async () => {
  const native = Object.assign(function NativeTextInput() {}, { State: {} });
  const sandbox = vm.createContext({
    exports: {},
    require: (name) => name === "react"
      ? { forwardRef: (render) => render, createElement: (type, props) => ({ type, props }) }
      : { default: native },
  });
  vm.runInContext(await readFile(new URL("../visual/harness/text-input.js", import.meta.url), "utf8"), sandbox);
  const TextInput = sandbox.exports.default;
  const ref = {};
  const onChangeText = vi.fn();
  const props = { value: "Draft", autoFocus: true, onChangeText, caretHidden: false };
  const input = TextInput(props, ref);
  expect(input.type).toBe(native);
  expect(TextInput.State).toBe(native.State);
  expect(input.props).toEqual({ ...props, ref, caretHidden: true });
});
