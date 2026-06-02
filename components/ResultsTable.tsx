import { ScreeningRecord } from "@/lib/api";

const COLUMNS: { key: keyof ScreeningRecord; label: string; wrap?: boolean }[] = [
  { key: "Score", label: "Score" },
  { key: "Name", label: "Name", wrap: true },
  { key: "Aliases", label: "Aliases", wrap: true },
  { key: "IMO", label: "IMO" },
  { key: "MMSI", label: "MMSI" },
  { key: "Source_Agency", label: "Source_Agency", wrap: true },
  { key: "Programs", label: "Programs", wrap: true },
  { key: "Country", label: "Country" },
];

function display(value: string | number): string {
  const s = String(value ?? "");
  return s === "" ? "无" : s;
}

export default function ResultsTable({ results }: { results: ScreeningRecord[] }) {
  return (
    <div className="table-wrap">
      <table className="results">
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th key={c.key}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {results.map((row, i) => (
            <tr key={i}>
              {COLUMNS.map((c) => {
                if (c.key === "Score") {
                  return (
                    <td key={c.key} className="score">
                      {Number(row.Score).toFixed(1)}
                    </td>
                  );
                }
                return (
                  <td key={c.key} className={c.wrap ? "wrap" : undefined}>
                    {display(row[c.key])}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
