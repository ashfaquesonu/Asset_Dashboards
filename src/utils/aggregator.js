/**
 * Aggregates raw deal arrays into per-project statistics.
 * Mirrors the Python script's process_deals + master_data logic.
 */

/**
 * Resolves a deal's project name from its custom field value.
 */
function getProjectName(deal, fieldId, enumMapping) {
  const raw = deal[fieldId];
  if (!raw) return "No Project Assigned";
  const val = String(Array.isArray(raw) ? raw[0] : raw);
  return enumMapping[val] || `Unknown (${val})`;
}

/**
 * Merges two stage-category maps (Set-valued) from qualified + not-qualified pipelines.
 *
 * @param {Object} mapQ  - { meetings: Set, won: Set, junk: Set, rsvp: Set, hot: Set }
 * @param {Object} mapNQ - same shape
 * @returns {Object} combined lookup
 */
export function mergeStagesMaps(mapQ, mapNQ) {
  const lookup = {};
  for (const key of ["meetings", "won", "junk", "rsvp", "hot"]) {
    lookup[key] = new Set([...(mapQ[key] || []), ...(mapNQ[key] || [])]);
  }
  return lookup;
}

/**
 * Aggregates deals into rows grouped by project name.
 *
 * @param {Array}  dealsQ       - deals from the qualified pipeline
 * @param {Array}  dealsNQ      - deals from the not-qualified pipeline
 * @param {string} fieldId      - the custom field ID
 * @param {Object} enumMapping  - ID → label map
 * @param {Object} stageLookup  - { meetings: Set, won: Set, junk: Set, rsvp: Set, hot: Set }
 * @returns {{ rows: Array, totalDeals: number }}
 */
export function aggregateDeals(
  dealsQ,
  dealsNQ,
  fieldId,
  enumMapping,
  stageLookup
) {
  const master = {};

  function processDeal(deal, isQualified) {
    const name = getProjectName(deal, fieldId, enumMapping);
    const stage = deal.STAGE_ID;

    if (!master[name]) {
      master[name] = {
        project: name,
        total: 0,
        qualified: 0,
        junk: 0,
        rsvp: 0,
        hot: 0,
        meetings: 0,
        won: 0,
      };
    }

    const m = master[name];
    m.total += 1;

    if (isQualified) m.qualified += 1;
    if (stageLookup.meetings.has(stage)) m.meetings += 1;
    if (stageLookup.won.has(stage)) m.won += 1;
    if (stageLookup.junk.has(stage)) m.junk += 1;
    if (stageLookup.rsvp.has(stage)) m.rsvp += 1;
    if (stageLookup.hot.has(stage)) m.hot += 1;
  }

  for (const d of dealsQ) processDeal(d, true);
  for (const d of dealsNQ) processDeal(d, false);

  // Compute derived fields
  const rows = Object.values(master).map((r) => ({
    ...r,
    qpct: r.total > 0 ? (r.qualified / r.total) * 100 : 0,
  }));

  // Sort by total descending
  rows.sort((a, b) => b.total - a.total);

  const totalDeals = rows.reduce((sum, r) => sum + r.total, 0);

  return { rows, totalDeals };
}
