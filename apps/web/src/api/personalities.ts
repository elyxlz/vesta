import { apiJson } from "./client";

export interface Personality {
  name: string;
  emoji: string;
  title: string;
  description: string;
  order: number;
}

export async function fetchPersonalities(): Promise<Personality[]> {
  return apiJson<Personality[]>("/personalities");
}
