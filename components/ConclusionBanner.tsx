import { ScreeningLevel } from "@/lib/api";

const ICONS: Record<ScreeningLevel, string> = {
  hit: "🚨",
  suspected: "⚠️",
  low: "👀",
  clear: "✅",
  below_threshold: "✅",
  error: "❌",
  empty_query: "⚠️",
};

export default function ConclusionBanner({
  level,
  conclusion,
}: {
  level: ScreeningLevel;
  conclusion: string;
}) {
  return (
    <div className={`banner ${level}`} role="status">
      <span aria-hidden>{ICONS[level] ?? "ℹ️"}</span>{" "}
      {conclusion}
    </div>
  );
}
