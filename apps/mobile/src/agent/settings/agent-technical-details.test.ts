import { beforeEach, expect, it, vi } from "vitest";
import { AgentTechnicalDetails } from "./agent-technical-details";

const fixture = vi.hoisted(() => ({ expanded: false, setExpanded: vi.fn() }));
vi.mock("react", async (load) => ({
  ...(await load<typeof import("react")>()),
  useState: () => [fixture.expanded, fixture.setExpanded],
}));
vi.mock("@/agent/AgentProvider", () => ({
  useAgent: () => ({
    agent: { status: "not_authenticated", startedAt: null, services: { chat: {} } },
    activityState: "idle",
  }),
}));
vi.mock("@/components/ui/Form", () => ({
  FormRow: "FormRow",
  FormSection: "FormSection",
}));

beforeEach(() => {
  fixture.expanded = false;
  vi.clearAllMocks();
});

it("keeps technical rows collapsed until explicitly opened", () => {
  const rows = AgentTechnicalDetails().props.children;
  expect(rows[0].props.expanded).toBe(false);
  expect(rows[1]).toBeNull();
  rows[0].props.onPress();
  expect(fixture.setExpanded).toHaveBeenCalledOnce();
  const toggle = fixture.setExpanded.mock.calls[0]![0];
  expect(toggle(false)).toBe(true);
  expect(toggle(true)).toBe(false);
});

it("shows the agent's technical facts without another identity hero", () => {
  fixture.expanded = true;
  const rows = AgentTechnicalDetails().props.children[1].props.children;
  expect(rows.map((row: { props: { label: string; value: string } }) => [
    row.props.label, row.props.value,
  ])).toEqual([
    ["Agent state", "not authenticated"],
    ["Activity", "idle"],
    ["Started", "not available"],
    ["Services", "1"],
  ]);
});
