Object.defineProperty(exports, "__esModule", { value: true });

const React = require("react");
const NativeTextInput =
  require("../../../node_modules/react-native/Libraries/Components/TextInput/TextInput").default;

// The native caret blinks independently of app animation settings. Preserve
// the real input, focus, selection, and keyboard; omit only its transient caret.
const TextInput = React.forwardRef(function VisualTextInput(props, ref) {
  return React.createElement(NativeTextInput, { ...props, ref, caretHidden: true });
});
Object.assign(TextInput, NativeTextInput);
exports.default = TextInput;
