const { withAndroidManifest } = require("expo/config-plugins");

module.exports = function withCleartextTraffic(config) {
  return withAndroidManifest(config, (modConfig) => {
    const application = modConfig.modResults.manifest.application?.[0];
    if (application) {
      application.$ = application.$ || {};
      application.$["android:usesCleartextTraffic"] = "true";
    }
    return modConfig;
  });
};
