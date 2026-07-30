import { redirect } from "next/navigation";

export default async function LegacyAccountPage({
  params,
}: {
  params: Promise<{ personaSlug: string }>;
}) {
  const { personaSlug } = await params;
  redirect(`/clientes/${personaSlug}/configuracoes`);
}
