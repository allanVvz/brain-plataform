import { type NextRequest } from "next/server";
import { NextResponse } from "next/server";

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isLogin = pathname === "/login";
  const hasSession = Boolean(request.cookies.get("ai_brain_session")?.value);

  if (!hasSession && !isLogin) {
    const requestedTarget = `${pathname}${request.nextUrl.search}`;
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    url.searchParams.set("next", requestedTarget);
    return NextResponse.redirect(url);
  }

  return NextResponse.next({ request: { headers: request.headers } });
}

export const config = {
  matcher: ["/((?!api-brain|_next/static|_next/image|favicon.ico).*)"],
};
