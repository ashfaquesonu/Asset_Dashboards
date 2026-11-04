import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

const PRESETS = [
  { key: "this_month", label: "This Month" },
  { key: "last_month", label: "Last Month" },
  { key: "last_30", label: "Last 30 Days" },
  { key: "ytd", label: "Year to Date" },
  { key: "custom", label: "Custom" },
];

function pad(n) {
  return String(n).padStart(2, "0");
}
function ymd(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function rangeFor(preset) {
  const t = new Date();
  const y = t.getFullYear();
  const m = t.getMonth();
  switch (preset) {
    case "this_month":
      return [ymd(new Date(y, m, 1)), ymd(t)];
    case "last_month":
      return [ymd(new Date(y, m - 1, 1)), ymd(new Date(y, m, 0))];
    case "last_30": {
      const s = new Date(t);
      s.setDate(s.getDate() - 29);
      return [ymd(s), ymd(t)];
    }
    case "ytd":
      return [ymd(new Date(y, 0, 1)), ymd(t)];
    default:
      return [null, null];
  }
}

const DEFAULT_KEYWORDS = {
  meetings: "First Meeting, 2nd SV/F2F, 3rd SV/F2F, ONLINE - MEETINGS",
  won: "Deal Won, Commission Claimed",
  junk: "Spam, Not Qualified, Junk, Unqualified, Real Estate Agent",
  rsvp: "RSVP",
  hot: "HOT PIPELINE",
};

export default function FilterBar({ onFetch, loading }) {
  const [preset, setPreset] = useState("ytd");
  const [startDate, setStartDate] = useState(() => ymd(new Date(new Date().getFullYear(), 0, 1)));
  const [endDate, setEndDate] = useState(() => ymd(new Date()));
  const [pipelineQ, setPipelineQ] = useState(16);
  const [pipelineNQ, setPipelineNQ] = useState(14);
  const [fieldName, setFieldName] = useState("Project Name-Facebook");
  const [keywords, setKeywords] = useState(DEFAULT_KEYWORDS);
  const [showAdvanced, setShowAdvanced] = useState(false);

  function handlePreset(key) {
    setPreset(key);
    if (key !== "custom") {
      const [s, e] = rangeFor(key);
      setStartDate(s);
      setEndDate(e);
      triggerFetch(s, e);
    }
  }

  function triggerFetch(s = startDate, e = endDate) {
    if (!s || !e) return;
    const kw = {};
    for (const [k, v] of Object.entries(keywords)) {
      kw[k] = v
        .split(",")
        .map((w) => w.trim())
        .filter(Boolean);
    }
    onFetch({
      startDate: s,
      endDate: e,
      pipelineQ: Number(pipelineQ),
      pipelineNQ: Number(pipelineNQ),
      fieldName,
      keywords: kw,
    });
  }

  function handleKeywordChange(key, value) {
    setKeywords((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <section className="panel">
      <h2>Filters</h2>

      {/* Preset pills */}
      <div className="presets" style={{ marginBottom: 14 }}>
        {PRESETS.map((p) => (
          <button
            key={p.key}
            className={`preset-btn ${preset === p.key ? "active" : ""}`}
            onClick={() => handlePreset(p.key)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Date range */}
      <div className="filter-bar">
        <div className="filter-group">
          <label>From</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => {
              setStartDate(e.target.value);
              setPreset("custom");
            }}
          />
        </div>
        <div className="filter-group">
          <label>To</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => {
              setEndDate(e.target.value);
              setPreset("custom");
            }}
          />
        </div>
        <div className="filter-group">
          <label>Qualified Pipeline</label>
          <input
            type="number"
            value={pipelineQ}
            onChange={(e) => setPipelineQ(e.target.value)}
            style={{ width: 90 }}
          />
        </div>
        <div className="filter-group">
          <label>Not Qualified Pipeline</label>
          <input
            type="number"
            value={pipelineNQ}
            onChange={(e) => setPipelineNQ(e.target.value)}
            style={{ width: 90 }}
          />
        </div>
      </div>

      {/* Advanced section */}
      <div
        className="advanced-toggle"
        onClick={() => setShowAdvanced(!showAdvanced)}
      >
        {showAdvanced ? <ChevronDown size={14} style={{ verticalAlign: "middle" }} /> : <ChevronRight size={14} style={{ verticalAlign: "middle" }} />}
        {" "}Advanced: custom field and stage keywords
      </div>

      {showAdvanced && (
        <div className="advanced-grid">
          <div className="wide">
            <div className="filter-group">
              <label>Custom Field Name</label>
              <input
                type="text"
                value={fieldName}
                onChange={(e) => setFieldName(e.target.value)}
              />
            </div>
          </div>
          {[
            { key: "meetings", label: "Meeting Stages" },
            { key: "won", label: "Won Stages" },
            { key: "junk", label: "Junk Stages" },
            { key: "rsvp", label: "RSVP Stages" },
            { key: "hot", label: "Hot Pipeline Stages" },
          ].map(({ key, label }) => (
            <div className="filter-group" key={key}>
              <label>{label} (comma separated)</label>
              <textarea
                rows={2}
                value={keywords[key]}
                onChange={(e) => handleKeywordChange(key, e.target.value)}
              />
            </div>
          ))}
        </div>
      )}

      {/* Action buttons */}
      <div className="actions-row">
        <button
          className="btn"
          disabled={loading}
          onClick={() => triggerFetch()}
        >
          {loading && <span className="spinner" />}
          {loading ? "Fetching…" : "Fetch Data"}
        </button>
      </div>
    </section>
  );
}
