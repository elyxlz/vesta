import { useRouter } from "expo-router";
import Stack from "expo-router/stack";

const IS_IOS = process.env.EXPO_OS === "ios";

export function NativeSheetCloseButton({
  accessibilityLabel,
  tintColor,
}: {
  accessibilityLabel: string;
  tintColor?: string;
}) {
  const router = useRouter();

  return (
    <Stack.Toolbar placement="left">
      <Stack.Toolbar.Button
        accessibilityLabel={accessibilityLabel}
        icon={IS_IOS ? "xmark" : undefined}
        separateBackground
        tintColor={tintColor}
        onPress={() => router.back()}
      >
        {IS_IOS ? undefined : "Close"}
      </Stack.Toolbar.Button>
    </Stack.Toolbar>
  );
}
