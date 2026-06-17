import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ensureFreshToken } from "@/lib/token-refresh";
import {
  getConnection,
  isTokenExpiringSoon,
  updateTokens,
} from "@/lib/connection";
import { startHostedLogin } from "@/lib/pkce";

vi.mock("@/lib/connection", () => ({
  getConnection: vi.fn(),
  isTokenExpiringSoon: vi.fn(),
  updateTokens: vi.fn(),
}));
vi.mock("@/lib/pkce", () => ({ startHostedLogin: vi.fn() }));

const getConnectionMock = vi.mocked(getConnection);
const isTokenExpiringSoonMock = vi.mocked(isTokenExpiringSoon);
const updateTokensMock = vi.mocked(updateTokens);
const startHostedLoginMock = vi.mocked(startHostedLogin);

const conn = {
  url: "https://box.example",
  accessToken: "access",
  refreshToken: "refresh",
  expiresAt: 0,
};

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  getConnectionMock.mockReturnValue(conn);
  isTokenExpiringSoonMock.mockReturnValue(true);
  startHostedLoginMock.mockResolvedValue();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("ensureFreshToken", () => {
  it("returns ok without refreshing while the token is still fresh", async () => {
    isTokenExpiringSoonMock.mockReturnValue(false);
    expect(await ensureFreshToken()).toBe("ok");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("stores the rotated tokens and returns ok on a successful refresh", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "a2",
          refresh_token: "r2",
          expires_in: 3600,
        }),
      ),
    );
    expect(await ensureFreshToken()).toBe("ok");
    expect(updateTokensMock).toHaveBeenCalledWith("a2", "r2", 3600);
  });

  it("returns expired when vestad rejects the refresh token (401)", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 401 }));
    expect(await ensureFreshToken()).toBe("expired");
    expect(updateTokensMock).not.toHaveBeenCalled();
  });

  it("returns transient on a server error so callers keep retrying", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 502 }));
    expect(await ensureFreshToken()).toBe("transient");
  });

  it("returns transient on a network failure so callers keep retrying", async () => {
    fetchMock.mockRejectedValue(new TypeError("network down"));
    expect(await ensureFreshToken()).toBe("transient");
  });

  it("bounces hosted connections through the PKCE flow as transient", async () => {
    getConnectionMock.mockReturnValue({ ...conn, hosted: true });
    expect(await ensureFreshToken()).toBe("transient");
    expect(startHostedLoginMock).toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
