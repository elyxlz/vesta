import { useEffect, useState } from "react";
import {
  useNavigation,
  useRouter,
  type NativeStackNavigationProp,
} from "expo-router";
import Stack from "expo-router/stack";
import closeIcon from "../../assets/toolbar-icons/close.xml";

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
        icon={IS_IOS ? "xmark" : closeIcon}
        separateBackground
        tintColor={tintColor}
        onPress={() => router.back()}
      />
    </Stack.Toolbar>
  );
}

// Detent gating is iOS-only: Android form sheets emit no sheetDetentChange,
// so the close button stays visible there from the first render.
function useDetentReached(visibleFromDetentIndex: number | undefined) {
  const navigation =
    useNavigation<
      NativeStackNavigationProp<Record<string, object | undefined>>
    >();
  const [detentIndex, setDetentIndex] = useState(0);

  useEffect(() => {
    if (!IS_IOS || visibleFromDetentIndex === undefined) return;
    return navigation.addListener("sheetDetentChange", (event) => {
      if (event.data.stable) setDetentIndex(event.data.index);
    });
  }, [navigation, visibleFromDetentIndex]);

  return (
    !IS_IOS ||
    visibleFromDetentIndex === undefined ||
    detentIndex >= visibleFromDetentIndex
  );
}
