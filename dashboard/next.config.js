/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["192.168.0.182", "localhost", "127.0.0.1"],
  async rewrites() {
    const backend = process.env.API_INTERNAL_BASE_URL;
    if (!backend) {
      throw new Error("API_INTERNAL_BASE_URL is required for /api-brain rewrites.");
    }
    return [
      {
        source: "/api-brain/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
