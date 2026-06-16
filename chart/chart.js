// Reads state.json (candles + levels + zones + bias) and renders the marked chart.
const chart = LightweightCharts.createChart(document.getElementById('chart'), {
  layout: { background: { color: '#0e1116' }, textColor: '#c9d1d9' },
  grid: { vertLines: { color: '#161b22' }, horzLines: { color: '#161b22' } },
  timeScale: { timeVisible: true },
});
const candles = chart.addCandlestickSeries({
  upColor: '#3fb950', downColor: '#f85149',
  wickUpColor: '#3fb950', wickDownColor: '#f85149', borderVisible: false,
});

const COLORS = { high: '#f85149', low: '#3fb950', pdh: '#f0883e', pdl: '#f0883e' };

function setBias(b) {
  // b is the per-TF confluence bias map {W,D,H4} with values UP/DOWN/FLAT.
  const cls = { UP: 'up', DOWN: 'down', FLAT: 'none' };
  for (const [id, key] of [['biasW', 'W'], ['biasD', 'D'], ['biasH4', 'H4']]) {
    const el = document.getElementById(id);
    const v = (b && b[key]) ? b[key] : null;
    el.textContent = v ? v.toLowerCase() : '—';
    el.className = v ? (cls[v] || 'none') : 'none';
  }
}

async function refresh() {
  let s;
  try { s = await (await fetch('state.json?t=' + Date.now())).json(); }
  catch (e) { return; }

  if (s.candles) {
    candles.setData(s.candles); // [{time, open, high, low, close}]
  }
  (window._lines || []).forEach(l => candles.removePriceLine(l));
  window._lines = (s.levels || []).map(lv => candles.createPriceLine({
    price: lv.price,
    color: COLORS[lv.source] || COLORS[lv.side] || '#9aa4b2',
    lineStyle: LightweightCharts.LineStyle.Dashed,
    lineWidth: 1,
    title: lv.source,
  }));

  setBias(s.bias_tf);

  // AOI bands colored by confluence label. no-trade AOIs are shown faint+dotted
  // (still being tracked, just not actionable) rather than hidden.
  (window._aoiLines || []).forEach(l => candles.removePriceLine(l));
  const LABEL_COLOR = { 'A+': '#3fb950', 'valid': '#58a6ff', 'weak': '#6e7681', 'no-trade': '#4a525c' };
  window._aoiLines = (s.aois || []).map(a => {
    const isNoTrade = a.label === 'no-trade';
    return candles.createPriceLine({
      price: a.proximal,
      color: LABEL_COLOR[a.label] || '#6e7681',
      lineWidth: a.label === 'A+' ? 2 : 1,
      lineStyle: isNoTrade ? LightweightCharts.LineStyle.Dotted : LightweightCharts.LineStyle.Solid,
      title: `${a.label} ${a.source}`,
    });
  });

  const a = document.getElementById('alert');
  if (s.last_alert && s.last_alert.text) {
    a.textContent = s.last_alert.text + (s.last_alert.time ? '  (' + s.last_alert.time + ')' : '');
    a.className = 'alert';
  }
  document.getElementById('updated').textContent = 'updated ' + (s.updated_at || '');
}

refresh();
setInterval(refresh, 15000);
