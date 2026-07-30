"use client";

import { useParams } from "next/navigation";
import { MessagesLayout } from "@/app/messages/MessagesLayout";
import { usePortal } from "../../PortalContext";

export default function ClientConversationPage() {
  const params = useParams<{ leadId: string }>();
  const { personaSlug, capabilities } = usePortal();
  return (
    <MessagesLayout
      initialLeadId={Number(params.leadId)}
      focused
      portalSlug={personaSlug}
      canEdit={capabilities.edit}
    />
  );
}
