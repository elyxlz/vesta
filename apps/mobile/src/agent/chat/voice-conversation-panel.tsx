import { Pressable, StyleSheet, View } from "react-native";
import Reanimated, {
  Easing,
  FadeIn,
  FadeInUp,
  FadeOut,
  FadeOutDown,
} from "react-native-reanimated";
import { Ionicons } from "@expo/vector-icons";
import { splitSpokenTail, type AgentRow, type OrbMotion } from "@vesta/core";
import { AgentOrb } from "@/components/AgentOrb";
import { FormSwitch } from "@/components/ui/form-switch";
import { Text } from "@/components/ui/Typography";
import { fontNames } from "@/theme/typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

const ORB_SIZE = 140;
const CONTROL_SIZE = 40;
const PILL_LINE_HEIGHT = 20;
const PILL_PADDING_VERTICAL = 6;
const PILL_MAX_LINES = 3;
// A one-line pill sits centered on the controls; growing to two lines, its bottom stays put.
const PILL_MARGIN_BOTTOM =
  (CONTROL_SIZE - (PILL_LINE_HEIGHT + 2 * PILL_PADDING_VERTICAL)) / 2;
// The sheet easing the web panel uses for its staggered slide.
const SHEET_EASE = Easing.bezier(0.32, 0.72, 0, 1).factory();
const ORB_ENTER_MS = 550;
const ORB_EXIT_MS = 270;
const ROW_ENTER_MS = 380;
const ROW_ENTER_DELAY_MS = 15;
const ROW_EXIT_MS = 190;
const WAKE_ENTER_DELAY_MS = 120;
const PANEL_PADDING_TOP = 4;
const PANEL_PADDING_HORIZONTAL = 8;

function RoundControl({
  label,
  icon,
  active,
  onPress,
}: {
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  active?: boolean;
  onPress: () => void;
}) {
  const { colors } = usePreferences();
  return (
    <Pressable
      accessibilityLabel={label}
      accessibilityRole="button"
      accessibilityState={
        active === undefined ? undefined : { selected: active }
      }
      hitSlop={4}
      onPress={onPress}
      style={({ pressed }) => [
        styles.control,
        active
          ? { backgroundColor: colors.danger, borderColor: colors.danger }
          : { borderColor: colors.border },
        { opacity: pressed ? 0.72 : 1 },
      ]}
    >
      <Ionicons name={icon} size={18} color={active ? "white" : colors.text} />
    </Pressable>
  );
}

// The live conversation surface: the agent's real status orb with voice motion overlaid, and one
// row of controls, the mirror of web's panel. Your words take the pill over as you speak, the
// freshest one bold so the eye can ride the stream; between turns the pill shows the phase.
// `wakeWordOn` is null for a voice service with no wake word, which shows no toggle.
export function VoiceConversationPanel({
  agent,
  name,
  label,
  motion,
  transcript,
  micMuted,
  wakeWordOn,
  height,
  onToggleMute,
  onToggleWakeWord,
  onEnd,
}: {
  agent: AgentRow | null;
  name: string;
  label: string;
  motion: OrbMotion | undefined;
  transcript: string;
  micMuted: boolean;
  wakeWordOn: boolean | null;
  height: number;
  onToggleMute: () => void;
  onToggleWakeWord: () => void;
  onEnd: () => void;
}) {
  const { colors } = usePreferences();
  const spoken = transcript.trim();
  const { head, tail } = splitSpokenTail(spoken);

  return (
    <View style={[styles.panel, { height }]}>
      <Reanimated.View
        entering={FadeInUp.duration(ORB_ENTER_MS).easing(SHEET_EASE)}
        exiting={FadeOutDown.duration(ORB_EXIT_MS).easing(SHEET_EASE)}
        pointerEvents="none"
        style={styles.orbLayer}
      >
        {agent ? (
          <AgentOrb
            name={name}
            status={agent.status}
            activityState={agent.activityState}
            operation={agent.operation}
            booting={agent.booting}
            rateLimited={agent.rateLimited}
            motion={motion}
            size={ORB_SIZE}
          />
        ) : null}
      </Reanimated.View>
      {wakeWordOn === null ? null : (
        <Reanimated.View
          entering={FadeIn.duration(ROW_ENTER_MS)
            .delay(WAKE_ENTER_DELAY_MS)
            .easing(SHEET_EASE)}
          exiting={FadeOut.duration(ROW_EXIT_MS).easing(SHEET_EASE)}
          style={styles.wakeCorner}
        >
          <Pressable
            accessibilityLabel="Wake word"
            accessibilityRole="switch"
            accessibilityState={{ checked: wakeWordOn }}
            onPress={onToggleWakeWord}
            style={[styles.wakeChip, { backgroundColor: colors.input }]}
          >
            <Text style={[styles.wakeLabel, { color: colors.secondaryText }]}>
              wake word
            </Text>
            {/* The chip is the control; the switch only shows its state. */}
            <View pointerEvents="none">
              <FormSwitch value={wakeWordOn} onValueChange={onToggleWakeWord} />
            </View>
          </Pressable>
        </Reanimated.View>
      )}
      <Reanimated.View
        entering={FadeInUp.duration(ROW_ENTER_MS)
          .delay(ROW_ENTER_DELAY_MS)
          .easing(SHEET_EASE)}
        exiting={FadeOutDown.duration(ROW_EXIT_MS).easing(SHEET_EASE)}
        style={styles.controlsRow}
      >
        <RoundControl
          label={micMuted ? "Unmute microphone" : "Mute microphone"}
          icon={micMuted ? "mic-off" : "mic"}
          active={micMuted}
          onPress={onToggleMute}
        />
        {/* The pill takes the bubble color while the microphone is transcribing the user. */}
        <View
          style={[
            styles.pill,
            {
              backgroundColor:
                motion === "listening" ? colors.bubble : colors.input,
            },
          ]}
        >
          {/* The words are anchored to the pill's bottom inside a three-line clip, so the newest
              word always sits at the bottom and older lines run out the top. */}
          {spoken ? (
            <View style={styles.pillClip}>
              <Text
                style={[
                  styles.pillText,
                  styles.pillTranscript,
                  { color: colors.secondaryText },
                ]}
              >
                {head}
                <Text style={[styles.pillTail, { color: colors.text }]}>
                  {tail}
                </Text>
              </Text>
            </View>
          ) : (
            <Text
              style={[
                styles.pillText,
                styles.pillPhase,
                { color: colors.secondaryText },
              ]}
            >
              {label}
            </Text>
          )}
        </View>
        <RoundControl label="End conversation" icon="close" onPress={onEnd} />
      </Reanimated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  // Laid out inside the composer's glass surface, which supplies the card.
  panel: {
    paddingHorizontal: PANEL_PADDING_HORIZONTAL,
    paddingTop: PANEL_PADDING_TOP,
    paddingBottom: 8,
    gap: 16,
    justifyContent: "flex-end",
    alignItems: "center",
  },
  // Centered on the whole card, beneath the control row.
  orbLayer: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    alignItems: "center",
    justifyContent: "center",
  },
  // The wake word toggle sits in the card's top right corner, above the orb layer.
  wakeCorner: {
    position: "absolute",
    top: PANEL_PADDING_TOP,
    right: PANEL_PADDING_HORIZONTAL,
  },
  wakeChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    height: CONTROL_SIZE,
    borderRadius: CONTROL_SIZE / 2,
    paddingLeft: 12,
    paddingRight: 4,
  },
  wakeLabel: { fontSize: 13, fontFamily: fontNames.sans.native["400"] },
  controlsRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    alignSelf: "stretch",
    gap: 12,
  },
  control: {
    width: CONTROL_SIZE,
    height: CONTROL_SIZE,
    borderRadius: CONTROL_SIZE / 2,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: "center",
    justifyContent: "center",
  },
  pill: {
    flex: 1,
    minWidth: 0,
    borderRadius: 16,
    paddingHorizontal: 10,
    paddingVertical: PILL_PADDING_VERTICAL,
    marginBottom: PILL_MARGIN_BOTTOM,
  },
  pillClip: { height: PILL_LINE_HEIGHT * PILL_MAX_LINES, overflow: "hidden" },
  pillTranscript: { position: "absolute", left: 0, right: 0, bottom: 0 },
  pillText: {
    fontSize: 14,
    lineHeight: PILL_LINE_HEIGHT,
    fontFamily: fontNames.sans.native["400"],
  },
  pillTail: { fontFamily: fontNames.sans.native["600"] },
  pillPhase: { textAlign: "center" },
});
