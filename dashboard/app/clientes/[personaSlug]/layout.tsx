import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import PortalProvider from "./PortalContext";

// Escopado ao portal do cliente — o admin continua em Inter/system-ui via
// app/layout.tsx. IBM Plex Mono cobre timestamps, score, telefone, slugs.
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--portal-font-sans",
  display: "swap",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--portal-font-mono",
  display: "swap",
});

export default async function ClientPersonaLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ personaSlug: string }>;
}) {
  const { personaSlug } = await params;
  return (
    <div className={`${plexSans.variable} ${plexMono.variable}`}>
      <PortalProvider personaSlug={personaSlug}>{children}</PortalProvider>
    </div>
  );
}
