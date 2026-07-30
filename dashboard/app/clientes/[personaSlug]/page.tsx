import { redirect } from "next/navigation";

export default async function ClientPersonaPage({ params }: { params: Promise<{ personaSlug: string }> }) {
  const { personaSlug } = await params;
  redirect(`/clientes/${personaSlug}/mensagens`);
}
