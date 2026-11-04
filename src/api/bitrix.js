/**
 * Bitrix24 REST API client.
 * Calls the webhook endpoints directly from the browser.
 */

const WEBHOOK_URL =
  "https://assethomezinternational.bitrix24.com/rest/1886/l4e7h7ol4uoqdb8b/";

/**
 * Generic Bitrix24 API call with retry on rate-limit.
 */
async function callBitrix(method, payload = {}) {
  for (let attempt = 0; attempt < 5; attempt++) {
    const res = await fetch(WEBHOOK_URL + method, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();

    // Rate limited — back off and retry
    if (data.error === "QUERY_LIMIT_EXCEEDED" || res.status === 429) {
      await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
      continue;
    }

    if (data.error) {
      throw new Error(`${data.error}: ${data.error_description || ""}`);
    }

    return data;
  }
  throw new Error("Bitrix24 rate limit reached. Try again in a minute.");
}

/**
 * Finds the custom field ID and its enum mapping by searching deal fields
 * for a label that contains `fieldName`.
 *
 * @returns {{ fieldId: string|null, enumMapping: Record<string, string> }}
 */
export async function fetchFieldInfo(fieldName = "Project Name-Facebook") {
  const data = await callBitrix("crm.deal.fields");
  const fields = data.result || {};

  for (const [fieldId, info] of Object.entries(fields)) {
    let label = info.formLabel || info.title;
    if (label && typeof label === "object") {
      label = Object.values(label)[0] || "";
    }
    if (label && String(label).toLowerCase().includes(fieldName.toLowerCase())) {
      const mapping = {};
      if (info.type === "enumeration") {
        for (const item of info.items || []) {
          mapping[String(item.ID)] = item.VALUE;
        }
      }
      return { fieldId, enumMapping: mapping };
    }
  }

  return { fieldId: null, enumMapping: {} };
}

/**
 * Fetches stages for a pipeline and categorises them by keyword sets.
 *
 * @returns {{ meetings: Set, won: Set, junk: Set, rsvp: Set, hot: Set }}
 */
export async function fetchStages(pipelineId, keywords) {
  const data = await callBitrix("crm.dealcategory.stage.list", {
    id: pipelineId,
  });
  const stages = data.result || [];

  const cats = {
    meetings: new Set(),
    won: new Set(),
    junk: new Set(),
    rsvp: new Set(),
    hot: new Set(),
  };

  for (const stage of stages) {
    const name = stage.NAME.toUpperCase();
    const id = stage.STATUS_ID;

    for (const [cat, kws] of Object.entries(keywords)) {
      if (kws.some((kw) => name.includes(kw.toUpperCase()))) {
        cats[cat].add(id);
      }
    }
  }

  return cats;
}

/**
 * Fetches all deals from a pipeline within a date range.
 * Handles Bitrix24 pagination (50 per batch).
 *
 * @param {number} pipelineId
 * @param {string} fieldId  - the custom field to select
 * @param {string} startDate - ISO date string
 * @param {string} endDate   - ISO date string
 * @param {function} onProgress - optional callback(fetchedSoFar)
 * @returns {Array} raw deal objects
 */
export async function fetchDeals(
  pipelineId,
  fieldId,
  startDate,
  endDate,
  onProgress
) {
  const allDeals = [];
  let nextBatch = 0;
  let hasMore = true;

  while (hasMore) {
    const data = await callBitrix("crm.deal.list", {
      filter: {
        CATEGORY_ID: pipelineId,
        ">=DATE_CREATE": startDate + "T00:00:00",
        "<=DATE_CREATE": endDate + "T23:59:59",
      },
      select: ["ID", "STAGE_ID", fieldId],
      start: nextBatch,
    });

    const deals = data.result || [];
    allDeals.push(...deals);

    if (onProgress) onProgress(allDeals.length);

    if (data.next !== undefined) {
      nextBatch = data.next;
      // Small delay to avoid hitting rate limits
      await new Promise((r) => setTimeout(r, 100));
    } else {
      hasMore = false;
    }
  }

  return allDeals;
}
