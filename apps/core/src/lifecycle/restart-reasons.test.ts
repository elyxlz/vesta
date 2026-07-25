import { describe, expect, it } from "vitest"

import vestadTokens from "../../fixtures/restart-reason-tokens.json"
import { RESTART_REASONS, restartBody } from "./restart-reasons"

// The fixture is produced from vestad's own token table (vestad/src/lifecycle.rs, CLIENT_TOKENS,
// via REGEN_API_FIXTURES=1). Tokens are the whole contract now that vestad owns the copy, so a
// token this side sends that vestad cannot resolve would silently downgrade the agent's greeting
// to the generic manual reason. Pinning them here makes that drift a failing test instead.
describe("restart reason tokens (vestad fixture)", () => {
  it("sends exactly the tokens vestad resolves", () => {
    expect([...Object.values(RESTART_REASONS)].sort()).toEqual([...vestadTokens].sort())
  })

  it("names the transition and leaves the copy to vestad", () => {
    expect(restartBody(RESTART_REASONS.model)).toEqual({
      reason_token: "provider.model",
    })
  })
})
