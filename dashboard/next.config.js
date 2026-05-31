/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["192.168.0.182", "localhost", "127.0.0.1"],
  async rewrites() {
    // The /api-brain rewrite runs server-side (Next server / Vercel function),
    // so it should resolve from a PRIVATE var. Precedence:
    //   API_INTERNAL_BASE_URL  (preferred, server-only, never exposed to browser)
    //   NEXT_PUBLIC_API_URL / NEXT_PUBLIC_AI_BRAIN_URL  (legacy, still honored)
    //   dev default -> Docker backend on 8080
    //   prod with nothing set -> 127.0.0.1:9 (fails fast instead of leaking)
    const configured =
      process.env.API_INTERNAL_BASE_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      process.env.NEXT_PUBLIC_AI_BRAIN_URL;
    const isProduction = process.env.NODE_ENV === "production" || process.env.VERCEL === "1";
    const backend = configured || (isProduction ? "http://127.0.0.1:9" : "http://localhost:8080");
    return [
      {
        source: "/api-brain/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
