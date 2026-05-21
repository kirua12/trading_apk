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

const money = (value) => {
  const n = Number(value || 0);
  return `${Math.round(n).toLocaleString()}원`;
};

const pct = (value) => `${(Number(value || 0) * 100).toFixed(2)}%`;

export default function App() {
  const [serverUrl, setServerUrl] = useState("http://192.168.0.2:8765");
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(null);
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [quote, setQuote] = useState(null);
  const [sellable, setSellable] = useState(null);

  const [ticker, setTicker] = useState("486290");
  const [quantity, setQuantity] = useState("1");
  const [limitPrice, setLimitPrice] = useState("");
  const [liveOrders, setLiveOrders] = useState(false);

  const [laoerTickers, setLaoerTickers] = useState("TQQQ,SOXL");
  const [laoerSeed, setLaoerSeed] = useState("6000000");
  const [events, setEvents] = useState([]);

  const baseUrl = useMemo(() => serverUrl.replace(/\/+$/, ""), [serverUrl]);

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

  async function run(label, fn) {
    setLoading(true);
    try {
      const result = await fn();
      setEvents((prev) => [`${new Date().toLocaleTimeString()} ${label} OK`, ...prev].slice(0, 10));
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setEvents((prev) => [`${new Date().toLocaleTimeString()} ${label} ERROR: ${message}`, ...prev].slice(0, 10));
      Alert.alert(label, message);
      return null;
    } finally {
      setLoading(false);
    }
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

  async function lookupQuote() {
    const clean = ticker.trim();
    const data = await run("quote", () => api(`/api/quote?ticker=${encodeURIComponent(clean)}`));
    if (data) {
      setQuote(data);
      const price = Number(data.bid || data.last || 0);
      if (price > 0) setLimitPrice(String(Math.round(price)));
    }
  }

  async function checkSellable() {
    const clean = ticker.trim();
    const data = await run("sellable", () => api(`/api/sellable?ticker=${encodeURIComponent(clean)}`));
    if (data) setSellable(data);
  }

  async function submitOrder(side) {
    const body = JSON.stringify({
      ticker: ticker.trim(),
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

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.headerRow}>
          <Text style={styles.title}>Trading Companion</Text>
          {loading ? <ActivityIndicator /> : null}
        </View>

        <Section title="Bridge">
          <Field label="Server URL" value={serverUrl} onChangeText={setServerUrl} autoCapitalize="none" />
          <Field label="Token" value={token} onChangeText={setToken} autoCapitalize="none" secureTextEntry />
          <View style={styles.row}>
            <Button title="Health" onPress={refreshHealth} />
            <Button title="Connect" onPress={connect} tone="primary" />
          </View>
          <Text style={styles.muted}>Connected: {String(status?.connected ?? false)}</Text>
        </Section>

        <Section title="Account">
          <View style={styles.row}>
            <Button title="Refresh Account" onPress={refreshAccount} />
            <Button title="Refresh Positions" onPress={refreshPositions} />
          </View>
          {account ? (
            <View style={styles.metrics}>
              <Metric label="Cash" value={money(account.cash)} />
              <Metric label="Equity" value={money(account.total_equity)} />
              <Metric label="Positions" value={money(account.positions_value)} />
            </View>
          ) : <Text style={styles.muted}>No account data.</Text>}
        </Section>

        <Section title="Positions">
          {positions.length === 0 ? <Text style={styles.muted}>No positions loaded.</Text> : null}
          {positions.map((pos) => (
            <TouchableOpacity key={pos.ticker} style={styles.position} onPress={() => setTicker(pos.ticker)}>
              <View>
                <Text style={styles.positionTitle}>{pos.ticker} {pos.name}</Text>
                <Text style={styles.muted}>qty {Number(pos.quantity).toLocaleString()} avg {money(pos.avg_price)}</Text>
              </View>
              <View style={styles.positionRight}>
                <Text style={styles.positionTitle}>{money(pos.current_price)}</Text>
                <Text style={[styles.muted, Number(pos.unrealized_pnl) >= 0 ? styles.good : styles.bad]}>
                  {money(pos.unrealized_pnl)} ({pct(pos.unrealized_pnl_pct)})
                </Text>
              </View>
            </TouchableOpacity>
          ))}
        </Section>

        <Section title="Manual Trade">
          <Field label="Ticker" value={ticker} onChangeText={setTicker} keyboardType="number-pad" />
          <View style={styles.row}>
            <Button title="Quote" onPress={lookupQuote} />
            <Button title="Sellable" onPress={checkSellable} />
          </View>
          {quote ? <Text style={styles.muted}>Last {money(quote.last)} Bid {money(quote.bid)} Ask {money(quote.ask)}</Text> : null}
          {sellable ? <Text style={styles.muted}>Sellable max {Number(sellable.max || 0).toLocaleString()} (p8104 {sellable.p8104 ?? "-"})</Text> : null}
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

        <Section title="Laoer">
          <Field label="Tickers" value={laoerTickers} onChangeText={setLaoerTickers} autoCapitalize="characters" />
          <Field label="Seed per ticker KRW" value={laoerSeed} onChangeText={setLaoerSeed} keyboardType="number-pad" />
          <Button title="Run Laoer Tick" onPress={runLaoerTick} tone="primary" />
        </Section>

        <Section title="Log">
          {events.map((event, index) => <Text key={`${event}-${index}`} style={styles.log}>{event}</Text>)}
        </Section>
      </ScrollView>
    </SafeAreaView>
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

function Field({ label, ...props }) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput style={styles.input} placeholderTextColor="#778" {...props} />
    </View>
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

function Button({ title, onPress, tone = "normal" }) {
  return (
    <TouchableOpacity style={[styles.button, styles[`button_${tone}`]]} onPress={onPress}>
      <Text style={styles.buttonText}>{title}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#111418" },
  container: { padding: 14, gap: 12 },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  title: { color: "#f4f7fb", fontSize: 24, fontWeight: "800" },
  section: { backgroundColor: "#1b2027", borderColor: "#303844", borderWidth: 1, borderRadius: 8, padding: 12, gap: 10 },
  sectionTitle: { color: "#f4f7fb", fontSize: 17, fontWeight: "700" },
  field: { gap: 5 },
  label: { color: "#aab4c3", fontSize: 12 },
  input: { backgroundColor: "#101318", borderColor: "#36404d", borderWidth: 1, borderRadius: 6, color: "#f4f7fb", paddingHorizontal: 10, paddingVertical: 9 },
  row: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  button: { backgroundColor: "#303844", paddingHorizontal: 14, paddingVertical: 10, borderRadius: 6, minWidth: 96, alignItems: "center" },
  button_primary: { backgroundColor: "#2f6fed" },
  button_buy: { backgroundColor: "#1f6f4a" },
  button_sell: { backgroundColor: "#9b3535" },
  button_normal: {},
  buttonText: { color: "#fff", fontWeight: "700" },
  muted: { color: "#aab4c3" },
  good: { color: "#55d18c" },
  bad: { color: "#ff7b72" },
  metrics: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  metric: { flexGrow: 1, minWidth: 100, backgroundColor: "#101318", borderRadius: 6, padding: 10 },
  metricValue: { color: "#f4f7fb", fontSize: 16, fontWeight: "700", marginTop: 4 },
  position: { flexDirection: "row", justifyContent: "space-between", backgroundColor: "#101318", borderRadius: 6, padding: 10, gap: 10 },
  positionTitle: { color: "#f4f7fb", fontWeight: "700" },
  positionRight: { alignItems: "flex-end" },
  switchRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  checkbox: { width: 18, height: 18, borderRadius: 4, borderColor: "#6b7481", borderWidth: 1 },
  checkboxOn: { backgroundColor: "#2f6fed", borderColor: "#2f6fed" },
  switchText: { color: "#f4f7fb" },
  log: { color: "#d0d7e2", fontSize: 12, marginBottom: 4 }
});
