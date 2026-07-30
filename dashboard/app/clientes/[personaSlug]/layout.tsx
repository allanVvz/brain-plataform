import PortalProvider from "./PortalContext";

export default async function ClientPersonaLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ personaSlug: string }>;
}) {
  const { personaSlug } = await params;
  return <PortalProvider personaSlug={personaSlug}>{children}</PortalProvider>;
}
