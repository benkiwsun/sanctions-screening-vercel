export type ScreeningLevel =
  | "hit"
  | "suspected"
  | "low"
  | "clear"
  | "below_threshold"
  | "error"
  | "empty_query";

export interface ScreeningRecord {
  Score: number;
  Name: string;
  Aliases: string;
  IMO: string;
  MMSI: string;
  Source_Agency: string;
  Programs: string;
  Country: string;
  Type: string;
  Details: string;
}

export interface ScreeningResult {
  query: string;
  threshold: number;
  level: ScreeningLevel;
  conclusion: string;
  max_score: number | null;
  hit_count: number;
  results: ScreeningRecord[];
  total_records: number;
  source_counts: Record<string, number>;
  sync_time: string;
}

export interface StatsResult {
  total_records: number;
  source_counts: Record<string, number>;
  sync_time: string;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function fetchStats(): Promise<StatsResult> {
  const res = await fetch("/api/stats", { method: "GET" });
  return handle<StatsResult>(res);
}

export async function runScreening(
  query: string,
  threshold: number
): Promise<ScreeningResult> {
  const res = await fetch("/api/screen", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, threshold }),
  });
  return handle<ScreeningResult>(res);
}
