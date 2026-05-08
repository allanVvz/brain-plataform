/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["192.168.0.182", "localhost", "127.0.0.1"],
  async rewrites() {
    const configured = process.env.NEXT_PUBLIC_API_URL;
    const backend = configured || (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "http://127.0.0.1:9");
    return [
      {
        source: "/api-brain/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
