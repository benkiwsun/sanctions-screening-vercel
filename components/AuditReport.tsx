"use client";

import { useRef, useState } from "react";
import { ScreeningLevel, ScreeningResult } from "@/lib/api";

const CONCLUSION_COLOR: Record<ScreeningLevel, string> = {
  hit: "#dc0000",
  suspected: "#ff8c00",
  low: "#cc9900",
  clear: "#16a34a",
  below_threshold: "#16a34a",
  error: "#cc9900",
  empty_query: "#cc9900",
};

const REPORT_COLUMNS: { key: keyof ScreeningResult["results"][number]; label: string }[] = [
  { key: "Score", label: "Score" },
  { key: "Name", label: "Name" },
  { key: "Aliases", label: "Aliases" },
  { key: "IMO", label: "IMO" },
  { key: "MMSI", label: "MMSI" },
  { key: "Source_Agency", label: "Source_Agency" },
  { key: "Programs", label: "Programs" },
  { key: "Country", label: "Country" },
];

function nowBeijing(): string {
  const fmt = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  return fmt.format(new Date()).replace(/\//g, "-");
}

function cell(value: string | number): string {
  const s = String(value ?? "").trim();
  return s === "" || s.toLowerCase() === "nan" || s.toLowerCase() === "none"
    ? "无"
    : s;
}

export default function AuditReport({
  result,
  buttonLabel,
}: {
  result: ScreeningResult;
  buttonLabel: string;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);
  const queryTime = nowBeijing();

  const isHit = result.results.length > 0;
  const color = CONCLUSION_COLOR[result.level] ?? "#16a34a";

  const handleDownload = async () => {
    if (!cardRef.current) return;
    setBusy(true);
    try {
      const html2canvas = (await import("html2canvas")).default;
      const canvas = await html2canvas(cardRef.current, {
        backgroundColor: "#fafafa",
        scale: 2,
        useCORS: true,
      });
      const dataUrl = canvas.toDataURL("image/jpeg", 0.95);
      const link = document.createElement("a");
      const prefix = isHit ? "筛查留痕" : "筛查放行";
      link.download = `${prefix}_${result.query}_检索报告.jpg`;
      link.href = dataUrl;
      link.click();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button className="btn-secondary" onClick={handleDownload} disabled={busy}>
        {busy ? "正在生成留痕图片…" : `📸 ${buttonLabel}`}
      </button>

      {/* Offscreen card captured by html2canvas */}
      <div className="report-offscreen" aria-hidden>
        <div className="report-card" ref={cardRef}>
          <h2>供应链制裁合规筛查 - 尽职调查留痕报告</h2>
          <div className="report-meta">查询时间: {queryTime} (GMT+8)</div>
          <div className="report-meta">筛查关键词: {result.query}</div>

          <div className="report-conclusion" style={{ color }}>
            {result.conclusion}
          </div>

          {isHit && (
            <table>
              <thead>
                <tr>
                  {REPORT_COLUMNS.map((c) => (
                    <th key={c.key}>{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.results.slice(0, 10).map((row, i) => (
                  <tr key={i}>
                    {REPORT_COLUMNS.map((c) => (
                      <td
                        key={c.key}
                        style={c.key === "Score" ? { color: "#c80000", fontWeight: 700 } : undefined}
                      >
                        {c.key === "Score"
                          ? Number(row.Score).toFixed(1)
                          : cell(row[c.key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="report-footer">
            <div style={{ fontWeight: 600, color: "#646464", marginBottom: 6 }}>
              Screening Against (筛查名单机构及数据量) — Local Sync Time:{" "}
              {result.sync_time} (GMT+8)
            </div>
            {Object.entries(result.source_counts).map(([agency, count]) => (
              <div key={agency}>
                • {agency || "Other Sources"}: {count.toLocaleString()} records
              </div>
            ))}
            <div className="total">
              Total Valid Records (全库总计实体数量):{" "}
              {result.total_records.toLocaleString()} Entities
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
