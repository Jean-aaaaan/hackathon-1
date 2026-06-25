"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

const REDIRECT_URI = `${process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000"}/auth/outlook/callback`;

function CallbackInner() {
  const router     = useRouter();
  const params     = useSearchParams();
  const [status, setStatus] = useState<"connecting" | "success" | "error">("connecting");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const code  = params.get("code");
    const state = params.get("state");
    const error = params.get("error");

    if (error) {
      setStatus("error");
      setMessage(params.get("error_description") || "Microsoft declined the request.");
      return;
    }

    if (!code) {
      setStatus("error");
      setMessage("No authorisation code returned from Microsoft.");
      return;
    }

    fetch("/api/v1/workspace/integrations/outlook/callback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ code, state: state ?? "" }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.data?.connected) {
          setStatus("success");
          setMessage(`Connected as ${d.data.user_email}`);
          const returnTo = typeof window !== "undefined" ? localStorage.getItem("outlook_oauth_return") : null;
          if (returnTo) localStorage.removeItem("outlook_oauth_return");
          setTimeout(() => router.push(returnTo ?? "/settings"), 1800);
        } else {
          setStatus("error");
          setMessage(d.error?.message || "Token exchange failed.");
        }
      })
      .catch(() => {
        setStatus("error");
        setMessage("Could not reach the API. Make sure the backend is running.");
      });
  }, [params, router]);

  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      background: "#f8f9fb",
    }}>
      <div style={{
        background: "#fff", borderRadius: 16, padding: "40px 48px",
        boxShadow: "0 4px 24px rgba(0,0,0,.08)", textAlign: "center", maxWidth: 400,
      }}>
        {status === "connecting" && (
          <>
            <div style={{
              width: 48, height: 48, border: "3px solid #4f46e5", borderTopColor: "transparent",
              borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 20px",
            }} />
            <p style={{ fontSize: 16, fontWeight: 600, color: "#111827", marginBottom: 6 }}>
              Connecting Outlook
            </p>
            <p style={{ fontSize: 13, color: "#6b7280" }}>Exchanging tokens with Microsoft...</p>
          </>
        )}

        {status === "success" && (
          <>
            <div style={{
              width: 48, height: 48, borderRadius: "50%", background: "#d1fae5",
              display: "flex", alignItems: "center", justifyContent: "center",
              margin: "0 auto 20px", fontSize: 24,
            }}>
              ✓
            </div>
            <p style={{ fontSize: 16, fontWeight: 600, color: "#111827", marginBottom: 6 }}>
              Outlook Connected
            </p>
            <p style={{ fontSize: 13, color: "#6b7280", marginBottom: 16 }}>{message}</p>
            <p style={{ fontSize: 12, color: "#9ca3af" }}>Redirecting to Settings...</p>
          </>
        )}

        {status === "error" && (
          <>
            <div style={{
              width: 48, height: 48, borderRadius: "50%", background: "#fee2e2",
              display: "flex", alignItems: "center", justifyContent: "center",
              margin: "0 auto 20px", fontSize: 24,
            }}>
              ✕
            </div>
            <p style={{ fontSize: 16, fontWeight: 600, color: "#111827", marginBottom: 6 }}>
              Connection Failed
            </p>
            <p style={{ fontSize: 13, color: "#6b7280", marginBottom: 20 }}>{message}</p>
            <button
              onClick={() => router.push("/settings")}
              style={{
                background: "#4f46e5", color: "#fff", border: "none", borderRadius: 8,
                padding: "10px 24px", fontSize: 13, fontWeight: 600, cursor: "pointer",
              }}
            >
              Back to Settings
            </button>
          </>
        )}
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

export default function OutlookCallbackPage() {
  return (
    <Suspense fallback={
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ width: 32, height: 32, border: "3px solid #4f46e5", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    }>
      <CallbackInner />
    </Suspense>
  );
}
