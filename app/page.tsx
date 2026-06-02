"use client";

import { useEffect, useState } from "react";
import {
  fetchStats,
  runScreening,
  ScreeningLevel,
  ScreeningResult,
  StatsResult,
} from "@/lib/api";
import ScreeningForm from "@/components/ScreeningForm";
import ConclusionBanner from "@/components/ConclusionBanner";
import ResultsTable from "@/components/ResultsTable";
import AuditReport from "@/components/AuditReport";

const REPORT_LABELS: Record<ScreeningLevel, string> = {
  hit: "下载 JPG 留痕报告 (命中限制交易)",
  suspected: "下载 JPG 留痕报告 (需进一步排查)",
  low: "下载 JPG 留痕报告 (低度相关需检查)",
  clear: "下载 JPG 留痕报告 (建议放行)",
  below_threshold: "下载 JPG 留痕报告 (建议放行)",
  error: "下载 JPG 留痕报告",
  empty_query: "下载 JPG 留痕报告",
};

export default function Home() {
  const [query, setQuery] = useState("");
  const [threshold, setThreshold] = useState(90);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScreeningResult | null>(null);

  const [stats, setStats] = useState<StatsResult | null>(null);

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  const handleScreen = async () => {
    setError(null);
    if (!query.trim()) {
      setResult(null);
      setError("请输入筛查关键词。");
      return;
    }
    setLoading(true);
    try {
      const r = await runScreening(query.trim(), threshold);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "筛查请求失败，请稍后重试。");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const dbCaption = stats
    ? Object.entries(stats.source_counts)
        .map(([k, v]) => `${k}: ${v.toLocaleString()}条`)
        .join(" | ")
    : null;

  const hasResults = !!result && result.results.length > 0;

  return (
    <main className="container">
      <h1 className="app-title">🔍 全球制裁合规筛查系统</h1>

      {dbCaption ? (
        <p className="db-caption">🟢 当前已加载数据库: {dbCaption}</p>
      ) : (
        <p className="db-caption loading">⏳ 正在加载并合并全球及中国制裁数据库…</p>
      )}

      <ScreeningForm
        query={query}
        setQuery={setQuery}
        threshold={threshold}
        setThreshold={setThreshold}
        onSubmit={handleScreen}
        loading={loading}
      />

      {error && <p className="error-text">❌ {error}</p>}

      {result && result.level !== "error" && result.level !== "empty_query" && (
        <section>
          <ConclusionBanner level={result.level} conclusion={result.conclusion} />

          {hasResults && <ResultsTable results={result.results} />}

          <div className="actions">
            <AuditReport result={result} buttonLabel={REPORT_LABELS[result.level]} />
          </div>

          {hasResults && (
            <details className="expander">
              <summary>查看更多信息（Details）</summary>
              <div className="table-wrap" style={{ border: "none", boxShadow: "none" }}>
                <table className="results">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>IMO</th>
                      <th>MMSI</th>
                      <th>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.results.map((row, i) => (
                      <tr key={i}>
                        <td className="wrap">{row.Name || "无"}</td>
                        <td>{row.IMO || "无"}</td>
                        <td>{row.MMSI || "无"}</td>
                        <td className="wrap">{row.Details || "无"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </section>
      )}
    </main>
  );
}
