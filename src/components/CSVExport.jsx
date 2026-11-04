import { Download } from "lucide-react";

export default function CSVExport({ data, startDate, endDate, disabled }) {
  function download() {
    const headers = [
      "Project Name-Facebook",
      "Total Deals",
      "Qualified Count (P16)",
      "Not Qualified/Spam",
      "RSVP Count",
      "Hot Pipeline",
      "Meetings",
      "Deal Won",
    ];

    const esc = (v) => `"${String(v).replace(/"/g, '""')}"`;

    const lines = [headers.map(esc).join(",")];

    [...data]
      .sort((a, b) => b.total - a.total)
      .forEach((r) => {
        lines.push(
          [r.project, r.total, r.qualified, r.junk, r.rsvp, r.hot, r.meetings, r.won]
            .map(esc)
            .join(",")
        );
      });

    const blob = new Blob(["\uFEFF" + lines.join("\r\n")], {
      type: "text/csv;charset=utf-8",
    });

    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `Leads_Report_${startDate}_to_${endDate}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  }

  return (
    <button className="btn ghost" disabled={disabled} onClick={download}>
      <Download size={16} />
      Download CSV
    </button>
  );
}
