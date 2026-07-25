import { describe, expect, it } from "vitest"
import { RESTART_REASONS, restartBody } from "./restart-reasons"

describe("restartBody", () => {
  it("puts operational copy under the legacy wire name and agent copy beside it", () => {
    expect(restartBody(RESTART_REASONS.model)).toEqual({
      reason: "provider: model changed",
      agent_message: "Your configured model changed.",
    })
  })

  it("gives every canonical reason a 'category: detail' log reason and a full sentence", () => {
    for (const reason of Object.values(RESTART_REASONS)) {
      expect(reason.logReason).toMatch(/^[a-z]+: .+/)
      expect(reason.agentMessage).toMatch(/\.$/)
    }
  })
})
