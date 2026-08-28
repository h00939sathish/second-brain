import React, { useState } from 'react';
import {
  KanbanTask,
  FileLease,
  AgentHandoff,
  ContextStreamMessage,
  KanbanStatus,
} from '../types';
import { useTrackComponentRender } from '../hooks/usePerformanceProfiler';

interface KanbanBoardViewProps {
  tasks: KanbanTask[];
  onUpdateTasks: (tasks: KanbanTask[]) => void;
  fileLeases: FileLease[];
  handoffs: AgentHandoff[];
  contextMessages: ContextStreamMessage[];
  onOpenTaskModal: (task: KanbanTask) => void;
  onAddTask: () => void;
  onTerminateTask?: (taskId: string) => void;
  onDeleteTask?: (taskId: string) => void;
  onDispatchTask?: (taskId: string) => void;
}

export const KanbanBoardView: React.FC<KanbanBoardViewProps> = ({
  tasks,
  onUpdateTasks,
  fileLeases,
  handoffs,
  contextMessages,
  onOpenTaskModal,
  onAddTask,
  onTerminateTask,
  onDeleteTask,
  onDispatchTask,
}) => {
  useTrackComponentRender('KanbanBoardView');
  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null);

  const columns: { id: KanbanStatus; label: string }[] = [
    { id: 'backlog', label: 'Backlog' },
    { id: 'planning', label: 'Planning' },
    { id: 'running', label: 'Running' },
    { id: 'review', label: 'Review' },
    { id: 'done', label: 'Done' },
  ];

  const handleDragStart = (id: string) => {
    setDraggedTaskId(id);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (status: KanbanStatus) => {
    if (!draggedTaskId) return;
    const updated = tasks.map((t) => (t.id === draggedTaskId ? { ...t, status } : t));
    onUpdateTasks(updated);
    fetch(`/api/tasks/${draggedTaskId}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    }).catch(() => null);
    setDraggedTaskId(null);
  };

  const moveTask = (taskId: string, direction: 'left' | 'right', e: React.MouseEvent) => {
    e.stopPropagation();
    const task = tasks.find((t) => t.id === taskId);
    if (!task) return;
    const colOrder: KanbanStatus[] = ['backlog', 'planning', 'running', 'review', 'done'];
    const currentIndex = colOrder.indexOf(task.status);
    const newIndex = direction === 'left' ? currentIndex - 1 : currentIndex + 1;
    if (newIndex >= 0 && newIndex < colOrder.length) {
      const newStatus = colOrder[newIndex];
      const updated = tasks.map((t) =>
        t.id === taskId ? { ...t, status: newStatus } : t
      );
      onUpdateTasks(updated);
      fetch(`/api/tasks/${taskId}/move`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      }).catch(() => null);
    }
  };

  const runningCount = tasks.filter((t) => t.status === 'running').length;

  return (
    <div className="space-y-6 pb-12">
      {/* Top Status / Telemetry Bar */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 p-4 bg-[#111111] border border-white/10 rounded-3xl">
        {/* KPI 1 */}
        <div className="flex flex-col">
          <span className="text-[10px] text-white/40 uppercase tracking-[0.2em]">
            Active Agents
          </span>
          <div className="flex items-center gap-1.5 mt-1">
            <span className="text-lg font-light text-white">1/4</span>
            <span className="font-code-sm text-[10px] text-[#C9A86A]">(Codex active)</span>
          </div>
        </div>

        {/* KPI 2 */}
        <div className="flex flex-col">
          <span className="text-[10px] text-white/40 uppercase tracking-[0.2em]">
            Tasks
          </span>
          <div className="flex items-center gap-1.5 mt-1">
            <span className="text-lg font-light text-white">{tasks.length}</span>
            <span className="font-code-sm text-[10px] text-[#4ADE80]">({runningCount} Active)</span>
          </div>
        </div>

        {/* KPI 3 */}
        <div className="flex flex-col">
          <span className="text-[10px] text-white/40 uppercase tracking-[0.2em]">
            Token Burn
          </span>
          <div className="flex items-center gap-1.5 mt-1">
            <span className="text-lg font-light text-white">42.5k</span>
            <span className="font-code-sm text-[10px] text-white/40">($0.18)</span>
          </div>
        </div>

        {/* KPI 4 */}
        <div className="flex flex-col">
          <span className="text-[10px] text-white/40 uppercase tracking-[0.2em]">
            Vault Health
          </span>
          <div className="flex items-center gap-2 mt-1.5">
            <div className="w-16 bg-white/10 h-1.5 rounded-full overflow-hidden">
              <div className="bg-[#4ADE80] h-full rounded-full" style={{ width: '94%' }}></div>
            </div>
            <span className="font-code-sm text-[10px] text-[#4ADE80]">2066/2200B</span>
          </div>
        </div>

        {/* KPI 5 */}
        <div className="flex flex-col col-span-2 md:col-span-1">
          <span className="text-[10px] text-white/40 uppercase tracking-[0.2em]">
            System Resources
          </span>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-code-sm text-[10px] text-white/60">CPU: <strong className="text-[#C9A86A]">24%</strong></span>
            <span className="font-code-sm text-[10px] text-white/60">RAM: <strong className="text-white">14.2G/32G</strong></span>
          </div>
        </div>
      </div>

      {/* Main Kanban & Right Rail Container */}
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
        {/* 5 Kanban Columns (Spans 3 col on xl screens) */}
        <div className="xl:col-span-3">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-white">
              <span className="material-symbols-outlined text-[18px] text-[#C9A86A]">view_column</span>
              <span>Autonomous Task Pipeline</span>
            </div>
            <button
              onClick={onAddTask}
              className="px-3.5 py-1.5 bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold rounded-full text-xs flex items-center gap-1.5 transition-all shadow-[0_0_12px_rgba(201,168,106,0.2)] cursor-pointer"
            >
              <span className="material-symbols-outlined text-[14px]">add</span>
              Add Task
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            {columns.map((col) => {
              const colTasks = tasks.filter((t) => t.status === col.id);
              return (
                <div
                  key={col.id}
                  onDragOver={handleDragOver}
                  onDrop={() => handleDrop(col.id)}
                  className="bg-[#111111] border border-white/10 rounded-2xl p-3 flex flex-col min-h-[460px] transition-colors"
                >
                  {/* Column Header */}
                  <div className="flex items-center justify-between pb-2 mb-3 border-b border-white/10">
                    <span className="text-[10px] text-white/60 uppercase tracking-[0.2em] font-medium">
                      {col.label}
                    </span>
                    <span className="font-code-sm text-[10px] px-2 py-0.5 rounded-full bg-white/10 text-white/70">
                      {colTasks.length}
                    </span>
                  </div>

                  {/* Tasks Container */}
                  <div className="flex-1 space-y-3">
                    {colTasks.map((task) => {
                      const isPlanningWarning = task.hasWarning;
                      const isRunning = task.status === 'running';

                      return (
                        <div
                          key={task.id}
                          draggable
                          onDragStart={() => handleDragStart(task.id)}
                          onClick={() => onOpenTaskModal(task)}
                          className={`p-3.5 bg-[#161616] rounded-xl border cursor-grab active:cursor-grabbing hover:border-white/30 transition-all group relative ${
                            isPlanningWarning
                              ? 'border-[#E5A93C]/70 shadow-[0_0_12px_rgba(229,169,60,0.15)]'
                              : isRunning
                              ? 'border-[#C9A86A]/70 shadow-[0_0_15px_rgba(201,168,106,0.2)]'
                              : 'border-white/10'
                          }`}
                        >
                          {/* Top Task Row */}
                          <div className="flex items-center justify-between mb-2">
                            <span className="font-code-sm text-[10px] text-white/40 truncate max-w-[100px]">
                              {task.id}
                            </span>
                            <div className="flex items-center gap-1.5">
                              {task.uptime && (
                                <span className="font-code-sm text-[9px] text-[#C9A86A]">
                                  {task.uptime}
                                </span>
                              )}
                              <span
                                className="w-5 h-5 rounded-full flex items-center justify-center font-code-sm text-[9px] font-bold text-black shadow-sm"
                                style={{ backgroundColor: task.assignee.color }}
                                title={task.assignee.name}
                              >
                                {task.assignee.code}
                              </span>
                            </div>
                          </div>

                          {/* Task Title */}
                          <p className="text-xs text-white/90 font-normal leading-relaxed line-clamp-3 mb-3">
                            {task.title}
                          </p>

                          {/* Running Progress Bar */}
                          {isRunning && (
                            <div className="w-full bg-white/10 h-1.5 rounded-full overflow-hidden mb-3">
                              <div
                                className="bg-[#C9A86A] h-full rounded-full transition-all duration-500 shadow-[0_0_8px_#C9A86A]"
                                style={{ width: `${task.progressPercent || 45}%` }}
                              ></div>
                            </div>
                          )}

                          {/* Warning Message if any */}
                          {task.warningMessage && (
                            <div className="font-code-sm text-[9px] text-[#E5A93C] mb-2 flex items-center gap-1">
                              <span className="material-symbols-outlined text-[12px]">warning</span>
                              <span className="truncate">{task.warningMessage}</span>
                            </div>
                          )}

                          {/* Tags & Spec Link */}
                          <div className="flex flex-wrap items-center justify-between gap-1 pt-2 border-t border-white/5">
                            <div className="flex items-center gap-1">
                              {task.tags.map((tg) => (
                                <span
                                  key={tg}
                                  className="font-code-sm text-[8px] uppercase tracking-wider px-1.5 py-0.5 rounded-full bg-white/5 text-white/60 border border-white/5"
                                >
                                  {tg}
                                </span>
                              ))}
                              {task.specLink && (
                                <span className="font-code-sm text-[9px] text-[#C9A86A] flex items-center gap-0.5">
                                  <span className="material-symbols-outlined text-[10px]">link</span>
                                  {task.specLink}
                                </span>
                              )}
                            </div>

                            {/* Quick card action buttons */}
                            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              {['backlog', 'planning'].includes(task.status) && onDispatchTask && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onDispatchTask(task.id);
                                  }}
                                  className="px-2 py-0.5 rounded-full bg-[#C9A86A]/20 hover:bg-[#C9A86A]/30 text-[#C9A86A] border border-[#C9A86A]/40 font-semibold text-[9px] cursor-pointer transition-all flex items-center gap-0.5"
                                  title="Dispatch task immediately to assigned agent"
                                >
                                  <span>⚡</span> Dispatch
                                </button>
                              )}
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (onTerminateTask) onTerminateTask(task.id);
                                }}
                                className="p-1 rounded hover:bg-red-500/20 text-white/40 hover:text-red-400 cursor-pointer"
                                title="Terminate Task (Stop agent & complete)"
                              >
                                <span className="text-[11px]">🛑</span>
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (onDeleteTask) onDeleteTask(task.id);
                                }}
                                className="p-1 rounded hover:bg-red-500/20 text-white/40 hover:text-red-400 cursor-pointer"
                                title="Delete Task"
                              >
                                <span className="material-symbols-outlined text-[12px]">delete</span>
                              </button>
                              <button
                                onClick={(e) => moveTask(task.id, 'left', e)}
                                className="p-0.5 rounded hover:bg-white/10 text-white/40 hover:text-white cursor-pointer"
                                title="Move Left"
                              >
                                <span className="material-symbols-outlined text-[12px]">chevron_left</span>
                              </button>
                              <button
                                onClick={(e) => moveTask(task.id, 'right', e)}
                                className="p-0.5 rounded hover:bg-white/10 text-white/40 hover:text-white cursor-pointer"
                                title="Move Right"
                              >
                                <span className="material-symbols-outlined text-[12px]">chevron_right</span>
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}

                    {colTasks.length === 0 && (
                      <div className="h-28 border border-dashed border-white/10 rounded-xl flex flex-col items-center justify-center text-white/20 font-code-sm text-xs">
                        <span>Drop Zone</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Activity Rail (Spans 1 col on xl screens) */}
        <div className="space-y-4">
          {/* Live File Leases */}
          <div className="bg-[#111111] border border-white/10 rounded-2xl p-4">
            <div className="flex items-center justify-between pb-2 mb-3 border-b border-white/10">
              <span className="text-[10px] text-white/60 uppercase tracking-[0.2em] font-medium flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[14px] text-[#C9A86A]">lock</span>
                Live File Leases
              </span>
              <span className="font-code-sm text-[10px] text-white/40">{fileLeases.length} Active</span>
            </div>

            <div className="space-y-2">
              {fileLeases.map((lease) => (
                <div
                  key={lease.id}
                  className="p-2.5 bg-[#161616] border border-white/5 rounded-xl flex items-center justify-between text-xs"
                >
                  <div className="flex items-center gap-2 truncate">
                    <span
                      className="w-4 h-4 rounded-full flex items-center justify-center font-code-sm text-[9px] font-bold text-black shrink-0"
                      style={{ backgroundColor: lease.holderColor }}
                    >
                      {lease.holderCode}
                    </span>
                    <span className="font-code-sm text-[11px] text-white/80 truncate">
                      {lease.file}
                    </span>
                  </div>
                  <span className="font-code-sm text-[10px] text-white/40 shrink-0 ml-2">
                    {lease.duration}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Recent Handoffs */}
          <div className="bg-[#111111] border border-white/10 rounded-2xl p-4">
            <div className="flex items-center justify-between pb-2 mb-3 border-b border-white/10">
              <span className="text-[10px] text-white/60 uppercase tracking-[0.2em] font-medium flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[14px] text-white">swap_horiz</span>
                Recent Handoffs
              </span>
              <span className="font-code-sm text-[10px] text-white/40">Live</span>
            </div>

            <div className="space-y-2">
              {handoffs.map((h) => (
                <div
                  key={h.id}
                  className="p-2.5 bg-[#161616] border border-white/5 rounded-xl flex items-center justify-between text-xs"
                >
                  <div className="flex items-center gap-1.5 font-code-sm text-[11px]">
                    <span className="text-[#C9A86A] font-medium">{h.from}</span>
                    <span className="text-white/40">→</span>
                    <span className="text-[#4ADE80] font-medium">{h.to}</span>
                  </div>
                  <span className="font-code-sm text-[10px] text-white/40">{h.timeAgo}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Shared Context Stream with CRT overlay */}
          <div className="bg-[#0c0c0c] border border-white/10 rounded-2xl p-4 relative overflow-hidden crt-overlay">
            <div className="flex items-center justify-between pb-2 mb-3 border-b border-white/10 relative z-10">
              <span className="text-[10px] text-[#C9A86A] uppercase tracking-[0.2em] font-medium flex items-center gap-1.5">
                <span className="material-symbols-outlined text-[14px] animate-pulse">terminal</span>
                Shared Context Stream
              </span>
              <span className="w-2 h-2 rounded-full bg-[#C9A86A] animate-ping"></span>
            </div>

            <div className="space-y-1.5 relative z-10 max-h-48 overflow-y-auto pr-1">
              {contextMessages.map((msg) => (
                <div key={msg.id} className="font-code-sm text-[11px] leading-relaxed">
                  <span className="text-white/30 mr-1.5">[{msg.timestamp}]</span>
                  <span className="font-medium mr-1.5" style={{ color: msg.color }}>
                    {msg.source}
                  </span>
                  <span className="text-white/70">{msg.text}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
