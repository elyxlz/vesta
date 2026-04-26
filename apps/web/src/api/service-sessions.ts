import { apiJson } from "./client";

export interface ServiceSession {
  sessionId: string;
  url: string;
  expiresIn: number;
}

interface ServiceSessionResponse {
  session_id: string;
  url: string;
  expires_in: number;
}

export async function createServiceSession(
  agent: string,
  service: string,
): Promise<ServiceSession> {
  const resp = await apiJson<ServiceSessionResponse>(
    `/agents/${encodeURIComponent(agent)}/services/${encodeURIComponent(service)}/session`,
    { method: "POST" },
  );
  return {
    sessionId: resp.session_id,
    url: resp.url,
    expiresIn: resp.expires_in,
  };
}
