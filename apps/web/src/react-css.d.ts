// CSS custom properties and the vendor-only text-security property, so an inline style object
// types them instead of asserting to CSSProperties.
import "react";

declare module "react" {
  interface CSSProperties {
    [customProperty: `--${string}`]: string | number | undefined;
    WebkitTextSecurity?: "none" | "circle" | "disc" | "square";
  }
}
