export type PlanDiagnosticNodeStatus = "valid" | "warning" | "error" | "cycle" | "orphan";

export interface PlanDiagnosticNode {
  entry_index: number;
  slug: string;
  title: string;
  type: string;
  parent_slug: string | null;
  parent_type: string | null;
  expected_parent_types: string[];
  status: PlanDiagnosticNodeStatus;
  issues: string[];
  suggested_action: string | null;
  chain_path: string[];
}

export interface PlanDiagnosticRootCause {
  kind: string;
  title: string;
  description: string;
  affected_entry_indexes: number[];
  raw_messages: string[];
  suggested_repair: string;
}

export interface SofiaQuestionOption {
  label: string;
  action: string;
  payload?: Record<string, unknown>;
}

export interface SofiaQuestion {
  kind: string;
  technical_error: string;
  affected_entry_index?: number;
  affected_title?: string;
  affected_type?: string;
  human_summary: string;
  probable_cause: string;
  question: string;
  options: SofiaQuestionOption[];
  severity: "blocking" | "warning" | "info";
}

export interface PlanDiagnostic {
  blocked: boolean;
  summary: {
    entry_count: number;
    blocked_count: number;
    cycle_count: number;
    orphan_count: number;
    error_count: number;
    warning_count: number;
    valid_count: number;
    root_cause_count: number;
  };
  nodes: PlanDiagnosticNode[];
  root_causes: PlanDiagnosticRootCause[];
  sofia_questions: SofiaQuestion[];
  questions_markdown: string;
  repair_suggestion: string;
}
