"use client";

import { useMemo } from "react";
import { api } from "@/lib/api";
import { usePortal } from "../PortalContext";
import { CampaignsAndTemplates, type CampaignsApi } from "@/components/disparos/CampaignsAndTemplates";

export default function ClientDisparosPage() {
  const { personaSlug, capabilities } = usePortal();

  const boundApi: CampaignsApi = useMemo(() => ({
    leadImports: () => api.portalLeadImports(personaSlug),
    audiences: () => api.portalAudiences(personaSlug),
    campaigns: () => api.portalCampaigns(personaSlug),
    campaignProviderHealth: () => api.portalCampaignProviderHealth(personaSlug),
    campaignPreview: (body) => api.portalCampaignPreview(personaSlug, body),
    createCampaign: (body) => api.portalCreateCampaign(personaSlug, body),
    pauseCampaign: (id, body) => api.portalPauseCampaign(personaSlug, id, body),
    cancelCampaign: (id, body) => api.portalCancelCampaign(personaSlug, id, body),
    sendCampaign: (id, body) => api.portalSendCampaign(personaSlug, id, body),
    campaign: (id) => api.campaign(id),
    messageTemplates: (provider) => api.portalMessageTemplates(personaSlug, provider),
    createMessageTemplate: (body) => api.portalCreateMessageTemplate(personaSlug, body),
    editMessageTemplate: (id, body) => api.portalEditMessageTemplate(personaSlug, id, body),
    submitMessageTemplate: (id, body) => api.portalSubmitMessageTemplate(personaSlug, id, body),
    syncMessageTemplateStatus: (id) => api.portalSyncMessageTemplateStatus(personaSlug, id),
  }), [personaSlug]);

  return (
    <CampaignsAndTemplates
      variant="portal"
      personaKey={personaSlug}
      capabilities={capabilities}
      api={boundApi}
    />
  );
}
