import Constants from "expo-constants";

const extra = Constants.expoConfig?.extra || Constants.manifest?.extra || {};

export const API_BASE_URL = String(extra.apiBaseUrl || "http://127.0.0.1:8008").replace(/\/+$/, "");
export const MOBILE_CLIENT_TOKEN = String(extra.mobileClientToken || "");
export const APP_CHANNEL = String(extra.appChannel || "production");

export function apiUrl(path) {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${cleanPath}`;
}
