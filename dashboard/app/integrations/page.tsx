import McpIntegrationsWorkspace from "@/components/integrations/mcp-integrations-workspace";

export default function IntegrationsPage() {
  return (
    <McpIntegrationsWorkspace
      readOnly
      title="Integracoes"
      subtitle="Visao resumida do mesmo contrato do MCP, sem edicao de credenciais nesta tela."
    />
  );
}
