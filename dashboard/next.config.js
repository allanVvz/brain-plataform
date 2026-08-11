/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  allowedDevOrigins: [
    ...(process.env.NEXT_ALLOWED_DEV_ORIGINS || "").split(",").map((value) => value.trim()).filter(Boolean),
    "localhost",
    "127.0.0.1",
  ],
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
    if (isProduction && !process.env.API_INTERNAL_BASE_URL) {
      throw new Error("API_INTERNAL_BASE_URL is required for production builds");
    }
    const backend = configured || "http://127.0.0.1:8080";
    return [
      {
        source: "/api-brain/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
