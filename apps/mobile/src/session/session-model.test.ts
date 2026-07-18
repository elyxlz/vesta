import { describe, expect, it } from "vitest";
import type { ConnectionConfig } from "@/api/types";
import { changesGateway } from "./session-model";

const connection: ConnectionConfig = {
  url: "https://gateway.example",
  accessToken: "access",
  refreshToken: "refresh",
  expiresAt: 1,
  hosted: false,
};

describe("gateway session identity", () => {
  it("keeps cached data when only credentials refresh", () => {
    expect(
      changesGateway(connection, {
        ...connection,
        accessToken: "next-access",
        refreshToken: "next-refresh",
      }),
    ).toBe(false);
  });

  it("invalidates cached data when the active gateway changes", () => {
    expect(changesGateway(null, connection)).toBe(true);
    expect(
      changesGateway(connection, {
        ...connection,
        url: "https://other-gateway.example",
      }),
    ).toBe(true);
    expect(changesGateway(connection, { ...connection, hosted: true })).toBe(
      true,
    );
  });
});
