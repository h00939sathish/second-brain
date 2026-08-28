export type NavigationTab = 
  | 'telemetry' 
  | 'kanban' 
  | 'graph' 
  | 'logs' 
  | 'specs' 
  | 'network';

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
