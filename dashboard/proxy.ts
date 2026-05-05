import { type NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { createClient } from "@/utils/supabase/middleware";

export async function proxy(request: NextRequest) {
  const { supabaseResponse } = createClient(request);
  const { pathname } = request.nextUrl;
  const isLogin = pathname === "/login";
  const hasSession = Boolean(request.cookies.get("ai_brain_session")?.value);

  if (!hasSession && !isLogin) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return supabaseResponse;
}

export const config = {
  matcher: ["/((?!api-brain|_next/static|_next/image|favicon.ico).*)"],
};
