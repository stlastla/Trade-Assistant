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
  for (const [id, key] of [['daily', 'daily_dir'], ['h4', 'h4_dir'], ['mom', 'mom14_dir']]) {
    const el = document.getElementById(id);
    const v = b ? b[key] : 'none';
    el.textContent = v;
    el.className = v;
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

  setBias(s.bias);
  const a = document.getElementById('alert');
  if (s.last_alert && s.last_alert.text) {
    a.textContent = s.last_alert.text + (s.last_alert.time ? '  (' + s.last_alert.time + ')' : '');
    a.className = 'alert';
  }
  document.getElementById('updated').textContent = 'updated ' + (s.updated_at || '');
}

refresh();
setInterval(refresh, 15000);
