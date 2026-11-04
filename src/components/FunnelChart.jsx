const fmt = (n) => Number(n).toLocaleString("en-US");
const pct = (n) => n.toFixed(1) + "%";

const STEPS = [
  { key: "total",     label: "Total Deals" },
  { key: "qualified", label: "Qualified" },
  { key: "meetings",  label: "Meetings" },
  { key: "won",       label: "Deal Won" },
];

export default function FunnelChart({ data }) {
  const sums = {};
  for (const s of STEPS) {
    sums[s.key] = data.reduce((sum, r) => sum + r[s.key], 0);
  }
  const max = sums.total || 1;

  return (
    <section className="panel">
      <h2>Lead Funnel</h2>
      {STEPS.map((s) => {
        const width = Math.max((sums[s.key] / max) * 100, sums[s.key] > 0 ? 0.8 : 0);
        return (
          <div className="funnel-row" key={s.key}>
            <span>{s.label}</span>
            <div className="bar-bg">
              <div className="bar-fill" style={{ width: `${width}%` }} />
            </div>
            <span className="stat">
              {fmt(sums[s.key])}{" "}
              <small>{pct((sums[s.key] / max) * 100)}</small>
            </span>
          </div>
        );
      })}
    </section>
  );
}
