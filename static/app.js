/* ── Theme ──────────────────────────────────────────────────────────────── */
function isDark() { return document.documentElement.classList.contains('dark'); }

function toggleTheme() {
  const dark = document.documentElement.classList.toggle('dark');
  try { localStorage.setItem('theme', dark ? 'dark' : 'light'); } catch (e) {}
  if (_currentChartTicker) loadChart(_currentChartTicker, _currentChartPeriod);
}

/* ── Clock ──────────────────────────────────────────────────────────────── */
function updateClock() {
  const el = document.getElementById('clock');
  if (el) el.textContent = new Date().toUTCString().replace('GMT', 'UTC');
}
updateClock();
setInterval(updateClock, 1000);

/* ── Section navigation ─────────────────────────────────────────────────── */
function showSection(name) {
  ['portfolio', 'research', 'reports'].forEach(s => {
    document.getElementById(`section-${s}`).classList.toggle('hidden', s !== name);
  });
  document.querySelectorAll('[data-nav]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.nav === name);
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

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
  const colours = { info: 'bg-accent', error: 'bg-neg', success: 'bg-pos' };
  const toast = document.createElement('div');
  toast.className = `fixed bottom-5 right-5 z-[100] px-4 py-3 rounded-lg text-white text-sm shadow-xl ${colours[type] || colours.info} transition-opacity`;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 400); }, 3500);
}

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

/* ── Portfolio Table ──────────────────────────────────────────────────────── */
function pnlCell(val, prefix = '$') {
  if (val == null) return `<td class="px-4 py-3 text-right tabular-nums text-muted">—</td>`;
  const cls = val >= 0 ? 'text-pos' : 'text-neg';
  const sign = val >= 0 ? '+' : '-';
  const abs = Math.abs(val).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
  return `<td class="px-4 py-3 text-right tabular-nums font-medium ${cls}">${sign}${prefix}${abs}</td>`;
}

function pctCell(val) {
  if (val == null) return `<td class="px-4 py-3 text-right tabular-nums text-muted">—</td>`;
  const cls = val >= 0 ? 'text-pos' : 'text-neg';
  const sign = val >= 0 ? '+' : '';
  return `<td class="px-4 py-3 text-right tabular-nums font-medium ${cls}">${sign}${val.toFixed(2)}%</td>`;
}

async function loadPortfolio() {
  const tbody = document.getElementById('portfolio-body');
  const summary = document.getElementById('portfolio-summary');
  try {
    const positions = await apiFetch('/api/portfolio/enriched');
    if (!positions.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center py-10 text-muted text-sm">No positions yet. Click "+ Add Position" to get started.</td></tr>';
      summary.classList.add('hidden');
      return;
    }

    const rows = positions.map(p => {
      const currentPrice = p.current_price != null
        ? `$${p.current_price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`
        : '<span class="text-muted">—</span>';
      return `
        <tr class="border-b border-line last:border-0 hover:bg-surface2/60 transition">
          <td class="px-4 py-3 font-mono font-semibold text-accent">${p.ticker}</td>
          <td class="px-4 py-3 text-right tabular-nums text-ink">${Number(p.shares).toLocaleString(undefined, {maximumFractionDigits: 4})}</td>
          <td class="px-4 py-3 text-right tabular-nums text-muted">$${Number(p.average_buy_price).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
          <td class="px-4 py-3 text-right tabular-nums text-ink">${currentPrice}</td>
          ${pnlCell(p.unrealised_pnl)}
          ${pctCell(p.return_pct)}
          <td class="px-4 py-3 text-muted text-xs">${new Date(p.date_added).toLocaleDateString()}</td>
          <td class="px-4 py-3 text-center">
            <button onclick="deletePosition('${p.ticker}')"
                    class="px-2.5 py-1 text-xs rounded-md text-neg hover:bg-neg/10 transition">Remove</button>
          </td>
        </tr>`;
    }).join('');

    tbody.innerHTML = rows;

    // Summary strip
    const totalValue = positions.reduce((s, p) => p.current_value != null ? s + p.current_value : s, 0);
    const totalPnl   = positions.reduce((s, p) => p.unrealised_pnl != null ? s + p.unrealised_pnl : s, 0);
    const totalCost  = positions.reduce((s, p) => s + (p.average_buy_price * p.shares), 0);
    const totalRet   = totalCost > 0 ? (totalPnl / totalCost) * 100 : null;
    const hasLive    = positions.some(p => p.current_price != null);

    if (hasLive) {
      summary.classList.remove('hidden');
      document.getElementById('sum-value').textContent = `$${fmt(totalValue)}`;
      const pnlEl = document.getElementById('sum-pnl');
      pnlEl.textContent = `${totalPnl >= 0 ? '+' : '-'}$${fmt(Math.abs(totalPnl))}`;
      pnlEl.className = `text-xl font-semibold mt-1 font-mono ${totalPnl >= 0 ? 'text-pos' : 'text-neg'}`;
      const retEl = document.getElementById('sum-return');
      retEl.textContent = totalRet != null ? `${totalRet >= 0 ? '+' : ''}${totalRet.toFixed(2)}%` : '—';
      retEl.className = `text-xl font-semibold mt-1 font-mono ${totalRet >= 0 ? 'text-pos' : 'text-neg'}`;
      document.getElementById('sum-count').textContent = positions.length;
    } else {
      summary.classList.add('hidden');
    }
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-10 text-neg text-sm">${e.message}</td></tr>`;
    summary.classList.add('hidden');
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

/* ── Price Chart ─────────────────────────────────────────────────────────── */
let _priceChart = null, _volumeChart = null;
let _currentChartTicker = null, _currentChartPeriod = '6mo';

function chartTheme() {
  const dark = isDark();
  return {
    text: dark ? '#94a3b8' : '#64748b',
    grid: dark ? '#2a2f39' : '#eef0f4',
    border: dark ? '#2a2f39' : '#e2e6ec',
    up:   dark ? '#34d399' : '#16a34a',
    down: dark ? '#f87171' : '#dc2626',
  };
}

function setChartPeriod(period) {
  _currentChartPeriod = period;
  document.querySelectorAll('.chart-period-btn').forEach(btn => {
    const active = btn.dataset.period === period;
    btn.className = `chart-period-btn px-2.5 py-1 text-xs rounded-md transition ${active ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:bg-surface2'}`;
  });
  if (_currentChartTicker) loadChart(_currentChartTicker, period);
}

async function loadChart(ticker, period = _currentChartPeriod) {
  try {
    const data = await apiFetch(`/api/chart/${ticker}?period=${period}`);
    renderChart(data);
  } catch (e) {
    console.warn('Chart load failed:', e.message);
  }
}

function renderChart(data) {
  const priceEl  = document.getElementById('price-chart');
  const volumeEl = document.getElementById('volume-chart');
  const t = chartTheme();

  if (_priceChart)  { _priceChart.remove();  _priceChart  = null; }
  if (_volumeChart) { _volumeChart.remove(); _volumeChart = null; }

  const chartOpts = {
    layout: { background: { color: 'transparent' }, textColor: t.text },
    grid:   { vertLines: { color: t.grid }, horzLines: { color: t.grid } },
    crosshair: { mode: 1 },
    rightPriceScale: { borderColor: t.border },
    timeScale: { borderColor: t.border, timeVisible: false },
  };

  _priceChart = LightweightCharts.createChart(priceEl, { ...chartOpts, height: 320 });
  const candleSeries = _priceChart.addCandlestickSeries({
    upColor: t.up, downColor: t.down,
    borderUpColor: t.up, borderDownColor: t.down,
    wickUpColor: t.up, wickDownColor: t.down,
  });
  candleSeries.setData(data.candles);

  const sma50s  = _priceChart.addLineSeries({ color: '#f59e0b', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
  const sma100s = _priceChart.addLineSeries({ color: '#ea580c', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
  const sma200s = _priceChart.addLineSeries({ color: '#dc2626', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
  sma50s.setData(data.sma50);
  sma100s.setData(data.sma100);
  sma200s.setData(data.sma200);
  _priceChart.timeScale().fitContent();

  _volumeChart = LightweightCharts.createChart(volumeEl, {
    ...chartOpts,
    height: 90,
    rightPriceScale: { borderColor: t.border, scaleMargins: { top: 0.1, bottom: 0 } },
  });
  const volData = data.volume.map(v => ({
    time: v.time, value: v.value,
    color: v.color === '#26a69a' ? t.up : t.down,
  }));
  const volSeries = _volumeChart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '' });
  volSeries.setData(volData);
  _volumeChart.timeScale().fitContent();

  _priceChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
    if (range) _volumeChart.timeScale().setVisibleLogicalRange(range);
  });
  _volumeChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
    if (range) _priceChart.timeScale().setVisibleLogicalRange(range);
  });
}

/* ── Research ────────────────────────────────────────────────────────────── */
function toggleDetails() {
  const body = document.getElementById('details-body');
  const chevron = document.getElementById('details-chevron');
  const open = body.classList.toggle('hidden');
  chevron.style.transform = open ? '' : 'rotate(180deg)';
}

async function runResearch() {
  const raw = document.getElementById('research-input').value.trim().toUpperCase();
  if (!raw) { showToast('Enter a ticker symbol first.', 'error'); return; }

  const spinner = document.getElementById('research-spinner');
  spinner.classList.remove('hidden');

  try {
    const d = await apiFetch(`/api/indicators/${raw}`);
    renderSummary(d);
    renderDetails(d);

    _currentChartTicker = raw;
    _currentChartPeriod = '6mo';
    document.querySelectorAll('.chart-period-btn').forEach(btn => {
      const active = btn.dataset.period === '6mo';
      btn.className = `chart-period-btn px-2.5 py-1 text-xs rounded-md transition ${active ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:bg-surface2'}`;
    });
    loadChart(raw, '6mo');

    // Reset AI analysis panel for the new ticker
    document.getElementById('analysis-result').classList.add('hidden');
    document.getElementById('analysis-placeholder').classList.remove('hidden');

    document.getElementById('research-empty').classList.add('hidden');
    document.getElementById('research-result').classList.remove('hidden');
  } catch (e) {
    showToast(`Lookup failed: ${e.message}`, 'error');
  } finally {
    spinner.classList.add('hidden');
  }
}

function renderSummary(d) {
  const close = d.latest_close;
  document.getElementById('rs-ticker').textContent = d.ticker;
  document.getElementById('rs-price').textContent = `$${fmt(close)}`;
  document.getElementById('rs-range').textContent =
    `52-week range: $${fmt(d['52_week_low'])} – $${fmt(d['52_week_high'])}`;

  /* ─ Overall signal (derived from existing indicators) ─ */
  const rsi = d.rsi_14;
  const hist = d.macd?.hist;
  let score = 0;
  if (close != null && d.sma_50 != null)  score += close > d.sma_50 ? 1 : -1;
  if (close != null && d.sma_200 != null) score += close > d.sma_200 ? 1 : -1;
  if (hist != null) score += hist > 0 ? 1 : -1;
  if (rsi != null) { if (rsi > 70) score -= 1; else if (rsi < 30) score += 1; }

  let label, cls, note;
  if (score >= 2)      { label = 'Bullish'; cls = 'text-pos bg-pos/10'; note = 'Price and momentum are trending upward.'; }
  else if (score <= -2){ label = 'Bearish'; cls = 'text-neg bg-neg/10'; note = 'Price and momentum are trending downward.'; }
  else                 { label = 'Neutral'; cls = 'text-muted bg-surface2'; note = 'Mixed signals — no clear trend right now.'; }
  document.getElementById('rs-signal').innerHTML =
    `<span class="inline-block px-3 py-1 rounded-full text-sm font-bold ${cls}">${label}</span>`;
  document.getElementById('rs-signal-note').textContent = note;

  /* ─ Momentum (RSI) ─ */
  const rsiEl = document.getElementById('rs-rsi');
  const rsiLbl = document.getElementById('rs-rsi-label');
  rsiEl.textContent = rsi != null ? rsi.toFixed(1) : '—';
  if (rsi == null) { rsiEl.className = 'text-lg font-bold font-mono mt-1 text-muted'; rsiLbl.textContent = ''; }
  else if (rsi < 30) { rsiEl.className = 'text-lg font-bold font-mono mt-1 text-pos'; rsiLbl.className = 'text-xs font-semibold text-pos'; rsiLbl.textContent = 'Oversold'; }
  else if (rsi < 45) { rsiEl.className = 'text-lg font-bold font-mono mt-1 text-ink'; rsiLbl.className = 'text-xs font-semibold text-muted'; rsiLbl.textContent = 'Weak'; }
  else if (rsi < 55) { rsiEl.className = 'text-lg font-bold font-mono mt-1 text-ink'; rsiLbl.className = 'text-xs font-semibold text-muted'; rsiLbl.textContent = 'Neutral'; }
  else if (rsi < 70) { rsiEl.className = 'text-lg font-bold font-mono mt-1 text-ink'; rsiLbl.className = 'text-xs font-semibold text-muted'; rsiLbl.textContent = 'Strong'; }
  else { rsiEl.className = 'text-lg font-bold font-mono mt-1 text-neg'; rsiLbl.className = 'text-xs font-semibold text-neg'; rsiLbl.textContent = 'Overbought'; }

  /* ─ Trend (MACD) ─ */
  const trendEl = document.getElementById('rs-trend');
  const trendLbl = document.getElementById('rs-trend-label');
  const bullish = hist != null && hist > 0;
  trendEl.textContent = d.macd?.macd != null ? d.macd.macd.toFixed(2) : '—';
  trendEl.className = `text-lg font-bold font-mono mt-1 ${hist == null ? 'text-muted' : bullish ? 'text-pos' : 'text-neg'}`;
  trendLbl.className = `text-xs font-semibold ${bullish ? 'text-pos' : 'text-neg'}`;
  trendLbl.textContent = hist != null ? (bullish ? 'Upward' : 'Downward') : '';

  /* ─ Suggested entry ─ */
  const oe = d.optimum_entry;
  document.getElementById('rs-entry').textContent = oe ? `$${fmt(oe.price)}` : '—';
  const entryLbl = document.getElementById('rs-entry-label');
  entryLbl.textContent = oe ? oe.signal : '';
  entryLbl.className = 'text-xs font-semibold text-accent';
}

function renderDetails(d) {
  const close = d.latest_close;

  /* ─ Moving Averages ─ */
  const smaTips = {
    'SMA 50':  '50-day average closing price. Short-to-medium term trend. Active traders watch this closely for momentum shifts.',
    'SMA 100': '100-day average closing price. Medium-term trend. A price crossing above this line is often seen as a bullish signal.',
    'SMA 200': '200-day average closing price. The most important long-term trend line. Institutions use this to define bull vs bear markets.',
  };
  const smaContainer = document.getElementById('md-smas');
  smaContainer.innerHTML = [['SMA 50', d.sma_50], ['SMA 100', d.sma_100], ['SMA 200', d.sma_200]].map(([lbl, val]) => {
    const above = val != null && close != null && close > val;
    const color = val == null ? 'text-muted' : above ? 'text-pos' : 'text-neg';
    const badge = val == null ? '' : above
      ? '<span class="text-xs font-bold text-pos bg-pos/10 px-1.5 py-0.5 rounded">ABOVE ▲</span>'
      : '<span class="text-xs font-bold text-neg bg-neg/10 px-1.5 py-0.5 rounded">BELOW ▼</span>';
    return `<div class="text-center">
      <span class="tip text-xs text-muted mb-1 inline-block" data-tip="${smaTips[lbl]}">${lbl}<i class="tip-icon">i</i></span>
      <p class="text-lg font-bold font-mono ${color}">$${fmt(val)}</p>
      <div class="mt-1">${badge}</div>
    </div>`;
  }).join('');

  /* ─ Bollinger Bands ─ */
  const bb = d.bollinger_bands;
  const bbTips = {
    'Upper': 'Resistance level — price approaching here may be overbought and due for a pullback.',
    'Middle': 'The moving-average baseline between the upper and lower bands.',
    'Lower': 'Support level — price approaching here may be oversold and due for a bounce.',
  };
  document.getElementById('md-bb-values').innerHTML = [
    ['Upper', bb.upper, 'text-neg'],
    ['Middle', bb.middle, 'text-ink'],
    ['Lower', bb.lower, 'text-pos'],
  ].map(([lbl, val, color]) => `<div class="text-center">
    <span class="tip text-xs text-muted mb-1 inline-block" data-tip="${bbTips[lbl]}">${lbl}<i class="tip-icon">i</i></span>
    <p class="text-lg font-bold font-mono ${color}">$${fmt(val)}</p>
  </div>`).join('');

  if (bb.upper != null && bb.lower != null && close != null) {
    const pct = Math.min(100, Math.max(0, ((close - bb.lower) / (bb.upper - bb.lower)) * 100));
    document.getElementById('md-bb-dot').style.left = `${pct}%`;
    const pos = pct > 80 ? 'Near upper band (overbought zone)' : pct < 20 ? 'Near lower band (oversold zone)' : 'Within bands';
    document.getElementById('md-bb-pos-label').textContent = pos;
  }

  /* ─ Fibonacci ─ */
  const fibOrder = [['1.0', '100%'], ['0.618', '61.8%'], ['0.500', '50%'], ['0.382', '38.2%'], ['0.236', '23.6%'], ['0.0', '0%']];
  document.getElementById('md-fib').innerHTML = fibOrder.map(([key, label]) => {
    const price = d.fibonacci_levels[key];
    const isSupport = price != null && close != null && price < close;
    const isCurrent = price != null && close != null && Math.abs(price - close) / close < 0.02;
    const tag = isCurrent
      ? '<span class="text-xs font-bold text-accent bg-accent-soft px-1.5 py-0.5 rounded">NEAR</span>'
      : isSupport
        ? '<span class="text-xs text-pos bg-pos/10 px-1.5 py-0.5 rounded">Support</span>'
        : '<span class="text-xs text-neg bg-neg/10 px-1.5 py-0.5 rounded">Resistance</span>';
    return `<div class="flex items-center justify-between py-1 border-b border-line last:border-0">
      <div class="flex items-center gap-2">
        <span class="text-xs text-muted w-10">${label}</span>
        <span class="text-sm font-mono font-semibold text-ink">$${fmt(price)}</span>
      </div>
      ${tag}
    </div>`;
  }).join('');

  /* ─ Volume ─ */
  const vol = d.volume;
  const ratio = vol.ratio_vs_ma;
  const volColor = ratio == null ? 'text-muted' : ratio > 1.5 ? 'text-pos' : ratio < 0.7 ? 'text-neg' : 'text-ink';
  const volSignal = ratio == null ? '' : ratio > 1.5 ? 'HIGH VOLUME ▲' : ratio < 0.7 ? 'LOW VOLUME ▼' : 'AVERAGE';
  document.getElementById('md-volume').innerHTML = `
    <div class="flex justify-between items-center">
      <span class="tip text-xs text-muted" data-tip="The number of shares traded today. Compare this to the 20-day average to gauge interest.">Latest Volume<i class="tip-icon">i</i></span>
      <span class="text-sm font-mono font-semibold text-ink">${fmtK(vol.latest)}</span>
    </div>
    <div class="flex justify-between items-center">
      <span class="tip text-xs text-muted" data-tip="The average daily trading volume over the past 20 days — the baseline for judging today's volume.">20-Day Avg Volume<i class="tip-icon">i</i></span>
      <span class="text-sm font-mono font-semibold text-ink">${fmtK(vol.ma_20)}</span>
    </div>
    <div class="flex justify-between items-center">
      <span class="tip text-xs text-muted" data-tip="Today's volume vs the 20-day average. Above 1.5× = high conviction. Below 0.7× = low interest.">Ratio vs Average<i class="tip-icon">i</i></span>
      <span class="text-sm font-mono font-semibold ${volColor}">${ratio != null ? ratio.toFixed(2) + 'x' : '—'}</span>
    </div>
    ${volSignal ? `<div class="mt-2 text-center"><span class="text-xs font-bold ${volColor} bg-surface2 px-3 py-1 rounded-full">${volSignal}</span></div>` : ''}
  `;
}

/* ── AI Analysis ─────────────────────────────────────────────────────────── */
async function runAnalysis() {
  if (!_currentChartTicker) { showToast('Search a ticker first.', 'error'); return; }
  const raw = _currentChartTicker;
  const spinner = document.getElementById('analyze-spinner');
  const resultEl = document.getElementById('analysis-result');
  const placeholderEl = document.getElementById('analysis-placeholder');
  const labelEl = document.getElementById('analysis-ticker-label');
  const bodyEl = document.getElementById('analysis-body');

  spinner.classList.remove('hidden');

  try {
    const data = await apiFetch(`/api/analyze/${raw}`);
    labelEl.textContent = `Analysis for ${data.ticker} — ${new Date().toLocaleString()}`;
    bodyEl.innerHTML = marked.parse(data.report);
    placeholderEl.classList.add('hidden');
    resultEl.classList.remove('hidden');
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
