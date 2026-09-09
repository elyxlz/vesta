import { beforeEach, expect, it, vi } from "vitest";
import { RenameAgentPanel } from "./rename-agent-panel";

const fixture = vi.hoisted(() => ({
  stateIndex: 0,
  values: ["Nova_Prime", true, null] as unknown[],
  setState: vi.fn(),
  replace: vi.fn(),
  mutate: vi.fn(),
  pending: false,
  agent: { operation: null as string | null, status: "alive" },
  mutation: {} as {
    onSuccess: (name: string) => void;
    onError: (error: unknown) => void;
  },
}));
vi.mock("react", async (load) => ({
  ...(await load<typeof import("react")>()),
  useState: () => [fixture.values[fixture.stateIndex++], fixture.setState],
}));
vi.mock("react-native", () => ({
  View: "View",
  StyleSheet: { create: (styles: unknown) => styles },
}));
vi.mock("expo-router", () => ({ useRouter: () => ({ replace: fixture.replace }) }));
vi.mock("@/agent/AgentProvider", () => ({
  useAgent: () => ({ name: "aria", agent: fixture.agent }),
}));
vi.mock("@/session/SessionProvider", () => ({ useSession: () => ({ api: {} }) }));
vi.mock("@/components/ui/Button", () => ({ Button: "Button" }));
vi.mock("@/components/ui/Form", () => ({ Field: "Field", FormSection: "FormSection" }));
vi.mock("@tanstack/react-query", () => ({
  useMutation: (options: typeof fixture.mutation) => {
    fixture.mutation = options;
    return { mutate: fixture.mutate, isPending: fixture.pending };
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  fixture.stateIndex = 0;
  fixture.values = ["Nova_Prime", true, null];
  fixture.pending = false;
  fixture.agent = { operation: null, status: "alive" };
});

it("keeps canonical-name guidance and the restart warning in the dedicated panel", () => {
  const panel = RenameAgentPanel();
  expect(panel.props.footer).toContain("Renaming restarts aria");
  expect(panel.props.children.props.children.props.description).toBe(
    "This will be saved as nova-prime.",
  );
  panel.props.actions.props.onPress();
  expect(fixture.mutate).toHaveBeenCalledOnce();
});

it("returns a successful rename to the renamed agent's main Settings", () => {
  RenameAgentPanel();
  fixture.mutation.onSuccess("nova-prime");
  expect(fixture.replace).toHaveBeenCalledWith({
    pathname: "/agent/[name]/settings",
    params: { name: "nova-prime" },
  });
});

it.each(["invalid", "busy", "pending"])("blocks a %s rename", (state) => {
  if (state === "invalid") fixture.values[0] = "aria";
  if (state === "busy") fixture.agent.operation = "backing_up";
  if (state === "pending") fixture.pending = true;
  RenameAgentPanel().props.actions.props.onPress();
  expect(fixture.mutate).not.toHaveBeenCalled();
});

it("retains server errors without navigating away", () => {
  RenameAgentPanel();
  fixture.mutation.onError(new Error("Name already exists"));
  expect(fixture.setState).toHaveBeenCalledWith("Name already exists");
  expect(fixture.replace).not.toHaveBeenCalled();
});
