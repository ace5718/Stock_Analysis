const API = "";
let selectedSymbol = null;
let chart = null;
let candleSeries = null;
let volumeSeries = null;
let ma5Series = null;
let ma20Series = null;
let ws = null;

async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

function fmtPct(n) {
  const cls = n >= 0 ? "up" : "down";
  const sign = n >= 0 ? "+" : "";
  return `<span class="${cls}">${sign}${Number(n).toFixed(2)}%</span>`;
}

async function loadSettings() {
  const s = await api("/api/settings");
  const sel = document.getElementById("ai-engine");
  if (sel) sel.value = s.ai_engine || "openai";
  const mode = document.getElementById("order-mode");
  if (mode) mode.value = s.order_mode || "notify_confirm";
  return s;
}

async function loadWatchlist() {
  const list = await api("/api/watchlist");
  const el = document.getElementById("watchlist");
  if (!el) return list;
  el.innerHTML = list
    .map(
      (w) =>
        `<div class="watch-item" data-symbol="${w.symbol}">
          <div class="sym">${w.symbol}</div>
          <div class="quote-line" id="q-${w.symbol}">—</div>
        </div>`
    )
    .join("");
  el.querySelectorAll(".watch-item").forEach((item) => {
    item.addEventListener("click", () => selectSymbol(item.dataset.symbol));
  });
  if (list.length && !selectedSymbol) selectSymbol(list[0].symbol);
  return list;
}

function selectSymbol(sym) {
  selectedSymbol = sym;
  document.querySelectorAll(".watch-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.symbol === sym);
  });
  loadChart(sym);
  loadAnalysis(sym);
}

function updateQuote(q) {
  const line = document.getElementById(`q-${q.symbol}`);
  if (!line) return;
  const cls = q.change >= 0 ? "up" : "down";
  line.innerHTML = `${q.price} <span class="${cls}">${q.change >= 0 ? "+" : ""}${q.change} (${q.change_percent}%)</span>`;
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/quotes`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "quote") updateQuote(msg.data);
    if (msg.type === "indicators" && msg.symbol === selectedSymbol) {
      renderIndicators(msg.data, msg.triggers);
    }
    if (msg.type === "analysis" && msg.symbol === selectedSymbol) {
      renderAnalysis(msg.data, msg.analyzed_at, msg.cached);
    }
    if (msg.type === "pending_order" || msg.type === "trade") {
      refreshPortfolio();
      refreshPending();
    }
  };
  ws.onclose = () => setTimeout(connectWs, 3000);
}

function renderIndicators(ind, triggers) {
  const bar = document.getElementById("indicators-bar");
  if (!bar) return;
  bar.innerHTML = `
    RSI: ${ind.rsi?.toFixed(1) ?? "—"}
    MACD: ${ind.macd_hist?.toFixed(3) ?? "—"}
    量比: ${ind.volume_ratio?.toFixed(2) ?? "—"}x
    ${(triggers || []).map((t) => `<span class="signal-tag">${t.label}</span>`).join("")}
  `;
}

function renderAnalysis(data, at, cached) {
  const el = document.getElementById("ai-panel");
  if (!el || !data) return;
  const dirMap = { buy: "買進", sell: "賣出", hold: "觀望" };
  const confMap = { high: "高", medium: "中", low: "低" };
  el.innerHTML = `
    <p><strong>建議：</strong>${dirMap[data.direction] || data.direction}
       <strong>信心：</strong>${confMap[data.confidence] || data.confidence}
       ${cached ? "(快取)" : ""}</p>
    <p>${data.reason || ""}</p>
    <p class="disclaimer">${data.disclaimer || ""}</p>
    <p class="disclaimer">上次分析：${at ? new Date(at).toLocaleString() : "—"}</p>
  `;
}

async function loadAnalysis(sym) {
  try {
    const c = await api(`/api/analysis/${sym}`);
    renderAnalysis(c.result, c.analyzed_at, true);
  } catch {
    const el = document.getElementById("ai-panel");
    if (el) el.innerHTML = "<p>尚無分析，待觸發訊號或按「立即分析」</p>";
  }
}

async function loadChart(sym) {
  const { candles } = await api(`/api/klines/${sym}?days=120`);
  if (!chart) initChart();
  const data = candles.map((c) => ({
    time: c.time,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));
  candleSeries.setData(data);
  volumeSeries.setData(
    candles.map((c) => ({ time: c.time, value: c.volume, color: c.close >= c.open ? "#f8514966" : "#3fb95066" }))
  );
  const ma5 = candles.filter((_, i, a) => i >= 4).map((c, i, a) => {
    const slice = a.slice(i, i + 5);
    if (slice.length < 5) return null;
    const avg = slice.reduce((s, x) => s + x.close, 0) / 5;
    return { time: c.time, value: avg };
  }).filter(Boolean);
  const ma20 = candles.map((c, i, a) => {
    if (i < 19) return null;
    const slice = a.slice(i - 19, i + 1);
    const avg = slice.reduce((s, x) => s + x.close, 0) / 20;
    return { time: c.time, value: avg };
  }).filter(Boolean);
  ma5Series.setData(ma5);
  ma20Series.setData(ma20);
}

function initChart() {
  const el = document.getElementById("chart");
  if (!el || !window.LightweightCharts) return;
  chart = LightweightCharts.createChart(el, {
    layout: { background: { color: "#161b22" }, textColor: "#8b949e" },
    grid: { vertLines: { color: "#30363d" }, horzLines: { color: "#30363d" } },
    width: el.clientWidth,
    height: 320,
  });
  candleSeries = chart.addCandlestickSeries({
    upColor: "#f85149",
    downColor: "#3fb950",
    borderVisible: false,
    wickUpColor: "#f85149",
    wickDownColor: "#3fb950",
  });
  volumeSeries = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "" });
  chart.priceScale("").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  ma5Series = chart.addLineSeries({ color: "#58a6ff", lineWidth: 1 });
  ma20Series = chart.addLineSeries({ color: "#d29922", lineWidth: 1 });
  window.addEventListener("resize", () => chart.applyOptions({ width: el.clientWidth }));
}

async function refreshPending() {
  const el = document.getElementById("pending-orders");
  if (!el) return;
  try {
    const orders = await api("/api/pending-orders");
    if (!orders.length) {
      el.innerHTML = "";
      return;
    }
    el.innerHTML =
      "<h4>待確認下單</h4>" +
      orders
        .map(
          (o) =>
            `<div class="form-row">${o.symbol} ${o.side} ${o.qty}股 @${o.price}
            <button data-id="${o.id}" class="btn-confirm">確認</button>
            <button data-id="${o.id}" class="btn-reject">拒絕</button></div>`
        )
        .join("");
    el.querySelectorAll(".btn-confirm").forEach((b) =>
      b.addEventListener("click", async () => {
        await api(`/api/pending-orders/${b.dataset.id}/confirm`, { method: "POST" });
        refreshPending();
        refreshPortfolio();
      })
    );
    el.querySelectorAll(".btn-reject").forEach((b) =>
      b.addEventListener("click", async () => {
        await api(`/api/pending-orders/${b.dataset.id}`, { method: "DELETE" });
        refreshPending();
      })
    );
  } catch {
    el.innerHTML = "";
  }
}

async function refreshPortfolio() {
  const p = await api("/api/portfolio");
  const el = document.getElementById("portfolio-summary");
  if (!el) return;
  const u = p.unrealized_pnl;
  const cls = u >= 0 ? "up" : "down";
  el.innerHTML = `
    虛擬資金：NT$${p.cash.toLocaleString()}
    總權益：NT$${p.total_equity.toLocaleString()}
    未實現：<span class="${cls}">NT$${u.toLocaleString()} (${p.positions[0]?.unrealized_pct || 0}%)</span>
  `;
}

document.addEventListener("DOMContentLoaded", async () => {
  if (document.getElementById("watchlist")) {
    await loadSettings();
    await loadWatchlist();
    connectWs();
    refreshPortfolio();
    refreshPending();
    document.getElementById("btn-analyze")?.addEventListener("click", async () => {
      if (!selectedSymbol) return;
      await api(`/api/analyze/${selectedSymbol}`, { method: "POST" });
      await loadAnalysis(selectedSymbol);
    });
    document.getElementById("ai-engine")?.addEventListener("change", async (e) => {
      await api("/api/settings", {
        method: "PATCH",
        body: JSON.stringify({ ai_engine: e.target.value }),
      });
    });
    document.getElementById("order-mode")?.addEventListener("change", async (e) => {
      await api("/api/settings", {
        method: "PATCH",
        body: JSON.stringify({ order_mode: e.target.value }),
      });
    });
    document.getElementById("btn-buy")?.addEventListener("click", async () => {
      const qty = parseInt(document.getElementById("trade-qty").value, 10);
      if (!selectedSymbol || !qty) return;
      await api("/api/trades", {
        method: "POST",
        body: JSON.stringify({ symbol: selectedSymbol, side: "buy", qty }),
      });
      refreshPortfolio();
    });
    document.getElementById("btn-sell")?.addEventListener("click", async () => {
      const qty = parseInt(document.getElementById("trade-qty").value, 10);
      if (!selectedSymbol || !qty) return;
      await api("/api/trades", {
        method: "POST",
        body: JSON.stringify({ symbol: selectedSymbol, side: "sell", qty }),
      });
      refreshPortfolio();
    });
    document.getElementById("btn-add-watch")?.addEventListener("click", async () => {
      const sym = document.getElementById("new-symbol").value.trim();
      if (!sym) return;
      await api("/api/watchlist", { method: "POST", body: JSON.stringify({ symbol: sym }) });
      document.getElementById("new-symbol").value = "";
      await loadWatchlist();
    });
  }
});

export { api, loadSettings, loadWatchlist, refreshPortfolio };
