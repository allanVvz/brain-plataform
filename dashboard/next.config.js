/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const backend = process.env.NEXT_PUBLIC_AI_BRAIN_URL || "http://localhost:8000";
    return [
      {
        source: "/api-brain/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
