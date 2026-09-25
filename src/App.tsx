import React, { useState, useEffect } from 'react';
import {
  NavigationTab,
  KanbanTask,
  LogEntry,
  InferenceRecord,
  QueueTask,
  WorkflowPipeline,
} from './types';
import {
  INITIAL_CONSUMPTION_DATA,
  INITIAL_INFERENCES,
  INITIAL_KANBAN_TASKS,
  INITIAL_FILE_LEASES,
  INITIAL_HANDOFFS,
  INITIAL_CONTEXT_MESSAGES,
  INITIAL_LOGS,
  INITIAL_GRAPH_NODES,
  INITIAL_QUEUE_TASKS,
  INITIAL_DAEMON_LOADS,
  INITIAL_PIPELINE,
} from './data/initialData';
import { TopAppBar } from './components/TopAppBar';
import { SideNavBar } from './components/SideNavBar';
import { WorkflowOrchestratorView } from './components/WorkflowOrchestratorView';
import { TokenTelemetryView } from './components/TokenTelemetryView';
import { KanbanBoardView } from './components/KanbanBoardView';
import { LiveTerminalLogsView } from './components/LiveTerminalLogsView';
import { KnowledgeGraphView } from './components/KnowledgeGraphView';
import { SpecsEditorView } from './components/SpecsEditorView';
import { NetworkLoadBalancerView } from './components/NetworkLoadBalancerView';
import { ChatroomDeliberationView } from './components/ChatroomDeliberationView';
import { DeployAgentModal } from './components/DeployAgentModal';
import { SearchModal } from './components/SearchModal';
import { SettingsModal } from './components/SettingsModal';
import { NotificationsDrawer } from './components/NotificationsDrawer';
import { TaskDetailModal } from './components/TaskDetailModal';
import { CreateTaskModal, DocsSupportModal } from './components/CreateTaskModal';

export const App: React.FC = () => {
  // Navigation & Brand state
  const [currentTab, setCurrentTab] = useState<NavigationTab>('kanban');
  const [brandVariant, setBrandVariant] = useState<'secondBrain' | 'antigravity'>('secondBrain');

  // Scope: '' means "everything" (the API's ?all=1 view). Reported by the backend,
  // never guessed here.
  const [workspace, setWorkspace] = useState<string>('');
  const [workspaces, setWorkspaces] = useState<string[]>([]);
  const [daemon, setDaemon] = useState<{ active: boolean; detail: string }>({
    active: false,
    detail: 'unknown',
  });
  const [vaultPath, setVaultPath] = useState<string>('');

  // Workflow Pipeline State
  const [pipeline, setPipeline] = useState<WorkflowPipeline>(INITIAL_PIPELINE);

  // Core domain states
  const [inferences, setInferences] = useState<InferenceRecord[]>(INITIAL_INFERENCES);
  const [consumptionData, setConsumptionData] = useState(INITIAL_CONSUMPTION_DATA);
  const [kanbanTasks, setKanbanTasks] = useState<KanbanTask[]>(INITIAL_KANBAN_TASKS);
  const [fileLeases, setFileLeases] = useState(INITIAL_FILE_LEASES);
  const [handoffs, setHandoffs] = useState(INITIAL_HANDOFFS);
  const [contextMessages, setContextMessages] = useState(INITIAL_CONTEXT_MESSAGES);
  const [logs, setLogs] = useState<LogEntry[]>(INITIAL_LOGS);
  const [graphNodes, setGraphNodes] = useState(INITIAL_GRAPH_NODES);
  const [queueTasks, setQueueTasks] = useState<QueueTask[]>(INITIAL_QUEUE_TASKS);
  const [daemonLoads, setDaemonLoads] = useState(INITIAL_DAEMON_LOADS);

  // Modal / Drawer state
  const [isDeployOpen, setIsDeployOpen] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [isCreateTaskOpen, setIsCreateTaskOpen] = useState(false);
  const [docsSupportType, setDocsSupportType] = useState<'docs' | 'support' | null>(null);
  const [selectedTask, setSelectedTask] = useState<KanbanTask | null>(null);

  // Live Second Brain Backend API Polling. Every request is scoped to the selected
  // workspace so the board, leases and logs cannot disagree with each other.
  useEffect(() => {
    const scope = workspace
      ? `?workspace=${encodeURIComponent(workspace)}`
      : '?all=1';
    const fetchLiveVaultData = async () => {
      try {
        const [statusRes, tasksRes, leasesRes, handoffsRes, contextRes, logsRes, graphRes] =
          await Promise.all([
            fetch('/api/status').catch(() => null),
            fetch(`/api/tasks${scope}`).catch(() => null),
            fetch(`/api/leases${scope}`).catch(() => null),
            fetch(`/api/handoffs${scope}`).catch(() => null),
            fetch(`/api/context${scope}`).catch(() => null),
            fetch(`/api/logs${scope}`).catch(() => null),
            fetch(`/api/graph${scope}`).catch(() => null),
          ]);

        if (statusRes && statusRes.ok) {
          const statusData = await statusRes.json();
          setDaemon(statusData.daemon ?? { active: false, detail: 'unreachable' });
          setWorkspaces(statusData.workspaces ?? []);
          setVaultPath(statusData.vault ?? '');
        }

        if (tasksRes && tasksRes.ok) {
          const tasksData = await tasksRes.json();
          if (Array.isArray(tasksData)) {
            setKanbanTasks(tasksData);
          }
        }

        if (leasesRes && leasesRes.ok) {
          const leasesData = await leasesRes.json();
          if (Array.isArray(leasesData)) {
            setFileLeases(leasesData);
          }
        }

        if (handoffsRes && handoffsRes.ok) {
          const handoffsData = await handoffsRes.json();
          if (Array.isArray(handoffsData)) {
            setHandoffs(handoffsData);
          }
        }

        if (contextRes && contextRes.ok) {
          const contextData = await contextRes.json();
          if (Array.isArray(contextData)) {
            setContextMessages(contextData);
          }
        }

        if (logsRes && logsRes.ok) {
          const logsData = await logsRes.json();
          if (Array.isArray(logsData)) {
            setLogs((prev) => {
              const existingIds = new Set(prev.map((l) => l.id));
              const newLogs = logsData.filter((l: LogEntry) => !existingIds.has(l.id));
              const merged = [...prev, ...newLogs];
              return merged.length > 500 ? merged.slice(-500) : merged;
            });
          }
        }

        if (graphRes && graphRes.ok) {
          const graphData = await graphRes.json();
          if (Array.isArray(graphData)) {
            setGraphNodes(graphData);
          }
        }
      } catch (err) {
        // Fall back gracefully to initial data
      }
    };

    fetchLiveVaultData();
    const interval = setInterval(fetchLiveVaultData, 3000);
    return () => clearInterval(interval);
  }, [workspace]);

  // Keyboard shortcut for Cmd+K Search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setIsSearchOpen((open) => !open);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleDeployAgent = (agent: { name: string; model: string; threadLimit: number; memoryLimit: string }) => {
    const newDaemonLoad = {
      name: agent.name,
      color: '#d0bcff',
      loadPercent: Math.floor(Math.random() * 40) + 20,
      activeThreads: agent.threadLimit,
      memoryUsage: agent.memoryLimit,
    };
    setDaemonLoads((prev) => [...prev, newDaemonLoad]);

    const now = new Date();
    const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(
      now.getMinutes()
    ).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}.000`;

    setLogs((prev) => {
      const nextLogs: LogEntry[] = [
        ...prev,
        {
          id: `deploy-${Date.now()}`,
          timestamp: timeStr,
          level: 'OK',
          tag: '[Deployer]',
          sourceColor: '#10b981',
          message: `Agent ${agent.name} (${agent.model}) spawned successfully with ${agent.threadLimit} threads.`,
        },
      ];
      return nextLogs.length > 500 ? nextLogs.slice(-500) : nextLogs;
    });
  };

  const handleAddTask = async (newTask: KanbanTask) => {
    setKanbanTasks((prev) => [newTask, ...prev]);

    const assigneeStr = (newTask.assignee?.name || '').toLowerCase();
    let agentId = 'opencode';
    if (assigneeStr.includes('codex')) agentId = 'codex';
    else if (assigneeStr.includes('claude')) agentId = 'claude';
    else if (assigneeStr.includes('antigravity') || assigneeStr.includes('agy')) agentId = 'antigravity';
    else if (assigneeStr.includes('hermes')) agentId = 'hermes';

    try {
      await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: newTask.title,
          project: newTask.tags?.[0] || 'Default',
          spec_id: newTask.specLink || '',
          agent: agentId,
        }),
      });
    } catch (e) {
      console.warn('Backend offline, using local state');
    }
  };

  const handleTerminateTask = async (taskId: string) => {
    setKanbanTasks((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, status: 'done', warningMessage: 'Terminated by Operator' } : t))
    );
    if (selectedTask?.id === taskId) {
      setSelectedTask((prev) => (prev ? { ...prev, status: 'done', warningMessage: 'Terminated by Operator' } : null));
    }
    try {
      await fetch(`/api/tasks/${taskId}/terminate`, { method: 'POST' });
    } catch {
      console.warn('Terminate API offline, updated locally');
    }
  };

  const handleDeleteTask = async (taskId: string) => {
    setKanbanTasks((prev) => prev.filter((t) => t.id !== taskId));
    if (selectedTask?.id === taskId) {
      setSelectedTask(null);
    }
    try {
      await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
    } catch {
      console.warn('Delete API offline, updated locally');
    }
  };

  const handleDispatchTask = async (taskId: string) => {
    setKanbanTasks((prev) =>
      prev.map((t) => (t.id === taskId ? { ...t, status: 'running' } : t))
    );
    if (selectedTask?.id === taskId) {
      setSelectedTask((prev) => (prev ? { ...prev, status: 'running' } : null));
    }
    try {
      await fetch('/api/dispatch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId }),
      });
    } catch {
      console.warn('Dispatch API offline, updated locally');
    }
  };

  const handleUpdateTasks = (newTasks: KanbanTask[]) => {
    setKanbanTasks(newTasks);
  };

  const handleLogEvent = (newLog: LogEntry) => {
    setLogs((prev) => [...prev, newLog]);
  };

  return (
    <div className="min-h-screen bg-[#050505] text-[#F5F5F5] flex flex-col font-sans selection:bg-[#C9A86A]/30 selection:text-[#F5F5F5]">
      {/* Top App Bar */}
      <TopAppBar
        currentTab={currentTab}
        onSelectTab={setCurrentTab}
        onOpenSearch={() => setIsSearchOpen(true)}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenNotifications={() => setIsNotificationsOpen(true)}
        daemon={daemon}
        workspaces={workspaces}
        workspace={workspace}
        onSelectWorkspace={setWorkspace}
        brandVariant={brandVariant}
      />

      <div className="flex flex-1 pt-14">
        {/* Side Navigation Bar (Desktop) */}
        <SideNavBar
          currentTab={currentTab}
          onSelectTab={setCurrentTab}
          onOpenDeployModal={() => setIsDeployOpen(true)}
          onOpenDocs={() => setDocsSupportType('docs')}
          onOpenSupport={() => setDocsSupportType('support')}
          brandVariant={brandVariant}
          activeAgentsCount={daemonLoads.length}
        />

        {/* Main Content Area */}
        <main className="flex-1 md:ml-64 p-4 md:p-6 lg:p-8 min-w-0 max-w-7xl overflow-x-hidden">
          {currentTab === 'workflow' && (
            <WorkflowOrchestratorView
              pipeline={pipeline}
              onUpdatePipeline={setPipeline}
              onLogEvent={handleLogEvent}
            />
          )}

          {currentTab === 'kanban' && (
            <KanbanBoardView
              tasks={kanbanTasks}
              onUpdateTasks={handleUpdateTasks}
              fileLeases={fileLeases}
              handoffs={handoffs}
              contextMessages={contextMessages}
              onOpenTaskModal={(task) => setSelectedTask(task)}
              onAddTask={() => setIsCreateTaskOpen(true)}
              onTerminateTask={handleTerminateTask}
              onDeleteTask={handleDeleteTask}
              onDispatchTask={handleDispatchTask}
            />
          )}

          {currentTab === 'deliberation' && (
            <ChatroomDeliberationView
              workspace={workspace}
              workspaces={workspaces}
              tasks={kanbanTasks}
            />
          )}

          {currentTab === 'telemetry' && (
            <TokenTelemetryView
              consumptionData={consumptionData}
              inferences={inferences}
              vaultPath={vaultPath}
            />
          )}

          {currentTab === 'graph' && (
            <KnowledgeGraphView
              nodes={graphNodes}
              onUpdateNodes={setGraphNodes}
            />
          )}

          {currentTab === 'logs' && (
            <LiveTerminalLogsView
              logs={logs}
              onAddLog={(newLog) => setLogs((prev) => [...prev, newLog])}
              onClearLogs={() => setLogs([])}
            />
          )}

          {currentTab === 'specs' && (
            <SpecsEditorView />
          )}

          {currentTab === 'network' && (
            <NetworkLoadBalancerView
              queueTasks={queueTasks}
              daemonLoads={daemonLoads}
              onOpenDeployModal={() => setIsDeployOpen(true)}
            />
          )}
        </main>
      </div>

      {/* Modals & Drawers */}
      <DeployAgentModal
        isOpen={isDeployOpen}
        onClose={() => setIsDeployOpen(false)}
        onDeploy={handleDeployAgent}
      />

      <SearchModal
        isOpen={isSearchOpen}
        onClose={() => setIsSearchOpen(false)}
        onNavigate={(tab) => {
          setCurrentTab(tab);
          setIsSearchOpen(false);
        }}
        tasks={kanbanTasks}
        onSelectTask={(task) => {
          setSelectedTask(task);
          setIsSearchOpen(false);
        }}
      />

      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        brandVariant={brandVariant}
        onToggleBrand={() =>
          setBrandVariant(brandVariant === 'secondBrain' ? 'antigravity' : 'secondBrain')
        }
      />

      <NotificationsDrawer
        isOpen={isNotificationsOpen}
        onClose={() => setIsNotificationsOpen(false)}
      />

      <TaskDetailModal
        task={selectedTask}
        isOpen={!!selectedTask}
        onClose={() => setSelectedTask(null)}
        onTerminate={handleTerminateTask}
        onDelete={handleDeleteTask}
        onStatusChange={(newStatus) => {
          if (selectedTask) {
            const updated = { ...selectedTask, status: newStatus };
            setKanbanTasks((prev) => prev.map((t) => (t.id === selectedTask.id ? updated : t)));
            setSelectedTask(updated);
            fetch(`/api/tasks/${selectedTask.id}/move`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ status: newStatus }),
            }).catch(() => null);
          }
        }}
      />

      <CreateTaskModal
        isOpen={isCreateTaskOpen}
        onClose={() => setIsCreateTaskOpen(false)}
        onAddTask={handleAddTask}
      />

      <DocsSupportModal
        type={docsSupportType}
        onClose={() => setDocsSupportType(null)}
      />
    </div>
  );
};

export default App;
