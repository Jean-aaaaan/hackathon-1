/**
 * Vantage Chrome Extension — Popup script
 * Handles settings save/load and connection status check.
 */

const DEFAULT_API_URL = "https://api.vantage.ai";

async function loadSettings() {
  const result = await chrome.storage.sync.get(["apiKey", "apiUrl"]);
  const apiKey = result.apiKey as string || "";
  const apiUrl = result.apiUrl as string || DEFAULT_API_URL;

  (document.getElementById("apiKey") as HTMLInputElement).value = apiKey;
  (document.getElementById("apiUrl") as HTMLInputElement).value = apiUrl;

  if (apiKey) {
    await checkConnection(apiKey, apiUrl);
  }
}

async function checkConnection(apiKey: string, apiUrl: string) {
  const dot = document.getElementById("connectionDot")!;
  const label = document.getElementById("connectionLabel")!;

  try {
    const res = await fetch(`${apiUrl}/health`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) {
      dot.classList.add("connected");
      label.textContent = "Connected";
    } else {
      dot.classList.remove("connected");
      label.textContent = "Auth failed";
    }
  } catch {
    dot.classList.remove("connected");
    label.textContent = "Cannot reach API";
  }
}

document.getElementById("saveBtn")?.addEventListener("click", async () => {
  const apiKey = (document.getElementById("apiKey") as HTMLInputElement).value.trim();
  const apiUrl = (document.getElementById("apiUrl") as HTMLInputElement).value.trim() || DEFAULT_API_URL;
  const status = document.getElementById("status")!;

  if (!apiKey) {
    status.textContent = "API key is required";
    status.className = "status error";
    return;
  }

  await chrome.storage.sync.set({ apiKey, apiUrl });

  status.textContent = "Saved! Testing connection…";
  status.className = "status";

  await checkConnection(apiKey, apiUrl);

  const connected = document.getElementById("connectionDot")!.classList.contains("connected");
  if (connected) {
    status.textContent = "Connected successfully ✓";
    status.className = "status success";
  } else {
    status.textContent = "Saved, but connection failed — check API key";
    status.className = "status error";
  }
});

loadSettings();
