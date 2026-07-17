import type { ReactElement } from "react";
import {
  Platform,
  type ColorValue,
  type NativeSyntheticEvent,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { requireNativeViewManager } from "expo-modules-core";
import {
  MenuView,
  type MenuAction as ExpoMenuAction,
} from "@expo/ui/community/menu";

export interface MessageMenuAction {
  id: string;
  title: string;
  systemImage?: Extract<ExpoMenuAction["image"], string>;
  destructive?: boolean;
  disabled?: boolean;
}

type TailSide = "none" | "leading" | "trailing";

interface MessageContextMenuProps {
  actions: MessageMenuAction[];
  children: ReactElement;
  onAction: (id: string) => void;
  style?: StyleProp<ViewStyle>;
  tailSide?: TailSide;
  tailOverhang?: number;
  previewCornerRadius?: number;
  bubbleFillColor?: ColorValue;
  bubbleStrokeColor?: ColorValue;
  bubbleStrokeWidth?: number;
}

interface NativeMessageContextMenuProps
  extends Omit<MessageContextMenuProps, "onAction"> {
  onAction: (
    event: NativeSyntheticEvent<{ id: string }>,
  ) => void;
}

const NativeMessageContextMenu =
  Platform.OS === "ios"
    ? requireNativeViewManager<NativeMessageContextMenuProps>(
        "VestaMessageMenu",
        "VestaMessageMenuView",
      )
    : null;

export function MessageContextMenu({
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
}: MessageContextMenuProps) {
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
        onAction={({ nativeEvent }) => onAction(nativeEvent.id)}
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
        image: action.systemImage,
        attributes: {
          destructive: action.destructive,
          disabled: action.disabled,
        },
      }))}
      onPressAction={({ nativeEvent }) => onAction(nativeEvent.event)}
      shouldOpenOnLongPress
      style={style}
    >
      {children}
    </MenuView>
  );
}
