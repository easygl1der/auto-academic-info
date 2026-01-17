const api = {
  pages: "/api/pages",
  crawlAll: "/api/crawl",
  meetings: "/api/meetings",
};

const formatDate = (value) => {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
};

const sanitize = (value) => (value ? String(value) : "-");

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }
  return response.json();
}

function renderPages(pages, container) {
  container.innerHTML = "";
  if (!pages.length) {
    container.textContent = "No pages monitored yet.";
    return;
  }
  pages.forEach((page) => {
    const item = document.createElement("div");
    item.className = "list-item";
    const title = document.createElement("strong");
    title.textContent = page.url;
    const meta = document.createElement("div");
    meta.className = "subtle";
    meta.textContent = `Last checked: ${formatDate(page.last_checked_at)}`;
    item.appendChild(title);
    item.appendChild(meta);
    container.appendChild(item);
  });
}

function renderMeetings(meetings, tableBody, detailsPanel) {
  tableBody.innerHTML = "";
  if (!meetings.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 7;
    cell.textContent = "No meetings captured yet.";
    row.appendChild(cell);
    tableBody.appendChild(row);
    return;
  }
  meetings.forEach((meeting) => {
    const row = document.createElement("tr");
    const cells = [
      sanitize(meeting.title || meeting.topic),
      sanitize(meeting.speaker),
      sanitize(meeting.start_time),
      sanitize(meeting.location),
      sanitize(meeting.mode),
      formatDate(meeting.last_updated_at),
    ];
    cells.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    const actionCell = document.createElement("td");
    const button = document.createElement("button");
    button.className = "secondary";
    button.textContent = "Details";
    button.addEventListener("click", () => loadMeetingDetails(meeting.id, detailsPanel));
    actionCell.appendChild(button);
    row.appendChild(actionCell);
    tableBody.appendChild(row);
  });
}

function renderMeetingDetails(meeting, history, panel) {
  panel.innerHTML = "";
  if (!meeting) {
    panel.textContent = "Select a meeting to view details.";
    return;
  }
  const fields = [
    ["Title", meeting.title || meeting.topic],
    ["Speaker", meeting.speaker],
    ["Time", meeting.start_time],
    ["Location", meeting.location],
    ["Mode", meeting.mode],
    ["Source Page", meeting.source_page_url],
    ["Source URL", meeting.source_url],
    ["Online Link", meeting.online_link],
    ["Speaker Intro", meeting.speaker_intro],
    ["Speaker Intro URL", meeting.speaker_intro_url],
    ["Abstract", meeting.abstract],
    ["Last Updated", formatDate(meeting.last_updated_at)],
  ];
  fields.forEach(([label, value]) => {
    const row = document.createElement("div");
    const key = document.createElement("strong");
    key.textContent = `${label}:`;
    const val = document.createElement("span");
    if (value && String(value).startsWith("http")) {
      const link = document.createElement("a");
      link.href = value;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = value;
      val.appendChild(link);
    } else {
      val.textContent = sanitize(value);
    }
    row.appendChild(key);
    row.appendChild(val);
    panel.appendChild(row);
  });

  if (history && history.length) {
    const historyHeader = document.createElement("div");
    historyHeader.style.marginTop = "12px";
    historyHeader.textContent = `History entries: ${history.length}`;
    panel.appendChild(historyHeader);
  }
}

async function loadMeetingDetails(meetingId, panel) {
  const detailsStatus = document.getElementById("details-status");
  try {
    detailsStatus.textContent = "Loading details...";
    const meeting = await fetchJSON(`${api.meetings}/${meetingId}`);
    const history = await fetchJSON(`${api.meetings}/${meetingId}/history`);
    renderMeetingDetails(meeting, history, panel);
    detailsStatus.textContent = "Details loaded.";
  } catch (error) {
    detailsStatus.textContent = `Failed to load details: ${error.message}`;
  }
}

async function runCrawl(statusElement) {
  try {
    statusElement.textContent = "Crawl queued...";
    await fetchJSON(api.crawlAll, { method: "POST" });
    statusElement.textContent = "Crawl queued. Refresh after a minute.";
  } catch (error) {
    statusElement.textContent = `Crawl failed: ${error.message}`;
  }
}

async function loadDashboard() {
  const pageCount = document.getElementById("stat-pages");
  const meetingCount = document.getElementById("stat-meetings");
  const refreshTime = document.getElementById("stat-refresh");
  const pagesList = document.getElementById("pages-list");
  const meetingsTable = document.getElementById("meetings-table");
  const meetingsStatus = document.getElementById("meetings-status");
  const detailsPanel = document.getElementById("meeting-details");
  const pagesStatus = document.getElementById("pages-status");

  try {
    meetingsStatus.textContent = "Loading meetings...";
    pagesStatus.textContent = "Loading pages...";
    const [pages, meetings] = await Promise.all([
      fetchJSON(api.pages),
      fetchJSON(api.meetings),
    ]);
    renderPages(pages, pagesList);
    renderMeetings(meetings, meetingsTable, detailsPanel);
    pageCount.textContent = pages.length;
    meetingCount.textContent = meetings.length;
    refreshTime.textContent = formatDate(new Date().toISOString());
    meetingsStatus.textContent = `Loaded ${meetings.length} meetings.`;
    pagesStatus.textContent = `Tracking ${pages.length} pages.`;
  } catch (error) {
    meetingsStatus.textContent = `Failed to load data: ${error.message}`;
  }
}

async function initDashboard() {
  await loadDashboard();
  const refreshButton = document.getElementById("refresh-button");
  const crawlButton = document.getElementById("crawl-button");
  if (refreshButton) {
    refreshButton.addEventListener("click", loadDashboard);
  }
  if (crawlButton) {
    crawlButton.addEventListener("click", () =>
      runCrawl(document.getElementById("meetings-status"))
    );
  }
}

async function initAddPage() {
  const form = document.getElementById("add-form");
  const input = document.getElementById("page-url");
  const status = document.getElementById("add-status");
  const pagesList = document.getElementById("pages-list");

  const loadPages = async () => {
    const pages = await fetchJSON(api.pages);
    renderPages(pages, pagesList);
  };

  await loadPages();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    status.textContent = "Adding...";
    try {
      await fetchJSON(api.pages, {
        method: "POST",
        body: JSON.stringify({ url: input.value }),
      });
      status.textContent = "Page added.";
      input.value = "";
      await loadPages();
    } catch (error) {
      status.textContent = `Failed to add: ${error.message}`;
    }
  });
}

const page = document.body.dataset.page;
if (page === "dashboard") {
  initDashboard();
}
if (page === "add") {
  initAddPage();
}
