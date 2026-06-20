/* ── Clock ──────────────────────────────────────────────────────────────── */
function updateClock() {
  const el = document.getElementById('clock');
  if (el) el.textContent = new Date().toUTCString().replace('GMT', 'UTC');
}
updateClock();
setInterval(updateClock, 1000);

/* ── Helpers ─────────────────────────────────────────────────────────────── */
async function apiFetch(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function showToast(msg, type = 'info') {
  const colours = { info: 'bg-brand-600', error: 'bg-red-600', success: 'bg-emerald-600' };
  const toast = document.createElement('div');
  toast.className = `fixed bottom-5 right-5 z-[100] px-4 py-3 rounded-lg text-white text-sm shadow-xl ${colours[type] || colours.info} transition-opacity`;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 400); }, 3500);
}

/* ── Portfolio Table ──────────────────────────────────────────────────────── */
async function loadPortfolio() {
  const tbody = document.getElementById('portfolio-body');
  try {
    const positions = await apiFetch('/api/portfolio');
    if (!positions.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center py-10 text-slate-500 text-sm">No positions yet. Click "+ Add Position" to get started.</td></tr>';
      return;
    }
    tbody.innerHTML = positions.map(p => `
      <tr class="border-b border-gray-800 hover:bg-gray-800/50 transition">
        <td class="px-4 py-3 font-mono font-semibold text-brand-400">${p.ticker}</td>
        <td class="px-4 py-3 text-right tabular-nums">${Number(p.shares).toLocaleString(undefined, {maximumFractionDigits: 4})}</td>
        <td class="px-4 py-3 text-right tabular-nums text-emerald-400">$${Number(p.average_buy_price).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
        <td class="px-4 py-3 text-slate-400 text-xs">${new Date(p.date_added).toLocaleDateString()}</td>
        <td class="px-4 py-3 text-center">
          <button onclick="deletePosition('${p.ticker}')"
                  class="px-2 py-1 text-xs rounded bg-red-900/60 hover:bg-red-700 text-red-300 hover:text-white transition">Remove</button>
        </td>
      </tr>`).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-center py-10 text-red-400 text-sm">${e.message}</td></tr>`;
  }
}

async function deletePosition(ticker) {
  if (!confirm(`Remove ${ticker} from portfolio?`)) return;
  try {
    await apiFetch(`/api/portfolio/${ticker}`, { method: 'DELETE' });
    showToast(`${ticker} removed.`, 'success');
    loadPortfolio();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

/* ── Modal ───────────────────────────────────────────────────────────────── */
function openModal() {
  document.getElementById('modal-backdrop').classList.remove('hidden');
  document.getElementById('m-ticker').focus();
  document.getElementById('modal-error').classList.add('hidden');
}
function closeModal() {
  document.getElementById('modal-backdrop').classList.add('hidden');
  ['m-ticker', 'm-shares', 'm-price'].forEach(id => document.getElementById(id).value = '');
}

async function submitPosition() {
  const ticker = document.getElementById('m-ticker').value.trim().toUpperCase();
  const shares = parseFloat(document.getElementById('m-shares').value);
  const price  = parseFloat(document.getElementById('m-price').value);
  const errEl  = document.getElementById('modal-error');

  if (!ticker || isNaN(shares) || isNaN(price) || shares <= 0 || price <= 0) {
    errEl.textContent = 'Please fill all fields with valid positive numbers.';
    errEl.classList.remove('hidden');
    return;
  }
  errEl.classList.add('hidden');

  try {
    await apiFetch('/api/portfolio', {
      method: 'POST',
      body: JSON.stringify({ ticker, shares, average_buy_price: price }),
    });
    showToast(`${ticker} saved!`, 'success');
    closeModal();
    loadPortfolio();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove('hidden');
  }
}

/* ── Analysis ─────────────────────────────────────────────────────────────── */
async function runAnalysis() {
  const raw    = document.getElementById('ticker-input').value.trim().toUpperCase();
  const spinner = document.getElementById('analyze-spinner');
  const resultEl = document.getElementById('analysis-result');
  const labelEl  = document.getElementById('analysis-ticker-label');
  const bodyEl   = document.getElementById('analysis-body');

  if (!raw) { showToast('Enter a ticker symbol first.', 'error'); return; }

  spinner.classList.remove('hidden');
  resultEl.classList.add('hidden');

  try {
    const data = await apiFetch(`/api/analyze/${raw}`);
    labelEl.textContent = `Analysis for ${data.ticker} — ${new Date().toLocaleString()}`;
    bodyEl.innerHTML = marked.parse(data.report);
    resultEl.classList.remove('hidden');
    resultEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    showToast(`Analysis failed: ${e.message}`, 'error');
  } finally {
    spinner.classList.add('hidden');
  }
}

/* ── Daily Report ─────────────────────────────────────────────────────────── */
async function loadLatestReport() {
  try {
    const data = await apiFetch('/api/report/latest');
    if (data.report) renderReport(data.report);
  } catch (_) { /* silently skip on startup */ }
}

async function triggerReport() {
  const spinner    = document.getElementById('report-spinner');
  const placeholder = document.getElementById('report-placeholder');
  spinner.classList.remove('hidden');
  placeholder.textContent = 'Generating report… this may take a moment.';
  placeholder.classList.remove('hidden');
  document.getElementById('report-body').classList.add('hidden');

  try {
    const data = await apiFetch('/api/report/trigger', { method: 'POST' });
    renderReport(data.report);
    showToast('Report generated!', 'success');
  } catch (e) {
    placeholder.textContent = `Error: ${e.message}`;
    showToast(e.message, 'error');
  } finally {
    spinner.classList.add('hidden');
  }
}

function renderReport(markdown) {
  const placeholder = document.getElementById('report-placeholder');
  const bodyEl      = document.getElementById('report-body');
  placeholder.classList.add('hidden');
  bodyEl.innerHTML = marked.parse(markdown);
  bodyEl.classList.remove('hidden');
}

/* ── Init ─────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  loadPortfolio();
  loadLatestReport();
});
