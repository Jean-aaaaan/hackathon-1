"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, RefreshCw } from "lucide-react";

const ERROR_MESSAGES: Record<string, { title: string; description: string }> = {
  access_denied:         { title: "Access denied",         description: "You cancelled the sign-in request. Try again when you're ready." },
  token_expired:         { title: "Session expired",       description: "Your session has expired. Please sign in again." },
  insufficient_scope:    { title: "Missing permissions",   description: "Your account doesn't have the required permissions. Contact your workspace admin." },
  workspace_not_found:   { title: "Workspace not found",   description: "No Vantage workspace is associated with your account. Contact support." },
  auth_failed:           { title: "Authentication failed",    description: "An error occurred during sign-in. Please try again." },
  no_workspace_access:   { title: "No workspace access",      description: "Your account isn't linked to a Vantage workspace. Contact your admin." },
  hubspot_auth_failed:   { title: "HubSpot connection failed", description: "Couldn't connect your HubSpot account. Check that you're authorising the correct portal." },
  hubspot_access_denied: { title: "HubSpot access denied",    description: "You declined the HubSpot authorisation. Go to Settings to try again." },
  default:               { title: "Something went wrong",  description: "An unexpected error occurred during sign-in. Please try again." },
};

function AuthErrorInner() {
  const searchParams = useSearchParams();
  const rawCode = searchParams.get("code") ?? "default";
  const code = rawCode in ERROR_MESSAGES ? rawCode : "default";
  const error = ERROR_MESSAGES[code];

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="max-w-md w-full">
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-8 text-center">
          {/* Icon */}
          <div className="w-14 h-14 bg-red-50 rounded-2xl flex items-center justify-center mx-auto mb-5">
            <AlertTriangle className="w-7 h-7 text-red-500" />
          </div>

          {/* Error content */}
          <h1 className="text-xl font-semibold text-gray-900 mb-2">{error.title}</h1>
          <p className="text-sm text-gray-500 leading-relaxed mb-2">{error.description}</p>

          {/* Actions */}
          <div className="flex flex-col sm:flex-row gap-3 mt-6">
            <Link
              href="/auth/login"
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-brand-600 text-white text-sm font-medium rounded-xl hover:bg-brand-700 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              Try again
            </Link>
            <Link
              href="/inbox"
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-white border border-gray-200 text-gray-600 text-sm font-medium rounded-xl hover:bg-gray-50 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to inbox
            </Link>
          </div>

          {/* Support */}
          <p className="text-xs text-gray-400 mt-5">
            Still having issues?{" "}
            <a href="mailto:support@invigilo.ai" className="text-brand-600 hover:underline">
              Contact support
            </a>
          </p>
        </div>

        {/* Error code badge */}
        <p className="text-center text-xs text-gray-300 mt-4">Error code: {code}</p>
      </div>
    </div>
  );
}

export default function AuthErrorPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
      </div>
    }>
      <AuthErrorInner />
    </Suspense>
  );
}
