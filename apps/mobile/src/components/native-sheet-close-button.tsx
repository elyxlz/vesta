import { useEffect, useState } from "react";
import {
  useNavigation,
  useRouter,
  type NativeStackNavigationProp,
} from "expo-router";
import Stack from "expo-router/stack";

const IS_IOS = process.env.EXPO_OS === "ios";

export function NativeSheetCloseButton({
  accessibilityLabel,
  tintColor,
  visibleFromDetentIndex,
}: {
  accessibilityLabel: string;
  tintColor?: string;
  visibleFromDetentIndex?: number;
}) {
  const router = useRouter();
  const visible = useDetentReached(visibleFromDetentIndex);

  if (!visible) return null;

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

function useDetentReached(visibleFromDetentIndex: number | undefined) {
  const navigation =
    useNavigation<
      NativeStackNavigationProp<Record<string, object | undefined>>
    >();
  const [detentIndex, setDetentIndex] = useState(0);

  useEffect(() => {
    if (visibleFromDetentIndex === undefined) return;
    return navigation.addListener("sheetDetentChange", (event) => {
      if (event.data.stable) setDetentIndex(event.data.index);
    });
  }, [navigation, visibleFromDetentIndex]);

  return (
    visibleFromDetentIndex === undefined ||
    detentIndex >= visibleFromDetentIndex
  );
}
