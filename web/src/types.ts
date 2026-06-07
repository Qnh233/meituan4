export type AgentEvent = {
  time_local: string;
  event_type: string;
  payload: Record<string, any>;
};

export type RunSummary = {
  id: string;
  runDir: string;
  status: string;
  startedAt: string;
  summary?: Record<string, any> | null;
};

export type SkillItem = {
  id: string;
  name?: string;
  description: string;
  scope?: "generic" | "project" | "system" | string;
  triggers?: string[];
};

export type ToolItem = {
  id: string;
  name: string;
  category: string;
  description: string;
  safety?: string;
};

export type EvaluationContract = Record<string, any>;
