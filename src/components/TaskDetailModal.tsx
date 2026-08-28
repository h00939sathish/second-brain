import React, { useState } from 'react';
import { KanbanTask, KanbanStatus } from '../types';

interface TaskDetailModalProps {
  task: KanbanTask | null;
  isOpen: boolean;
  onClose: () => void;
  onStatusChange?: (newStatus: KanbanStatus) => void;
  onDispatch?: (taskId: string) => void;
}

export const TaskDetailModal: React.FC<TaskDetailModalProps> = ({
  task,
  isOpen,
  onClose,
  onStatusChange,
  onDispatch,
}) => {
  const [isDispatching, setIsDispatching] = useState(false);
  const [dispatchResult, setDispatchResult] = useState<string | null>(null);

  if (!isOpen || !task) return null;

  const statuses: { label: string; value: KanbanStatus; color: string }[] = [
    { label: 'Backlog', value: 'backlog', color: '#64748b' },
    { label: 'Planning', value: 'planning', color: '#a855f7' },
    { label: 'Running', value: 'running', color: '#10b981' },
    { label: 'Review', value: 'review', color: '#06b6d4' },
    { label: 'Done (Closed)', value: 'done', color: '#22c55e' },
  ];

  const handleStatusClick = async (newStatus: KanbanStatus) => {
    if (onStatusChange) {
      onStatusChange(newStatus);
    }
  };

  const handleDispatchClick = async () => {
    setIsDispatching(true);
    setDispatchResult(null);
    try {
      const res = await fetch('/api/dispatch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: task.id }),
      });
      const data = await res.json();
      setDispatchResult(data.success ? 'Agent dispatched successfully!' : 'Dispatch failed');
    } catch {
      setDispatchResult('Server offline');
    } finally {
      setIsDispatching(false);
    }
  };

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-lg bg-[#111111] border border-white/10 rounded-3xl shadow-2xl p-6 relative max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between pb-4 mb-4 border-b border-white/10">
          <div className="flex items-center gap-2">
            <span className="font-code-sm text-xs text-[#C9A86A] font-semibold">{task.id}</span>
            <span
              className="px-2.5 py-0.5 rounded-full font-code-sm text-[10px] font-semibold uppercase tracking-wider"
              style={{
                backgroundColor: `${task.assignee.color}20`,
                color: task.assignee.color,
                border: `1px solid ${task.assignee.color}50`,
              }}
            >
              [{task.status}]
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-white/40 hover:text-white p-2 rounded-full cursor-pointer hover:bg-white/10 transition-colors"
            title="Close Modal"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="space-y-4 font-code-sm text-xs">
          <div>
            <label className="text-white/40 text-[9px] uppercase tracking-wider">Task Directive</label>
            <h3 className="text-base font-medium text-white mt-0.5 leading-snug">{task.title}</h3>
          </div>

          {/* Quick Status Bar */}
          <div>
            <label className="text-white/40 text-[9px] uppercase tracking-wider block mb-1.5">Change Pipeline Stage</label>
            <div className="grid grid-cols-5 gap-1.5 p-1 bg-[#161616] border border-white/10 rounded-2xl">
              {statuses.map((st) => (
                <button
                  key={st.value}
                  onClick={() => handleStatusClick(st.value)}
                  className={`py-1.5 px-2 rounded-xl text-[10px] font-medium transition-all cursor-pointer text-center truncate ${
                    task.status === st.value
                      ? 'bg-white/20 text-white font-bold shadow-sm'
                      : 'text-white/40 hover:text-white hover:bg-white/5'
                  }`}
                  style={{
                    borderColor: task.status === st.value ? st.color : 'transparent',
                    borderWidth: '1px',
                  }}
                >
                  {st.label.split(' ')[0]}
                </button>
              ))}
            </div>
          </div>

          {task.description && (
            <div>
              <label className="text-white/40 text-[9px] uppercase tracking-wider">Execution Context</label>
              <p className="text-white/70 text-xs bg-[#161616] p-4 rounded-2xl border border-white/5 mt-1 leading-relaxed whitespace-pre-wrap">
                {task.description}
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 p-4 bg-[#161616] border border-white/5 rounded-2xl">
            <div>
              <span className="text-white/40 text-[9px] uppercase tracking-wider block">Assigned Role</span>
              <div className="flex items-center gap-2 mt-1">
                <span
                  className="w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold text-black"
                  style={{ backgroundColor: task.assignee.color }}
                >
                  {task.assignee.code}
                </span>
                <span className="text-white font-medium">{task.assignee.name}</span>
              </div>
            </div>

            <div>
              <span className="text-white/40 text-[9px] uppercase tracking-wider block">Pipeline Stage</span>
              <span className="text-[#C9A86A] font-medium mt-1 block uppercase">
                [{task.status}]
              </span>
            </div>

            {task.specLink && (
              <div className="col-span-2">
                <span className="text-white/40 text-[9px] uppercase tracking-wider block">Linked Upstream Spec</span>
                <span className="text-[#C9A86A] font-medium mt-1 block">[[{task.specLink}]]</span>
              </div>
            )}
          </div>

          {dispatchResult && (
            <div className="p-3 bg-[#10b981]/10 border border-[#10b981]/30 rounded-2xl text-[#10b981] text-xs">
              {dispatchResult}
            </div>
          )}

          <div className="flex items-center justify-between pt-4 border-t border-white/10 gap-3">
            <button
              onClick={handleDispatchClick}
              disabled={isDispatching}
              className="px-4 py-2 rounded-full bg-white/10 hover:bg-white/20 text-white font-medium text-xs cursor-pointer transition-all disabled:opacity-50"
            >
              {isDispatching ? 'Dispatching...' : '⚡ Trigger Dispatch'}
            </button>

            <div className="flex items-center gap-2">
              {task.status !== 'done' && (
                <button
                  onClick={() => handleStatusClick('done')}
                  className="px-4 py-2 rounded-full bg-[#10b981]/20 hover:bg-[#10b981]/30 text-[#10b981] border border-[#10b981]/40 font-semibold text-xs cursor-pointer transition-all"
                >
                  ✓ Mark as Done
                </button>
              )}
              <button
                onClick={onClose}
                className="px-5 py-2 rounded-full bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold text-xs shadow-[0_0_10px_rgba(201,168,106,0.25)] cursor-pointer transition-all"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
