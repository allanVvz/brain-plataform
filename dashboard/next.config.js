/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["192.168.0.182", "localhost", "127.0.0.1"],
  async rewrites() {
    const configured = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_AI_BRAIN_URL;
    const isProduction = process.env.NODE_ENV === "production" || process.env.VERCEL === "1";
    const backend = configured || (isProduction ? "http://127.0.0.1:9" : "http://127.0.0.1:8000");
    return [
      {
        source: "/api-brain/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
