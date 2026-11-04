import { useState, useMemo } from "react";
import { Search, ArrowUp, ArrowDown } from "lucide-react";

const fmt = (n) => Number(n).toLocaleString("en-US");
const pct = (n) => n.toFixed(1) + "%";

const COLS = [
  { key: "project",   label: "Project",              align: "left" },
  { key: "total",     label: "Total Deals",          align: "right" },
  { key: "qualified", label: "Qualified (P16)",      align: "right" },
  { key: "qpct",      label: "Qualified %",          align: "right" },
  { key: "junk",      label: "Not Qualified / Spam", align: "right" },
  { key: "rsvp",      label: "RSVP",                 align: "right" },
  { key: "hot",       label: "Hot Pipeline",         align: "right" },
  { key: "meetings",  label: "Meetings",             align: "right" },
  { key: "won",       label: "Deal Won",             align: "right" },
];

export default function DataTable({ data }) {
  const [sortKey, setSortKey] = useState("total");
  const [sortDir, setSortDir] = useState(-1);
  const [query, setQuery] = useState("");

  const rows = useMemo(() => {
    let filtered = data;
    if (query) {
      const q = query.toLowerCase();
      filtered = data.filter((r) => r.project.toLowerCase().includes(q));
    }
    return [...filtered].sort((a, b) => {
      const x = a[sortKey];
      const y = b[sortKey];
      const cmp = typeof x === "string" ? x.localeCompare(y) : x - y;
      return cmp * sortDir;
    });
  }, [data, sortKey, sortDir, query]);

  function handleSort(key) {
    if (sortKey === key) {
      setSortDir((d) => d * -1);
    } else {
      setSortKey(key);
      setSortDir(key === "project" ? 1 : -1);
    }
  }

  // Footer totals
  const sum = (k) => rows.reduce((a, r) => a + r[k], 0);
  const totalSum = sum("total");
  const qualSum = sum("qualified");

  function renderCell(row, col) {
    const val = row[col.key];
    switch (col.key) {
      case "project":
        return val;
      case "qpct":
        return pct(val);
      case "rsvp":
        return (
          <span className={`pill-cell ${val === 0 ? "zero" : ""}`}>
            {fmt(val)}
          </span>
        );
      case "hot":
        return <span className={val ? "cell-hot" : ""}>{fmt(val)}</span>;
      case "won":
        return <span className={val ? "cell-won" : ""}>{fmt(val)}</span>;
      default:
        return fmt(val);
    }
  }

  return (
    <section className="panel">
      <div className="table-tools">
        <h2>Status by Project</h2>
        <div className="search-wrap">
          <Search size={16} />
          <input
            className="search-input"
            type="search"
            placeholder="Search project name…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>

      <div className="scroll">
        <table>
          <thead>
            <tr>
              {COLS.map((col) => {
                const active = sortKey === col.key;
                return (
                  <th
                    key={col.key}
                    aria-sort={
                      active
                        ? sortDir === 1
                          ? "ascending"
                          : "descending"
                        : undefined
                    }
                    style={{ textAlign: col.align }}
                  >
                    <button onClick={() => handleSort(col.key)}>
                      {col.label}
                      {active &&
                        (sortDir === 1 ? (
                          <ArrowUp size={12} />
                        ) : (
                          <ArrowDown size={12} />
                        ))}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td className="empty-state" colSpan={COLS.length}>
                  No projects match your search.
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.project}>
                  {COLS.map((col) => (
                    <td key={col.key} style={{ textAlign: col.align }}>
                      {renderCell(row, col)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
          {rows.length > 0 && (
            <tfoot>
              <tr>
                <td>Total ({rows.length} projects)</td>
                <td style={{ textAlign: "right" }}>{fmt(totalSum)}</td>
                <td style={{ textAlign: "right" }}>{fmt(qualSum)}</td>
                <td style={{ textAlign: "right" }}>
                  {pct(totalSum ? (qualSum / totalSum) * 100 : 0)}
                </td>
                <td style={{ textAlign: "right" }}>{fmt(sum("junk"))}</td>
                <td style={{ textAlign: "right" }}>{fmt(sum("rsvp"))}</td>
                <td style={{ textAlign: "right" }}>{fmt(sum("hot"))}</td>
                <td style={{ textAlign: "right" }}>{fmt(sum("meetings"))}</td>
                <td style={{ textAlign: "right" }}>{fmt(sum("won"))}</td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </section>
  );
}
