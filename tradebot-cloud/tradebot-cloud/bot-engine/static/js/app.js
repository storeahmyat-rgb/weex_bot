/* ============================================
   Binance Futures Bot - Frontend Logic (v2)
   - Multi-coin support
   - Amount mode: fixed USDT or % of wallet
   - Real chart with historical candles
   - Error-resistant
   ============================================ */

// ===== State =====
let chart = null;
let candleSeries = null;
let ema8Series = null;
let ema13Series = null;
let ema21Series = null;
let ema55Series = null;
let isRunning = false;
let socket = null;

// Multi-coin state
let coins = [];              // list of symbol strings
let activeSymbol = null;     // currently displayed symbol
let signalsBySymbol = {};    // {BTCUSDT: 'BUY', ...}
let indicatorsBySymbol = {}; // latest indicators per symbol
let positionsBySymbol = {};  // latest position per symbol
let chartDataBySymbol = {};  // latest chart_data per symbol

// ===== DOM Helpers =====
const $ = (id) => document.getElementById(id);

function log(level, msg) {
    const logs = $('logs');
    if (!logs) return;
    const entry = document.createElement('div');
    entry.className = `log-entry ${level}`;
    const time = new Date().toLocaleTimeString();
    entry.innerHTML = `<span class="log-time">${time}</span><span class="log-msg">${msg}</span>`;
    logs.appendChild(entry);
    logs.scrollTop = logs.scrollHeight;
    while (logs.children.length > 500) logs.removeChild(logs.firstChild);
}

function setBotRunning(running) {
    isRunning = running;
    const startBtn = $('startBtn');
    const stopBtn = $('stopBtn');
    if (startBtn) startBtn.disabled = running;
    if (stopBtn) stopBtn.disabled = !running;
    const pill = $('botStatusPill');
    const text = $('botStatusText');
    if (pill && text) {
        if (running) {
            pill.classList.add('running');
            text.textContent = 'RUNNING';
        } else {
            pill.classList.remove('running');
            text.textContent = 'STOPPED';
        }
    }
}

function fmt(n) {
    if (n == null || isNaN(n)) return '--';
    if (n >= 1000) return Number(n).toFixed(2);
    if (n >= 1) return Number(n).toFixed(4);
    return Number(n).toFixed(6);
}

// ===== EMA Stack Visualizer =====
function renderEMAStack(data) {
    const container = $('emaStackList');
    if (!container) return;
    if (!data || !data.ema_8 || !data.ema_55) {
        container.innerHTML = '<div class="ema-stack-empty">Waiting for data...</div>';
        return;
    }
    // Build array and sort by value DESC (top = highest)
    const emas = [
        { name: 'EMA 8',  value: data.ema_8,  cls: 'ema-8'  },
        { name: 'EMA 13', value: data.ema_13, cls: 'ema-13' },
        { name: 'EMA 21', value: data.ema_21, cls: 'ema-21' },
        { name: 'EMA 55', value: data.ema_55, cls: 'ema-55' },
    ];
    emas.sort((a, b) => b.value - a.value);

    container.innerHTML = '';
    emas.forEach((ema, idx) => {
        const posLabel = idx === 0 ? 'TOP' : idx === emas.length - 1 ? 'BOTTOM' : '';
        const posClass = idx === 0 ? 'top' : idx === emas.length - 1 ? 'bottom' : '';
        const row = document.createElement('div');
        row.className = `ema-stack-row ${ema.cls} ${posClass}`;
        row.innerHTML = `
            <span class="pos-num">${idx + 1}</span>
            <span class="ema-name">${ema.name}</span>
            ${posLabel ? `<span class="pos-label">${posLabel}</span>` : ''}
            <span class="ema-value">$${fmt(ema.value)}</span>
        `;
        container.appendChild(row);
    });

    // Highlight the EMA55 rule
    const ruleEl = $('emaStackRule');
    if (ruleEl) {
        const ema55Idx = emas.findIndex(e => e.name === 'EMA 55');
        if (ema55Idx === 0) {
            ruleEl.style.color = '#f6465d';
            ruleEl.style.borderColor = 'rgba(246, 70, 93, 0.5)';
            ruleEl.style.background = 'rgba(246, 70, 93, 0.08)';
            ruleEl.textContent = 'EMA55 is at TOP → SELL signal fires → Bot opens SHORT';
        } else if (ema55Idx === emas.length - 1) {
            ruleEl.style.color = '#0ecb81';
            ruleEl.style.borderColor = 'rgba(14, 203, 129, 0.5)';
            ruleEl.style.background = 'rgba(14, 203, 129, 0.08)';
            ruleEl.textContent = 'EMA55 is at BOTTOM → BUY signal fires → Bot opens LONG';
        } else {
            ruleEl.style.color = '#f0b90b';
            ruleEl.style.borderColor = 'rgba(240, 185, 11, 0.3)';
            ruleEl.style.background = 'rgba(240, 185, 11, 0.08)';
            ruleEl.textContent = 'EMA55 in middle → HOLD (no action). Strategy: EMA55 at BOTTOM = BUY | EMA55 at TOP = SELL';
        }
    }
}

// ===== HTTP Fallback for Chart Data (when socket disconnects) =====
async function fetchChartData(symbol) {
    if (!symbol || !isRunning) return;
    try {
        const r = await fetch(`/api/test_chart?symbol=${symbol}`);
        const data = await r.json();
        if (data.success && data.candles && data.candles.length > 0) {
            chartDataBySymbol[symbol] = { symbol, candles: data.candles, emas: {} };
            if (symbol === activeSymbol) {
                renderChartForSymbol(symbol);
            }
        }
    } catch (e) {
        // Silent fail
    }
}

// ===== Chart Setup (TradingView style with zoom/pan) =====
function initChart() {
    try {
        if (typeof LightweightCharts === 'undefined') {
            log('warn', 'Chart library load nahi hui.');
            return false;
        }
        const container = $('chart');
        if (!container) return false;

        // Force container height if 0 (CSS issue fix)
        if (container.clientHeight < 100) {
            container.style.height = '500px';
        }

        chart = LightweightCharts.createChart(container, {
            layout: {
                background: { type: 'solid', color: '#0b0e11' },
                textColor: '#848e9c',
                fontFamily: 'JetBrains Mono, monospace',
                fontSize: 11,
            },
            grid: {
                vertLines: { color: '#1e2126' },
                horzLines: { color: '#1e2126' },
            },
            timeScale: {
                borderColor: '#2a2e36',
                timeVisible: true,
                secondsVisible: false,
                rightOffset: 5,
                barSpacing: 8,
                minBarSpacing: 2,
                fixLeftEdge: false,
                fixRightEdge: false,
            },
            rightPriceScale: {
                borderColor: '#2a2e36',
                scaleMargins: { top: 0.1, bottom: 0.1 },
            },
            crosshair: {
                mode: 1,  // Magnet mode
                vertLine: { color: '#f0b90b', width: 1, style: 2, labelBackgroundColor: '#f0b90b' },
                horzLine: { color: '#f0b90b', width: 1, style: 2, labelBackgroundColor: '#f0b90b' },
            },
            // TradingView style interactions
            handleScroll: true,    // Enable panning (drag to move)
            handleScale: true,     // Enable zoom (scroll wheel)
            kineticScroll: true,   // Smooth scrolling
            width: container.clientWidth || 800,
            height: container.clientHeight || 500,
        });

        candleSeries = chart.addCandlestickSeries({
            upColor: '#0ecb81',
            downColor: '#f6465d',
            borderUpColor: '#0ecb81',
            borderDownColor: '#f6465d',
            borderVisible: false,
            wickUpColor: '#0ecb81',
            wickDownColor: '#f6465d',
        });
        ema8Series  = chart.addLineSeries({ color: '#2196f3', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        ema13Series = chart.addLineSeries({ color: '#ff9800', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        ema21Series = chart.addLineSeries({ color: '#9c27b0', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        ema55Series = chart.addLineSeries({ color: '#f44336', lineWidth: 3, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });

        const ro = new ResizeObserver(() => {
            if (chart) {
                chart.applyOptions({
                    width: container.clientWidth,
                    height: container.clientHeight || 500
                });
            }
        });
        ro.observe(container);
        log('success', '✅ Chart ready (TradingView style - zoom/pan enabled)');
        return true;
    } catch (e) {
        console.error('Chart init failed:', e);
        log('warn', `Chart init failed: ${e.message}. Bot phir bhi chalega.`);
        return false;
    }
}

function renderChartForSymbol(symbol) {
    if (!chart || !symbol) return;
    const data = chartDataBySymbol[symbol];
    if (!data) return;
    try {
        if (data.candles && data.candles.length > 0) {
            // Sort by time and remove duplicates (LightweightCharts requires this)
            let candles = data.candles.slice().sort((a, b) => a.time - b.time);
            let unique = [];
            let lastTime = 0;
            for (let c of candles) {
                if (c.time > lastTime) {
                    unique.push(c);
                    lastTime = c.time;
                }
            }
            candleSeries.setData(unique);
        }
        if (data.emas) {
            if (data.emas.ema8) {
                let e8 = data.emas.ema8.slice().sort((a, b) => a.time - b.time);
                let u8 = []; let lt = 0;
                for (let c of e8) { if (c.time > lt) { u8.push(c); lt = c.time; } }
                ema8Series.setData(u8);
            }
            if (data.emas.ema13) {
                let e13 = data.emas.ema13.slice().sort((a, b) => a.time - b.time);
                let u13 = []; let lt = 0;
                for (let c of e13) { if (c.time > lt) { u13.push(c); lt = c.time; } }
                ema13Series.setData(u13);
            }
            if (data.emas.ema21) {
                let e21 = data.emas.ema21.slice().sort((a, b) => a.time - b.time);
                let u21 = []; let lt = 0;
                for (let c of e21) { if (c.time > lt) { u21.push(c); lt = c.time; } }
                ema21Series.setData(u21);
            }
            if (data.emas.ema55) {
                let e55 = data.emas.ema55.slice().sort((a, b) => a.time - b.time);
                let u55 = []; let lt = 0;
                for (let c of e55) { if (c.time > lt) { u55.push(c); lt = c.time; } }
                ema55Series.setData(u55);
            }
        }
        chart.timeScale().fitContent();
    } catch (e) {
        console.error('Chart render failed:', e);
    }
}

// ===== Socket Setup (failsafe with auto-reconnect) =====
function initSocket() {
    try {
        if (typeof io === 'undefined') {
            log('warn', 'Socket.IO load nahi hui. Status polling se hogi.');
            return false;
        }
        // Use polling first (Railway proxy friendly), then upgrade to websocket
        socket = io({
            transports: ['polling', 'websocket'],
            reconnection: true,          // Auto-reconnect on disconnect
            reconnectionAttempts: Infinity,  // Never give up
            reconnectionDelay: 1000,     // Start at 1s
            reconnectionDelayMax: 5000,  // Max 5s between retries
            timeout: 20000,              // 20s connect timeout
            pingInterval: 10000,         // Send ping every 10s (keepalive)
            pingTimeout: 30000,          // 30s ping timeout
        });

        socket.on('connect', () => {
            log('success', '✅ Socket connected');
            // Re-fetch chart data on reconnect (in case we missed updates)
            if (activeSymbol && isRunning) {
                fetchChartData(activeSymbol);
            }
        });
        socket.on('disconnect', (reason) => {
            log('warn', `⚠️ Socket disconnected: ${reason}. Auto-reconnecting...`);
        });
        socket.on('reconnect', (attempt) => {
            log('success', `✅ Socket reconnected (attempt ${attempt})`);
        });
        socket.on('reconnect_error', (error) => {
            // Silent - don't spam logs
        });
        socket.on('connect_error', (error) => {
            // Silent - don't spam logs
        });

        socket.on('log', (data) => log(data.level || 'info', data.msg));

        socket.on('status', (data) => {
            setBotRunning(!!data.running);
            if (data.message) log('info', data.message);
            if (data.symbols) {
                // update coins from server if running
                if (data.running && data.symbols.length && coins.length === 0) {
                    coins = [...data.symbols];
                    renderCoinChips();
                    renderCoinTabs();
                    if (!activeSymbol && coins.length) selectSymbol(coins[0]);
                    if ($('statCoins')) $('statCoins').textContent = coins.length;
                }
                // Update trades/stats from workers
                if (data.workers) {
                    let totalTrades = 0;
                    for (const sym in data.workers) {
                        totalTrades += data.workers[sym].trades_today || 0;
                    }
                    if ($('statTrades')) $('statTrades').textContent = totalTrades;
                }
            }
        });

        socket.on('indicators', (data) => {
            const sym = data.symbol;
            if (!sym) return;
            indicatorsBySymbol[sym] = data;
            if (sym === activeSymbol) {
                if ($('indicatorsSymbol')) $('indicatorsSymbol').textContent = sym;
                const mp = data.mark_price;
                if ($('indPrice')) $('indPrice').textContent = (mp && mp > 0) ? `$${fmt(mp)}` : '--';
                if ($('indEma8'))  $('indEma8').textContent  = (data.ema_8 && data.ema_8 > 0)  ? `$${fmt(data.ema_8)}`  : '--';
                if ($('indEma13')) $('indEma13').textContent = (data.ema_13 && data.ema_13 > 0) ? `$${fmt(data.ema_13)}` : '--';
                if ($('indEma21')) $('indEma21').textContent = (data.ema_21 && data.ema_21 > 0) ? `$${fmt(data.ema_21)}` : '--';
                if ($('indEma55')) $('indEma55').textContent = (data.ema_55 && data.ema_55 > 0) ? `$${fmt(data.ema_55)}` : '--';
                renderEMAStack(data);
            }
        });

        socket.on('chart_data', (data) => {
            const sym = data.symbol;
            if (!sym) return;
            chartDataBySymbol[sym] = data;
            if (sym === activeSymbol) {
                renderChartForSymbol(sym);
            }
        });

        socket.on('signal', (data) => {
            const sym = data.symbol;
            if (!sym) return;
            const prevSignal = signalsBySymbol[sym];
            signalsBySymbol[sym] = data.signal;
            // Only log when signal CHANGES (not every tick - prevents spam)
            if (prevSignal !== data.signal && data.signal !== 'HOLD') {
                log(data.signal === 'BUY' ? 'success' : 'warn',
                    `[${sym}] SIGNAL: ${data.signal} - ${data.reason}`);
            }
            // Update coin tab
            const tab = document.querySelector(`.coin-tab[data-symbol="${sym}"]`);
            if (tab) {
                tab.classList.remove('signal-buy', 'signal-sell', 'signal-hold');
                tab.classList.add(`signal-${data.signal.toLowerCase()}`);
            }
            // Update indicator panel if active
            if (sym === activeSymbol) {
                const el = $('indSignal');
                if (el) {
                    el.textContent = data.signal;
                    el.className = '';
                    el.classList.add(`signal-${data.signal.toLowerCase()}`);
                }
            }
            if (data.signal !== 'HOLD') {
                log(data.signal === 'BUY' ? 'success' : 'warn',
                    `[${sym}] SIGNAL: ${data.signal} - ${data.reason}`);
            }
        });

        socket.on('position', (data) => {
            const sym = data.symbol;
            if (!sym) return;
            positionsBySymbol[sym] = data;
            if (sym === activeSymbol) updatePositionUI(data);
        });

        // Balance event from MonitorThread (works even when bot is STOPPED)
        socket.on('balance', (data) => {
            const bal = data.balance || 0;
            const exchange = (data.exchange || 'binance').toUpperCase();
            const env = data.testnet ? (exchange === 'WEEX' ? 'DEMO' : 'TESTNET') : 'LIVE';
            if ($('statBalance')) {
                $('statBalance').textContent = `$${Number(bal).toFixed(2)}`;
                $('statBalance').title = `${exchange} ${env} balance`;
            }
        });

        return true;
    } catch (e) {
        console.error('Socket init failed:', e);
        log('warn', `Socket init failed: ${e.message}`);
        return false;
    }
}

function updatePositionUI(data) {
    if ($('positionSymbol')) $('positionSymbol').textContent = data.symbol || '--';
    const posSide = $('posSide');
    if (posSide) {
        posSide.textContent = data.side;
        posSide.className = '';
        if (data.side === 'LONG') posSide.classList.add('pos-side-long');
        else if (data.side === 'SHORT') posSide.classList.add('pos-side-short');
    }
    if ($('posSize')) $('posSize').textContent = Math.abs(data.size || 0).toFixed(4);
    if ($('posEntry')) $('posEntry').textContent = data.entry_price ? `$${fmt(data.entry_price)}` : '--';
    if ($('posMark')) $('posMark').textContent = data.mark_price ? `$${fmt(data.mark_price)}` : '--';
    const pnl = data.unrealized_pnl || 0;
    const pnlEl = $('posPnl');
    if (pnlEl) {
        pnlEl.textContent = `$${pnl.toFixed(2)}`;
        pnlEl.className = '';
        if (pnl > 0) pnlEl.classList.add('pnl-positive');
        else if (pnl < 0) pnlEl.classList.add('pnl-negative');
        else pnlEl.classList.add('pnl-zero');
    }
    if ($('posLeverage')) $('posLeverage').textContent = `${data.leverage || 1}x`;
}

// ===== Multi-Coin Management =====
function renderCoinChips() {
    const container = $('coinChips');
    if (!container) return;
    container.innerHTML = '';
    coins.forEach((sym, idx) => {
        const chip = document.createElement('div');
        chip.className = 'coin-chip' + (sym === activeSymbol ? ' active' : '');
        chip.innerHTML = `<span class="sym">${sym}</span><span class="remove" data-sym="${sym}">×</span>`;
        chip.addEventListener('click', (e) => {
            if (e.target.classList.contains('remove')) return;
            selectSymbol(sym);
        });
        chip.querySelector('.remove').addEventListener('click', (e) => {
            e.stopPropagation();
            removeCoin(sym);
        });
        container.appendChild(chip);
    });
}

function renderCoinTabs() {
    const container = $('coinTabs');
    if (!container) return;
    if (coins.length === 0) {
        container.innerHTML = '<span class="hint-inline">No coins added yet. Add coins from settings panel.</span>';
        return;
    }
    container.innerHTML = '';
    coins.forEach(sym => {
        const tab = document.createElement('div');
        tab.className = 'coin-tab' + (sym === activeSymbol ? ' active' : '');
        tab.dataset.symbol = sym;
        const sig = signalsBySymbol[sym];
        if (sig) tab.classList.add(`signal-${sig.toLowerCase()}`);
        tab.innerHTML = `${sym}<span class="signal-dot"></span>`;
        tab.addEventListener('click', () => selectSymbol(sym));
        container.appendChild(tab);
    });
}

function selectSymbol(sym) {
    activeSymbol = sym;
    if ($('chartTitle')) $('chartTitle').textContent = `Price Chart - ${sym}`;
    if ($('statSymbol')) $('statSymbol').textContent = sym;
    renderCoinChips();
    renderCoinTabs();
    // Tell backend which coin is active (so it only sends chart data for this coin)
    if (isRunning && sym) {
        fetch('/api/active_symbol', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: sym })
        }).catch(() => {});
    }
    // Render cached data immediately
    if (indicatorsBySymbol[sym]) {
        const data = indicatorsBySymbol[sym];
        if ($('indicatorsSymbol')) $('indicatorsSymbol').textContent = sym;
        if ($('indPrice')) $('indPrice').textContent = `$${fmt(data.mark_price)}`;
        if ($('indEma8'))  $('indEma8').textContent  = data.ema_8  ? `$${fmt(data.ema_8)}`  : '--';
        if ($('indEma13')) $('indEma13').textContent = data.ema_13 ? `$${fmt(data.ema_13)}` : '--';
        if ($('indEma21')) $('indEma21').textContent = data.ema_21 ? `$${fmt(data.ema_21)}` : '--';
        if ($('indEma55')) $('indEma55').textContent = data.ema_55 ? `$${fmt(data.ema_55)}` : '--';
        renderEMAStack(data);
        const sig = signalsBySymbol[sym] || 'HOLD';
        const el = $('indSignal');
        if (el) {
            el.textContent = sig;
            el.className = '';
            el.classList.add(`signal-${sig.toLowerCase()}`);
        }
    } else {
        // reset
        ['indPrice','indEma8','indEma13','indEma21','indEma55'].forEach(id => {
            if ($(id)) $(id).textContent = '--';
        });
        if ($('indicatorsSymbol')) $('indicatorsSymbol').textContent = sym;
        const el = $('indSignal');
        if (el) { el.textContent = '--'; el.className = ''; }
        renderEMAStack(null);
    }
    if (positionsBySymbol[sym]) {
        updatePositionUI(positionsBySymbol[sym]);
    } else {
        updatePositionUI({ symbol: sym, side: 'NONE', size: 0, entry_price: 0, mark_price: 0, unrealized_pnl: 0, leverage: 1 });
    }
    if (chartDataBySymbol[sym]) {
        renderChartForSymbol(sym);
    } else if (chart) {
        // Clear chart
        try {
            candleSeries.setData([]);
            ema8Series.setData([]);
            ema13Series.setData([]);
            ema21Series.setData([]);
            ema55Series.setData([]);
        } catch (e) {}
    }
}

function addCoin() {
    const input = $('coinInput');
    if (!input) return;
    const sym = input.value.trim().toUpperCase();
    if (!sym) return;
    if (!/^[A-Z0-9]+USDT$/.test(sym)) {
        log('warn', `${sym} valid nahi. Format: BTCUSDT, ETHUSDT, etc.`);
        return;
    }
    if (coins.includes(sym)) {
        log('info', `${sym} pehle se added hai.`);
        input.value = '';
        return;
    }
    coins.push(sym);
    input.value = '';
    renderCoinChips();
    renderCoinTabs();
    if (!activeSymbol) selectSymbol(sym);
    if ($('statCoins')) $('statCoins').textContent = coins.length;
    log('info', `${sym} added.`);
    // Auto-save coins to config
    saveSettings();
}

function removeCoin(sym) {
    coins = coins.filter(c => c !== sym);
    delete signalsBySymbol[sym];
    delete indicatorsBySymbol[sym];
    delete positionsBySymbol[sym];
    delete chartDataBySymbol[sym];
    if (activeSymbol === sym) {
        activeSymbol = coins[0] || null;
        if (activeSymbol) selectSymbol(activeSymbol);
        else if ($('chartTitle')) $('chartTitle').textContent = 'Price Chart - Select a coin';
    }
    renderCoinChips();
    renderCoinTabs();
    if ($('statCoins')) $('statCoins').textContent = coins.length;
    log('info', `${sym} removed.`);
    // Auto-save coins to config
    saveSettings();
}

// ===== Amount Mode Toggle =====
function setAmountMode(mode) {
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    if (mode === 'percent') {
        $('fixedAmountGroup').classList.add('hidden');
        $('percentAmountGroup').classList.remove('hidden');
    } else {
        $('fixedAmountGroup').classList.remove('hidden');
        $('percentAmountGroup').classList.add('hidden');
    }
}

// ===== Settings Load/Save =====
async function loadSettings() {
    try {
        const r = await fetch('/api/config');
        const cfg = await r.json();
        // Exchange
        const exchange = cfg.exchange || 'binance';
        setExchange(exchange);
        if ($('apiPassphrase')) $('apiPassphrase').placeholder = cfg.api_passphrase ? 'Saved' : 'WEEX Passphrase';
        if ($('timeframe')) $('timeframe').value = cfg.timeframe || '1d';
        if ($('leverage')) $('leverage').value = cfg.leverage || 10;
        if ($('amount')) $('amount').value = cfg.amount || 100;
        if ($('amountPct')) $('amountPct').value = cfg.amount_pct || 10;
        if ($('stopLossPct')) $('stopLossPct').value = cfg.stop_loss_pct || 2;
        if ($('takeProfitPct')) {
            const tp = (cfg.stop_loss_pct || 2) * 3;
            $('takeProfitPct').value = tp.toFixed(1);
        }
        if ($('mode')) $('mode').value = cfg.mode || 'both';
        if ($('testnet')) $('testnet').value = String(cfg.testnet ?? true);
        if (cfg.api_key && $('apiKey')) $('apiKey').placeholder = cfg.api_key_masked || 'Saved';

        // Notifications - Telegram
        if ($('telegramEnabled')) $('telegramEnabled').checked = !!cfg.telegram_enabled;
        if ($('telegramBotToken')) $('telegramBotToken').placeholder = cfg.telegram_bot_token ? 'Saved' : 'Bot Token';
        if ($('telegramChatId')) $('telegramChatId').value = cfg.telegram_chat_id || '';
        // Email
        if ($('emailEnabled')) $('emailEnabled').checked = !!cfg.email_enabled;
        if ($('emailSender')) $('emailSender').value = cfg.email_sender || '';
        if ($('emailPassword')) $('emailPassword').placeholder = cfg.email_password ? 'Saved' : 'App Password';
        if ($('emailReceiver')) $('emailReceiver').value = cfg.email_receiver || '';
        if ($('emailSmtpServer')) $('emailSmtpServer').value = cfg.email_smtp_server || 'smtp.gmail.com';
        if ($('emailSmtpPort')) $('emailSmtpPort').value = cfg.email_smtp_port || 587;
        // WhatsApp
        if ($('whatsappEnabled')) $('whatsappEnabled').checked = !!cfg.whatsapp_enabled;
        if ($('whatsappPhone')) $('whatsappPhone').value = cfg.whatsapp_phone || '';
        if ($('whatsappApikey')) $('whatsappApikey').placeholder = cfg.whatsapp_apikey ? 'Saved' : 'CallMeBot API Key';

        // Amount mode
        const amtMode = cfg.amount_mode || 'fixed';
        setAmountMode(amtMode);

        // Coins
        const savedCoins = Array.isArray(cfg.symbols_list) ? cfg.symbols_list : (cfg.symbol ? [cfg.symbol] : ['BTCUSDT']);
        coins = savedCoins.map(s => String(s).toUpperCase());
        if (coins.length === 0) coins = ['BTCUSDT'];
        if (!activeSymbol) activeSymbol = coins[0];
        renderCoinChips();
        renderCoinTabs();
        selectSymbol(activeSymbol);
        if ($('statCoins')) $('statCoins').textContent = coins.length;

        updateEnvBadge(cfg.testnet ?? true, exchange);
    } catch (e) {
        log('error', `Settings load failed: ${e}`);
    }
}

function setExchange(exchange) {
    const prevExchange = document.querySelector('.exchange-btn.active')?.dataset.exchange || null;
    document.querySelectorAll('.exchange-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.exchange === exchange);
    });
    // Show/hide passphrase field
    const passGroup = $('passphraseGroup');
    if (passGroup) {
        if (exchange === 'weex') {
            passGroup.classList.remove('hidden');
        } else {
            passGroup.classList.add('hidden');
        }
    }
    // Show/hide WEEX-only leverage buttons (200x-500x)
    document.querySelectorAll('.weex-only').forEach(btn => {
        btn.style.display = exchange === 'weex' ? '' : 'none';
    });
    // Update max leverage label and input max
    const maxLevLabel = $('maxLevLabel');
    const levInput = $('leverage');
    const maxLevBtn = $('maxLeverageBtn');
    if (exchange === 'weex') {
        if (maxLevLabel) maxLevLabel.textContent = '500';
        if (levInput) levInput.max = '500';
        if (maxLevBtn) maxLevBtn.textContent = 'SET 500x LEVERAGE';
    } else {
        if (maxLevLabel) maxLevLabel.textContent = '125';
        if (levInput) levInput.max = '125';
        if (maxLevBtn) maxLevBtn.textContent = 'SET 100x LEVERAGE';
    }
    // Update env badge
    const testnet = $('testnet') ? $('testnet').value === 'true' : true;
    updateEnvBadge(testnet, exchange);

    // CRITICAL FIX: When exchange is switched, auto-refresh the coin dropdown
    // from the NEW exchange's API. Previously the dropdown always showed
    // Binance coins even after switching to WEEX, causing invalid-coin errors.
    if (prevExchange && prevExchange !== exchange) {
        log('info', `Exchange switched: ${prevExchange} -> ${exchange}. Refreshing coin list...`);
        refreshCoinDropdown(exchange);
        // Warn user about existing coin selections
        if (coins.length > 0) {
            log('warn', `⚠️ You have ${coins.length} coins selected. Some may not exist on ${exchange.toUpperCase()}. Verify before starting.`);
        }
    }
}

// Fetch fresh coin list from /api/symbols and populate the dropdown (datalist)
async function refreshCoinDropdown(exchange) {
    try {
        const r = await fetch('/api/symbols');
        const data = await r.json();
        if (data.success && data.symbols && data.symbols.length > 0) {
            const datalist = $('coinSuggestions');
            if (datalist) {
                datalist.innerHTML = '';
                data.symbols.forEach(sym => {
                    const opt = document.createElement('option');
                    opt.value = sym;
                    datalist.appendChild(opt);
                });
            }
            log('success', `Loaded ${data.symbols.length} ${exchange.toUpperCase()} coins into dropdown.`);
        }
    } catch (e) {
        log('error', `Failed to refresh coin dropdown: ${e}`);
    }
}

async function saveSettings() {
    log('info', 'Save request bhej rahe hain...');
    if (coins.length === 0) {
        log('warn', 'Kam az kam ek coin add karein.');
        return;
    }
    const exchange = document.querySelector('.exchange-btn.active')?.dataset.exchange || 'binance';
    const cfg = {
        exchange: exchange,
        api_key: $('apiKey').value || undefined,
        api_secret: $('apiSecret').value || undefined,
        api_passphrase: $('apiPassphrase').value || undefined,
        symbols_list: coins,
        symbol: coins[0],
        timeframe: $('timeframe').value,
        leverage: parseInt($('leverage').value),
        amount_mode: document.querySelector('.toggle-btn.active')?.dataset.mode || 'fixed',
        amount: parseFloat($('amount').value),
        amount_pct: parseFloat($('amountPct').value),
        stop_loss_pct: parseFloat($('stopLossPct').value) || 0,
        take_profit_pct: parseFloat($('takeProfitPct').value) || 0,
        mode: $('mode').value,
        testnet: $('testnet').value === 'true',
        // Notifications
        telegram_enabled: $('telegramEnabled')?.checked || false,
        telegram_bot_token: $('telegramBotToken')?.value || undefined,
        telegram_chat_id: $('telegramChatId')?.value || undefined,
        email_enabled: $('emailEnabled')?.checked || false,
        email_sender: $('emailSender')?.value || undefined,
        email_password: $('emailPassword')?.value || undefined,
        email_receiver: $('emailReceiver')?.value || undefined,
        email_smtp_server: $('emailSmtpServer')?.value || undefined,
        email_smtp_port: parseInt($('emailSmtpPort')?.value) || undefined,
        whatsapp_enabled: $('whatsappEnabled')?.checked || false,
        whatsapp_phone: $('whatsappPhone')?.value || undefined,
        whatsapp_apikey: $('whatsappApikey')?.value || undefined,
    };
    if (cfg.leverage < 1 || cfg.leverage > 500) {
        log('warn', 'Leverage 1-500 ke beech hona chahiye');
        return;
    }
    // Exchange-specific cap
    const maxLev = exchange === 'weex' ? 500 : 125;
    if (cfg.leverage > maxLev) {
        log('warn', `${exchange.toUpperCase()} pe max leverage ${maxLev}x hai`);
        cfg.leverage = maxLev;
    }
    try {
        const r = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cfg),
        });
        const data = await r.json();
        if (data.success) {
            log('success', `Settings saved! Exchange: ${exchange.toUpperCase()}`);
            $('apiKey').value = '';
            $('apiSecret').value = '';
            $('apiPassphrase').value = '';
            $('apiKey').placeholder = 'Saved';
            if (exchange === 'weex') $('apiPassphrase').placeholder = 'Saved';
            // Clear notification sensitive fields
            if ($('telegramBotToken')) { $('telegramBotToken').value = ''; $('telegramBotToken').placeholder = 'Saved'; }
            if ($('emailPassword')) { $('emailPassword').value = ''; $('emailPassword').placeholder = 'Saved'; }
            if ($('whatsappApikey')) { $('whatsappApikey').value = ''; $('whatsappApikey').placeholder = 'Saved'; }
            updateEnvBadge(cfg.testnet, exchange);
            if (cfg.stop_loss_pct > 0) log('info', `Stop Loss ACTIVE: ${cfg.stop_loss_pct}%`);
            else log('info', `Stop Loss OFF`);
            if (cfg.take_profit_pct > 0) log('info', `Take Profit ACTIVE: ${cfg.take_profit_pct}%`);
            else log('info', `Take Profit: opposite-signal only`);
            // Log notification status
            const notifs = [];
            if (cfg.telegram_enabled) notifs.push('Telegram');
            if (cfg.email_enabled) notifs.push('Email');
            if (cfg.whatsapp_enabled) notifs.push('WhatsApp');
            if (notifs.length > 0) {
                log('info', `Notifications ON: ${notifs.join(', ')}`);
            } else {
                log('info', `Notifications OFF`);
            }
            // Show monitor status (auto-started by backend after Save)
            if (data.monitor) {
                if (data.monitor.success) {
                    log('success', `🔌 Monitor connected to ${exchange.toUpperCase()} — live balance/chart streaming now`);
                    // Immediately fetch balance (don't wait for next 10s cycle)
                    refreshBalance();
                } else if (data.monitor.error && data.monitor.error.indexOf('API key') >= 0) {
                    log('warn', `⚠️ Monitor not started: ${data.monitor.error}`);
                } else if (data.monitor.error && data.monitor.error !== 'skipped') {
                    log('warn', `⚠️ Monitor: ${data.monitor.error}`);
                }
            }
        } else {
            log('error', `Save failed: ${data.error}`);
        }
    } catch (e) {
        log('error', `Save failed: ${e}`);
    }
}

function updateEnvBadge(testnet, exchange) {
    const exBadge = $('exchangeBadge');
    const modeBadge = $('modeBadge');
    if (exBadge) {
        exBadge.textContent = (exchange || 'binance').toUpperCase();
        exBadge.style.color = exchange === 'weex' ? '#0ecb81' : '#f0b90b';
    }
    if (modeBadge) {
        if (exchange === 'weex') {
            modeBadge.textContent = testnet ? 'DEMO' : 'LIVE';
        } else {
            modeBadge.textContent = testnet ? 'TESTNET' : 'MAINNET';
        }
        modeBadge.style.color = testnet ? '#f0b90b' : '#f6465d';
    }
}

// ===== Bot Controls =====
async function startBot() {
    if (coins.length === 0) {
        log('warn', 'Pehle coins add karein ya "Load All Coins" dabao.');
        return;
    }
    log('info', 'Start request bhej rahe hain...');
    // Add 30s timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);
    try {
        const r = await fetch('/api/start', { method: 'POST', signal: controller.signal });
        clearTimeout(timeoutId);
        const data = await r.json();
        if (data.success) {
            log('success', 'Bot started!');
            setBotRunning(true);
        } else {
            log('error', `Start failed: ${data.error}`);
        }
    } catch (e) {
        clearTimeout(timeoutId);
        if (e.name === 'AbortError') {
            log('error', 'Start timeout (30s). FORCE RESET dabao aur dobara try karo.');
        } else {
            log('error', `Start error: ${e}`);
        }
    }
}

async function stopBot() {
    log('info', 'Stop request bhej rahe hain...');
    try {
        const r = await fetch('/api/stop', { method: 'POST' });
        const data = await r.json();
        if (data.success) {
            log('success', 'Bot stopped');
            setBotRunning(false);
        } else {
            log('error', `Stop failed: ${data.error}`);
        }
    } catch (e) {
        log('error', `Stop error: ${e}`);
    }
}

async function closePosition() {
    if (!activeSymbol) {
        log('warn', 'Pehle ek coin select karein.');
        return;
    }
    if (!confirm(`${activeSymbol} ki position close karein?`)) return;
    log('warn', `[${activeSymbol}] Manual close request bhej rahe hain...`);
    try {
        const r = await fetch('/api/close', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: activeSymbol }),
        });
        const data = await r.json();
        if (data.success) {
            log('success', `[${activeSymbol}] Position close request accepted`);
        } else {
            log('error', `[${activeSymbol}] Close failed: ${data.error}`);
        }
    } catch (e) {
        log('error', `Close error: ${e}`);
    }
}

async function refreshStatus() {
    try {
        const r = await fetch('/api/status');
        const s = await r.json();
        setBotRunning(!!s.running);
        if (s.workers) {
            let totalTrades = 0;
            for (const sym in s.workers) totalTrades += s.workers[sym].trades_today || 0;
            if ($('statTrades')) $('statTrades').textContent = totalTrades;
            // If backend says running but has symbols, sync coins array
            if (s.running && s.symbols && s.symbols.length && coins.length === 0) {
                coins = [...s.symbols];
                renderCoinChips();
                renderCoinTabs();
                if (!activeSymbol && coins.length) selectSymbol(coins[0]);
                if ($('statCoins')) $('statCoins').textContent = coins.length;
            }
        }
        // HTTP fallback: If socket is disconnected, fetch chart data via HTTP
        if (isRunning && activeSymbol && (!socket || !socket.connected)) {
            fetchChartData(activeSymbol);
        }
    } catch (e) { /* ignore */ }
}

async function refreshBalance() {
    // Try to fetch balance even when bot is STOPPED — the monitor trader
    // (started after Save) handles this. Backend returns error if no trader.
    try {
        const r = await fetch('/api/balance');
        const d = await r.json();
        if (d.success && $('statBalance')) {
            $('statBalance').textContent = `$${Number(d.balance).toFixed(2)}`;
            const exchange = (d.exchange || 'binance').toUpperCase();
            const env = d.testnet ? (exchange === 'WEEX' ? 'DEMO' : 'TESTNET') : 'LIVE';
            $('statBalance').title = `${exchange} ${env} balance`;
        } else if (!d.success && d.error && d.error.includes('not connected')) {
            // No trader at all — show dashes
            if ($('statBalance')) $('statBalance').textContent = '--';
        }
    } catch (e) { /* ignore */ }
}

// ===== Attach Event Listeners FIRST =====
function attachListeners() {
    const saveBtn = $('saveSettings');
    const startBtn = $('startBtn');
    const stopBtn = $('stopBtn');
    const closeBtn = $('closeBtn');
    const clearLogs = $('clearLogs');

    if (saveBtn) saveBtn.addEventListener('click', saveSettings);
    if (startBtn) startBtn.addEventListener('click', startBot);
    if (stopBtn) stopBtn.addEventListener('click', stopBot);
    if (closeBtn) closeBtn.addEventListener('click', closePosition);

    // Test Connection button - checks API credentials
    const testConnBtn = $('testConnBtn');
    if (testConnBtn) {
        testConnBtn.addEventListener('click', async () => {
            log('info', '🔌 Testing API connection...');
            testConnBtn.disabled = true;
            testConnBtn.textContent = 'Testing...';
            try {
                const r = await fetch('/api/test_connection', { method: 'POST' });
                const data = await r.json();
                if (data.success) {
                    log('success', `✅ ${data.message}`);
                    if (data.balance !== undefined) {
                        log('info', `💰 Balance: $${Number(data.balance).toFixed(2)} (${data.exchange.toUpperCase()} ${data.demo ? 'DEMO' : 'LIVE'})`);
                    }
                    // Refresh balance display
                    refreshBalance();
                } else {
                    log('error', `❌ Connection FAILED: ${data.cause || 'Unknown'}`);
                    log('warn', `🔧 Fix: ${data.fix || 'Check settings'}`);
                    log('error', `📋 Error detail: ${data.error || ''}`);
                }
            } catch (e) {
                log('error', `Test connection error: ${e}`);
            } finally {
                testConnBtn.disabled = false;
                testConnBtn.textContent = '🔌 TEST CONNECTION (Check API Keys)';
            }
        });
    }

    // Force Stop button - emergency reset
    const forceStopBtn = $('forceStopBtn');
    if (forceStopBtn) {
        forceStopBtn.addEventListener('click', async () => {
            if (!confirm('FORCE RESET karein? Yeh sab state clear kar dega. Position (agar open hai) Binance pe rahegi, lekin bot ka internal state reset ho jaayega.')) return;
            log('warn', 'Force reset request bhej rahe hain...');
            try {
                const r = await fetch('/api/force_stop', { method: 'POST' });
                const data = await r.json();
                if (data.success) {
                    log('success', '✅ Force reset done! Ab START fresh kar sakte ho.');
                    setBotRunning(false);
                    // Refresh status
                    setTimeout(refreshStatus, 1000);
                } else {
                    log('error', `Force reset failed: ${data.error}`);
                }
            } catch (e) {
                log('error', `Force reset error: ${e}`);
            }
        });
    }
    if (clearLogs) clearLogs.addEventListener('click', () => {
        const logs = $('logs');
        if (logs) logs.innerHTML = '';
    });

    // Test notification button - sends current form values WITHOUT saving
    const testNotifBtn = $('testNotificationBtn');
    if (testNotifBtn) {
        testNotifBtn.addEventListener('click', async () => {
            // Collect current form values (no save needed)
            const testData = {
                telegram_enabled: $('telegramEnabled')?.checked || false,
                telegram_bot_token: $('telegramBotToken')?.value || undefined,
                telegram_chat_id: $('telegramChatId')?.value || undefined,
                email_enabled: $('emailEnabled')?.checked || false,
                email_sender: $('emailSender')?.value || undefined,
                email_password: $('emailPassword')?.value || undefined,
                email_receiver: $('emailReceiver')?.value || undefined,
                email_smtp_server: $('emailSmtpServer')?.value || undefined,
                email_smtp_port: parseInt($('emailSmtpPort')?.value) || undefined,
                whatsapp_enabled: $('whatsappEnabled')?.checked || false,
                whatsapp_phone: $('whatsappPhone')?.value || undefined,
                whatsapp_apikey: $('whatsappApikey')?.value || undefined,
            };

            // Check if at least one channel is enabled
            if (!testData.telegram_enabled && !testData.email_enabled && !testData.whatsapp_enabled) {
                log('warn', 'Pehle koi channel enable karein (Telegram/Email/WhatsApp checkbox on karein)');
                return;
            }

            log('info', 'Test notification bhej rahe hain (bina save kiye)...');
            testNotifBtn.disabled = true;
            testNotifBtn.textContent = 'Sending...';
            try {
                const r = await fetch('/api/test_notification', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(testData),
                });
                const data = await r.json();
                if (data.success) {
                    log('success', `✅ Notification sent! ${data.message || ''}`);
                } else if (data.results) {
                    // Detailed per-channel errors
                    const results = data.results;
                    let hadAny = false;
                    for (const ch of ['telegram', 'email', 'whatsapp']) {
                        const r = results[ch];
                        if (r) {
                            hadAny = true;
                            if (r.success) {
                                log('success', `${ch}: ✅ sent`);
                            } else {
                                log('error', `${ch}: ❌ ${r.error}`);
                            }
                        }
                    }
                    if (!hadAny) {
                        log('warn', 'Koi channel enabled nahi hai. Checkbox on karein.');
                    }
                } else {
                    log('error', `Test failed: ${data.error || 'unknown'}`);
                }
            } catch (e) {
                log('error', `Test error: ${e}`);
            } finally {
                testNotifBtn.disabled = false;
                testNotifBtn.textContent = 'Test';
            }
        });
    }

    // Add coin
    const addCoinBtn = $('addCoinBtn');
    if (addCoinBtn) addCoinBtn.addEventListener('click', addCoin);
    const coinInput = $('coinInput');
    if (coinInput) {
        coinInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); addCoin(); }
        });
    }

    // Load All Coins - populate dropdown ONLY (NOT active tabs)
    const loadAllBtn = $('loadAllCoinsBtn');
    if (loadAllBtn) {
        loadAllBtn.addEventListener('click', async () => {
            log('info', 'Saare coins dropdown mein load ho rahe hain...');
            loadAllBtn.disabled = true;
            loadAllBtn.textContent = 'Loading...';
            try {
                const r = await fetch('/api/symbols');
                const data = await r.json();
                if (data.success && data.symbols && data.symbols.length > 0) {
                    // Populate ONLY the datalist (autocomplete dropdown)
                    const datalist = $('coinSuggestions');
                    if (datalist) {
                        datalist.innerHTML = '';
                        data.symbols.forEach(sym => {
                            const opt = document.createElement('option');
                            opt.value = sym;
                            datalist.appendChild(opt);
                        });
                    }
                    log('success', `${data.symbols.length} coins dropdown mein available. Type karein aur "+ Add" dabayein.`);
                } else {
                    log('error', `Coins load fail: ${data.error || 'unknown'}`);
                }
            } catch (e) {
                log('error', `Coins load error: ${e}`);
            } finally {
                loadAllBtn.disabled = false;
                loadAllBtn.textContent = 'Load All Coins';
            }
        });
    }

    // Auto-load all coins when bot starts (populate dropdown only)
    async function autoLoadCoins() {
        try {
            const r = await fetch('/api/symbols');
            const data = await r.json();
            if (data.success && data.symbols && data.symbols.length > 0) {
                const datalist = $('coinSuggestions');
                if (datalist) {
                    datalist.innerHTML = '';
                    data.symbols.forEach(sym => {
                        const opt = document.createElement('option');
                        opt.value = sym;
                        datalist.appendChild(opt);
                    });
                }
            }
        } catch (e) {
            // Silent fail
        }
    }

    // Auto-calculate TP from SL (1:3 RR)
    const slInput = $('stopLossPct');
    if (slInput) {
        slInput.addEventListener('input', () => {
            const sl = parseFloat(slInput.value) || 0;
            const tp = sl * 3;
            const tpInput = $('takeProfitPct');
            if (tpInput) tpInput.value = tp.toFixed(1);
        });
        // Trigger once on load
        slInput.dispatchEvent(new Event('input'));
    }

    // Exchange toggle
    document.querySelectorAll('.exchange-btn').forEach(btn => {
        btn.addEventListener('click', () => setExchange(btn.dataset.exchange));
    });

    // Amount mode toggle
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => setAmountMode(btn.dataset.mode));
    });

    // Quick leverage
    document.querySelectorAll('.quick-leverage .btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const lev = btn.dataset.lev;
            const levInput = $('leverage');
            if (levInput) levInput.value = lev;
            document.querySelectorAll('.quick-leverage .btn').forEach(b => {
                b.style.background = '';
                b.style.color = '';
            });
            btn.style.background = '#f0b90b';
            btn.style.color = '#0b0e11';
            log('info', `Leverage set to ${lev}x (Save dabana padega apply karne ke liye)`);
        });
    });

    // Max leverage button (100x for Binance, 500x for WEEX)
    const maxLevBtn = $('maxLeverageBtn');
    if (maxLevBtn) {
        maxLevBtn.addEventListener('click', () => {
            const exchange = document.querySelector('.exchange-btn.active')?.dataset.exchange || 'binance';
            const maxLev = exchange === 'weex' ? 500 : 100;
            const levInput = $('leverage');
            if (levInput) levInput.value = maxLev;
            log('info', `⚠ Leverage set to ${maxLev}x (Save dabana padega)`);
            // Highlight matching quick-lev button
            document.querySelectorAll('.quick-leverage .btn').forEach(b => {
                b.style.background = '';
                b.style.color = '';
            });
            const btnMatch = document.querySelector(`.quick-leverage .btn[data-lev="${maxLev}"]`);
            if (btnMatch) {
                btnMatch.style.background = '#f0b90b';
                btnMatch.style.color = '#0b0e11';
            }
        });
    }

    // Testnet badge
    const tn = $('testnet');
    if (tn) tn.addEventListener('change', () => {
        const exchange = document.querySelector('.exchange-btn.active')?.dataset.exchange || 'binance';
        updateEnvBadge(tn.value === 'true', exchange);
    });
}

// ===== Main Init =====
document.addEventListener('DOMContentLoaded', () => {
    try { attachListeners(); } catch (e) { console.error(e); }
    try { initSocket(); } catch (e) { console.error(e); }
    try { loadSettings(); } catch (e) { console.error(e); }
    try { refreshStatus(); } catch (e) { console.error(e); }

    log('info', 'Welcome! Coins add karein, settings set karein, aur START dabayein.');
    log('info', 'Strategy: EMA 8,13,21,55 crossover (55 at bottom = LONG, 55 at top = SHORT)');

    try { initChart(); } catch (e) { console.error(e); }

    // Auto-populate coin dropdown from the SELECTED exchange on page load
    // (delayed so loadSettings can set the exchange first)
    setTimeout(() => {
        const exchange = document.querySelector('.exchange-btn.active')?.dataset.exchange || 'binance';
        refreshCoinDropdown(exchange);
    }, 800);

    setInterval(refreshStatus, 3000);
    setInterval(refreshBalance, 10000);
});
