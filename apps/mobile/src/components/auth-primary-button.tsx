import type { ComponentProps } from "react";
import { StyleSheet } from "react-native";
import { Button } from "@/components/ui/Button";

type AuthPrimaryButtonProps = Omit<
  ComponentProps<typeof Button>,
  "labelStyle" | "pill" | "size" | "variant"
>;

export function AuthPrimaryButton(props: AuthPrimaryButtonProps) {
  return (
    <Button
      {...props}
      pill
      size="large"
      variant="primary"
      labelStyle={styles.label}
    />
  );
}

const styles = StyleSheet.create({
  label: { fontSize: 14.5, lineHeight: 18, fontWeight: "600" },
});
