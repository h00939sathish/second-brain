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
import { DeployAgentModal } from './components/DeployAgentModal';
import { SearchModal } from './components/SearchModal';
import { SettingsModal } from './components/SettingsModal';
import { NotificationsDrawer } from './components/NotificationsDrawer';
import { TaskDetailModal } from './components/TaskDetailModal';
import { CreateTaskModal, DocsSupportModal } from './components/CreateTaskModal';

export const App: React.FC = () => {
  // Navigation & Brand state
  const [currentTab, setCurrentTab] = useState<NavigationTab>('workflow');
  const [brandVariant, setBrandVariant] = useState<'secondBrain' | 'antigravity'>('secondBrain');
  const [daemonSeconds, setDaemonSeconds] = useState(15);

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

  // Live Second Brain Backend API Polling
  useEffect(() => {
    const fetchLiveVaultData = async () => {
      try {
        const [tasksRes, leasesRes, handoffsRes, contextRes, logsRes, graphRes] = await Promise.all([
          fetch('/api/tasks').catch(() => null),
          fetch('/api/leases').catch(() => null),
          fetch('/api/handoffs').catch(() => null),
          fetch('/api/context').catch(() => null),
          fetch('/api/logs').catch(() => null),
          fetch('/api/graph').catch(() => null),
        ]);

        if (tasksRes && tasksRes.ok) {
          const tasksData = await tasksRes.json();
          if (Array.isArray(tasksData) && tasksData.length > 0) {
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
          if (Array.isArray(handoffsData) && handoffsData.length > 0) {
            setHandoffs(handoffsData);
          }
        }

        if (contextRes && contextRes.ok) {
          const contextData = await contextRes.json();
          if (Array.isArray(contextData) && contextData.length > 0) {
            setContextMessages(contextData);
          }
        }

        if (logsRes && logsRes.ok) {
          const logsData = await logsRes.json();
          if (Array.isArray(logsData) && logsData.length > 0) {
            setLogs((prev) => {
              const existingIds = new Set(prev.map((l) => l.id));
              const newLogs = logsData.filter((l: LogEntry) => !existingIds.has(l.id));
              return [...prev, ...newLogs];
            });
          }
        }

        if (graphRes && graphRes.ok) {
          const graphData = await graphRes.json();
          if (Array.isArray(graphData) && graphData.length > 0) {
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
  }, []);

  // Daemon Heartbeat timer
  useEffect(() => {
    const interval = setInterval(() => {
      setDaemonSeconds((s) => s + 1);
    }, 1000);

    return () => clearInterval(interval);
  }, []);

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

    setLogs((prev) => [
      ...prev,
      {
        id: `deploy-${Date.now()}`,
        timestamp: timeStr,
        level: 'OK',
        tag: '[Deployer]',
        sourceColor: '#10b981',
        message: `Agent ${agent.name} (${agent.model}) spawned successfully with ${agent.threadLimit} threads.`,
      },
    ]);
  };

  const handleAddTask = async (newTask: KanbanTask) => {
    setKanbanTasks((prev) => [newTask, ...prev]);

    try {
      await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: newTask.title,
          project: newTask.tags?.[0] || 'Default',
          spec_id: newTask.specLink || '',
          agent: newTask.assignee?.name?.toLowerCase().includes('codex') ? 'codex' : 'opencode',
        }),
      });
    } catch (e) {
      console.warn('Backend offline, using local state');
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
        activeDaemonSeconds={daemonSeconds}
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
            />
          )}

          {currentTab === 'telemetry' && (
            <TokenTelemetryView
              consumptionData={consumptionData}
              inferences={inferences}
            />
          )}

          {currentTab === 'graph' && (
            <KnowledgeGraphView
              nodes={graphNodes}
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
              onDeployClick={() => setIsDeployOpen(true)}
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
        onBrandChange={setBrandVariant}
      />

      <NotificationsDrawer
        isOpen={isNotificationsOpen}
        onClose={() => setIsNotificationsOpen(false)}
      />

      <TaskDetailModal
        task={selectedTask}
        isOpen={!!selectedTask}
        onClose={() => setSelectedTask(null)}
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
        onCreated={handleAddTask}
      />

      <DocsSupportModal
        type={docsSupportType}
        onClose={() => setDocsSupportType(null)}
      />
    </div>
  );
};

export default App;
