import { describe, expect, it } from "vitest";
import type { ConnectionConfig } from "@/api/types";
import { changesGateway, connectionKeyOf } from "./session-model";

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

describe("connectionKeyOf (controller rebuild key)", () => {
  it("is stable when only the tokens rotate, so the controller is reused", () => {
    expect(
      connectionKeyOf({
        ...connection,
        accessToken: "next-access",
        refreshToken: "next-refresh",
        expiresAt: 999,
      }),
    ).toBe(connectionKeyOf(connection));
  });

  it("changes when the gateway switches, so the controller rebuilds", () => {
    expect(
      connectionKeyOf({ ...connection, url: "https://other.example" }),
    ).not.toBe(connectionKeyOf(connection));
    expect(connectionKeyOf({ ...connection, hosted: true })).not.toBe(
      connectionKeyOf(connection),
    );
  });

  it("is null without a connection", () => {
    expect(connectionKeyOf(null)).toBeNull();
  });
});
