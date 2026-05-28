const API = "";
let currentMarket = localStorage.getItem("market") || "tw";
let selectedSymbol = null;
let chart = null;
let candleSeries = null;
let volumeSeries = null;
let ma5Series = null;
let ma20Series = null;
let ws = null;
let portfolioRefreshTimer = null;
/** @type {Record<string, number>} */
const quotePrices = {};

const FEE_TW = 0.001425;
const TAX_TW = 0.003;
const FEE_CRYPTO = 0.001;

function marketQ() {
  return `market=${encodeURIComponent(currentMarket)}`;
}

async function api(path, opts = {}) {
  const sep = path.includes("?") ? "&" : "?";
  const needsMarket =
    path.startsWith("/api/") &&
    !path.includes("market=") &&
    !path.startsWith("/api/settings") &&
    !path.includes("/api/backtest");
  const url =
    API +
    path +
    (needsMarket && !path.match(/\/api\/(analyze|analysis|klines)\//)
      ? `${sep}${marketQ()}`
      : "");
  const r = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

function apiPath(path) {
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}${marketQ()}`;
}

function fmtPct(n) {
  const cls = n >= 0 ? "up" : "down";
  const sign = n >= 0 ? "+" : "";
  return `<span class="${cls}">${sign}${Number(n).toFixed(2)}%</span>`;
}

function isCrypto() {
  return currentMarket === "crypto";
}

function displaySymbol(sym) {
  if (isCrypto() && sym.endsWith("USDT")) return sym.replace("USDT", "");
  return sym;
}

function updateMarketUi() {
  document.querySelectorAll(".market-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.market === currentMarket);
  });
  const title = document.getElementById("page-title");
  if (title) {
    title.textContent = isCrypto() ? "虛擬貨幣 AI 模擬交易" : "台股 AI 模擬交易";
  }
  const input = document.getElementById("new-symbol");
  if (input) input.placeholder = isCrypto() ? "BTC" : "2330";
  const hint = document.getElementById("watch-hint");
  if (hint) {
    hint.textContent = isCrypto()
      ? "輸入 BTC、ETH 等（自動補 USDT），最多 5 檔"
      : "台股代號 4 碼，最多 5 檔";
  }
  const qtyInput = document.getElementById("trade-qty");
  const qtyLabel = document.getElementById("trade-qty-label");
  const qtyHint = document.getElementById("trade-qty-hint");
  if (qtyInput) {
    if (isCrypto()) {
      qtyInput.value = "0.01";
      qtyInput.step = "0.000001";
      qtyInput.min = "0.000001";
      if (qtyLabel) qtyLabel.textContent = "數量（顆）";
      if (qtyHint) {
        qtyHint.textContent =
          "虛擬貨幣為小數數量（例：0.01 BTC）。勿填 1000（那是台股張數）。";
      }
    } else {
      qtyInput.value = "1000";
      qtyInput.step = "1000";
      qtyInput.min = "1000";
      if (qtyLabel) qtyLabel.textContent = "股數";
      if (qtyHint) qtyHint.textContent = "台股須為 1000 股的整數倍（1 張 = 1000 股）。";
    }
  }
  updateTradeEstimate();
}

function fmtMoney(amount, currency) {
  const n = Number(amount);
  if (!Number.isFinite(n)) return "—";
  const digits = currency === "USDT" ? 2 : 0;
  return `${currency} ${n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

function updateTradeEstimate() {
  const el = document.getElementById("trade-estimate");
  if (!el) return;

  const qty = parseFloat(document.getElementById("trade-qty")?.value);
  const price = selectedSymbol ? quotePrices[selectedSymbol] : 0;
  const currency = isCrypto() ? "USDT" : "TWD";
  const unit = isCrypto() ? "顆" : "股";

  if (!selectedSymbol || !qty || qty <= 0) {
    el.innerHTML = "<span class='disclaimer'>輸入數量後顯示預估成交金額</span>";
    return;
  }
  if (!price || price <= 0) {
    el.innerHTML = `<span class="disclaimer">${displaySymbol(selectedSymbol)}：尚無報價，無法估算金額</span>`;
    return;
  }

  const notional = qty * price;
  const feeRate = isCrypto() ? FEE_CRYPTO : FEE_TW;
  const fee = notional * feeRate;
  const buyTotal = notional + fee;
  const sellTax = isCrypto() ? 0 : notional * TAX_TW;
  const sellNet = notional - fee - sellTax;

  const priceStr = isCrypto()
    ? `${Number(price).toLocaleString(undefined, { maximumFractionDigits: 4 })} USDT / ${unit}`
    : `${Number(price).toLocaleString()} TWD / ${unit}`;

  el.innerHTML = `
    <div><strong>${displaySymbol(selectedSymbol)}</strong>　單價約 ${priceStr}</div>
    <div class="est-row">
      <span class="est-buy">買進應付：${fmtMoney(buyTotal, currency)}
        <span class="disclaimer">（成交 ${fmtMoney(notional, currency)}＋手續費 ${fmtMoney(fee, currency)}）</span>
      </span>
      <span class="est-sell">賣出實收：${fmtMoney(sellNet, currency)}
        <span class="disclaimer">（成交 ${fmtMoney(notional, currency)}－手續費 ${fmtMoney(fee, currency)}${
          sellTax > 0 ? `－證交稅 ${fmtMoney(sellTax, currency)}` : ""
        }）</span>
      </span>
    </div>
  `;
}

async function syncQuotePrice(sym) {
  if (!sym) return;
  if (quotePrices[sym] > 0) {
    updateTradeEstimate();
    return;
  }
  try {
    const quotes = await api("/api/quotes");
    const p = quotes[sym]?.price;
    if (p) quotePrices[sym] = Number(p);
    updateTradeEstimate();
  } catch {
    updateTradeEstimate();
  }
}

async function fillMaxBuyQty() {
  if (!selectedSymbol) return;
  try {
    const d = await api(apiPath(`/api/trades/max-qty?symbol=${selectedSymbol}`));
    const el = document.getElementById("trade-qty");
    if (el && d.max_qty > 0) el.value = String(d.max_qty);
    if (d.price) quotePrices[selectedSymbol] = Number(d.price);
    updateTradeEstimate();
  } catch (e) {
    alert(e.message || "無法計算可買上限");
  }
}

async function submitTrade(side) {
  const qty = parseFloat(document.getElementById("trade-qty")?.value);
  if (!selectedSymbol || !qty) return;
  try {
    await api("/api/trades", {
      method: "POST",
      body: JSON.stringify({
        symbol: selectedSymbol,
        side,
        qty,
        market: currentMarket,
      }),
    });
    refreshPortfolio();
  } catch (e) {
    alert(e.message || "下單失敗");
  }
}

async function setMarket(market) {
  if (market === currentMarket) return;
  currentMarket = market;
  localStorage.setItem("market", market);
  selectedSymbol = null;
  updateMarketUi();
  if (ws) {
    ws.close();
    ws = null;
  }
  await loadWatchlist();
  connectWs();
  refreshPortfolio();
  refreshPending();
  updateTradeEstimate();
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
          <div class="sym">${displaySymbol(w.symbol)}</div>
          <div class="quote-line" id="q-${w.symbol}">—</div>
        </div>`
    )
    .join("");
  el.querySelectorAll(".watch-item").forEach((item) => {
    item.addEventListener("click", () => selectSymbol(item.dataset.symbol));
  });
  if (list.length && !selectedSymbol) selectSymbol(list[0].symbol);
  else if (selectedSymbol && !list.find((w) => w.symbol === selectedSymbol)) {
    selectedSymbol = list[0]?.symbol || null;
    if (selectedSymbol) selectSymbol(selectedSymbol);
  }
  return list;
}

function selectSymbol(sym) {
  selectedSymbol = sym;
  document.querySelectorAll(".watch-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.symbol === sym);
  });
  document.querySelectorAll(".positions-table tbody tr").forEach((el) => {
    el.classList.toggle("active", el.dataset.symbol === sym);
  });
  loadChart(sym);
  loadAnalysis(sym);
  syncQuotePrice(sym);
}

function updateQuote(q) {
  if (q.market && q.market !== currentMarket) return;
  if (q.price) quotePrices[q.symbol] = Number(q.price);
  const line = document.getElementById(`q-${q.symbol}`);
  if (!line) return;
  const cls = q.change >= 0 ? "up" : "down";
  const price = isCrypto() ? Number(q.price).toFixed(2) : q.price;
  line.innerHTML = `${price} <span class="${cls}">${q.change >= 0 ? "+" : ""}${q.change} (${q.change_percent}%)</span>`;
  if (q.symbol === selectedSymbol) updateTradeEstimate();
  schedulePortfolioRefresh();
}

function schedulePortfolioRefresh() {
  clearTimeout(portfolioRefreshTimer);
  portfolioRefreshTimer = setTimeout(() => refreshPortfolio(), 400);
}

function fmtQty(qty) {
  const n = Number(qty);
  if (!Number.isFinite(n)) return "—";
  return isCrypto()
    ? n.toLocaleString(undefined, { maximumFractionDigits: 6 })
    : n.toLocaleString();
}

function renderPositions(p) {
  const el = document.getElementById("positions-list");
  if (!el) return;
  const positions = p.positions || [];
  const cur = p.currency || (isCrypto() ? "USDT" : "TWD");

  if (!positions.length) {
    el.innerHTML = '<p class="positions-empty">目前無持倉</p>';
    return;
  }

  const unit = isCrypto() ? "顆" : "股";
  const costDigits = isCrypto() ? 4 : 2;
  const priceDigits = isCrypto() ? 4 : 2;

  el.innerHTML = `
    <table class="positions-table">
      <thead>
        <tr>
          <th>標的</th>
          <th>數量</th>
          <th>成本</th>
          <th>現價</th>
          <th>市值</th>
          <th>未實現</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        ${positions
          .map((pos) => {
            const u = pos.unrealized_pnl;
            const pct = pos.unrealized_pct;
            const cls = u >= 0 ? "up" : "down";
            const active = pos.symbol === selectedSymbol ? "active" : "";
            return `<tr class="${active}" data-symbol="${pos.symbol}" data-qty="${pos.qty}">
              <td><strong>${displaySymbol(pos.symbol)}</strong></td>
              <td>${fmtQty(pos.qty)} ${unit}</td>
              <td>${Number(pos.avg_cost).toLocaleString(undefined, {
                maximumFractionDigits: costDigits,
              })}</td>
              <td>${Number(pos.price).toLocaleString(undefined, {
                maximumFractionDigits: priceDigits,
              })}</td>
              <td>${cur} ${Number(pos.market_value).toLocaleString(undefined, {
                maximumFractionDigits: isCrypto() ? 2 : 0,
              })}</td>
              <td class="${cls}">${cur} ${Number(u).toLocaleString()}
                <span class="disclaimer">(${pct >= 0 ? "+" : ""}${pct}%)</span></td>
              <td><button type="button" class="btn-pos-sell" data-symbol="${pos.symbol}" data-qty="${pos.qty}">賣出</button></td>
            </tr>`;
          })
          .join("")}
      </tbody>
    </table>
  `;

  el.querySelectorAll("tbody tr").forEach((row) => {
    row.addEventListener("click", (ev) => {
      if (ev.target.closest(".btn-pos-sell")) return;
      selectSymbol(row.dataset.symbol);
    });
  });
  el.querySelectorAll(".btn-pos-sell").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const sym = btn.dataset.symbol;
      const qty = btn.dataset.qty;
      selectSymbol(sym);
      const qtyInput = document.getElementById("trade-qty");
      if (qtyInput) qtyInput.value = isCrypto() ? String(qty) : String(Math.floor(Number(qty)));
      updateTradeEstimate();
      document.getElementById("btn-sell")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  });
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/quotes?market=${currentMarket}`);
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
  const c = await api(apiPath(`/api/analysis/${sym}`));
  const result = c?.result ?? c?.result_json;
  if (!result && !c?.result) {
    const parsed = typeof c?.result_json === "string" ? JSON.parse(c.result_json) : null;
    if (parsed) {
      renderAnalysis(parsed, c.analyzed_at, true);
      return;
    }
    const el = document.getElementById("ai-panel");
    if (el) el.innerHTML = "<p>尚無分析，待觸發訊號或按「立即分析」</p>";
    return;
  }
  renderAnalysis(c.result || result, c.analyzed_at, true);
}

function normalizeDateStr(t) {
  if (t == null) return null;
  if (typeof t === "number") {
    const ms = t > 1e12 ? t : t * 1000;
    const d = new Date(ms);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  const s = String(t);
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10);
  return null;
}

function toChartTime(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  if (!y || !m || !d) return null;
  return { year: y, month: m, day: d };
}

function sanitizeCandles(raw) {
  const byDay = new Map();
  for (const c of raw || []) {
    const dateStr = normalizeDateStr(c.time);
    const open = Number(c.open);
    const high = Number(c.high);
    const low = Number(c.low);
    const close = Number(c.close);
    const volume = Number(c.volume) || 0;
    if (
      !dateStr ||
      !Number.isFinite(open) ||
      !Number.isFinite(high) ||
      !Number.isFinite(low) ||
      !Number.isFinite(close)
    ) {
      continue;
    }
    byDay.set(dateStr, { dateStr, open, high, low, close, volume });
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([, c]) => {
      const time = toChartTime(c.dateStr);
      if (!time) return null;
      return { time, open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume };
    })
    .filter(Boolean);
}

function computeMA(candles, period) {
  const out = [];
  for (let i = period - 1; i < candles.length; i++) {
    let sum = 0;
    for (let j = 0; j < period; j++) sum += candles[i - j].close;
    out.push({ time: candles[i].time, value: sum / period });
  }
  return out;
}

async function loadChart(sym) {
  const { candles: raw } = await api(apiPath(`/api/klines/${sym}?days=120`));
  if (!chart) initChart();
  if (!candleSeries) return;

  const candles = sanitizeCandles(raw);
  if (!candles.length) {
    candleSeries.setData([]);
    volumeSeries.setData([]);
    ma5Series.setData([]);
    ma20Series.setData([]);
    return;
  }

  candleSeries.setData(
    candles.map((c) => ({
      time: c.time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }))
  );
  volumeSeries.setData(
    candles.map((c) => ({
      time: c.time,
      value: c.volume,
      color: c.close >= c.open ? "#f8514966" : "#3fb95066",
    }))
  );
  ma5Series.setData(computeMA(candles, 5));
  ma20Series.setData(computeMA(candles, 20));
  chart.timeScale().applyOptions({
    timeVisible: true,
    secondsVisible: false,
  });
  chart.timeScale().fitContent();
  const last = candles[candles.length - 1];
  const el = document.getElementById("chart-meta");
  if (el && last?.time) {
    const { year, month, day } = last.time;
    const label = isCrypto() ? "加密貨幣日 K" : "日 K";
    el.textContent = `${label} · ${displaySymbol(sym)} · 共 ${candles.length} 根 · 最後 ${year}/${month}/${day}`;
  }
}

function initChart() {
  const el = document.getElementById("chart");
  if (!el || !window.LightweightCharts) return;
  chart = LightweightCharts.createChart(el, {
    layout: { background: { color: "#161b22" }, textColor: "#8b949e" },
    grid: { vertLines: { color: "#30363d" }, horzLines: { color: "#30363d" } },
    localization: {
      locale: "zh-TW",
      dateFormat: "yyyy-MM-dd",
    },
    width: el.clientWidth,
    height: 320,
  });
  chart.applyOptions({
    timeScale: {
      timeVisible: true,
      secondsVisible: false,
    },
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
    const unit = isCrypto() ? "" : "股";
    el.innerHTML =
      "<h4>待確認下單</h4>" +
      orders
        .map(
          (o) =>
            `<div class="form-row">${displaySymbol(o.symbol)} ${o.side} ${o.qty}${unit} @${o.price}
            <button data-id="${o.id}" class="btn-confirm">確認</button>
            <button data-id="${o.id}" class="btn-reject">拒絕</button></div>`
        )
        .join("");
    el.querySelectorAll(".btn-confirm").forEach((b) =>
      b.addEventListener("click", async () => {
        await api(apiPath(`/api/pending-orders/${b.dataset.id}/confirm`), { method: "POST" });
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
  if (el) {
    const u = p.unrealized_pnl;
    const cls = u >= 0 ? "up" : "down";
    const cur = p.currency || (isCrypto() ? "USDT" : "NT$");
    const holdings = p.holdings_value ?? 0;
    el.innerHTML = `
      虛擬資金：${cur}${p.cash.toLocaleString()}
      持倉市值：${cur}${holdings.toLocaleString()}
      總權益：${cur}${p.total_equity.toLocaleString()}
      未實現：<span class="${cls}">${cur}${u.toLocaleString()}</span>
    `;
  }
  renderPositions(p);
}

document.addEventListener("DOMContentLoaded", async () => {
  if (document.getElementById("watchlist")) {
    updateMarketUi();
    document.querySelectorAll(".market-tab").forEach((btn) => {
      btn.addEventListener("click", () => setMarket(btn.dataset.market));
    });
    await loadSettings();
    await loadWatchlist();
    connectWs();
    refreshPortfolio();
    refreshPending();
    document.getElementById("btn-analyze")?.addEventListener("click", async () => {
      if (!selectedSymbol) return;
      await api(apiPath(`/api/analyze/${selectedSymbol}`), { method: "POST" });
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
    document.getElementById("trade-qty")?.addEventListener("input", updateTradeEstimate);
    document.getElementById("btn-max-qty")?.addEventListener("click", fillMaxBuyQty);
    document.getElementById("btn-buy")?.addEventListener("click", () => submitTrade("buy"));
    document.getElementById("btn-sell")?.addEventListener("click", () => submitTrade("sell"));
    document.getElementById("btn-add-watch")?.addEventListener("click", async () => {
      const sym = document.getElementById("new-symbol").value.trim();
      if (!sym) return;
      await api("/api/watchlist", {
        method: "POST",
        body: JSON.stringify({ symbol: sym, market: currentMarket }),
      });
      document.getElementById("new-symbol").value = "";
      await loadWatchlist();
    });
  }
});

export { api, loadSettings, loadWatchlist, refreshPortfolio, currentMarket };
