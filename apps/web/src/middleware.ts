import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/auth/login", "/auth/callback", "/auth/error", "/onboarding"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public paths
  if (PUBLIC_PATHS.some(p => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // Dev bypass — skips WorkOS auth entirely for local development.
  // Active when NODE_ENV=development (i.e. `next dev`). Never true in production builds.
  if (process.env.NODE_ENV === "development") {
    return NextResponse.next();
  }

  // Check for session cookie
  const session = request.cookies.get("vantage_session");
  if (!session) {
    const loginUrl = new URL("/auth/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|api/auth).*)",
  ],
};
