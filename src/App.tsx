import React, { useState, useEffect } from 'react';
import { NavigationTab, KanbanTask, LogEntry, InferenceRecord, QueueTask } from './types';
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
} from './data/initialData';
import { TopAppBar } from './components/TopAppBar';
import { SideNavBar } from './components/SideNavBar';
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
  const [currentTab, setCurrentTab] = useState<NavigationTab>('telemetry');
  const [brandVariant, setBrandVariant] = useState<'secondBrain' | 'antigravity'>('secondBrain');
  const [daemonSeconds, setDaemonSeconds] = useState(15);

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

  // Daemon Heartbeat timer & simulated live telemetry
  useEffect(() => {
    const interval = setInterval(() => {
      setDaemonSeconds((s) => s + 1);

      // Random background daemon ping in logs occasionally
      if (Math.random() > 0.7) {
        const now = new Date();
        const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(
          now.getMinutes()
        ).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}.${String(
          now.getMilliseconds()
        ).padStart(3, '0')}`;

        const events = [
          { tag: '[Codex-A]', msg: 'Cache vector verified (0.34ms).', color: '#22d3ee', lvl: 'OK' as const },
          { tag: '[Claude-S]', msg: 'AST structural tokens synced.', color: '#ec6a06', lvl: 'INFO' as const },
          { tag: '[Sys-Mon]', msg: 'Memory garbage collection reclaimed 84MB.', color: '#4cd7f6', lvl: 'SYS' as const },
        ];
        const ev = events[Math.floor(Math.random() * events.length)];

        setLogs((prev) => [
          ...prev,
          {
            id: `log-auto-${Date.now()}`,
            timestamp: timeStr,
            level: ev.lvl,
            tag: ev.tag,
            sourceColor: ev.color,
            message: ev.msg,
          },
        ]);
      }
    }, 3000);

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

  const handleAddTask = (newTask: KanbanTask) => {
    setKanbanTasks((prev) => [newTask, ...prev]);
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
          {currentTab === 'telemetry' && (
            <TokenTelemetryView
              consumptionData={consumptionData}
              inferences={inferences}
            />
          )}

          {currentTab === 'kanban' && (
            <KanbanBoardView
              tasks={kanbanTasks}
              onUpdateTasks={setKanbanTasks}
              fileLeases={fileLeases}
              handoffs={handoffs}
              contextMessages={contextMessages}
              onOpenTaskModal={(task) => setSelectedTask(task)}
              onAddTask={() => setIsCreateTaskOpen(true)}
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
              daemonLoads={daemonLoads}
              queueTasks={queueTasks}
              onOpenDeployModal={() => setIsDeployOpen(true)}
            />
          )}
        </main>
      </div>

      {/* Mobile Bottom Navigation Bar */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 h-16 bg-[#050505]/95 backdrop-blur-md border-t border-white/10 z-40 flex items-center justify-around px-2">
        {[
          { tab: 'telemetry' as NavigationTab, icon: 'monitoring', label: 'Telemetry' },
          { tab: 'kanban' as NavigationTab, icon: 'view_kanban', label: 'Kanban' },
          { tab: 'graph' as NavigationTab, icon: 'hub', label: 'Graph' },
          { tab: 'logs' as NavigationTab, icon: 'terminal', label: 'Logs' },
          { tab: 'specs' as NavigationTab, icon: 'description', label: 'Specs' },
          { tab: 'network' as NavigationTab, icon: 'device_hub', label: 'Network' },
        ].map((item) => {
          const isActive = currentTab === item.tab;
          return (
            <button
              key={item.tab}
              onClick={() => setCurrentTab(item.tab)}
              className={`flex flex-col items-center justify-center flex-1 py-1 transition-colors ${
                isActive ? 'text-[#C9A86A]' : 'text-white/40 hover:text-white/80'
              }`}
            >
              <span 
                className="material-symbols-outlined text-[20px]"
                style={{ fontVariationSettings: isActive ? "'FILL' 1" : "'FILL' 0" }}
              >
                {item.icon}
              </span>
              <span className="font-code-sm text-[9px] uppercase tracking-wider mt-0.5">{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Modals & Drawers */}
      <DeployAgentModal
        isOpen={isDeployOpen}
        onClose={() => setIsDeployOpen(false)}
        onDeploy={handleDeployAgent}
      />

      <SearchModal
        isOpen={isSearchOpen}
        onClose={() => setIsSearchOpen(false)}
        onNavigate={(tab) => setCurrentTab(tab)}
      />

      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        brandVariant={brandVariant}
        onToggleBrand={() =>
          setBrandVariant((b) => (b === 'secondBrain' ? 'antigravity' : 'secondBrain'))
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
