const apiBaseUrl = process.env.EXPO_PUBLIC_ASSISTENTE_API_URL || "http://127.0.0.1:8008";
const mobileClientToken = process.env.EXPO_PUBLIC_ASSISTENTE_CLIENT_TOKEN || "";

module.exports = {
  expo: {
    name: "Assistente Elite",
    slug: "assistente-elite",
    version: "0.1.0",
    orientation: "portrait",
    userInterfaceStyle: "dark",
    scheme: "assistenteelite",
    assetBundlePatterns: ["**/*"],
    ios: {
      supportsTablet: true,
      bundleIdentifier: "com.assistenteelite.mobile",
      infoPlist: {
        NSMicrophoneUsageDescription: "O Assistente Elite usa o microfone para enviar comandos de voz quando voce tocar em gravar."
      }
    },
    android: {
      package: "com.assistenteelite.mobile",
      usesCleartextTraffic: true,
      permissions: ["RECORD_AUDIO"]
    },
    plugins: [
      [
        "expo-audio",
        {
          microphonePermission: "Permita que o Assistente Elite use o microfone para comandos de voz.",
          recordAudioAndroid: true,
          enableBackgroundRecording: false,
          enableBackgroundPlayback: false
        }
      ]
    ],
    extra: {
      apiBaseUrl,
      mobileClientToken,
      appChannel: process.env.EXPO_PUBLIC_ASSISTENTE_CHANNEL || "production"
    }
  }
};
