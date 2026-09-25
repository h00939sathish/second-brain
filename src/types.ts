export type NavigationTab = 
  | 'workflow'
  | 'telemetry' 
  | 'kanban' 
  | 'graph' 
  | 'logs' 
  | 'specs' 
  | 'network'
  | 'deliberation';

export type AgentRoleType = 'planning' | 'building' | 'reviewing' | 'qa' | 'deployment';

export interface WorkflowAgent {
  id: string;
  name: string;
  code: string;
  model: string;
  avatarIcon: string;
  role: AgentRoleType;
  color: string;
  temperature: number;
  systemPrompt: string;
  status: 'idle' | 'executing' | 'completed' | 'paused';
  metrics?: {
    avgLatency: string;
    tokenBurn: string;
    successRate: string;
  };
}

export interface WorkflowStageNode {
  id: string;
  title: string;
  stageType: AgentRoleType;
  description: string;
  assignedAgentId: string;
  agentName: string;
  agentModel: string;
  agentColor: string;
  status: 'idle' | 'active' | 'passed' | 'failed' | 'skipped';
  autoHandoff: boolean;
  requiredApproval: boolean;
  maxRetries: number;
  outputArtifactName?: string;
  systemInstruction?: string;
}

export interface WorkflowPipeline {
  id: string;
  name: string;
  description: string;
  activeStageId: string | null;
  isRunning: boolean;
  currentStepIndex: number;
  stages: WorkflowStageNode[];
}

export type TimeRange = '1H' | '24H' | '7D';

export interface InferenceRecord {
  id: string;
  modelRoute: string;
  modelColor: 'primary' | 'secondary' | 'tertiary' | 'outline' | 'emerald';
  tokensIn: number;
  tokensOut: number;
  latency: string;
  latencyMs: number;
  resourceImpact: string;
  cost: number;
  timestamp: string;
  status: 'ok' | 'warning' | 'error';
}

export interface ModelConsumptionPoint {
  timeLabel: string;
  gpt5: number;
  gemini: number;
  claude: number;
}

export type KanbanStatus = 'backlog' | 'planning' | 'running' | 'review' | 'done';

export interface KanbanTask {
  id: string;
  title: string;
  status: KanbanStatus;
  assignee: {
    code: string;
    name: string;
    color: string;
  };
  uptime?: string;
  hasWarning?: boolean;
  warningMessage?: string;
  tags: string[];
  specLink?: string;
  progressPercent?: number;
  description?: string;
  tokenCost?: number;
  createdAt: string;
}

export interface FileLease {
  id: string;
  file: string;
  holder: string;
  holderCode: string;
  holderColor: string;
  duration: string;
}

export interface AgentHandoff {
  id: string;
  from: string;
  fromCode: string;
  to: string;
  toCode: string;
  timeAgo: string;
}

export interface ContextStreamMessage {
  id: string;
  source: string;
  color: string;
  text: string;
  timestamp: string;
}

export interface LogEntry {
  id: string;
  timestamp: string;
  level: 'INFO' | 'OK' | 'WARN' | 'ERR' | 'SYS';
  tag: string;
  sourceColor: string;
  message: string;
  jsonPayload?: Record<string, unknown>;
  errorCode?: string;
}

export interface GraphNode {
  id: string;
  label: string;
  type: 'spec' | 'task' | 'claim';
  x: number;
  y: number;
  status: 'complete' | 'in_progress' | 'pending';
  connections: string[];
  meta?: Record<string, string>;
}

export interface QueueTask {
  id: string;
  priority: 'CRITICAL' | 'HIGH' | 'NORMAL' | 'LOW';
  targetDaemon: string;
  daemonColor: string;
  status: 'Processing' | 'Queued';
  estWait: string;
}

export interface DaemonLoadInfo {
  name: string;
  color: string;
  loadPercent: number;
  activeThreads: number;
  memoryUsage: string;
}

export interface SquadData {
  name: string;
  workspace: string;
  roles: Record<string, string>;
  configured: boolean;
  active_sessions?: Record<string, any>;
  routing_matrix?: Record<string, string>;
}

export interface DeliberationMessage {
  message_id: string;
  task_id: string;
  round: number;
  timestamp: string;
  sender: string;
  recipient: string;
  type: string;
  severity: string;
  body: string;
  references: string[];
}

export interface DeliberationProposal {
  proposal_id: string;
  agent: string;
  plan: string[];
  files_expected: string[];
  risks: string[];
  questions: string[];
  status: string;
}

export interface DeliberationRoomData {
  context: {
    task_id: string;
    title: string;
    workspace: string;
    project: string;
    risk: string;
    mode: string;
    domains: string[];
    status: string;
    current_round: number;
    max_rounds: number;
    required_participants: string[];
    required_acknowledgements: number;
    created_at: string;
    updated_at: string;
  };
  proposals: DeliberationProposal[];
  presence: Record<string, { agent: string; state: string; focus: string; files: string[]; updated_at: string }>;
  messages: DeliberationMessage[];
  decision?: {
    decision_id: string;
    task_id: string;
    status: string;
    authorized_files: string[];
    agreed_plan: string[];
    participants: string[];
    timestamp: string;
  };
}
