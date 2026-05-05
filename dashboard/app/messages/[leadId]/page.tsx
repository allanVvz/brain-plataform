"use client";

import { use } from "react";
import { MessagesLayout } from "../page";

export default function FocusedMessagesPage({ params }: { params: Promise<{ leadId: string }> }) {
  const { leadId } = use(params);
  const initialLeadId = Number(leadId);

  return (
    <MessagesLayout
      initialLeadId={Number.isFinite(initialLeadId) ? initialLeadId : null}
      focused
    />
  );
}
