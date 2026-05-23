import React, { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View
} from "react-native";

const TABS = [
  { key: "top100", label: "TOP" },
  { key: "search", label: "Search" },
  { key: "chart", label: "Chart" },
  { key: "trade", label: "Trade" },
  { key: "auto", label: "Auto" }
];

const SORTS = [
  { key: "trading_value", label: "Value" },
  { key: "volume", label: "Volume" },
  { key: "market_cap", label: "Cap" },
  { key: "change_rate", label: "Change" }
];

const money = (value, suffix = " KRW") => {
  const n = Number(value || 0);
  if (!Number.isFinite(n) || n === 0) return "-";
  return `${Math.round(n).toLocaleString()}${suffix}`;
};

const compact = (value) => {
  const n = Number(value || 0);
  if (!Number.isFinite(n) || n === 0) return "-";
  if (Math.abs(n) >= 1000000000000) return `${(n / 1000000000000).toFixed(1)}T`;
  if (Math.abs(n) >= 100000000) return `${(n / 100000000).toFixed(1)}B`;
  if (Math.abs(n) >= 10000) return `${(n / 10000).toFixed(1)}M`;
  return Math.round(n).toLocaleString();
};

const pct = (value) => {
  const n = Number(value || 0);
  if (!Number.isFinite(n)) return "-";
  return `${n.toFixed(2)}%`;
};

const cleanTicker = (value) => {
  const raw = String(value || "").trim().toUpperCase();
  if (/^\d{1,6}$/.test(raw)) return raw.padStart(6, "0");
  return raw;
};

export default function App() {
  const [activeTab, setActiveTab] = useState("top100");
  const [serverUrl, setServerUrl] = useState("http://192.168.0.2:8765");
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(null);
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [events, setEvents] = useState([]);
  const [certPassword, setCertPassword] = useState("");
  const [certPressEnter, setCertPressEnter] = useState(true);
  const [certWindowKeywords, setCertWindowKeywords] = useState("공동인증서,인증서,비밀번호,전자서명");
  const [pcWindows, setPcWindows] = useState([]);

  const [top100, setTop100] = useState([]);
  const [topSort, setTopSort] = useState("trading_value");

  const [ticker, setTicker] = useState("486290");
  const [selectedName, setSelectedName] = useState("");
  const [quote, setQuote] = useState(null);
  const [chartData, setChartData] = useState([]);
  const [sellable, setSellable] = useState(null);

  const [quantity, setQuantity] = useState("1");
  const [limitPrice, setLimitPrice] = useState("");
  const [liveOrders, setLiveOrders] = useState(false);

  const [laoerTickers, setLaoerTickers] = useState("TQQQ,SOXL");
  const [laoerSeed, setLaoerSeed] = useState("6000000");

  const baseUrl = useMemo(() => serverUrl.replace(/\/+$/, ""), [serverUrl]);
  const normalizedTicker = cleanTicker(ticker);

  async function api(path, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    };
    const response = await fetch(`${baseUrl}${path}`, { ...options, headers });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    return payload.data;
  }

  async function run(label, fn, { quiet = false } = {}) {
    setLoading(true);
    try {
      const result = await fn();
      pushEvent(`${label} OK`);
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      pushEvent(`${label} ERROR: ${message}`);
      if (!quiet) Alert.alert(label, message);
      return null;
    } finally {
      setLoading(false);
    }
  }

  function pushEvent(message) {
    setEvents((prev) => [`${new Date().toLocaleTimeString()} ${message}`, ...prev].slice(0, 14));
  }

  async function refreshHealth() {
    const data = await run("health", () => api("/api/health"));
    if (data) setStatus(data);
  }

  async function connect() {
    const data = await run("connect", () => api("/api/connect", { method: "POST", body: "{}" }));
    if (!data) return;
    setAccount(data.balance);
    setPositions(data.positions || []);
    setStatus((prev) => ({ ...(prev || {}), connected: true }));
  }

  async function refreshAccount() {
    const data = await run("account", () => api("/api/account"));
    if (data) setAccount(data);
  }

  async function refreshPositions() {
    const data = await run("positions", () => api("/api/positions"));
    if (data) setPositions(data);
  }

  async function refreshPcWindows() {
    const q = encodeURIComponent(certWindowKeywords);
    const data = await run("pc windows", () => api(`/api/pc-windows?keywords=${q}`));
    if (data) setPcWindows(data);
  }

  async function sendCertPassword() {
    if (!certPassword) {
      Alert.alert("Certificate", "Password is required.");
      return;
    }
    const body = JSON.stringify({
      password: certPassword,
      press_enter: certPressEnter,
      keywords: certWindowKeywords
    });
    const data = await run("cert password", () => api("/api/cert/type-password", { method: "POST", body }));
    setCertPassword("");
    if (data) {
      Alert.alert("Certificate", `Typed ${data.chars_typed} chars into\n${data.window?.title || "PC window"}`);
    }
  }

  async function refreshTop100() {
    const path = `/api/top100?limit=100&market=ALL&sort=${encodeURIComponent(topSort)}`;
    const data = await run("top100", () => api(path));
    if (data) setTop100(data);
  }

  async function lookupQuote(nextTicker = normalizedTicker) {
    const clean = cleanTicker(nextTicker);
    if (!clean) return null;
    const data = await run("quote", () => api(`/api/quote?ticker=${encodeURIComponent(clean)}`));
    if (data) {
      setQuote(data);
      const price = Number(data.bid || data.last || 0);
      if (price > 0) setLimitPrice(String(Math.round(price)));
    }
    return data;
  }

  async function refreshChart(nextTicker = normalizedTicker) {
    const clean = cleanTicker(nextTicker);
    if (!clean) return;
    const data = await run("chart", () => api(`/api/chart?ticker=${encodeURIComponent(clean)}&count=120`));
    if (data) setChartData(data);
  }

  async function checkSellable() {
    const clean = normalizedTicker;
    const data = await run("sellable", () => api(`/api/sellable?ticker=${encodeURIComponent(clean)}`));
    if (data) setSellable(data);
  }

  function openTicker(item, tab = "chart") {
    const nextTicker = cleanTicker(typeof item === "string" ? item : item?.ticker);
    if (!nextTicker) return;
    setTicker(nextTicker);
    setSelectedName(typeof item === "string" ? "" : item?.name || "");
    setQuote(null);
    setSellable(null);
    setActiveTab(tab);
    if (tab === "chart") refreshChart(nextTicker);
    if (tab === "trade") lookupQuote(nextTicker);
  }

  async function submitOrder(side) {
    const body = JSON.stringify({
      ticker: normalizedTicker,
      side,
      quantity: Number(quantity),
      limit_price: Number(limitPrice),
      dry_run: !liveOrders
    });
    const data = await run(`${side} order`, () => api("/api/order", { method: "POST", body }));
    if (data) {
      Alert.alert(`${side} result`, `${data.status}\n${data.rejection_reason || data.broker_order_id || ""}`);
    }
  }

  async function runLaoerTick() {
    const body = JSON.stringify({
      tickers: laoerTickers,
      seed_per_ticker_krw: laoerSeed ? Number(laoerSeed) : null,
      dry_run: !liveOrders
    });
    const data = await run("laoer tick", () => api("/api/laoer/tick", { method: "POST", body }));
    if (data) {
      Alert.alert("Laoer tick", `items=${data.items?.length || 0}, errors=${data.errors?.length || 0}`);
    }
  }

  function renderActiveTab() {
    if (activeTab === "top100") {
      return (
        <Screen>
          <HeaderLine title="Market Top 100" subtitle="Tap a row for chart, Trade for order screen." />
          <View style={styles.segment}>
            {SORTS.map((sort) => (
              <TouchableOpacity
                key={sort.key}
                style={[styles.segmentButton, topSort === sort.key && styles.segmentActive]}
                onPress={() => setTopSort(sort.key)}
              >
                <Text style={[styles.segmentText, topSort === sort.key && styles.segmentTextActive]}>{sort.label}</Text>
              </TouchableOpacity>
            ))}
          </View>
          <Button title="Refresh Top 100" onPress={refreshTop100} tone="primary" />
          {top100.length === 0 ? <Empty text="No ranking loaded." /> : null}
          {top100.map((item) => (
            <TouchableOpacity key={`${item.rank}-${item.ticker}`} style={styles.rankRow} onPress={() => openTicker(item, "chart")}>
              <View style={styles.rankLeft}>
                <Text style={styles.rankNo}>{item.rank}</Text>
                <View>
                  <Text style={styles.rowTitle}>{item.ticker} {item.name}</Text>
                  <Text style={styles.muted}>as of {item.as_of || "-"}  {item.source}</Text>
                </View>
              </View>
              <View style={styles.rankRight}>
                <Text style={styles.priceText}>{money(item.price)}</Text>
                <Text style={[styles.muted, Number(item.change_rate) >= 0 ? styles.good : styles.bad]}>
                  {pct(item.change_rate)}  V {compact(item.trading_value)}
                </Text>
                <TouchableOpacity style={styles.smallTradeButton} onPress={() => openTicker(item, "trade")}>
                  <Text style={styles.smallTradeText}>Trade</Text>
                </TouchableOpacity>
              </View>
            </TouchableOpacity>
          ))}
        </Screen>
      );
    }

    if (activeTab === "search") {
      return (
        <Screen>
          <HeaderLine title="Search" subtitle="Search, connect bridge, and load account." />
          <Section title="Bridge">
            <Field label="Server URL" value={serverUrl} onChangeText={setServerUrl} autoCapitalize="none" />
            <Field label="Token" value={token} onChangeText={setToken} autoCapitalize="none" secureTextEntry />
            <View style={styles.row}>
              <Button title="Health" onPress={refreshHealth} />
              <Button title="Connect" onPress={connect} tone="primary" />
            </View>
            <Text style={styles.muted}>Connected: {String(status?.connected ?? false)}</Text>
          </Section>

          <Section title="PC Certificate">
            <Field label="Window keywords" value={certWindowKeywords} onChangeText={setCertWindowKeywords} autoCapitalize="none" />
            <Field label="Certificate password" value={certPassword} onChangeText={setCertPassword} secureTextEntry autoCapitalize="none" />
            <TouchableOpacity style={styles.switchRow} onPress={() => setCertPressEnter(!certPressEnter)}>
              <View style={[styles.checkbox, certPressEnter && styles.checkboxOn]} />
              <Text style={styles.switchText}>Press Enter after typing {certPressEnter ? "ON" : "OFF"}</Text>
            </TouchableOpacity>
            <View style={styles.row}>
              <Button title="Find Windows" onPress={refreshPcWindows} />
              <Button title="Type to PC" onPress={sendCertPassword} tone="sell" />
            </View>
            {pcWindows.length === 0 ? <Text style={styles.muted}>Connect first, then send while the certificate password window is visible on the PC.</Text> : null}
            {pcWindows.slice(0, 3).map((win) => (
              <View key={`${win.hwnd}-${win.title}`} style={styles.windowRow}>
                <Text style={styles.rowTitle} numberOfLines={1}>{win.title}</Text>
                <Text style={styles.muted} numberOfLines={1}>{win.class_name}</Text>
              </View>
            ))}
          </Section>

          <Section title="Ticker">
            <Field label="Ticker" value={ticker} onChangeText={setTicker} autoCapitalize="characters" />
            <View style={styles.row}>
              <Button title="Quote" onPress={() => lookupQuote()} />
              <Button title="Chart" onPress={() => openTicker(normalizedTicker, "chart")} tone="primary" />
              <Button title="Trade" onPress={() => openTicker(normalizedTicker, "trade")} tone="buy" />
            </View>
            <QuoteBlock quote={quote} />
          </Section>

          <Section title="Account">
            <View style={styles.row}>
              <Button title="Refresh Account" onPress={refreshAccount} />
              <Button title="Positions" onPress={refreshPositions} />
            </View>
            {account ? (
              <View style={styles.metrics}>
                <Metric label="Cash" value={money(account.cash)} />
                <Metric label="Equity" value={money(account.total_equity)} />
                <Metric label="Positions" value={money(account.positions_value)} />
              </View>
            ) : <Empty text="No account data." />}
          </Section>

          <Section title="Positions">
            {positions.length === 0 ? <Empty text="No positions loaded." /> : null}
            {positions.map((pos) => (
              <TouchableOpacity key={pos.ticker} style={styles.position} onPress={() => openTicker(pos, "chart")}>
                <View>
                  <Text style={styles.rowTitle}>{pos.ticker} {pos.name}</Text>
                  <Text style={styles.muted}>qty {Number(pos.quantity).toLocaleString()} avg {money(pos.avg_price)}</Text>
                </View>
                <View style={styles.positionRight}>
                  <Text style={styles.rowTitle}>{money(pos.current_price)}</Text>
                  <Text style={[styles.muted, Number(pos.unrealized_pnl) >= 0 ? styles.good : styles.bad]}>
                    {money(pos.unrealized_pnl)} ({pct(Number(pos.unrealized_pnl_pct) * 100)})
                  </Text>
                </View>
              </TouchableOpacity>
            ))}
          </Section>
        </Screen>
      );
    }

    if (activeTab === "chart") {
      return (
        <Screen>
          <HeaderLine title={`${normalizedTicker} ${selectedName}`} subtitle="Daily chart from pykrx." />
          <View style={styles.row}>
            <Field compact label="Ticker" value={ticker} onChangeText={setTicker} autoCapitalize="characters" />
            <Button title="Load" onPress={() => refreshChart()} tone="primary" />
            <Button title="Trade" onPress={() => openTicker(normalizedTicker, "trade")} tone="buy" />
          </View>
          <MiniChart data={chartData} />
          <Section title="Recent">
            {chartData.slice(-8).reverse().map((row) => (
              <View key={`${row.date}-${row.close}`} style={styles.ohlcvRow}>
                <Text style={styles.muted}>{row.date}</Text>
                <Text style={styles.rowTitle}>{money(row.close)}</Text>
                <Text style={styles.muted}>vol {compact(row.volume)}</Text>
              </View>
            ))}
          </Section>
        </Screen>
      );
    }

    if (activeTab === "trade") {
      return (
        <Screen>
          <HeaderLine title={`${normalizedTicker} Trade`} subtitle={selectedName || "Manual order screen"} />
          <Section title="Market">
            <Field label="Ticker" value={ticker} onChangeText={setTicker} autoCapitalize="characters" />
            <View style={styles.row}>
              <Button title="Quote" onPress={() => lookupQuote()} />
              <Button title="Sellable" onPress={checkSellable} />
              <Button title="Chart" onPress={() => openTicker(normalizedTicker, "chart")} tone="primary" />
            </View>
            <QuoteBlock quote={quote} />
            {sellable ? <Text style={styles.muted}>Sellable max {Number(sellable.max || 0).toLocaleString()} (p8104 {sellable.p8104 ?? "-"})</Text> : null}
          </Section>

          <Section title="Order">
            <Field label="Quantity" value={quantity} onChangeText={setQuantity} keyboardType="number-pad" />
            <Field label="Limit Price" value={limitPrice} onChangeText={setLimitPrice} keyboardType="number-pad" />
            <TouchableOpacity style={styles.switchRow} onPress={() => setLiveOrders(!liveOrders)}>
              <View style={[styles.checkbox, liveOrders && styles.checkboxOn]} />
              <Text style={styles.switchText}>Live orders {liveOrders ? "ON" : "OFF"} default is dry-run</Text>
            </TouchableOpacity>
            <View style={styles.row}>
              <Button title="BUY" onPress={() => submitOrder("BUY")} tone="buy" />
              <Button title="SELL" onPress={() => submitOrder("SELL")} tone="sell" />
            </View>
          </Section>
        </Screen>
      );
    }

    return (
      <Screen>
        <HeaderLine title="Auto Trading" subtitle="Laoer tick runner and recent logs." />
        <Section title="Laoer">
          <Field label="Tickers" value={laoerTickers} onChangeText={setLaoerTickers} autoCapitalize="characters" />
          <Field label="Seed per ticker KRW" value={laoerSeed} onChangeText={setLaoerSeed} keyboardType="number-pad" />
          <TouchableOpacity style={styles.switchRow} onPress={() => setLiveOrders(!liveOrders)}>
            <View style={[styles.checkbox, liveOrders && styles.checkboxOn]} />
            <Text style={styles.switchText}>Live orders {liveOrders ? "ON" : "OFF"}</Text>
          </TouchableOpacity>
          <Button title="Run Laoer Tick" onPress={runLaoerTick} tone="primary" />
        </Section>
        <Section title="Log">
          {events.length === 0 ? <Empty text="No events yet." /> : null}
          {events.map((event, index) => <Text key={`${event}-${index}`} style={styles.log}>{event}</Text>)}
        </Section>
      </Screen>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.appHeader}>
        <View>
          <Text style={styles.appTitle}>Trading</Text>
          <Text style={styles.appSubtitle}>{status?.connected ? "Bridge connected" : "Bridge offline"}  {liveOrders ? "LIVE" : "DRY"}</Text>
        </View>
        {loading ? <ActivityIndicator color="#8bd4a8" /> : null}
      </View>
      <View style={styles.content}>
        <ScrollView contentContainerStyle={styles.scrollContent}>
          {renderActiveTab()}
        </ScrollView>
      </View>
      <View style={styles.tabBar}>
        {TABS.map((tab) => (
          <TouchableOpacity
            key={tab.key}
            style={[styles.tabButton, activeTab === tab.key && styles.tabButtonActive]}
            onPress={() => setActiveTab(tab.key)}
          >
            <Text style={[styles.tabText, activeTab === tab.key && styles.tabTextActive]}>{tab.label}</Text>
          </TouchableOpacity>
        ))}
      </View>
    </SafeAreaView>
  );
}

function Screen({ children }) {
  return <View style={styles.screen}>{children}</View>;
}

function HeaderLine({ title, subtitle }) {
  return (
    <View style={styles.headerLine}>
      <Text style={styles.screenTitle} numberOfLines={1}>{title}</Text>
      <Text style={styles.screenSubtitle} numberOfLines={2}>{subtitle}</Text>
    </View>
  );
}

function Section({ title, children }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

function Field({ label, compact: isCompact, ...props }) {
  return (
    <View style={[styles.field, isCompact && styles.fieldCompact]}>
      <Text style={styles.label}>{label}</Text>
      <TextInput style={styles.input} placeholderTextColor="#778" {...props} />
    </View>
  );
}

function Button({ title, onPress, tone = "normal" }) {
  return (
    <TouchableOpacity style={[styles.button, styles[`button_${tone}`]]} onPress={onPress}>
      <Text style={styles.buttonText}>{title}</Text>
    </TouchableOpacity>
  );
}

function Metric({ label, value }) {
  return (
    <View style={styles.metric}>
      <Text style={styles.muted}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
    </View>
  );
}

function Empty({ text }) {
  return <Text style={styles.empty}>{text}</Text>;
}

function QuoteBlock({ quote }) {
  if (!quote) return null;
  return (
    <View style={styles.quoteBlock}>
      <Metric label="Last" value={money(quote.last)} />
      <Metric label="Bid" value={money(quote.bid)} />
      <Metric label="Ask" value={money(quote.ask)} />
    </View>
  );
}

function MiniChart({ data }) {
  const rows = data.slice(-56);
  if (rows.length === 0) {
    return <View style={styles.chartBox}><Empty text="No chart loaded." /></View>;
  }
  const closes = rows.map((row) => Number(row.close || 0)).filter((n) => Number.isFinite(n) && n > 0);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = Math.max(max - min, 1);
  const last = closes[closes.length - 1] || 0;

  return (
    <View style={styles.chartBox}>
      <View style={styles.chartHeader}>
        <Text style={styles.rowTitle}>{money(last)}</Text>
        <Text style={styles.muted}>{rows[0]?.date || ""} to {rows[rows.length - 1]?.date || ""}</Text>
      </View>
      <View style={styles.bars}>
        {rows.map((row, index) => {
          const close = Number(row.close || 0);
          const prev = Number(rows[index - 1]?.close || close);
          const height = 8 + ((close - min) / range) * 108;
          return (
            <View key={`${row.date}-${index}`} style={styles.barWrap}>
              <View
                style={[
                  styles.bar,
                  { height },
                  close >= prev ? styles.barUp : styles.barDown
                ]}
              />
            </View>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#101418" },
  appHeader: {
    height: 70,
    paddingHorizontal: 16,
    paddingTop: 10,
    paddingBottom: 8,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#151a1f",
    borderBottomWidth: 1,
    borderBottomColor: "#2b3137"
  },
  appTitle: { color: "#f4f1e8", fontSize: 25, fontWeight: "800" },
  appSubtitle: { color: "#9aa7a7", marginTop: 2 },
  content: { flex: 1 },
  scrollContent: { padding: 14, paddingBottom: 18 },
  screen: { gap: 12 },
  headerLine: { gap: 3 },
  screenTitle: { color: "#f4f1e8", fontSize: 23, fontWeight: "800" },
  screenSubtitle: { color: "#9aa7a7", fontSize: 13 },
  section: {
    backgroundColor: "#1b2022",
    borderColor: "#30383a",
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    gap: 10
  },
  sectionTitle: { color: "#f4f1e8", fontSize: 16, fontWeight: "800" },
  row: { flexDirection: "row", gap: 8, flexWrap: "wrap", alignItems: "flex-end" },
  field: { gap: 5 },
  fieldCompact: { flex: 1, minWidth: 140 },
  label: { color: "#9aa7a7", fontSize: 12 },
  input: {
    backgroundColor: "#111619",
    borderColor: "#3a4446",
    borderWidth: 1,
    borderRadius: 7,
    color: "#f4f1e8",
    paddingHorizontal: 10,
    paddingVertical: 10
  },
  button: {
    backgroundColor: "#30383a",
    paddingHorizontal: 14,
    paddingVertical: 11,
    borderRadius: 7,
    minWidth: 94,
    alignItems: "center"
  },
  button_primary: { backgroundColor: "#2d6a6f" },
  button_buy: { backgroundColor: "#247547" },
  button_sell: { backgroundColor: "#9b3535" },
  button_normal: {},
  buttonText: { color: "#fff", fontWeight: "800" },
  segment: {
    flexDirection: "row",
    backgroundColor: "#151a1f",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#2d3438",
    overflow: "hidden"
  },
  segmentButton: { flex: 1, paddingVertical: 10, alignItems: "center" },
  segmentActive: { backgroundColor: "#315f55" },
  segmentText: { color: "#9aa7a7", fontWeight: "700", fontSize: 12 },
  segmentTextActive: { color: "#fff" },
  muted: { color: "#9aa7a7" },
  empty: { color: "#7f8a8d", paddingVertical: 8 },
  good: { color: "#69d08d" },
  bad: { color: "#ff7b72" },
  rankRow: {
    backgroundColor: "#1b2022",
    borderColor: "#30383a",
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 10
  },
  rankLeft: { flexDirection: "row", gap: 11, flex: 1 },
  rankNo: { color: "#d6b56d", fontSize: 18, fontWeight: "900", minWidth: 28, textAlign: "right" },
  rankRight: { alignItems: "flex-end", gap: 4, maxWidth: 150 },
  rowTitle: { color: "#f4f1e8", fontWeight: "800" },
  priceText: { color: "#f4f1e8", fontWeight: "900" },
  smallTradeButton: { backgroundColor: "#247547", borderRadius: 6, paddingHorizontal: 10, paddingVertical: 5 },
  smallTradeText: { color: "#fff", fontWeight: "800", fontSize: 12 },
  metrics: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  metric: { flexGrow: 1, minWidth: 96, backgroundColor: "#111619", borderRadius: 7, padding: 10 },
  metricValue: { color: "#f4f1e8", fontSize: 15, fontWeight: "800", marginTop: 4 },
  quoteBlock: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  position: { flexDirection: "row", justifyContent: "space-between", backgroundColor: "#111619", borderRadius: 7, padding: 10, gap: 10 },
  positionRight: { alignItems: "flex-end" },
  windowRow: { backgroundColor: "#111619", borderRadius: 7, padding: 9, gap: 3 },
  chartBox: {
    backgroundColor: "#1b2022",
    borderColor: "#30383a",
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    minHeight: 180
  },
  chartHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 12 },
  bars: { height: 126, flexDirection: "row", alignItems: "flex-end", gap: 2 },
  barWrap: { flex: 1, alignItems: "center", justifyContent: "flex-end", height: 126 },
  bar: { width: "70%", minHeight: 4, borderTopLeftRadius: 3, borderTopRightRadius: 3 },
  barUp: { backgroundColor: "#5fc48a" },
  barDown: { backgroundColor: "#de5f57" },
  ohlcvRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: "#2b3137" },
  switchRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  checkbox: { width: 19, height: 19, borderRadius: 5, borderColor: "#6b7481", borderWidth: 1 },
  checkboxOn: { backgroundColor: "#247547", borderColor: "#247547" },
  switchText: { color: "#f4f1e8" },
  log: { color: "#d0d7d2", fontSize: 12, marginBottom: 5 },
  tabBar: {
    height: 66,
    flexDirection: "row",
    backgroundColor: "#151a1f",
    borderTopWidth: 1,
    borderTopColor: "#2b3137",
    paddingHorizontal: 6,
    paddingTop: 6,
    paddingBottom: 7
  },
  tabButton: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    minWidth: 0
  },
  tabButtonActive: { backgroundColor: "#263133" },
  tabText: { color: "#8d989b", fontSize: 12, fontWeight: "800" },
  tabTextActive: { color: "#f4f1e8" }
});
