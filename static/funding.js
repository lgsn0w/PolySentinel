let fundingAddress = "";
let fundingReport = null;
let fundingRequest = null;
let fundingRequestId = 0;
let fundingTimer = null;
let evidenceLimit = 100;
const uiText =
  typeof window.translateUI === "function"
    ? window.translateUI
    : (value) => String(value);

function validAddress(value) {
  return /^0x[0-9a-fA-F]{40}$/.test(String(value));
}

function fundingText(tag, value, className = "") {
  const element = document.createElement(tag);
  element.textContent = uiText(value);
  element.className = className;
  return element;
}

function addressLink(value) {
  if (!validAddress(value)) return fundingText("span", "Unknown address");
  const link = fundingText(
    "a",
    `${value.slice(0, 8)}…${value.slice(-6)}`,
    "wallet-link",
  );
  link.href = `https://polygonscan.com/address/${value}`;
  link.title = value;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function transactionLink(value) {
  if (!/^0x[0-9a-fA-F]{64}$/.test(String(value)))
    return fundingText("span", "Invalid transaction");
  const link = fundingText("a", `${value.slice(0, 10)}…`, "wallet-link");
  link.href = `https://polygonscan.com/tx/${value}`;
  link.title = value;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function fundingDate(value) {
  const date = new Date(Number(value) * 1000);
  return value && Number.isFinite(date.getTime())
    ? date.toLocaleString(window.uiLocale)
    : uiText("Not available");
}

function fundingTable(headers, rows) {
  const table = document.createElement("table");
  table.className = "funding-table";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  headers.forEach((value) => headRow.appendChild(fundingText("th", value)));
  head.appendChild(headRow);
  const body = document.createElement("tbody");
  rows.forEach((values) => {
    const row = document.createElement("tr");
    values.forEach((value) => {
      const cell = document.createElement("td");
      if (value && typeof value === "object") cell.appendChild(value);
      else cell.textContent = uiText(value);
      row.appendChild(cell);
    });
    body.appendChild(row);
  });
  table.append(head, body);
  return table;
}

function renderEvidence() {
  const direction = document.getElementById("funding-direction").value || "all";
  const contract = document.getElementById("funding-asset").value || "all";
  const category = document.getElementById("funding-category").value || "all";
  const edges = (fundingReport?.edges || []).filter((edge) => {
    if (
      category !== "all" &&
      (edge.classification?.category || "unknown") !== category
    )
      return false;
    if (contract !== "all" && (edge.contract || "native") !== contract)
      return false;
    if (direction === "incoming")
      return edge.receiver === fundingAddress && edge.sender !== fundingAddress;
    if (direction === "outgoing")
      return edge.sender === fundingAddress && edge.receiver !== fundingAddress;
    if (direction === "upstream") return edge.depth > 0;
    return true;
  });
  const table = fundingTable(
    [
      "Time",
      "Hop",
      "From → To",
      "Token units",
      "Asset contract",
      "Classification",
      "Evidence",
    ],
    edges.slice(0, evidenceLimit).map((edge) => {
      const path = document.createElement("span");
      path.append(addressLink(edge.sender), " → ", addressLink(edge.receiver));
      const asset = document.createElement("span");
      asset.append(fundingText("div", edge.asset || "Unknown token"));
      if (edge.contract) asset.appendChild(addressLink(edge.contract));
      else
        asset.appendChild(
          fundingText("small", "Native POL; not necessarily trading capital"),
        );
      const evidence = document.createElement("span");
      evidence.append(
        transactionLink(edge.hash),
        fundingText("small", edge.kind),
      );
      if (edge.identity_ambiguous || edge.ambiguous_identity)
        evidence.appendChild(fundingText("small", "Event identity incomplete"));
      evidence.appendChild(
        fundingText(
          "small",
          `Observed: ${fundingDate(edge.observed_at)}${edge.retained_from_previous ? " · retained from a previous lookup" : ""}`,
        ),
      );
      if (Number.isInteger(edge.log_index))
        evidence.appendChild(
          fundingText("small", `Receipt log #${edge.log_index}`),
        );
      const classification = document.createElement("span");
      classification.append(
        fundingText("div", classificationLabel(edge.classification?.category)),
        fundingText(
          "small",
          edge.classification?.reason || "Receipt not classified",
        ),
      );
      if (edge.receipt_stale)
        classification.appendChild(
          fundingText(
            "small",
            "Cached receipt is older than one hour; refresh before relying on it.",
          ),
        );
      return [
        fundingDate(edge.timestamp),
        Number(edge.depth) + 1,
        path,
        String(edge.amount),
        asset,
        classification,
        evidence,
      ];
    }),
  );
  const container = document.getElementById("funding-evidence");
  container.replaceChildren(
    fundingText(
      "p",
      `${Math.min(evidenceLimit, edges.length)} of ${edges.length} observed edges`,
    ),
    table,
  );
  if (edges.length > evidenceLimit) {
    const more = fundingText("button", "Show 100 more", "btn");
    more.type = "button";
    more.addEventListener("click", () => {
      evidenceLimit += 100;
      renderEvidence();
    });
    container.appendChild(more);
  }
}

function classificationLabel(category) {
  return (
    {
      direct_transfer: "Verified simple transfer",
      direct_transfer_in: "Verified simple inflow",
      direct_transfer_out: "Verified simple outflow",
      trade_related: "Trading-related (not a deposit claim)",
      payout_redemption: "Redemption-related",
      position_split: "Position split-related",
      positions_merge: "Position merge-related",
      unknown: "Unknown",
    }[category] || "Unknown"
  );
}

function renderClassification(report) {
  const classification = report.classification || {
    status: "not_requested",
    counts: {},
    direct_transfers: [],
  };
  const status = document.getElementById("classification-status");
  status.textContent = uiText(
    `Receipt classification: ${uiText(classification.status)}. ${classification.verified_receipts ?? 0} verified receipts in the last job; ${classification.skipped_receipts ?? 0} skipped; ${classification.unavailable_receipts ?? 0} unavailable; ${classification.failed_execution_receipts ?? 0} failed executions. Last checked: ${fundingDate(classification.checked_at)}`,
  );
  const counts = Object.entries(classification.counts || {}).map(
    ([category, count]) => [classificationLabel(category), count],
  );
  document
    .getElementById("classification-counts")
    .replaceChildren(
      fundingTable(["Classification", "Observed edges"], counts),
    );
  const direct = classification.direct_transfers || [];
  const rows = direct
    .slice(0, 100)
    .map((edge) => [
      edge.receiver === fundingAddress
        ? "Inflow / deposit candidate"
        : "Outflow / withdrawal candidate",
      addressLink(edge.sender),
      addressLink(edge.receiver),
      String(edge.amount),
      addressLink(edge.contract),
      transactionLink(edge.hash),
      `Log #${edge.log_index}${edge.receipt_stale ? " · stale cached receipt" : ""}`,
    ]);
  document
    .getElementById("classification-direct")
    .replaceChildren(
      rows.length
        ? fundingTable(
            [
              "Direction",
              "From",
              "To",
              "Token units",
              "Contract",
              "Evidence",
              "Log identity",
            ],
            rows,
          )
        : fundingText(
            "p",
            "No supported simple transfers confirmed in the classified sample. This is not proof that no deposits exist.",
          ),
      fundingText(
        "p",
        `${rows.length} of ${direct.length} simple root transfers shown; use the evidence category filter for the rest.`,
        "muted",
      ),
    );
}

function renderFunding(report) {
  fundingReport = report;
  renderClassification(report);
  document.getElementById("funding-results").hidden = false;
  const states = {
    not_requested:
      "No investigation yet. Choose Investigate / refresh to start.",
    queued:
      "Queued. Keep the scanner running; this report refreshes automatically.",
    running:
      "Tracing transfers in the background. Previous evidence, if shown, is retained until the result arrives.",
    complete:
      "Bounded investigation finished. This is not a claim of complete lifetime coverage.",
    partial:
      "Partial evidence. Inspect coverage and warnings before drawing conclusions.",
    unsupported: "The API key or plan cannot access these Polygon endpoints.",
    no_key:
      "Set ETHERSCAN_API_KEY in .env and restart the web server and scanner.",
    error:
      "Investigation failed. Previous evidence may be retained; retry after the cooldown.",
  };
  document.getElementById("funding-status").textContent = uiText(
    `${states[report.status] || report.status} Last checked: ${fundingDate(report.checked_at)}${report.configured === false ? " Etherscan key is not configured." : ""}`,
  );
  const exportLink = document.getElementById("funding-export");
  exportLink.hidden = !report.checked_at;
  exportLink.href = `/api/funding/${fundingAddress}?download=1`;
  const summary = (report.summary || []).map((item) => [
    addressLink(item.sender),
    `${item.amount}${item.identity_ambiguous ? " (API-row total; event identity ambiguous)" : ""}`,
    item.asset,
    item.contract === "native" ? "Native POL" : addressLink(item.contract),
    item.transfers,
    fundingDate(item.first_seen),
    fundingDate(item.last_seen),
  ]);
  document
    .getElementById("funding-summary")
    .replaceChildren(
      summary.length
        ? fundingTable(
            [
              "Sender",
              "Token units",
              "Asset",
              "Contract",
              "Transfers",
              "First in sample",
              "Last in sample",
            ],
            summary,
          )
        : fundingText(
            "p",
            "No direct inflows in the available evidence. This does not mean the wallet was never funded.",
          ),
    );
  const paths = new Map();
  for (const edge of report.edges || []) {
    if (
      !edge.ancestry ||
      edge.receipt_stale ||
      !["direct_transfer", "direct_transfer_in"].includes(
        edge.classification?.category,
      )
    )
      continue;
    const key = `${edge.depth}:${edge.sender}:${edge.receiver}:${edge.contract || "native"}`;
    if (!paths.has(key)) paths.set(key, edge);
  }
  const pathNodes = [...paths.values()].slice(0, 80).map((edge) => {
    const card = document.createElement("div");
    card.className = "funding-path";
    card.append(
      fundingText(
        "small",
        `Hop ${Number(edge.depth) + 1} · ${edge.asset} · sample transfer ${edge.amount}`,
      ),
      addressLink(edge.sender),
      " → ",
      addressLink(edge.receiver),
      " ",
      transactionLink(edge.hash),
    );
    return card;
  });
  document
    .getElementById("funding-graph")
    .replaceChildren(
      ...(pathNodes.length
        ? pathNodes
        : [fundingText("p", "No paths available.")]),
      fundingText(
        "p",
        `${Math.min(80, paths.size)} of ${paths.size} distinct transfer relationships shown. Full evidence is below and in the JSON export.`,
        "muted",
      ),
    );
  const relationships = (report.relationships || []).map((signal) => {
    const card = document.createElement("div");
    card.className = "funding-card";
    card.append(
      fundingText(
        "div",
        signal.type === "shared_funder"
          ? "Shared observed sender"
          : "Shared observed destination",
      ),
      addressLink(signal.wallet),
      " ↔ ",
      addressLink(signal.counterparty),
      fundingText("small", `Asset: ${signal.contract}; ${signal.strength}`),
    );
    card.appendChild(fundingText("small", "Root transaction evidence:"));
    for (const hash of signal.root_transactions || [])
      card.append(transactionLink(hash), " ");
    card.appendChild(fundingText("small", "Peer transaction evidence:"));
    for (const hash of signal.peer_transactions || [])
      card.append(transactionLink(hash), " ");
    return card;
  });
  document
    .getElementById("funding-relationships")
    .replaceChildren(
      ...(relationships.length
        ? relationships
        : [
            fundingText(
              "p",
              "No matching counterparties among saved investigations. Investigate other wallets to expand this comparison.",
            ),
          ]),
      fundingText(
        "p",
        "These are raw transfer matches, not deposit-only comparisons. Unlabelled shared services, trading and unsolicited transfers can produce these links. No common-owner conclusion is made.",
        "muted",
      ),
    );
  const behavior = (report.behavior || []).map((signal) => {
    const card = document.createElement("div");
    card.className = "funding-card";
    card.append(
      addressLink(signal.wallet),
      fundingText(
        "div",
        `${signal.matching_trades} sampled trades across ${signal.markets} markets overlapped within 120 seconds on the same side and outcome.`,
      ),
      fundingText(
        "small",
        "Descriptive overlap only. Shared news, bots and active markets can explain it; no statistical significance or coordination is established.",
      ),
    );
    for (const pair of signal.transactions || [])
      card.append(
        transactionLink(pair.root),
        " ↔ ",
        transactionLink(pair.peer),
        " ",
      );
    return card;
  });
  document
    .getElementById("funding-behavior")
    .replaceChildren(
      ...(behavior.length
        ? behavior
        : [
            fundingText(
              "p",
              "No repeated cross-market timing overlap in the bounded locally tracked trade sample.",
            ),
          ]),
    );
  const coverage = Array.isArray(report.coverage)
    ? report.coverage
    : report.coverage?.streams || [];
  const coverageRows = coverage.map((item) => [
    addressLink(item.address),
    item.action || item.endpoint || "Unknown",
    item.pages ?? 0,
    `${item.rows ?? 0} rows; ${item.invalid_rows ?? 0} invalid; ${item.ambiguous_rows ?? 0} ambiguous`,
    item.complete ? "Endpoint sample exhausted" : "Limited / unavailable",
    item.error || item.reason || "—",
    item.contract ? addressLink(item.contract) : "All assets",
    item.cutoff ? fundingDate(item.cutoff) : "Root / no cutoff",
  ]);
  const stops = (report.nodes || [])
    .filter((node) => node.stop_reason)
    .map((node) => {
      const card = document.createElement("div");
      card.className = "funding-card";
      card.append(
        addressLink(node.address),
        fundingText(
          "small",
          `${node.label || "Unlabelled wallet"} · ${node.stop_reason}`,
        ),
      );
      if (node.source === "https://docs.polymarket.com/resources/contracts") {
        const source = fundingText(
          "a",
          "Official contract source",
          "wallet-link",
        );
        source.href = node.source;
        source.target = "_blank";
        source.rel = "noopener noreferrer";
        card.appendChild(source);
      }
      return card;
    });
  document
    .getElementById("funding-coverage")
    .replaceChildren(
      fundingText(
        "p",
        `Status: ${report.status}. Root: ${fundingAddress}. ${report.requests ?? 0} upstream calls; ${(report.nodes || []).length} address/asset states.`,
      ),
      fundingTable(
        [
          "Wallet",
          "Stream",
          "Pages",
          "Rows",
          "Coverage",
          "Problem",
          "Asset filter",
          "Before",
        ],
        coverageRows,
      ),
      ...stops,
    );
  const warningList = document.createElement("ul");
  for (const warning of [
    ...(report.warnings || []),
    ...(report.limitations || []),
    ...(report.edges_truncated
      ? [
          "Display and JSON export are capped at the newest 10,000 stored edges. Older evidence remains in the database; displayed totals are incomplete.",
        ]
      : []),
    ...(report.relationships_truncated
      ? ["Relationship comparison reached its result limit."]
      : []),
    ...(report.behavior_truncated
      ? ["Trading overlap reached its comparison limit."]
      : []),
    ...(report.previous_evidence_retained
      ? [
          `Previous transfer evidence retained from ${fundingDate(report.previous_evidence_checked_at)} and merged with any new observations; the latest lookup was incomplete.`,
        ]
      : []),
  ])
    warningList.appendChild(fundingText("li", warning));
  document.getElementById("funding-warnings").replaceChildren(warningList);
  const assets = new Map(
    (report.edges || []).map((edge) => [
      edge.contract || "native",
      edge.asset || "Unknown",
    ]),
  );
  const select = document.getElementById("funding-asset");
  const selected = select.value;
  const all = fundingText("option", "All contracts");
  all.value = "all";
  select.replaceChildren(
    all,
    ...[...assets].map(([contract, symbol]) => {
      const option = fundingText("option", `${symbol} · ${contract}`);
      option.value = contract;
      return option;
    }),
  );
  select.value = assets.has(selected) ? selected : "all";
  renderEvidence();
}

async function loadFunding(address, start = false, action = "investigate") {
  if (!validAddress(address)) {
    document.getElementById("funding-status").textContent = uiText(
      "Enter a valid 0x Polygon address (40 hexadecimal characters).",
    );
    return;
  }
  clearTimeout(fundingTimer);
  if (fundingRequest) fundingRequest.abort();
  const controller = new AbortController();
  fundingRequest = controller;
  const requestId = ++fundingRequestId;
  if (address.toLowerCase() !== fundingAddress) {
    fundingReport = null;
    document.getElementById("funding-results").hidden = true;
    document.getElementById("funding-export").hidden = true;
    evidenceLimit = 100;
  }
  fundingAddress = address.toLowerCase();
  document.getElementById("funding-address").value = fundingAddress;
  document.getElementById("funding-status").textContent = uiText(
    start ? "Requesting investigation…" : "Loading saved evidence…",
  );
  const timeout = setTimeout(() => controller.abort(), 15000);
  let actionMessage = "";
  try {
    if (start) {
      const response = await fetch(`/api/funding/${fundingAddress}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
        signal: controller.signal,
      });
      const result = await response.json();
      if (requestId !== fundingRequestId || controller.signal.aborted) return;
      if (!response.ok)
        actionMessage =
          result.error ||
          (result.status === "cooldown"
            ? "Please wait ten minutes between investigations of the same wallet."
            : "The investigation queue is full. Try again shortly.");
    }
    const response = await fetch(`/api/funding/${fundingAddress}`, {
      signal: controller.signal,
    });
    if (!response.ok)
      throw new Error(`Report unavailable (${response.status})`);
    const report = await response.json();
    if (requestId !== fundingRequestId || controller.signal.aborted) return;
    renderFunding(report);
    if (actionMessage)
      document.getElementById("funding-status").textContent =
        uiText(actionMessage);
    if (
      report.status === "queued" ||
      report.status === "running" ||
      ["queued", "running"].includes(report.classification?.status)
    )
      fundingTimer = setTimeout(() => loadFunding(fundingAddress), 5000);
  } catch (error) {
    if (requestId === fundingRequestId)
      document.getElementById("funding-status").textContent = uiText(
        error.name === "AbortError"
          ? "Report request timed out. You can retry."
          : "Unable to load evidence. You can retry.",
      );
  } finally {
    clearTimeout(timeout);
    if (requestId === fundingRequestId) fundingRequest = null;
  }
}

document.getElementById("funding-form").addEventListener("submit", (event) => {
  event.preventDefault();
  loadFunding(document.getElementById("funding-address").value.trim());
});
document
  .getElementById("funding-run")
  .addEventListener("click", () =>
    loadFunding(document.getElementById("funding-address").value.trim(), true),
  );
document
  .getElementById("funding-classify")
  .addEventListener("click", () =>
    loadFunding(
      document.getElementById("funding-address").value.trim(),
      true,
      "classify",
    ),
  );
for (const id of ["funding-direction", "funding-asset", "funding-category"])
  document.getElementById(id).addEventListener("change", () => {
    evidenceLimit = 100;
    renderEvidence();
  });
const initialAddress = new URLSearchParams(window.location.search).get(
  "address",
);
if (initialAddress) loadFunding(initialAddress);
