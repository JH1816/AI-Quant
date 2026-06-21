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
function pnlCell(val, prefix = '$') {
  if (val == null) return `<td class="px-4 py-3 text-right tabular-nums text-slate-500">—</td>`;
  const cls = val >= 0 ? 'text-emerald-400' : 'text-red-400';
  const sign = val >= 0 ? '+' : '-';
  const abs = Math.abs(val).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
  return `<td class="px-4 py-3 text-right tabular-nums font-medium ${cls}">${sign}${prefix}${abs}</td>`;
}

function pctCell(val) {
  if (val == null) return `<td class="px-4 py-3 text-right tabular-nums text-slate-500">—</td>`;
  const cls = val >= 0 ? 'text-emerald-400' : 'text-red-400';
  const sign = val >= 0 ? '+' : '';
  return `<td class="px-4 py-3 text-right tabular-nums font-medium ${cls}">${sign}${val.toFixed(2)}%</td>`;
}

async function loadPortfolio() {
  const tbody = document.getElementById('portfolio-body');
  try {
    const positions = await apiFetch('/api/portfolio/enriched');
    if (!positions.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center py-10 text-slate-500 text-sm">No positions yet. Click "+ Add Position" to get started.</td></tr>';
      return;
    }

    const rows = positions.map(p => {
      const currentPrice = p.current_price != null
        ? `$${p.current_price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`
        : '<span class="text-slate-500">—</span>';
      return `
        <tr class="border-b border-gray-800 hover:bg-gray-800/50 transition">
          <td class="px-4 py-3 font-mono font-semibold text-brand-400">${p.ticker}</td>
          <td class="px-4 py-3 text-right tabular-nums">${Number(p.shares).toLocaleString(undefined, {maximumFractionDigits: 4})}</td>
          <td class="px-4 py-3 text-right tabular-nums text-slate-300">$${Number(p.average_buy_price).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
          <td class="px-4 py-3 text-right tabular-nums text-slate-300">${currentPrice}</td>
          ${pnlCell(p.unrealised_pnl)}
          ${pctCell(p.return_pct)}
          <td class="px-4 py-3 text-slate-400 text-xs">${new Date(p.date_added).toLocaleDateString()}</td>
          <td class="px-4 py-3 text-center">
            <button onclick="deletePosition('${p.ticker}')"
                    class="px-2 py-1 text-xs rounded bg-red-900/60 hover:bg-red-700 text-red-300 hover:text-white transition">Remove</button>
          </td>
        </tr>`;
    }).join('');

    // Totals footer
    const totalValue = positions.reduce((s, p) => p.current_value != null ? s + p.current_value : s, 0);
    const totalPnl   = positions.reduce((s, p) => p.unrealised_pnl != null ? s + p.unrealised_pnl : s, 0);
    const hasLive    = positions.some(p => p.current_price != null);
    const footerPnlCls = totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400';
    const footerPnlSign = totalPnl >= 0 ? '+' : '-';
    const footer = hasLive ? `
      <tr class="border-t-2 border-gray-700 bg-gray-900/80 font-semibold text-xs">
        <td class="px-4 py-2.5 text-slate-400 uppercase tracking-wide" colspan="3">Portfolio Total</td>
        <td class="px-4 py-2.5 text-right tabular-nums text-slate-200">$${totalValue.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
        <td class="px-4 py-2.5 text-right tabular-nums ${footerPnlCls}">${footerPnlSign}$${Math.abs(totalPnl).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
        <td class="px-4 py-2.5" colspan="3"></td>
      </tr>` : '';

    tbody.innerHTML = rows + footer;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-10 text-red-400 text-sm">${e.message}</td></tr>`;
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

/* ── Metrics Dashboard ───────────────────────────────────────────────────── */
function fmt(n, decimals = 2) {
  if (n == null) return '—';
  return Number(n).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
function fmtK(n) {
  if (n == null) return '—';
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  return Number(n).toLocaleString();
}

async function loadMetrics() {
  const raw = document.getElementById('metrics-input').value.trim().toUpperCase();
  if (!raw) { showToast('Enter a ticker symbol first.', 'error'); return; }

  const spinner = document.getElementById('metrics-spinner');
  spinner.classList.remove('hidden');
  document.getElementById('metrics-result').classList.add('hidden');

  try {
    const d = await apiFetch(`/api/indicators/${raw}`);
    renderMetrics(d);
    document.getElementById('metrics-result').classList.remove('hidden');
    document.getElementById('metrics-result').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    showToast(`Metrics error: ${e.message}`, 'error');
  } finally {
    spinner.classList.add('hidden');
  }
}

function renderMetrics(d) {
  const close = d.latest_close;

  /* ─ Price card ─ */
  document.getElementById('md-price').textContent = `$${fmt(close)}`;
  document.getElementById('md-52w').textContent =
    `52w: $${fmt(d['52_week_low'])} – $${fmt(d['52_week_high'])}`;

  /* ─ RSI card ─ */
  const rsi = d.rsi_14;
  const rsiEl = document.getElementById('md-rsi');
  const rsiLbl = document.getElementById('md-rsi-label');
  rsiEl.textContent = rsi != null ? rsi.toFixed(1) : '—';
  if (rsi == null) { rsiEl.className = 'text-2xl font-bold font-mono text-slate-400'; rsiLbl.textContent = ''; }
  else if (rsi < 30) { rsiEl.className = 'text-2xl font-bold font-mono text-emerald-400'; rsiLbl.className = 'text-xs font-semibold mt-1 text-emerald-400'; rsiLbl.textContent = 'OVERSOLD'; }
  else if (rsi < 45) { rsiEl.className = 'text-2xl font-bold font-mono text-yellow-400'; rsiLbl.className = 'text-xs font-semibold mt-1 text-yellow-400'; rsiLbl.textContent = 'WEAK'; }
  else if (rsi < 55) { rsiEl.className = 'text-2xl font-bold font-mono text-slate-200'; rsiLbl.className = 'text-xs font-semibold mt-1 text-slate-400'; rsiLbl.textContent = 'NEUTRAL'; }
  else if (rsi < 70) { rsiEl.className = 'text-2xl font-bold font-mono text-orange-400'; rsiLbl.className = 'text-xs font-semibold mt-1 text-orange-400'; rsiLbl.textContent = 'STRONG'; }
  else { rsiEl.className = 'text-2xl font-bold font-mono text-red-400'; rsiLbl.className = 'text-xs font-semibold mt-1 text-red-400'; rsiLbl.textContent = 'OVERBOUGHT'; }

  /* ─ MACD card ─ */
  const macd = d.macd.macd; const sig = d.macd.signal; const hist = d.macd.hist;
  const macdEl = document.getElementById('md-macd');
  const macdLbl = document.getElementById('md-macd-label');
  macdEl.textContent = macd != null ? macd.toFixed(3) : '—';
  const bullish = hist != null && hist > 0;
  macdEl.className = `text-2xl font-bold font-mono ${bullish ? 'text-emerald-400' : 'text-red-400'}`;
  macdLbl.className = `text-xs font-semibold mt-1 ${bullish ? 'text-emerald-400' : 'text-red-400'}`;
  macdLbl.textContent = hist != null ? (bullish ? 'BULLISH' : 'BEARISH') : '';

  /* ─ Optimum Entry card ─ */
  const oe = d.optimum_entry;
  document.getElementById('md-entry').textContent = oe ? `$${fmt(oe.price)}` : '—';
  const sigEl = document.getElementById('md-entry-signal');
  sigEl.textContent = oe ? oe.signal : '';
  const sigColors = { 'BUY NOW': 'text-emerald-400', 'ACCUMULATE': 'text-green-400', 'WAIT': 'text-amber-400', 'OVERSOLD': 'text-brand-400' };
  sigEl.className = `text-xs font-bold mt-1 ${sigColors[oe?.signal] || 'text-slate-400'}`;
  document.getElementById('md-entry-basis').textContent = oe ? oe.basis : '';

  /* ─ Moving Averages ─ */
  const smaTips = {
    'SMA 50':  '50-day average closing price. Short-to-medium term trend. Active traders watch this closely for momentum shifts.',
    'SMA 100': '100-day average closing price. Medium-term trend. A price crossing above this line is often seen as a bullish signal.',
    'SMA 200': '200-day average closing price. The most important long-term trend line. Institutions and funds use this to define bull vs bear markets.',
  };
  const smaContainer = document.getElementById('md-smas');
  smaContainer.innerHTML = [['SMA 50', d.sma_50], ['SMA 100', d.sma_100], ['SMA 200', d.sma_200]].map(([lbl, val]) => {
    const above = val != null && close != null && close > val;
    const color = val == null ? 'text-slate-400' : above ? 'text-emerald-400' : 'text-red-400';
    const badge = val == null ? '' : above
      ? '<span class="text-xs font-bold text-emerald-400 bg-emerald-400/10 px-1.5 py-0.5 rounded">ABOVE ▲</span>'
      : '<span class="text-xs font-bold text-red-400 bg-red-400/10 px-1.5 py-0.5 rounded">BELOW ▼</span>';
    return `<div class="text-center">
      <span class="tip text-xs text-slate-500 mb-1 inline-block" data-tip="${smaTips[lbl]}">${lbl}<i class="tip-icon">i</i></span>
      <p class="text-lg font-bold font-mono ${color}">$${fmt(val)}</p>
      <div class="mt-1">${badge}</div>
    </div>`;
  }).join('');

  /* ─ Bollinger Bands ─ */
  const bb = d.bollinger_bands;
  const bbTips = {
    'Upper Band': 'Resistance level — price approaching here may be overbought and due for a pullback.',
    'Middle Band': 'The 5-day moving average. Acts as a neutral baseline between the upper and lower bands.',
    'Lower Band': 'Support level — price approaching here may be oversold and due for a bounce.',
  };
  document.getElementById('md-bb-values').innerHTML = [
    ['Upper Band', bb.upper, 'text-red-400'],
    ['Middle Band', bb.middle, 'text-slate-300'],
    ['Lower Band', bb.lower, 'text-emerald-400'],
  ].map(([lbl, val, color]) => `<div class="text-center">
    <span class="tip text-xs text-slate-500 mb-1 inline-block" data-tip="${bbTips[lbl]}">${lbl}<i class="tip-icon">i</i></span>
    <p class="text-lg font-bold font-mono ${color}">$${fmt(val)}</p>
  </div>`).join('');

  if (bb.upper != null && bb.lower != null && close != null) {
    const pct = Math.min(100, Math.max(0, ((close - bb.lower) / (bb.upper - bb.lower)) * 100));
    document.getElementById('md-bb-dot').style.left = `${pct}%`;
    const pos = pct > 80 ? 'Near Upper Band (overbought zone)' : pct < 20 ? 'Near Lower Band (oversold zone)' : 'Within Bands';
    document.getElementById('md-bb-pos-label').textContent = pos;
  }

  /* ─ Fibonacci ─ */
  const fibOrder = [['1.0', '100%'], ['0.618', '61.8%'], ['0.500', '50%'], ['0.382', '38.2%'], ['0.236', '23.6%'], ['0.0', '0%']];
  document.getElementById('md-fib').innerHTML = fibOrder.map(([key, label]) => {
    const price = d.fibonacci_levels[key];
    const isSupport = price != null && close != null && price < close;
    const isResist  = price != null && close != null && price > close;
    const isCurrent = price != null && close != null && Math.abs(price - close) / close < 0.02;
    const tag = isCurrent
      ? '<span class="text-xs font-bold text-brand-400 bg-brand-400/10 px-1.5 py-0.5 rounded">NEAR</span>'
      : isSupport
        ? '<span class="text-xs text-emerald-400/80 bg-emerald-400/10 px-1.5 py-0.5 rounded">Support</span>'
        : '<span class="text-xs text-red-400/80 bg-red-400/10 px-1.5 py-0.5 rounded">Resistance</span>';
    return `<div class="flex items-center justify-between py-1 border-b border-gray-800 last:border-0">
      <div class="flex items-center gap-2">
        <span class="text-xs text-slate-500 w-10">${label}</span>
        <span class="text-sm font-mono font-semibold text-slate-200">$${fmt(price)}</span>
      </div>
      ${tag}
    </div>`;
  }).join('');

  /* ─ Volume ─ */
  const vol = d.volume;
  const ratio = vol.ratio_vs_ma;
  const volColor = ratio == null ? 'text-slate-400' : ratio > 1.5 ? 'text-emerald-400' : ratio < 0.7 ? 'text-red-400' : 'text-slate-300';
  const volSignal = ratio == null ? '' : ratio > 1.5 ? 'HIGH VOLUME ▲' : ratio < 0.7 ? 'LOW VOLUME ▼' : 'AVERAGE';
  document.getElementById('md-volume').innerHTML = `
    <div class="flex justify-between items-center">
      <span class="tip text-xs text-slate-400" data-tip="The number of shares traded today. Compare this to the 20-day average to gauge interest.">Latest Volume<i class="tip-icon">i</i></span>
      <span class="text-sm font-mono font-semibold text-slate-200">${fmtK(vol.latest)}</span>
    </div>
    <div class="flex justify-between items-center">
      <span class="tip text-xs text-slate-400" data-tip="The average daily trading volume over the past 20 days. This is the baseline for judging whether today's volume is high or low.">20-Day Avg Volume<i class="tip-icon">i</i></span>
      <span class="text-sm font-mono font-semibold text-slate-200">${fmtK(vol.ma_20)}</span>
    </div>
    <div class="flex justify-between items-center">
      <span class="tip text-xs text-slate-400" data-tip="Today's volume divided by the 20-day average. Above 1.5× = high conviction move. Below 0.7× = low interest. A big price move on high volume is more reliable than one on low volume.">Ratio vs 20-Day Avg<i class="tip-icon">i</i></span>
      <span class="text-sm font-mono font-semibold ${volColor}">${ratio != null ? ratio.toFixed(2) + 'x' : '—'}</span>
    </div>
    ${volSignal ? `<div class="mt-2 text-center"><span class="text-xs font-bold ${volColor} bg-gray-800 px-3 py-1 rounded-full">${volSignal}</span></div>` : ''}
  `;
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
