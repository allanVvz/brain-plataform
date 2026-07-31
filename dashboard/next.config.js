/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  allowedDevOrigins: ["192.168.0.182", "localhost", "127.0.0.1"],
  async redirects() {
    return [
      { source: "/wa-validator", destination: "/settings?tab=chatbot&view=validations", permanent: false },
      { source: "/tools", destination: "/settings?tab=tools", permanent: false },
      { source: "/logs", destination: "/settings?tab=logs", permanent: false },
      { source: "/access", destination: "/settings?tab=access", permanent: false },
      { source: "/knowledge/import-vault", destination: "/knowledge/sync", permanent: false },
    ];
  },
  async rewrites() {
    const configured =
      process.env.API_INTERNAL_BASE_URL ||
      process.env.API_INTERNAL_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      process.env.NEXT_PUBLIC_AI_BRAIN_URL;
    const isProduction = process.env.NODE_ENV === "production" || process.env.VERCEL === "1";
    // Production runs on Vercel while the API remains on the VPS. Keep the
    // explicit env var as the source of truth, but never fall back to a
    // loopback sink in a deployed dashboard.
    const backend = configured || (isProduction ? "https://api.vzforeal.com" : "http://127.0.0.1:8080");
    return [
      {
        source: "/api-brain/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
