"use strict";

Object.defineProperty(exports, "__esModule", { value: true });

const React = require("react");
const stackModule = require("expo-router/build/layouts/Stack");

const NativeStack = stackModule.default;

function withoutAnimation(options) {
  if (typeof options === "function") {
    return (...args) => ({
      ...(options(...args) ?? {}),
      animation: "none",
    });
  }

  return {
    ...(options ?? {}),
    animation: "none",
  };
}

function disableScreenAnimations(child) {
  if (!React.isValidElement(child)) return child;

  if (child.type === NativeStack.Screen) {
    return React.cloneElement(child, {
      options: withoutAnimation(child.props.options),
    });
  }

  if (child.props.children !== undefined) {
    return React.cloneElement(child, undefined, React.Children.map(
      child.props.children,
      disableScreenAnimations,
    ));
  }

  return child;
}

function VisualStack({ children, screenOptions, ...props }) {
  return React.createElement(
    NativeStack,
    {
      ...props,
      screenOptions: withoutAnimation(screenOptions),
    },
    React.Children.map(children, disableScreenAnimations),
  );
}

Object.assign(VisualStack, NativeStack);

exports.Stack = VisualStack;
exports.default = VisualStack;
