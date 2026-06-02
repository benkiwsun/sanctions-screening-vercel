"use client";

export default function ScreeningForm({
  query,
  setQuery,
  threshold,
  setThreshold,
  onSubmit,
  loading,
}: {
  query: string;
  setQuery: (v: string) => void;
  threshold: number;
  setThreshold: (v: number) => void;
  onSubmit: () => void;
  loading: boolean;
}) {
  return (
    <div className="form-card">
      <div className="field">
        <label htmlFor="query">请输入交易对手名称 (支持模糊匹配)：</label>
        <input
          id="query"
          className="text-input"
          type="text"
          value={query}
          placeholder="例如输入公司英文名、中文简称或船舶 IMO 编号"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !loading) onSubmit();
          }}
        />
      </div>

      <div className="field">
        <label htmlFor="threshold">相似度容忍度 (%)</label>
        <div className="slider-row">
          <input
            id="threshold"
            type="range"
            min={60}
            max={100}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
          />
          <span className="slider-value">{threshold}%</span>
        </div>
        <div className="help">
          设置 90% 表示允许极轻微的拼写错误。设置 100% 则必须精确匹配。中文搜索已支持自动包含匹配，无需特意调低此值。
        </div>
      </div>

      <button className="btn-primary" onClick={onSubmit} disabled={loading}>
        {loading ? "正在执行智能检索…" : "开始筛查"}
      </button>
    </div>
  );
}
