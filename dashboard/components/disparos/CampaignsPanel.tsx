"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { CampaignsAndTemplates, type CampaignsApi } from "./CampaignsAndTemplates";

const FULL_CAPABILITIES = { view: true, edit: true, manage: true };

export function CampaignsPanel() {
  const [personaId, setPersonaId] = useState("");

  useEffect(() => {
    setPersonaId(window.localStorage.getItem("ai-brain-persona-id") || "");
    const onPersona = () => setPersonaId(window.localStorage.getItem("ai-brain-persona-id") || "");
    window.addEventListener("ai-brain-persona-change", onPersona);
    return () => window.removeEventListener("ai-brain-persona-change", onPersona);
  }, []);

  const boundApi: CampaignsApi = useMemo(() => ({
    leadImports: () => api.leadImports(personaId),
    audiences: () => api.audiences(personaId),
    campaigns: () => api.campaigns(personaId),
    campaignProviderHealth: () => api.campaignProviderHealth(personaId),
    campaignPreview: (body) => api.campaignPreview({ ...body, persona_id: personaId }),
    createCampaign: (body) => api.createCampaign({ ...body, persona_id: personaId }),
    pauseCampaign: (id, body) => api.pauseCampaign(id, body),
    cancelCampaign: (id, body) => api.cancelCampaign(id, body),
    sendCampaign: (id, body) => api.sendCampaign(id, body),
    campaign: (id) => api.campaign(id),
    messageTemplates: (provider) => api.messageTemplates(personaId, provider),
    createMessageTemplate: (body) => api.createMessageTemplate({ ...body, persona_id: personaId }),
    editMessageTemplate: (id, body) => api.editMessageTemplate(id, body),
    submitMessageTemplate: (id, body) => api.submitMessageTemplate(id, body),
    syncMessageTemplateStatus: (id) => api.syncMessageTemplateStatus(id),
  }), [personaId]);

  return (
    <CampaignsAndTemplates
      variant="internal"
      personaKey={personaId}
      capabilities={FULL_CAPABILITIES}
      api={boundApi}
    />
  );
}
