/**
 * PC Parts Auto Researcher — Interactive Live Dashboard Application
 */

const STATE = {
  activeTab: 'tab-overall',
  stats: {},
  summary: {},
  local: {},
  listings: [],
  filters: {
    search: '',
    category: '',
    model: '',
    localOnly: false,
    sortBy: 'overall_score',
  },
  activeModelFilter: 'ALL',
};

// Initialize Dashboard
document.addEventListener('DOMContentLoaded', () => {
  initEventListeners();
  loadAllData();

  // Auto-refresh stats and data every 30 seconds
  setInterval(() => {
    loadStats();
    if (STATE.activeTab === 'tab-explorer') {
      loadListings();
    }
  }, 30000);
});

function initEventListeners() {
  // Navigation Tabs
  document.querySelectorAll('.nav-tab').forEach((tabBtn) => {
    tabBtn.addEventListener('click', (e) => {
      document.querySelectorAll('.nav-tab').forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach((p) => p.classList.remove('active'));

      tabBtn.classList.add('active');
      const targetId = tabBtn.getAttribute('data-tab');
      document.getElementById(targetId).classList.add('active');
      STATE.activeTab = targetId;

      if (targetId === 'tab-explorer') {
        loadListings();
      }
    });
  });

  // Manual Scan Button
  const refreshBtn = document.getElementById('refresh-btn');
  refreshBtn.addEventListener('click', () => {
    triggerManualScan();
  });

  // Explorer Filters
  const searchInput = document.getElementById('filter-search');
  searchInput.addEventListener('input', debounce((e) => {
    STATE.filters.search = e.target.value;
    loadListings();
  }, 250));

  document.getElementById('filter-category').addEventListener('change', (e) => {
    STATE.filters.category = e.target.value;
    loadListings();
  });

  document.getElementById('filter-model').addEventListener('change', (e) => {
    STATE.filters.model = e.target.value;
    loadListings();
  });

  document.getElementById('filter-local-only').addEventListener('change', (e) => {
    STATE.filters.localOnly = e.target.checked;
    loadListings();
  });

  document.getElementById('filter-sort').addEventListener('change', (e) => {
    STATE.filters.sortBy = e.target.value;
    loadListings();
  });
}

async function loadAllData() {
  await Promise.all([loadStats(), loadSummary(), loadLocal()]);
}

async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) return;
    const data = await res.json();
    STATE.stats = data;

    document.getElementById('metric-total-listings').innerText = data.total_verified_canadian;
    document.getElementById('metric-local-deals').innerText = data.total_local_20km;
    document.getElementById('metric-ram-count').innerText = data.total_ram;
    document.getElementById('last-updated-text').innerText = data.is_scanning ? 'Scanning now...' : `Updated ${data.last_updated || 'recently'}`;

    const refreshBtn = document.getElementById('refresh-btn');
    const refreshText = document.getElementById('refresh-btn-text');
    if (data.is_scanning) {
      refreshBtn.disabled = true;
      refreshText.innerText = 'Scanning...';
    } else {
      refreshBtn.disabled = false;
      refreshText.innerText = 'Run Scan';
    }
  } catch (err) {
    console.error('Error fetching stats:', err);
  }
}

async function loadSummary() {
  try {
    const res = await fetch('/api/summary');
    if (!res.ok) return;
    const data = await res.json();
    STATE.summary = data;
    renderOverallLeaderboard(data.top_5_overall_cpus || []);
    renderModelBreakdowns(data.top_5_by_model || {});
  } catch (err) {
    console.error('Error fetching summary:', err);
  }
}

async function loadLocal() {
  try {
    const res = await fetch('/api/local');
    if (!res.ok) return;
    const data = await res.json();
    STATE.local = data;
    renderLocalRadar(data.top_local_cpus || [], data.top_local_ram || []);
  } catch (err) {
    console.error('Error fetching local listings:', err);
  }
}

async function loadListings() {
  try {
    const params = new URLSearchParams();
    if (STATE.filters.search) params.append('search', STATE.filters.search);
    if (STATE.filters.category) params.append('category', STATE.filters.category);
    if (STATE.filters.model) params.append('model', STATE.filters.model);
    if (STATE.filters.localOnly) params.append('local_only', 'true');
    if (STATE.filters.sortBy) params.append('sort_by', STATE.filters.sortBy);

    const res = await fetch(`/api/listings?${params.toString()}`);
    if (!res.ok) return;
    const data = await res.json();
    STATE.listings = data.listings || [];
    renderExplorerTable(STATE.listings, data.total);
  } catch (err) {
    console.error('Error fetching listings:', err);
  }
}

async function triggerManualScan() {
  const refreshBtn = document.getElementById('refresh-btn');
  const refreshText = document.getElementById('refresh-btn-text');
  refreshBtn.disabled = true;
  refreshText.innerText = 'Starting...';

  try {
    const res = await fetch('/api/refresh', { method: 'POST' });
    const data = await res.json();
    setTimeout(() => {
      loadStats();
    }, 1500);
  } catch (err) {
    console.error('Error triggering scan:', err);
    refreshBtn.disabled = false;
    refreshText.innerText = 'Run Scan';
  }
}

function renderOverallLeaderboard(items) {
  const container = document.getElementById('overall-leaderboard-container');
  if (!items || items.length === 0) {
    container.innerHTML = `<div class="loading-state">No verified CPU listings found.</div>`;
    return;
  }

  container.innerHTML = items.map((item, idx) => {
    const rank = idx + 1;
    const modelName = item.model_bucket.replace('CPU - ', '');
    const isEbay = item.listing_url.includes('ebay');
    const sourceIcon = isEbay ? 'eBay' : 'Marketplace';

    return `
      <div class="rank-card ${rank === 1 ? 'rank-1' : ''}">
        <div>
          <div class="rank-card-header">
            <span class="rank-badge">#${rank} Overall</span>
            <span class="model-tag">${modelName}</span>
          </div>
          <h3 class="card-title" title="${item.title}">${item.title}</h3>
          
          <div class="card-price-row">
            <div class="card-price">CAD $${item.price.toFixed(2)}</div>
            <div class="benchmark-chip">
              Benchmark: <strong>${item.benchmark_score.toLocaleString()}</strong> pts
            </div>
          </div>

          <div class="card-stats-grid">
            <div class="stat-item">
              <span>Overall Value</span>
              <span style="color: var(--accent-green)">${item.overall_score.toFixed(1)} / 100</span>
            </div>
            <div class="stat-item">
              <span>Seller Trust</span>
              <span>${item.trust_score.toFixed(0)} / 100</span>
            </div>
            <div class="stat-item">
              <span>Condition</span>
              <span>${item.condition}</span>
            </div>
            <div class="stat-item">
              <span>Source</span>
              <span>${sourceIcon}</span>
            </div>
          </div>
        </div>

        <div class="card-footer">
          <span class="loc-pill" title="${item.location}">${item.location}</span>
          <a href="${item.listing_url}" target="_blank" rel="noopener noreferrer" class="btn-external">
            View Listing &rarr;
          </a>
        </div>
      </div>
    `;
  }).join('');
}

function renderLocalRadar(cpus, rams) {
  const cpuContainer = document.getElementById('local-cpus-container');
  const ramContainer = document.getElementById('local-ram-container');

  if (!cpus || cpus.length === 0) {
    cpuContainer.innerHTML = `<div class="loading-state">No current 20km local CPU listings found. Check Toronto / GTA options in Master Summary.</div>`;
  } else {
    cpuContainer.innerHTML = cpus.map((item, idx) => `
      <div class="rank-card">
        <div class="rank-card-header">
          <span class="rank-badge">#${idx + 1} Local CPU</span>
          <span class="model-tag">${item.model_bucket.replace('CPU - ', '')}</span>
        </div>
        <h4 class="card-title">${item.title}</h4>
        <div class="card-price-row">
          <div class="card-price">CAD $${item.price.toFixed(2)}</div>
          <div class="benchmark-chip">PassMark: <strong>${item.benchmark_score.toLocaleString()}</strong></div>
        </div>
        <div class="card-footer">
          <span class="loc-pill">📍 ${item.location}</span>
          <a href="${item.listing_url}" target="_blank" rel="noopener" class="btn-external">View &rarr;</a>
        </div>
      </div>
    `).join('');
  }

  if (!rams || rams.length === 0) {
    ramContainer.innerHTML = `<div class="loading-state">No current 20km local RAM listings found.</div>`;
  } else {
    ramContainer.innerHTML = rams.map((item, idx) => `
      <div class="rank-card">
        <div class="rank-card-header">
          <span class="rank-badge">#${idx + 1} Local RAM</span>
          <span class="model-tag">DDR4 UDIMM</span>
        </div>
        <h4 class="card-title">${item.title}</h4>
        <div class="card-price-row">
          <div class="card-price">CAD $${item.price.toFixed(2)}</div>
          <div class="benchmark-chip">Score: <strong>${item.composite_score.toFixed(1)}/100</strong></div>
        </div>
        <div class="card-footer">
          <span class="loc-pill">📍 ${item.location}</span>
          <a href="${item.listing_url}" target="_blank" rel="noopener" class="btn-external">View &rarr;</a>
        </div>
      </div>
    `).join('');
  }
}

function renderModelBreakdowns(models) {
  const container = document.getElementById('model-breakdowns-container');
  const pillContainer = document.getElementById('model-filter-pill-container');

  const modelKeys = Object.keys(models).filter(k => models[k] && models[k].length > 0);

  if (modelKeys.length === 0) {
    container.innerHTML = `<div class="loading-state">No model breakdowns available.</div>`;
    return;
  }

  // Render Pill Buttons
  pillContainer.innerHTML = `
    <button class="pill-btn ${STATE.activeModelFilter === 'ALL' ? 'active' : ''}" onclick="filterModelView('ALL')">All Models</button>
    ${modelKeys.map(k => `
      <button class="pill-btn ${STATE.activeModelFilter === k ? 'active' : ''}" onclick="filterModelView('${k}')">${k.replace('CPU - ', '')}</button>
    `).join('')}
  `;

  // Render Model Groups
  container.innerHTML = modelKeys
    .filter(k => STATE.activeModelFilter === 'ALL' || STATE.activeModelFilter === k)
    .map(modelName => `
      <div class="model-group-block">
        <h3 class="model-group-title">📌 ${modelName} Top Deals</h3>
        <div class="leaderboard-grid">
          ${models[modelName].map((item, idx) => `
            <div class="rank-card">
              <div>
                <div class="rank-card-header">
                  <span class="rank-badge">#${idx + 1}</span>
                  <span class="model-tag">${modelName.replace('CPU - ', '')}</span>
                </div>
                <h4 class="card-title">${item.title}</h4>
                <div class="card-price-row">
                  <div class="card-price">CAD $${item.price.toFixed(2)}</div>
                  <div class="benchmark-chip">Value: <strong>${item.composite_score.toFixed(1)}</strong></div>
                </div>
                <div class="card-stats-grid">
                  <div class="stat-item">
                    <span>Trust</span>
                    <span>${item.trust_score.toFixed(0)}/100</span>
                  </div>
                  <div class="stat-item">
                    <span>Condition</span>
                    <span>${item.condition}</span>
                  </div>
                </div>
              </div>
              <div class="card-footer">
                <span class="loc-pill">${item.location}</span>
                <a href="${item.listing_url}" target="_blank" rel="noopener" class="btn-external">View &rarr;</a>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `).join('');
}

window.filterModelView = function(modelKey) {
  STATE.activeModelFilter = modelKey;
  renderModelBreakdowns(STATE.summary.top_5_by_model || {});
};

function renderExplorerTable(items, totalCount) {
  const tbody = document.getElementById('explorer-table-body');
  const countText = document.getElementById('results-count-text');

  countText.innerText = `Showing ${items.length} of ${totalCount} verified listings`;

  if (!items || items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="loading-state">No matching listings found.</td></tr>`;
    return;
  }

  tbody.innerHTML = items.map(item => {
    const isCpu = item.category.toUpperCase() === 'CPU';
    const benchmarkStr = isCpu && item.benchmark_score > 0 ? `${item.benchmark_score.toLocaleString()} pts` : '-';
    const overallValStr = isCpu && item.overall_score > 0 ? `${item.overall_score.toFixed(1)}/100` : `${item.composite_score.toFixed(1)}/100`;

    return `
      <tr>
        <td><span class="model-tag">${item.model_bucket.replace('CPU - ', '') || item.category}</span></td>
        <td style="font-weight: 500; color: #fff;">${item.title}</td>
        <td style="font-family: var(--font-mono); font-weight: 700; color: #fff;">$${item.price.toFixed(2)}</td>
        <td style="font-family: var(--font-mono);">${benchmarkStr}</td>
        <td style="font-family: var(--font-mono); color: var(--accent-green); font-weight: 600;">${overallValStr}</td>
        <td>${item.trust_score.toFixed(0)}/100</td>
        <td>${item.location}</td>
        <td>
          <a href="${item.listing_url}" target="_blank" rel="noopener" class="btn-external">
            Link &rarr;
          </a>
        </td>
      </tr>
    `;
  }).join('');
}

function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}
