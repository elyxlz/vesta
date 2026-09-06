Object.defineProperty(exports, "__esModule", { value: true });

const React = require("react");
const NativeActivityIndicator =
  require("../../../node_modules/react-native/Libraries/Components/ActivityIndicator/ActivityIndicator").default;

// Keep the real native spinner, including its layout, size and color. UIKit's
// indefinite animation ignores UIView.setAnimationsEnabled(false); show its
// stopped frame instead. Deliberately hidden indicators remain hidden.
exports.default = function VisualActivityIndicator(props) {
  return React.createElement(NativeActivityIndicator, {
    ...props,
    animating: false,
    hidesWhenStopped:
      props.animating === false ? props.hidesWhenStopped : false,
  });
};
