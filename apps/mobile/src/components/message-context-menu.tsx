import type { ReactElement } from "react";
import type {
  ColorValue,
  NativeSyntheticEvent,
  StyleProp,
  ViewStyle,
} from "react-native";
import { requireNativeViewManager } from "expo-modules-core";
import {
  MenuView,
  type MenuAction as ExpoMenuAction,
} from "@expo/ui/community/menu";

export interface MessageMenuAction<Id extends string = string> {
  id: Id;
  title: string;
  systemImage?: Extract<ExpoMenuAction["image"], string>;
  androidImage?: Exclude<ExpoMenuAction["image"], string>;
  destructive?: boolean;
  disabled?: boolean;
}

type TailSide = "none" | "leading" | "trailing";

interface MessageContextMenuProps<Id extends string> {
  actions: MessageMenuAction<Id>[];
  children: ReactElement;
  onAction: (id: Id) => void;
  style?: StyleProp<ViewStyle>;
  tailSide?: TailSide;
  tailOverhang?: number;
  previewCornerRadius?: number;
  bubbleFillColor?: ColorValue;
  bubbleStrokeColor?: ColorValue;
  bubbleStrokeWidth?: number;
}

interface NativeMessageContextMenuProps
  extends Omit<MessageContextMenuProps<string>, "onAction"> {
  onAction: (
    event: NativeSyntheticEvent<{ id: string }>,
  ) => void;
}

const NativeMessageContextMenu =
  process.env.EXPO_OS === "ios"
    ? requireNativeViewManager<NativeMessageContextMenuProps>(
        "VestaMessageMenu",
        "VestaMessageMenuView",
      )
    : null;

export function MessageContextMenu<Id extends string = string>({
  actions,
  children,
  onAction,
  style,
  tailSide = "none",
  tailOverhang = 0,
  previewCornerRadius = 22,
  bubbleFillColor = "transparent",
  bubbleStrokeColor = "transparent",
  bubbleStrokeWidth = 0,
}: MessageContextMenuProps<Id>) {
  const emitAction = (id: string) => {
    const action = actions.find((entry) => entry.id === id);
    if (action) onAction(action.id);
  };

  if (NativeMessageContextMenu) {
    const tailLayout =
      tailSide === "none"
        ? null
        : {
            marginHorizontal: -tailOverhang,
            paddingHorizontal: tailOverhang,
          };

    return (
      <NativeMessageContextMenu
        actions={actions}
        bubbleFillColor={bubbleFillColor}
        bubbleStrokeColor={bubbleStrokeColor}
        bubbleStrokeWidth={bubbleStrokeWidth}
        onAction={({ nativeEvent }) => emitAction(nativeEvent.id)}
        previewCornerRadius={previewCornerRadius}
        style={[style, tailLayout]}
        tailOverhang={tailOverhang}
        tailSide={tailSide}
      >
        {children}
      </NativeMessageContextMenu>
    );
  }

  return (
    <MenuView
      actions={actions.map((action) => ({
        id: action.id,
        title: action.title,
        image: action.androidImage ?? action.systemImage,
        attributes: {
          destructive: action.destructive,
          disabled: action.disabled,
        },
      }))}
      onPressAction={({ nativeEvent }) => emitAction(nativeEvent.event)}
      shouldOpenOnLongPress
      style={style}
    >
      {children}
    </MenuView>
  );
}
