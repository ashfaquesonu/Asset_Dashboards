const fmt = (n) => Number(n).toLocaleString("en-US");
const pct = (n) => n.toFixed(1) + "%";

const CARDS = [
  { key: "total",     label: "Total Deals",          color: "" },
  { key: "qualified", label: "Qualified",             color: "" },
  { key: "junk",      label: "Not Qualified / Spam",  color: "red" },
  { key: "rsvp",      label: "RSVP",                  color: "" },
  { key: "hot",       label: "Hot Pipeline",           color: "amber" },
  { key: "meetings",  label: "Meetings",              color: "" },
  { key: "won",       label: "Deal Won",              color: "green" },
];

export default function KPICards({ data }) {
  const totals = {};
  for (const c of CARDS) {
    totals[c.key] = data.reduce((sum, r) => sum + r[c.key], 0);
  }
  const t = totals.total || 1;

  return (
    <section className="kpis">
      {CARDS.map((c) => (
        <div className={`kpi ${c.color}`} key={c.key}>
          <div className="value">{fmt(totals[c.key])}</div>
          <div className="label">{c.label}</div>
          {c.key !== "total" && (
            <div className="sub">{pct((totals[c.key] / t) * 100)} of total</div>
          )}
        </div>
      ))}
    </section>
  );
}
