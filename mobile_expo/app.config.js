module.exports = {
  expo: {
    name: "Trading Companion",
    slug: "trading-companion",
    version: "0.1.0",
    orientation: "portrait",
    platforms: ["android"],
    plugins: ["./plugins/withCleartextTraffic"],
    android: {
      package: "com.local.tradingcompanion",
      versionCode: 1
    }
  }
};
