const API_BASE = "http://localhost:8000";

const questionInput = document.getElementById("question");
const submitBtn = document.getElementById("submit");
const thinking = document.getElementById("thinking");
const answerBox = document.getElementById("answer");
const messageUserBox = document.getElementById("message-user");
const suggestionsBox = document.getElementById("suggestions");
const closestMatches = document.getElementById("closest-matches");
const closestMatchesContent = document.getElementById("closest-matches-content");
const citationsBox = document.getElementById("citations");
const statusBar = document.getElementById("status-bar");
const evidenceBox = document.getElementById("evidence-pack");
const advancedTools = document.getElementById("advanced-tools");
const advancedInventory = document.getElementById("kb-inventory");
const advancedRetrieval = document.getElementById("retrieval-debug");
const kbInventoryToggle = document.getElementById("toggle-kb-inventory");
const retrievalDebugToggle = document.getElementById("toggle-retrieval-debug");
const kbInventoryContent = document.getElementById("kb-inventory-content");
const retrievalDebugContent = document.getElementById("retrieval-debug-content");
const retrievalSummary = document.getElementById("retrieval-summary");
let latestStatus = null;
let latestRetrievalDebug = null;

const filters = {
  primaryOnly: document.getElementById("primary-only"),
  includeGuidance: document.getElementById("include-guidance"),
  includeDebates: document.getElementById("include-debates"),
  showEvidence: document.getElementById("show-evidence"),
};

const envConfig = window.APP_CONFIG || window.ENV || window.__ENV__ || {};
const nodeEnv =
  envConfig.NODE_ENV ||
  envConfig.mode ||
  envConfig.environment ||
  (typeof process !== "undefined" && process.env ? process.env.NODE_ENV : undefined);
const showDevToolsFlag =
  envConfig.VITE_SHOW_DEV_TOOLS ||
  envConfig.SHOW_DEV_TOOLS ||
  envConfig.showDevTools ||
  (typeof process !== "undefined" && process.env ? process.env.VITE_SHOW_DEV_TOOLS : undefined) ||
  window.VITE_SHOW_DEV_TOOLS ||
  window.SHOW_DEV_TOOLS;
const isDevHost = ["localhost", "127.0.0.1"].includes(window.location.hostname);
const devToolsEnabled =
  (nodeEnv ? nodeEnv !== "production" : isDevHost) ||
  (typeof showDevToolsFlag === "string" ? showDevToolsFlag.toLowerCase() === "true" : Boolean(showDevToolsFlag));

function renderStatus(status) {
  latestStatus = status || null;
  if (!status) {
    statusBar.textContent = devToolsEnabled
      ? "KB status hidden. Enable \"Show KB inventory\" in Advanced / Developer tools to load it."
      : "Status not available.";
    if (advancedInventory) {
      advancedInventory.classList.add("hidden");
    }
    return;
  }
  const refreshed = status.last_refreshed ? new Date(status.last_refreshed).toLocaleString() : "n/a";
  statusBar.innerHTML = `KB refreshed: <strong>${refreshed}</strong><br/>Chunks: ${status.total_chunks}`;
  renderInventory(status);
}

function excerptText(text, maxWords = 50) {
  if (!text) return "";
  const words = text.split(/\s+/);
  if (words.length <= maxWords) return text;
  return `${words.slice(0, maxWords).join(" ")}...`;
}

function renderAnswer(answer, status, messageUser, assessment) {
  if (!answer) {
    answerBox.innerHTML = "";
    return;
  }
  const lock = `<div class="section-lock">Section lock: ${answer.section_lock || "off"}</div>`;
  if (status === "insufficient_evidence" || answer.refused) {
    const refusalText = messageUser || answer.refusal_reason || answer.text;
    answerBox.innerHTML = `<div class="refusal">${refusalText}</div>${lock}`;
    return;
  }
  const confidenceLabel =
    (assessment && assessment.confidence_label) || (answer.confidence && answer.confidence.level) || "";
  const conf = confidenceLabel ? `<span class="confidence">Confidence: ${confidenceLabel}</span>` : "";
  answerBox.innerHTML = `<div>${answer.text} ${conf} ${lock}</div>`;
}

function renderCitations(citations) {
  citationsBox.innerHTML = "";
  citations.forEach((c) => {
    const card = document.createElement("div");
    card.className = "citation-card";
    const header = document.createElement("div");
    header.className = "citation-header";
    header.innerHTML = `<div><strong>${c.citation_id}</strong> ${c.title} <span class="badge">${c.source_type}</span></div><span>${c.location_pointer || ""}</span>`;
    const body = document.createElement("div");
    body.className = "citation-body hidden";
    body.innerHTML = `<p>${c.excerpt}</p><small>${c.publisher} • ${c.date_published || ""}</small>`;
    header.addEventListener("click", () => {
      body.classList.toggle("hidden");
    });
    card.appendChild(header);
    card.appendChild(body);
    citationsBox.appendChild(card);
  });
}

function renderSuggestions(message, suggestions) {
  if (!messageUserBox || !suggestionsBox) return;
  if (!message && (!suggestions || !suggestions.length)) {
    messageUserBox.classList.add("hidden");
    messageUserBox.textContent = "";
    suggestionsBox.classList.add("hidden");
    suggestionsBox.innerHTML = "";
    return;
  }
  messageUserBox.classList.remove("hidden");
  messageUserBox.textContent = message;
  if (suggestions && suggestions.length) {
    suggestionsBox.classList.remove("hidden");
    suggestionsBox.innerHTML = suggestions.map((s) => `<li>${s}</li>`).join("");
  } else {
    suggestionsBox.classList.add("hidden");
    suggestionsBox.innerHTML = "";
  }
}

function renderClosestMatches(matches, status) {
  if (!closestMatches || !closestMatchesContent) return;
  if (status !== "insufficient_evidence") {
    closestMatches.classList.add("hidden");
    closestMatchesContent.innerHTML = "";
    closestMatches.open = false;
    return;
  }
  if (!matches || !matches.length) {
    closestMatches.classList.remove("hidden");
    closestMatchesContent.innerHTML = '<div class="muted">No close matches were retrieved.</div>';
    closestMatches.open = false;
    return;
  }
  const cards = matches
    .map((m) => {
      const metaBits = [m.publisher, m.date_published].filter(Boolean).join(" • ");
      const location = m.location_pointer ? `<div class="meta">${m.location_pointer}</div>` : "";
      return `<div class="match-card">
        <div><strong>${m.title || "Untitled"}</strong> <span class="badge">${m.source_type || ""}</span></div>
        ${location}
        <div class="muted">${excerptText(m.chunk_text || "", 50)}</div>
        <div class="meta">${metaBits}</div>
      </div>`;
    })
    .join("");
  closestMatchesContent.innerHTML = cards;
  closestMatches.classList.remove("hidden");
  closestMatches.open = false;
}

function renderEvidence(evidence) {
  if (!filters.showEvidence.checked || !evidence) {
    evidenceBox.classList.add("hidden");
    evidenceBox.innerHTML = "";
    return;
  }
  evidenceBox.classList.remove("hidden");
  evidenceBox.innerHTML = "<strong>Evidence pack</strong>";
  const list = document.createElement("ul");
  evidence.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = `${item.title} (${item.location_pointer || ""})`;
    list.appendChild(li);
  });
  evidenceBox.appendChild(list);
}

function renderInventory(status) {
  if (!kbInventoryContent || !status || !devToolsEnabled || !kbInventoryToggle || !kbInventoryToggle.checked) {
    if (advancedInventory) {
      advancedInventory.classList.add("hidden");
    }
    if (kbInventoryContent) {
      kbInventoryContent.innerHTML = "";
    }
    return;
  }
  advancedInventory?.classList.remove("hidden");
  const total = status.total_chunks || 0;
  const counts = status.chunk_counts_by_type || {};
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const rows = entries
    .map(([type, count]) => {
      const pct = total ? ((count / total) * 100).toFixed(1) : "0.0";
      return `<tr><td>${type}</td><td>${count}</td><td>${pct}%</td></tr>`;
    })
    .join("");

  const guidanceCount = counts["Regulator Guidance"] || 0;
  const guidanceWarning =
    guidanceCount === 0
      ? `<div class="inventory-warning">No chunks tagged as Regulator Guidance are present. Either the guidance wasn’t ingested, or doc_type mapping doesn’t recognise it.</div>`
      : `<div class="inventory">Regulator Guidance chunks: ${guidanceCount}</div>`;

  const sources = status.guidance_source_counts || {};
  const topSources = Object.entries(sources)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10);
  const guidanceList = topSources.length
    ? `<div class="inventory"><strong>Top guidance sources</strong><ul>${topSources
        .map(([title, count]) => `<li>${title} — ${count}</li>`)
        .join("")}</ul></div>`
    : "";

  kbInventoryContent.innerHTML = `
    <div class="inventory">Total chunks: ${total}</div>
    ${
      rows
        ? `<table class="inventory-table"><thead><tr><th>Doc type</th><th>Chunks</th><th>%</th></tr></thead><tbody>${rows}</tbody></table>`
        : `<div class="inventory">No inventory data available.</div>`
    }
    ${guidanceWarning}
    ${guidanceList}
  `;
}

function renderRetrievalDebug(debugInfo) {
  if (!retrievalDebugContent || !retrievalSummary) return;
  if (!devToolsEnabled || !retrievalDebugToggle || !retrievalDebugToggle.checked) {
    retrievalSummary.textContent = "Retrieval debug is disabled.";
    retrievalDebugContent.innerHTML = "";
    if (advancedRetrieval) {
      advancedRetrieval.classList.add("hidden");
    }
    return;
  }

  advancedRetrieval?.classList.remove("hidden");
  if (!debugInfo || !debugInfo.results) {
    retrievalSummary.textContent = "Run a query to see retrieval details.";
    retrievalDebugContent.innerHTML = "";
    return;
  }

  latestRetrievalDebug = debugInfo;
  const filtersSummary = debugInfo.summary?.filters || {};
  const breakdown = debugInfo.summary?.doc_type_breakdown || {};
  const breakdownStr = Object.entries(breakdown)
    .sort((a, b) => b[1] - a[1])
    .map(([type, count]) => `${type}: ${count}`)
    .join(", ");
  const sectionLock = debugInfo.summary?.section_lock || "off";
  const mode = debugInfo.summary?.retrieval_mode ? ` • Mode: ${debugInfo.summary.retrieval_mode}` : "";
  retrievalSummary.innerHTML = `Filters applied: primary_only=${Boolean(filtersSummary.primary_only)}, include_guidance=${Boolean(
    filtersSummary.include_guidance
  )}, include_debates=${Boolean(filtersSummary.include_debates)}<br/>Section lock: ${sectionLock}${mode}<br/>Retrieved doc_type breakdown: ${
    breakdownStr || "n/a"
  }`;

  const rows = debugInfo.results
    .map((r) => {
      const score = r.relevance_score !== undefined ? Number(r.relevance_score).toFixed(3) : "n/a";
      const bm25 = r.bm25_score !== undefined ? Number(r.bm25_score).toFixed(3) : "n/a";
      const flags = (r.reason_flags || []).map((flag) => `<span class="pill">${flag}</span>`).join(" ");
      const section = r.section || r.location_pointer || "";
      return `<tr>
        <td>${r.rank}</td>
        <td><strong>${r.doc_id}</strong><div class="muted">${r.chunk_id || ""}</div></td>
        <td>${r.doc_type || ""}</td>
        <td>${r.title || ""}<div class="muted">${r.location_pointer || ""}</div></td>
        <td>${r.date || ""}</td>
        <td>${section}</td>
        <td>${score}<div class="muted">bm25 ${bm25}</div></td>
        <td>${flags}</td>
      </tr>`;
    })
    .join("");

  retrievalDebugContent.innerHTML = `
    <table>
      <thead>
        <tr><th>Rank</th><th>Doc</th><th>Type</th><th>Title</th><th>Date</th><th>Section</th><th>Score</th><th>Flags</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

async function submitQuery() {
  const question = questionInput.value.trim();
  if (!question) return;
  thinking.classList.remove("hidden");
  answerBox.innerHTML = "";
  citationsBox.innerHTML = "";
  renderSuggestions(null, null);
  renderClosestMatches([], null);
  renderEvidence(null);
  renderRetrievalDebug(null);

  const includeInventory = devToolsEnabled && kbInventoryToggle && kbInventoryToggle.checked;
  const includeRetrievalDebug = devToolsEnabled && retrievalDebugToggle && retrievalDebugToggle.checked;

  const payload = {
    question,
    filters: {
      primary_only: filters.primaryOnly.checked,
      include_guidance: filters.includeGuidance.checked,
      include_debates: filters.includeDebates.checked,
    },
    debug: {
      include_evidence_pack: filters.showEvidence.checked,
      include_kb_status: includeInventory,
      include_retrieval_debug: includeRetrievalDebug,
    },
  };

  try {
    const res = await fetch(`${API_BASE}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    const showGuidance = data.status === "insufficient_evidence";
    renderAnswer(data.answer, data.status, data.message_user, data.evidence_assessment);
    renderSuggestions(showGuidance ? data.message_user : null, showGuidance ? data.suggestions : null);
    renderClosestMatches(data.closest_matches, data.status);
    renderCitations(data.citations || []);
    renderEvidence(data.evidence_pack);
    if (includeInventory) {
      renderStatus(data.kb_status);
    } else {
      renderStatus(null);
    }
    if (includeRetrievalDebug) {
      renderRetrievalDebug(data.retrieval_debug);
    } else {
      latestRetrievalDebug = null;
      renderRetrievalDebug(null);
    }
  } catch (err) {
    answerBox.innerHTML = `<div class="refusal">Request failed. ${err}</div>`;
    renderSuggestions(null, null);
    renderClosestMatches([], null);
  } finally {
    thinking.classList.add("hidden");
  }
}

submitBtn.addEventListener("click", submitQuery);
questionInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitQuery();
});
filters.showEvidence.addEventListener("change", () => {
  if (filters.showEvidence.checked) {
    evidenceBox.classList.remove("hidden");
  } else {
    evidenceBox.classList.add("hidden");
  }
});

async function fetchStatus() {
  if (!devToolsEnabled || !kbInventoryToggle || !kbInventoryToggle.checked) return;
  try {
    const res = await fetch(`${API_BASE}/status`);
    const data = await res.json();
    renderStatus(data);
  } catch (err) {
    statusBar.textContent = "Status unavailable.";
  }
}

if (advancedTools) {
  if (devToolsEnabled) {
    advancedTools.open = false;
    advancedTools.classList.remove("hidden");
  } else {
    advancedTools.remove();
  }
}

if (kbInventoryToggle) {
  kbInventoryToggle.checked = false;
  kbInventoryToggle.addEventListener("change", () => {
    if (kbInventoryToggle.checked) {
      if (latestStatus) {
        renderInventory(latestStatus);
      } else {
        fetchStatus();
      }
    } else {
      renderInventory(null);
    }
  });
}

if (retrievalDebugToggle) {
  retrievalDebugToggle.checked = false;
  retrievalDebugToggle.addEventListener("change", () => {
    if (retrievalDebugToggle.checked) {
      renderRetrievalDebug(latestRetrievalDebug);
    } else {
      renderRetrievalDebug(null);
    }
  });
}

renderRetrievalDebug(null);
renderStatus(null);
