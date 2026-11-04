import { useState, useCallback, useRef, useEffect } from "react";
import { fetchFieldInfo, fetchStages, fetchDeals } from "./api/bitrix";
import { mergeStagesMaps, aggregateDeals } from "./utils/aggregator";
import FilterBar from "./components/FilterBar";
import KPICards from "./components/KPICards";
import FunnelChart from "./components/FunnelChart";
import DataTable from "./components/DataTable";
import CSVExport from "./components/CSVExport";
import { RefreshCw, Printer } from "lucide-react";

const AUTO_REFRESH_MS = 10 * 60 * 1000; // 10 minutes

export default function App() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [statusType, setStatusType] = useState(""); // "" | "error"
  const [lastFetch, setLastFetch] = useState(null);
  const [dateRange, setDateRange] = useState({ start: "", end: "" });
  const [totalDeals, setTotalDeals] = useState(0);

  // Persist last filter config for auto-refresh
  const lastConfigRef = useRef(null);
  const timerRef = useRef(null);

  const showStatus = useCallback((msg, type = "") => {
    setStatus(msg);
    setStatusType(type);
  }, []);

  const handleFetch = useCallback(
    async (config) => {
      const {
        startDate,
        endDate,
        pipelineQ,
        pipelineNQ,
        fieldName,
        keywords,
      } = config;

      lastConfigRef.current = config;
      setLoading(true);
      showStatus("Discovering field configuration…");

      try {
        // Step 1: Find the custom field
        const { fieldId, enumMapping } = await fetchFieldInfo(fieldName);
        if (!fieldId) {
          throw new Error(
            `Field "${fieldName}" was not found in Bitrix24 deal fields.`
          );
        }

        // Step 2: Get stage maps for both pipelines
        showStatus("Loading pipeline stages…");
        const [stagesQ, stagesNQ] = await Promise.all([
          fetchStages(pipelineQ, keywords),
          fetchStages(pipelineNQ, keywords),
        ]);
        const stageLookup = mergeStagesMaps(stagesQ, stagesNQ);

        // Step 3: Fetch deals from both pipelines
        showStatus("Fetching qualified deals…");
        const dealsQ = await fetchDeals(
          pipelineQ,
          fieldId,
          startDate,
          endDate,
          (n) => showStatus(`Fetching qualified deals… ${n} loaded`)
        );

        showStatus("Fetching not-qualified deals…");
        const dealsNQ = await fetchDeals(
          pipelineNQ,
          fieldId,
          startDate,
          endDate,
          (n) => showStatus(`Fetching not-qualified deals… ${n} loaded`)
        );

        // Step 4: Aggregate
        showStatus("Processing data…");
        const result = aggregateDeals(
          dealsQ,
          dealsNQ,
          fieldId,
          enumMapping,
          stageLookup
        );

        setData(result.rows);
        setTotalDeals(result.totalDeals);
        setDateRange({ start: startDate, end: endDate });
        setLastFetch(new Date());

        if (result.rows.length > 0) {
          showStatus(
            `Done — ${result.totalDeals.toLocaleString()} deals across ${result.rows.length} projects.`
          );
        } else {
          showStatus("No deals found for these filters.");
        }

        // Schedule auto-refresh
        if (timerRef.current) clearInterval(timerRef.current);
        timerRef.current = setInterval(() => {
          if (lastConfigRef.current) {
            handleFetch(lastConfigRef.current);
          }
        }, AUTO_REFRESH_MS);
      } catch (err) {
        console.error(err);
        showStatus(err.message || "An error occurred.", "error");
      } finally {
        setLoading(false);
      }
    },
    [showStatus]
  );

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const niceDate = (s) => {
    if (!s) return "";
    const d = new Date(s + "T00:00:00");
    return d.toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  };

  return (
    <div className="wrap">
      {/* Header */}
      <header className="header">
        <div>
          <h1>Facebook Leads Dashboard</h1>
          <div className="meta">
            {lastFetch
              ? `Live from Bitrix24 • Last updated ${lastFetch.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} • Auto-refreshes every 10 min`
              : "Set your filters and click Fetch Data. Numbers come live from Bitrix24."}
          </div>
        </div>
        {dateRange.start && (
          <div className="period">
            {niceDate(dateRange.start)} — {niceDate(dateRange.end)}
          </div>
        )}
      </header>

      {/* Filters */}
      <FilterBar onFetch={handleFetch} loading={loading} />

      {/* Status bar */}
      {status && (
        <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 8 }}>
          {loading && <span className="spinner" />}
          <span className={`status ${statusType === "error" ? "error" : ""}`}>
            {status}
          </span>
        </div>
      )}

      {/* Results - only shown once data exists */}
      {data.length > 0 && (
        <>
          {/* Action bar */}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 10,
              marginBottom: 20,
              alignItems: "center",
            }}
          >
            <CSVExport
              data={data}
              startDate={dateRange.start}
              endDate={dateRange.end}
              disabled={loading || data.length === 0}
            />
            <button
              className="btn ghost"
              onClick={() => window.print()}
            >
              <Printer size={16} />
              Print / PDF
            </button>
            {lastConfigRef.current && (
              <button
                className="btn ghost"
                disabled={loading}
                onClick={() => handleFetch(lastConfigRef.current)}
              >
                <RefreshCw size={16} />
                Refresh Now
              </button>
            )}
          </div>

          {/* KPI Cards */}
          <KPICards data={data} />

          {/* Funnel */}
          <FunnelChart data={data} />

          {/* Table */}
          <DataTable data={data} />
        </>
      )}
    </div>
  );
}
