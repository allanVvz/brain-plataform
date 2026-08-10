/**
 * Handoff State Validation & Synchronization
 *
 * Garante que:
 * 1. Nunca há handoff sem o toggle olho mudar visualmente
 * 2. Estado do backend (handoff_level) sempre sincroniza com UI
 * 3. Tudo é logado para auditoria
 *
 * Princípio: Se handoff_level != "none", o toggle DEVE mostrar isso visualmente
 */

export interface HandoffValidationResult {
  valid: boolean;
  issue?: string;
  suggestedAction?: "sync" | "resume" | "pause" | "acknowledge";
  logs: HandoffLog[];
}

export interface HandoffLog {
  timestamp: string;
  lead_ref: number;
  event: string;
  handoff_level_before?: string;
  handoff_level_after?: string;
  ai_paused?: boolean;
  notes?: string;
}

const VALIDATION_LOGS: HandoffLog[] = [];

function log(lead_ref: number, event: string, details?: Record<string, any>) {
  const entry: HandoffLog = {
    timestamp: new Date().toISOString(),
    lead_ref,
    event,
    ...details,
  };

  VALIDATION_LOGS.push(entry);
  console.log(`[HANDOFF-VALIDATION] ${event}`, {
    lead_ref,
    ...details,
    timestamp: entry.timestamp,
  });

  // Limitar tamanho do buffer
  if (VALIDATION_LOGS.length > 1000) {
    VALIDATION_LOGS.splice(0, VALIDATION_LOGS.length - 1000);
  }
}

/**
 * VALIDAÇÃO CRÍTICA:
 * Se handoff_level != "none", SEMPRE deve estar visível no toggle
 */
export function validateHandoffState(
  lead_ref: number,
  handoff_level: "none" | "partial" | "full" | null | undefined,
  ai_paused: boolean | null | undefined
): HandoffValidationResult {
  const logs: HandoffLog[] = [];

  // Normalizar valores
  const level = handoff_level ?? (ai_paused ? "full" : "none");
  const isInHandoff = level !== "none";

  // Regra 1: Se há handoff, ai_paused DEVE ser true
  if (isInHandoff && !ai_paused) {
    const issue =
      `VIOLATION: Handoff detectado (level=${level}) mas ai_paused=${ai_paused}`;
    log(lead_ref, "HANDOFF_STATE_MISMATCH", {
      handoff_level: level,
      ai_paused,
      notes: issue,
    });

    return {
      valid: false,
      issue,
      suggestedAction:
        level === "full" ? "sync" : level === "partial" ? "acknowledge" : "pause",
      logs: VALIDATION_LOGS,
    };
  }

  // Regra 2: Se ai_paused=true mas handoff_level="none", algo está errado
  if (ai_paused && level === "none") {
    const issue = `INCONSISTENCY: ai_paused=true mas handoff_level="none" (deve ser "full")`;
    log(lead_ref, "AI_PAUSED_WITHOUT_HANDOFF", {
      ai_paused,
      handoff_level: level,
      notes: issue,
    });

    return {
      valid: false,
      issue,
      suggestedAction: "sync",
      logs: VALIDATION_LOGS,
    };
  }

  // Regra 3: Se houve handoff uma vez, deve estar documentado
  if (isInHandoff) {
    log(lead_ref, "HANDOFF_STATE_OK", {
      handoff_level: level,
      ai_paused,
      notes: `Handoff state is consistent (level=${level}, paused=${ai_paused})`,
    });
  }

  return {
    valid: true,
    logs: VALIDATION_LOGS,
  };
}

/**
 * SINCRONIZAÇÃO FORÇADA
 * Quando houver inconsistência, forçar estado correto
 */
export function syncHandoffState(
  lead_ref: number,
  currentState: { handoff_level?: string; ai_paused?: boolean }
): {
  correctedState: { handoff_level: string; ai_paused: boolean };
  requiresApiCall: boolean;
} {
  const current_level = currentState.handoff_level ?? "none";
  const current_paused = currentState.ai_paused ?? false;

  const correction = {
    handoff_level: current_level,
    ai_paused: current_paused,
  };

  let requiresApiCall = false;

  // Se há handoff mas não está pausado, forçar pausa
  if (current_level !== "none" && !current_paused) {
    correction.ai_paused = true;
    requiresApiCall = true;
    log(lead_ref, "HANDOFF_FORCED_PAUSE", {
      handoff_level_before: current_level,
      ai_paused_before: current_paused,
      handoff_level_after: current_level,
      ai_paused_after: true,
      notes: "Forced pause because handoff detected without pause state",
    });
  }

  // Se está pausado mas sem handoff level, definir como "full"
  if (current_paused && current_level === "none") {
    correction.handoff_level = "full";
    requiresApiCall = true;
    log(lead_ref, "HANDOFF_LEVEL_CORRECTED", {
      handoff_level_before: current_level,
      handoff_level_after: "full",
      ai_paused: current_paused,
      notes: "Corrected handoff level because ai_paused=true without level",
    });
  }

  return {
    correctedState: {
      handoff_level: correction.handoff_level,
      ai_paused: correction.ai_paused,
    },
    requiresApiCall,
  };
}

/**
 * WEBHOOK INTERCEPTOR
 * Valida TODA resposta que contém lead data antes de renderizar
 */
export function validateLeadResponse(leadData: any): {
  validated: boolean;
  corrected?: any;
  validationIssues: string[];
} {
  const issues: string[] = [];

  if (!leadData) {
    return { validated: true, validationIssues: [] };
  }

  const lead_ref = leadData.id || leadData.lead_ref;
  const result = validateHandoffState(
    lead_ref,
    leadData.handoff_level,
    leadData.ai_paused
  );

  if (!result.valid) {
    issues.push(result.issue || "Unknown handoff state issue");

    // Auto-corrigir se possível
    const sync = syncHandoffState(lead_ref, {
      handoff_level: leadData.handoff_level,
      ai_paused: leadData.ai_paused,
    });

    return {
      validated: false,
      corrected: {
        ...leadData,
        ...sync.correctedState,
        _handoff_validation_corrected: true,
        _handoff_validation_message: result.issue,
      },
      validationIssues: issues,
    };
  }

  return {
    validated: true,
    validationIssues: issues,
  };
}

/**
 * MONITOR CONTÍNUO
 * Verifica a cada atualização se toggle reflete estado real
 */
export function setupHandoffMonitor(
  onIssueDetected: (issue: HandoffValidationResult) => void
) {
  // Verificar a cada 30 segundos
  const interval = setInterval(() => {
    const logs = getRecentLogs();
    const violations = logs.filter(
      (l) =>
        l.event === "HANDOFF_STATE_MISMATCH" ||
        l.event === "AI_PAUSED_WITHOUT_HANDOFF"
    );

    if (violations.length > 0) {
      onIssueDetected({
        valid: false,
        issue: `Detected ${violations.length} handoff state violations`,
        logs: violations,
      });
    }
  }, 30000);

  return () => clearInterval(interval);
}

/**
 * AUDITORIA
 */
export function getRecentLogs(minutes: number = 60): HandoffLog[] {
  const cutoff = new Date(Date.now() - minutes * 60 * 1000);
  return VALIDATION_LOGS.filter((l) => new Date(l.timestamp) > cutoff);
}

export function exportValidationLogs(): {
  totalLogs: number;
  violations: HandoffLog[];
  lastUpdate: string;
} {
  const violations = VALIDATION_LOGS.filter(
    (l) =>
      l.event === "HANDOFF_STATE_MISMATCH" ||
      l.event === "AI_PAUSED_WITHOUT_HANDOFF" ||
      l.event === "HANDOFF_FORCED_PAUSE"
  );

  return {
    totalLogs: VALIDATION_LOGS.length,
    violations,
    lastUpdate: new Date().toISOString(),
  };
}

/**
 * RESET (apenas para testes)
 */
export function resetLogs() {
  VALIDATION_LOGS.length = 0;
}
