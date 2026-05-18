import { apiUrl, MOBILE_CLIENT_TOKEN } from "./config";

function authHeaders(extra = {}) {
  return {
    ...(MOBILE_CLIENT_TOKEN ? { "X-Assistente-Mobile-Token": MOBILE_CLIENT_TOKEN } : {}),
    ...extra
  };
}

async function request(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: authHeaders(options.headers || {})
  });

  const text = await response.text();
  let body = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { error: text };
  }
  if (!response.ok) {
    throw new Error(body.detail || body.error || `HTTP ${response.status}`);
  }
  return body;
}

export function getBootstrap() {
  return request("/mobile/bootstrap");
}

export function getMobileStatus() {
  return request("/mobile/status");
}

export function sendChat(message, clientId = "mobile") {
  return request("/mobile/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, client_id: clientId })
  });
}

export function sendNotification(message) {
  return request("/mobile/notifications/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: "Assistente Elite Mobile",
      message,
      channels: ["app"]
    })
  });
}

export function getBrainStatus() {
  return request("/mobile/brain/status");
}

export function scanBrain() {
  return request("/mobile/brain/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}"
  });
}

export function searchBrain(query, limit = 12) {
  return request(`/mobile/brain/search?query=${encodeURIComponent(query)}&limit=${limit}`);
}

export function openBrainResult(query, kind = "") {
  return request("/mobile/brain/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, kind, background: true })
  });
}

export function getBrowserStatus() {
  return request("/mobile/browser/status");
}

export function getBrowserApprovals(limit = 20) {
  return request(`/mobile/browser/approvals?limit=${limit}`);
}

export function decideBrowserApproval(approvalId, approved, note = "") {
  return request(`/mobile/browser/approvals/${encodeURIComponent(approvalId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved, note })
  });
}

export async function transcribeAudio(uri, mimeType = "audio/mp4") {
  const formData = new FormData();
  formData.append("audio", {
    uri,
    name: "comando-voz.m4a",
    type: mimeType
  });

  const response = await fetch(apiUrl("/mobile/voice/transcribe"), {
    method: "POST",
    headers: authHeaders(),
    body: formData
  });

  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail || body.error || `HTTP ${response.status}`);
  }
  return body;
}
