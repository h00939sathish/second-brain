import React, { useState, useEffect } from 'react';
import {
  WorkflowPipeline,
  WorkflowStageNode,
  WorkflowAgent,
  AgentRoleType,
  LogEntry,
} from '../types';
import { AVAILABLE_AGENTS } from '../data/initialData';
import { useTrackComponentRender } from '../hooks/usePerformanceProfiler';

interface WorkflowOrchestratorViewProps {
  pipeline: WorkflowPipeline;
  onUpdatePipeline: (pipeline: WorkflowPipeline) => void;
  onLogEvent?: (log: LogEntry) => void;
}

const ROLE_META: Record<
  AgentRoleType,
  { label: string; icon: string; color: string; bg: string; border: string; desc: string }
> = {
  planning: {
    label: 'Planning',
    icon: 'architecture',
    color: '#C9A86A',
    bg: 'bg-[#C9A86A]/10',
    border: 'border-[#C9A86A]/30',
    desc: 'Requirements breakdown, system architecture, contracts & spec synthesis.',
  },
  building: {
    label: 'Building',
    icon: 'code',
    color: '#22d3ee',
    bg: 'bg-[#22d3ee]/10',
    border: 'border-[#22d3ee]/30',
    desc: 'Algorithmic code synthesis, refactoring, type generation & implementation.',
  },
  reviewing: {
    label: 'Reviewing',
    icon: 'verified_user',
    color: '#a855f7',
    bg: 'bg-[#a855f7]/10',
    border: 'border-[#a855f7]/30',
    desc: 'AST security audits, leak checks, code hygiene & boundary verification.',
  },
  qa: {
    label: 'QA & Testing',
    icon: 'troubleshoot',
    color: '#38bdf8',
    bg: 'bg-[#38bdf8]/10',
    border: 'border-[#38bdf8]/30',
    desc: 'Automated test matrices, regression suites & synthetic user simulations.',
  },
  deployment: {
    label: 'Deployment',
    icon: 'rocket_launch',
    color: '#f59e0b',
    bg: 'bg-[#f59e0b]/10',
    border: 'border-[#f59e0b]/30',
    desc: 'Container containerization, artifact hashing & zero-downtime routing.',
  },
};

export const WorkflowOrchestratorView: React.FC<WorkflowOrchestratorViewProps> = ({
  pipeline,
  onUpdatePipeline,
  onLogEvent,
}) => {
  useTrackComponentRender('WorkflowOrchestratorView');

  // Drag states
  const [draggedStageIndex, setDraggedStageIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [draggedAgent, setDraggedAgent] = useState<WorkflowAgent | null>(null);
  const [agentDropTargetStageId, setAgentDropTargetStageId] = useState<string | null>(null);

  // Inspector & modal states
  const [selectedStageId, setSelectedStageId] = useState<string | null>(pipeline.stages[0]?.id || null);
  const [isAgentDrawerOpen, setIsAgentDrawerOpen] = useState(true);
  const [activePreset, setActivePreset] = useState<string>('full-lifecycle');
  const [filterRole, setFilterRole] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState('');

  // Simulation execution state
  const [simulatedLogs, setSimulatedLogs] = useState<string[]>([]);
  const [executionProgress, setExecutionProgress] = useState(0);

  const selectedStage = pipeline.stages.find((s) => s.id === selectedStageId) || pipeline.stages[0];

  // Pipeline Execution Step Simulator
  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (pipeline.isRunning) {
      timer = setInterval(() => {
        setExecutionProgress((prev) => {
          if (prev >= 100) {
            // Next stage
            const nextIdx = pipeline.currentStepIndex + 1;
            if (nextIdx < pipeline.stages.length) {
              const updatedStages = [...pipeline.stages];
              updatedStages[pipeline.currentStepIndex].status = 'passed';
              updatedStages[nextIdx].status = 'active';

              const currentStage = updatedStages[pipeline.currentStepIndex];
              const nextStage = updatedStages[nextIdx];

              const logMsg = `[Workflow] Stage "${currentStage.title}" completed. Handing off to "${nextStage.title}" (${nextStage.agentName})`;
              setSimulatedLogs((l) => [logMsg, ...l.slice(0, 15)]);

              if (onLogEvent) {
                onLogEvent({
                  id: `wf-${Date.now()}`,
                  timestamp: new Date().toLocaleTimeString(),
                  level: 'OK',
                  tag: '[Workflow]',
                  sourceColor: currentStage.agentColor,
                  message: logMsg,
                });
              }

              onUpdatePipeline({
                ...pipeline,
                currentStepIndex: nextIdx,
                activeStageId: nextStage.id,
                stages: updatedStages,
              });
              return 0;
            } else {
              // Finished pipeline
              const updatedStages = pipeline.stages.map((s) => ({ ...s, status: 'passed' as const }));
              const finishMsg = `[Workflow] Pipeline "${pipeline.name}" completed all ${pipeline.stages.length} stages successfully!`;
              setSimulatedLogs((l) => [finishMsg, ...l.slice(0, 15)]);

              if (onLogEvent) {
                onLogEvent({
                  id: `wf-done-${Date.now()}`,
                  timestamp: new Date().toLocaleTimeString(),
                  level: 'OK',
                  tag: '[Workflow-Engine]',
                  sourceColor: '#C9A86A',
                  message: finishMsg,
                });
              }

              onUpdatePipeline({
                ...pipeline,
                isRunning: false,
                currentStepIndex: 0,
                activeStageId: null,
                stages: updatedStages,
              });
              return 0;
            }
          }
          return prev + 20;
        });
      }, 700);
    }
    return () => clearInterval(timer);
  }, [pipeline, onUpdatePipeline, onLogEvent]);

  // Stage Reordering Handlers (Drag & Drop)
  const handleStageDragStart = (e: React.DragEvent, index: number) => {
    e.dataTransfer.setData('type', 'stage-reorder');
    e.dataTransfer.setData('index', index.toString());
    setDraggedStageIndex(index);
  };

  const handleStageDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault();
    if (draggedStageIndex !== null && draggedStageIndex !== index) {
      setDragOverIndex(index);
    }
  };

  const handleStageDrop = (e: React.DragEvent, targetIndex: number) => {
    e.preventDefault();
    const type = e.dataTransfer.getData('type');

    if (type === 'stage-reorder' && draggedStageIndex !== null) {
      const updatedStages = [...pipeline.stages];
      const [movedStage] = updatedStages.splice(draggedStageIndex, 1);
      updatedStages.splice(targetIndex, 0, movedStage);

      onUpdatePipeline({
        ...pipeline,
        stages: updatedStages,
      });

      const log = `[Workflow] Reordered stage: "${movedStage.title}" shifted to position #${targetIndex + 1}`;
      setSimulatedLogs((l) => [log, ...l.slice(0, 15)]);
    }

    setDraggedStageIndex(null);
    setDragOverIndex(null);
  };

  // Agent Placement Handlers (Drag Agent Card onto Stage)
  const handleAgentDragStart = (e: React.DragEvent, agent: WorkflowAgent) => {
    e.dataTransfer.setData('type', 'agent-assign');
    e.dataTransfer.setData('agentId', agent.id);
    setDraggedAgent(agent);
  };

  const handleStageAgentDragOver = (e: React.DragEvent, stageId: string) => {
    e.preventDefault();
    setAgentDropTargetStageId(stageId);
  };

  const handleStageAgentDrop = (e: React.DragEvent, stageId: string) => {
    e.preventDefault();
    const type = e.dataTransfer.getData('type');
    const agentId = e.dataTransfer.getData('agentId');

    if (type === 'agent-assign' && agentId) {
      const agent = AVAILABLE_AGENTS.find((a) => a.id === agentId);
      if (agent) {
        const updatedStages = pipeline.stages.map((stage) => {
          if (stage.id === stageId) {
            return {
              ...stage,
              assignedAgentId: agent.id,
              agentName: agent.name,
              agentModel: agent.model,
              agentColor: agent.color,
            };
          }
          return stage;
        });

        onUpdatePipeline({
          ...pipeline,
          stages: updatedStages,
        });

        const log = `[Workflow] Assigned agent "${agent.name}" (${agent.model}) to stage "${stageId}"`;
        setSimulatedLogs((l) => [log, ...l.slice(0, 15)]);

        if (onLogEvent) {
          onLogEvent({
            id: `assign-${Date.now()}`,
            timestamp: new Date().toLocaleTimeString(),
            level: 'INFO',
            tag: '[Workflow-Routing]',
            sourceColor: agent.color,
            message: log,
          });
        }
      }
    }
    setDraggedAgent(null);
    setAgentDropTargetStageId(null);
  };

  // Preset Workflows loader
  const loadPreset = (presetKey: string) => {
    setActivePreset(presetKey);
    if (presetKey === 'full-lifecycle') {
      onUpdatePipeline({
        ...pipeline,
        name: 'Standard Autonomous Multi-Agent Flow',
        description: 'Complete lifecycle: Planning → Building → Reviewing → QA Validation → Deployment',
        isRunning: false,
        currentStepIndex: 0,
        stages: [
          {
            id: 'stage-1',
            title: 'Planning & Architecture Spec',
            stageType: 'planning',
            description: 'Deconstruct prompt into interface contracts, schema models, and atomic milestones.',
            assignedAgentId: 'agent-gemini-planner',
            agentName: 'Gemini Architect',
            agentModel: 'Gemini 3.7 Pro',
            agentColor: '#C9A86A',
            status: 'idle',
            autoHandoff: true,
            requiredApproval: false,
            maxRetries: 2,
            outputArtifactName: 'architecture-spec.md',
          },
          {
            id: 'stage-2',
            title: 'Code Generation & Implementation',
            stageType: 'building',
            description: 'Write type-safe implementation, UI components, backend routes, and database hooks.',
            assignedAgentId: 'agent-codex-builder',
            agentName: 'Codex 5.6 Engine',
            agentModel: 'Codex 5.6 DeepCode',
            agentColor: '#22d3ee',
            status: 'idle',
            autoHandoff: true,
            requiredApproval: false,
            maxRetries: 3,
            outputArtifactName: 'src/app-bundle.ts',
          },
          {
            id: 'stage-3',
            title: 'Security Audit & Code Review',
            stageType: 'reviewing',
            description: 'Inspect AST structures, detect leak risks, audit imports, and enforce zero-side-effects.',
            assignedAgentId: 'agent-antigravity-reviewer',
            agentName: 'Antigravity Gatekeeper',
            agentModel: 'Antigravity Audit 2.0',
            agentColor: '#a855f7',
            status: 'idle',
            autoHandoff: true,
            requiredApproval: true,
            maxRetries: 2,
            outputArtifactName: 'security-audit.json',
          },
          {
            id: 'stage-4',
            title: 'E2E Matrix & Regression QA',
            stageType: 'qa',
            description: 'Execute automated regression matrices and synthetic user interaction test suites.',
            assignedAgentId: 'agent-benchmark-qa',
            agentName: 'E2E Matrix QA',
            agentModel: 'Gemini 3.7 Flash Test',
            agentColor: '#38bdf8',
            status: 'idle',
            autoHandoff: true,
            requiredApproval: false,
            maxRetries: 1,
            outputArtifactName: 'qa-results.xml',
          },
          {
            id: 'stage-5',
            title: 'Zero-Downtime Deployment',
            stageType: 'deployment',
            description: 'Compile production bundle and route traffic through reverse proxy canary.',
            assignedAgentId: 'agent-cloud-deployer',
            agentName: 'Container Daemon Deployer',
            agentModel: 'Cloud Automation Daemon',
            agentColor: '#f59e0b',
            status: 'idle',
            autoHandoff: false,
            requiredApproval: true,
            maxRetries: 1,
            outputArtifactName: 'deploy-receipt.json',
          },
        ],
      });
    } else if (presetKey === 'rapid-prototype') {
      onUpdatePipeline({
        ...pipeline,
        name: 'Rapid Prototyping Pipeline',
        description: 'Fast dual-stage workflow optimized for instant UI experimentation: Planning → Fast Building',
        isRunning: false,
        currentStepIndex: 0,
        stages: [
          {
            id: 'stage-proto-1',
            title: 'Rapid Spec Formulation',
            stageType: 'planning',
            description: 'Generate concise UI blueprint and mock datasets in sub-second inference.',
            assignedAgentId: 'agent-claude-reasoner',
            agentName: 'Claude Synthesizer',
            agentModel: 'Claude 3.7 Sonnet',
            agentColor: '#ec6a06',
            status: 'idle',
            autoHandoff: true,
            requiredApproval: false,
            maxRetries: 1,
            outputArtifactName: 'spec.json',
          },
          {
            id: 'stage-proto-2',
            title: 'Rapid Scaffolding & Code',
            stageType: 'building',
            description: 'Synthesize complete functional prototype with hot module bindings.',
            assignedAgentId: 'agent-opencode-builder',
            agentName: 'OpenCode Specialist',
            agentModel: 'OpenCode DeepSeek R1',
            agentColor: '#10b981',
            status: 'idle',
            autoHandoff: true,
            requiredApproval: false,
            maxRetries: 2,
            outputArtifactName: 'prototype.tsx',
          },
        ],
      });
    } else if (presetKey === 'security-critical') {
      onUpdatePipeline({
        ...pipeline,
        name: 'High-Assurance Security Flow',
        description: 'Paranoid verification workflow with double code review, AST inspection, and strict approval gates.',
        isRunning: false,
        currentStepIndex: 0,
        stages: [
          {
            id: 'stage-sec-1',
            title: 'Threat Modeling & Spec',
            stageType: 'planning',
            description: 'Identify zero-trust surface boundaries and cryptographic requirements.',
            assignedAgentId: 'agent-gemini-planner',
            agentName: 'Gemini Architect',
            agentModel: 'Gemini 3.7 Pro',
            agentColor: '#C9A86A',
            status: 'idle',
            autoHandoff: true,
            requiredApproval: true,
            maxRetries: 2,
            outputArtifactName: 'threat-model.md',
          },
          {
            id: 'stage-sec-2',
            title: 'Defensive Implementation',
            stageType: 'building',
            description: 'Implement hardened handlers with sanitization and bounded buffers.',
            assignedAgentId: 'agent-codex-builder',
            agentName: 'Codex 5.6 Engine',
            agentModel: 'Codex 5.6 DeepCode',
            agentColor: '#22d3ee',
            status: 'idle',
            autoHandoff: true,
            requiredApproval: false,
            maxRetries: 2,
            outputArtifactName: 'hardened-core.ts',
          },
          {
            id: 'stage-sec-3',
            title: 'Gatekeeper Static Analysis',
            stageType: 'reviewing',
            description: 'Scan AST tree, inspect OWASP Top 10 vulnerabilities, and verify token isolation.',
            assignedAgentId: 'agent-antigravity-reviewer',
            agentName: 'Antigravity Gatekeeper',
            agentModel: 'Antigravity Audit 2.0',
            agentColor: '#a855f7',
            status: 'idle',
            autoHandoff: true,
            requiredApproval: true,
            maxRetries: 1,
            outputArtifactName: 'ast-audit.json',
          },
          {
            id: 'stage-sec-4',
            title: 'Sentinel Policy Review',
            stageType: 'reviewing',
            description: 'Verify strict zero-regression guarantees and boundary constraint contracts.',
            assignedAgentId: 'agent-sentinel-reviewer',
            agentName: 'Sentinel Code Reviewer',
            agentModel: 'Sentinel Guard LLM',
            agentColor: '#f43f5e',
            status: 'idle',
            autoHandoff: false,
            requiredApproval: true,
            maxRetries: 1,
            outputArtifactName: 'sentinel-signoff.json',
          },
        ],
      });
    }
  };

  // Add new stage
  const handleAddNewStage = (role: AgentRoleType) => {
    const defaultAgent = AVAILABLE_AGENTS.find((a) => a.role === role) || AVAILABLE_AGENTS[0];
    const newStage: WorkflowStageNode = {
      id: `stage-${Date.now()}`,
      title: `Custom ${ROLE_META[role].label} Stage`,
      stageType: role,
      description: `Custom stage dedicated to ${ROLE_META[role].desc.toLowerCase()}`,
      assignedAgentId: defaultAgent.id,
      agentName: defaultAgent.name,
      agentModel: defaultAgent.model,
      agentColor: defaultAgent.color,
      status: 'idle',
      autoHandoff: true,
      requiredApproval: false,
      maxRetries: 2,
      outputArtifactName: `artifact-${role}-${Date.now().toString().slice(-4)}.json`,
    };

    onUpdatePipeline({
      ...pipeline,
      stages: [...pipeline.stages, newStage],
    });
    setSelectedStageId(newStage.id);

    const log = `[Workflow] Added new ${ROLE_META[role].label} stage to workflow pipeline.`;
    setSimulatedLogs((l) => [log, ...l.slice(0, 15)]);
  };

  // Delete stage
  const handleDeleteStage = (stageId: string) => {
    if (pipeline.stages.length <= 1) return;
    const updatedStages = pipeline.stages.filter((s) => s.id !== stageId);
    onUpdatePipeline({
      ...pipeline,
      stages: updatedStages,
    });
    if (selectedStageId === stageId) {
      setSelectedStageId(updatedStages[0]?.id || null);
    }
  };

  // Update selected stage property
  const handleUpdateStageProp = (key: keyof WorkflowStageNode, val: unknown) => {
    if (!selectedStage) return;
    const updatedStages = pipeline.stages.map((stage) => {
      if (stage.id === selectedStage.id) {
        return {
          ...stage,
          [key]: val,
        };
      }
      return stage;
    });

    onUpdatePipeline({
      ...pipeline,
      stages: updatedStages,
    });
  };

  // Start / Pause Pipeline Execution
  const toggleExecution = () => {
    if (pipeline.isRunning) {
      onUpdatePipeline({
        ...pipeline,
        isRunning: false,
      });
      const log = `[Workflow] Paused workflow execution.`;
      setSimulatedLogs((l) => [log, ...l.slice(0, 15)]);
    } else {
      const updatedStages = pipeline.stages.map((s, idx) => ({
        ...s,
        status: idx === 0 ? ('active' as const) : ('idle' as const),
      }));

      onUpdatePipeline({
        ...pipeline,
        isRunning: true,
        currentStepIndex: 0,
        activeStageId: pipeline.stages[0]?.id || null,
        stages: updatedStages,
      });
      setExecutionProgress(0);

      const log = `[Workflow] Initiated live execution of "${pipeline.name}" with ${pipeline.stages.length} connected agent stages.`;
      setSimulatedLogs((l) => [log, ...l.slice(0, 15)]);
    }
  };

  // Reset Pipeline
  const handleResetPipeline = () => {
    const updatedStages = pipeline.stages.map((s) => ({ ...s, status: 'idle' as const }));
    onUpdatePipeline({
      ...pipeline,
      isRunning: false,
      currentStepIndex: 0,
      activeStageId: null,
      stages: updatedStages,
    });
    setExecutionProgress(0);
    setSimulatedLogs((l) => ['[Workflow] Reset pipeline state to idle.', ...l.slice(0, 15)]);
  };

  // Filter available agents
  const filteredAgents = AVAILABLE_AGENTS.filter((agent) => {
    const matchesRole = filterRole === 'ALL' || agent.role === filterRole;
    const matchesQuery =
      agent.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      agent.model.toLowerCase().includes(searchQuery.toLowerCase()) ||
      agent.systemPrompt.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesRole && matchesQuery;
  });

  return (
    <div className="space-y-6">
      {/* Top Banner & Control Deck */}
      <div className="bg-[#111111] border border-white/10 rounded-3xl p-6 shadow-2xl relative overflow-hidden">
        {/* Background circuit glow */}
        <div className="absolute top-0 right-0 w-96 h-96 bg-[#C9A86A]/5 rounded-full blur-3xl pointer-events-none"></div>

        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 relative z-10">
          <div>
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-[#C9A86A]/10 border border-[#C9A86A]/30 flex items-center justify-center text-[#C9A86A] shadow-[0_0_12px_rgba(201,168,106,0.2)]">
                <span className="material-symbols-outlined text-[24px]">account_tree</span>
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-xl font-light tracking-wide text-white">
                    Agent Workflow Orchestrator
                  </h1>
                  <span className="font-code-sm text-[10px] px-2.5 py-0.5 rounded-full bg-[#C9A86A]/15 text-[#C9A86A] border border-[#C9A86A]/30">
                    DRAG & DROP WORKFLOW
                  </span>
                  {pipeline.isRunning && (
                    <span className="font-code-sm text-[10px] px-2.5 py-0.5 rounded-full bg-[#4ADE80]/15 text-[#4ADE80] border border-[#4ADE80]/30 flex items-center gap-1.5 animate-pulse">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#4ADE80]"></span>
                      RUNNING STEP {pipeline.currentStepIndex + 1}/{pipeline.stages.length}
                    </span>
                  )}
                </div>
                <p className="font-code-sm text-xs text-white/50 mt-1">
                  Drag and reorder workflow stages or drag specialized AI agents (Planning, Building, Reviewing, QA, Deployment) directly onto any stage to customize autonomous execution.
                </p>
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center gap-2.5">
            {/* Presets dropdown */}
            <div className="flex items-center gap-1 bg-[#161616] p-1 rounded-full border border-white/10">
              <button
                onClick={() => loadPreset('full-lifecycle')}
                className={`px-3 py-1.5 rounded-full text-xs font-code-sm transition-all cursor-pointer ${
                  activePreset === 'full-lifecycle'
                    ? 'bg-[#C9A86A] text-black font-semibold shadow-[0_0_8px_rgba(201,168,106,0.3)]'
                    : 'text-white/50 hover:text-white'
                }`}
              >
                Full Lifecycle
              </button>
              <button
                onClick={() => loadPreset('rapid-prototype')}
                className={`px-3 py-1.5 rounded-full text-xs font-code-sm transition-all cursor-pointer ${
                  activePreset === 'rapid-prototype'
                    ? 'bg-[#C9A86A] text-black font-semibold shadow-[0_0_8px_rgba(201,168,106,0.3)]'
                    : 'text-white/50 hover:text-white'
                }`}
              >
                Rapid Prototype
              </button>
              <button
                onClick={() => loadPreset('security-critical')}
                className={`px-3 py-1.5 rounded-full text-xs font-code-sm transition-all cursor-pointer ${
                  activePreset === 'security-critical'
                    ? 'bg-[#C9A86A] text-black font-semibold shadow-[0_0_8px_rgba(201,168,106,0.3)]'
                    : 'text-white/50 hover:text-white'
                }`}
              >
                Hardened Security
              </button>
            </div>

            {/* Toggle Run / Pause */}
            <button
              onClick={toggleExecution}
              className={`px-4 py-2 rounded-full font-code-sm text-xs flex items-center gap-2 transition-all cursor-pointer shadow-lg ${
                pipeline.isRunning
                  ? 'bg-amber-500 hover:bg-amber-400 text-black font-semibold'
                  : 'bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold shadow-[0_0_15px_rgba(201,168,106,0.3)]'
              }`}
            >
              <span className="material-symbols-outlined text-[18px]">
                {pipeline.isRunning ? 'pause' : 'play_arrow'}
              </span>
              <span>{pipeline.isRunning ? 'Pause Workflow' : 'Execute Workflow'}</span>
            </button>

            {/* Reset */}
            <button
              onClick={handleResetPipeline}
              className="p-2 bg-white/5 hover:bg-white/10 border border-white/10 text-white/50 hover:text-white rounded-full transition-colors cursor-pointer"
              title="Reset Pipeline Status"
            >
              <span className="material-symbols-outlined text-[18px]">restart_alt</span>
            </button>

            {/* Agent Pool Drawer Toggle */}
            <button
              onClick={() => setIsAgentDrawerOpen(!isAgentDrawerOpen)}
              className={`px-3.5 py-2 rounded-full border font-code-sm text-xs flex items-center gap-1.5 transition-all cursor-pointer ${
                isAgentDrawerOpen
                  ? 'bg-white/15 border-white/30 text-white'
                  : 'bg-white/5 border-white/10 text-white/60 hover:text-white'
              }`}
            >
              <span className="material-symbols-outlined text-[16px] text-[#C9A86A]">smart_toy</span>
              <span>{isAgentDrawerOpen ? 'Hide Agent Pool' : 'Show Agent Pool'}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Main Workspace Layout */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        {/* Left Column: Interactive Workflow Canvas & Stage Cards */}
        <div className={isAgentDrawerOpen ? 'xl:col-span-8 space-y-6' : 'xl:col-span-12 space-y-6'}>
          {/* Canvas Board */}
          <div className="bg-[#111111] border border-white/10 rounded-3xl p-6 shadow-xl space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-white/10">
              <div className="flex items-center gap-3">
                <div className="w-2.5 h-2.5 rounded-full bg-[#C9A86A]"></div>
                <div>
                  <h2 className="text-base font-light text-white">{pipeline.name}</h2>
                  <p className="font-code-sm text-xs text-white/40">{pipeline.description}</p>
                </div>
              </div>

              {/* Add Stage Buttons */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="font-code-sm text-[10px] text-white/40 uppercase mr-1">Add Stage:</span>
                {(['planning', 'building', 'reviewing', 'qa', 'deployment'] as AgentRoleType[]).map((r) => (
                  <button
                    key={r}
                    onClick={() => handleAddNewStage(r)}
                    className="px-2.5 py-1 rounded-full text-[10px] font-code-sm uppercase tracking-wider bg-white/5 hover:bg-white/10 border border-white/10 text-white/70 hover:text-white flex items-center gap-1 transition-all cursor-pointer"
                    title={`Add new ${r} stage`}
                  >
                    <span className="material-symbols-outlined text-[12px]" style={{ color: ROLE_META[r].color }}>
                      {ROLE_META[r].icon}
                    </span>
                    <span>+{r.slice(0, 4)}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Drag & Drop Visual Flow / Pipeline Sequence */}
            <div className="space-y-4">
              <div className="text-[11px] font-code-sm uppercase tracking-wider text-white/40 flex items-center justify-between">
                <span>Ordered Execution Pipeline ({pipeline.stages.length} Connected Nodes)</span>
                <span className="text-[10px] text-[#C9A86A] flex items-center gap-1">
                  <span className="material-symbols-outlined text-[14px]">drag_indicator</span>
                  Drag stage handles to re-order • Drop agents to assign
                </span>
              </div>

              {/* Connected Stage Nodes */}
              <div className="space-y-3">
                {pipeline.stages.map((stage, index) => {
                  const roleMeta = ROLE_META[stage.stageType];
                  const isSelected = selectedStageId === stage.id;
                  const isCurrentActive = pipeline.isRunning && pipeline.currentStepIndex === index;
                  const isDragOver = dragOverIndex === index;
                  const isAgentTarget = agentDropTargetStageId === stage.id;

                  return (
                    <div
                      key={stage.id}
                      draggable={!pipeline.isRunning}
                      onDragStart={(e) => handleStageDragStart(e, index)}
                      onDragOver={(e) => handleStageDragOver(e, index)}
                      onDrop={(e) => handleStageDrop(e, index)}
                      onDragEnter={() => handleStageDragOver({ preventDefault: () => {} } as React.DragEvent, index)}
                      className={`relative group rounded-2xl border transition-all ${
                        isDragOver ? 'border-[#C9A86A] bg-[#C9A86A]/10 scale-[1.01]' : ''
                      } ${
                        isAgentTarget
                          ? 'border-[#22d3ee] ring-2 ring-[#22d3ee]/40 bg-[#22d3ee]/10'
                          : ''
                      } ${
                        isSelected
                          ? 'border-[#C9A86A] bg-[#161616] shadow-[0_0_20px_rgba(201,168,106,0.15)]'
                          : 'border-white/10 bg-[#141414] hover:border-white/20'
                      }`}
                    >
                      {/* Connection Line indicator */}
                      {index < pipeline.stages.length - 1 && (
                        <div className="absolute left-8 -bottom-3.5 w-0.5 h-3.5 bg-gradient-to-b from-white/20 to-white/10 z-0 pointer-events-none">
                          <div className="w-1.5 h-1.5 rounded-full bg-[#C9A86A] -left-0.5 relative animate-pulse"></div>
                        </div>
                      )}

                      <div
                        onClick={() => setSelectedStageId(stage.id)}
                        onDragOver={(e) => handleStageAgentDragOver(e, stage.id)}
                        onDrop={(e) => handleStageAgentDrop(e, stage.id)}
                        className="p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 cursor-pointer relative z-10"
                      >
                        {/* Left: Drag handle, Step number, Role & Title */}
                        <div className="flex items-center gap-3.5 min-w-0">
                          {/* Drag Handle */}
                          <div
                            className="p-1.5 text-white/30 hover:text-white cursor-grab active:cursor-grabbing rounded-lg hover:bg-white/5 transition-colors"
                            title="Drag to change workflow position"
                          >
                            <span className="material-symbols-outlined text-[18px]">drag_indicator</span>
                          </div>

                          {/* Step Number Badge */}
                          <div
                            className={`w-7 h-7 rounded-full font-code-sm text-xs font-semibold flex items-center justify-center shrink-0 border ${
                              isCurrentActive
                                ? 'bg-[#C9A86A] text-black border-[#C9A86A] shadow-[0_0_10px_#C9A86A]'
                                : stage.status === 'passed'
                                ? 'bg-[#4ADE80]/20 text-[#4ADE80] border-[#4ADE80]/40'
                                : 'bg-white/5 text-white/60 border-white/10'
                            }`}
                          >
                            {stage.status === 'passed' ? (
                              <span className="material-symbols-outlined text-[14px]">check</span>
                            ) : (
                              index + 1
                            )}
                          </div>

                          {/* Stage Role Badge */}
                          <div
                            className={`px-2.5 py-1 rounded-full text-[10px] font-code-sm uppercase font-semibold flex items-center gap-1.5 shrink-0 ${roleMeta.bg} ${roleMeta.border} border`}
                            style={{ color: roleMeta.color }}
                          >
                            <span className="material-symbols-outlined text-[14px]">{roleMeta.icon}</span>
                            <span>{roleMeta.label}</span>
                          </div>

                          {/* Title & Description */}
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <h3 className="font-medium text-white text-sm truncate">{stage.title}</h3>
                              {stage.requiredApproval && (
                                <span className="px-1.5 py-0.2 rounded bg-amber-500/20 border border-amber-500/30 text-amber-400 font-code-sm text-[9px] uppercase">
                                  Gate Approval
                                </span>
                              )}
                            </div>
                            <p className="font-code-sm text-xs text-white/40 truncate max-w-md mt-0.5">
                              {stage.description}
                            </p>
                          </div>
                        </div>

                        {/* Right: Assigned Agent Chip & Stage Status */}
                        <div className="flex items-center gap-3 shrink-0 pl-10 md:pl-0">
                          {/* Agent Chip / Dropzone */}
                          <div
                            className="flex items-center gap-2.5 px-3 py-1.5 rounded-full bg-[#0c0c0c] border border-white/10 group-hover:border-white/25 transition-all shadow-inner"
                            title={`Assigned Agent: ${stage.agentName} (${stage.agentModel}). Drag an agent here to change.`}
                          >
                            <div
                              className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold"
                              style={{ backgroundColor: `${stage.agentColor}33`, color: stage.agentColor }}
                            >
                              {stage.agentName.slice(0, 2).toUpperCase()}
                            </div>
                            <div className="text-left">
                              <div className="font-medium text-xs text-white flex items-center gap-1">
                                <span>{stage.agentName}</span>
                                <span className="material-symbols-outlined text-[12px] text-white/40">swap_horiz</span>
                              </div>
                              <div className="text-[9px] font-code-sm text-white/40">{stage.agentModel}</div>
                            </div>
                          </div>

                          {/* Stage Status badge */}
                          <div className="font-code-sm text-[11px] min-w-[75px] text-right">
                            {isCurrentActive ? (
                              <span className="text-[#C9A86A] flex items-center justify-end gap-1 font-semibold animate-pulse">
                                <span className="material-symbols-outlined text-[14px]">sync</span>
                                Executing
                              </span>
                            ) : stage.status === 'passed' ? (
                              <span className="text-[#4ADE80] flex items-center justify-end gap-1">
                                <span className="material-symbols-outlined text-[14px]">done_all</span>
                                Passed
                              </span>
                            ) : (
                              <span className="text-white/40">Idle</span>
                            )}
                          </div>

                          {/* Stage Actions */}
                          <div className="flex items-center gap-1">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteStage(stage.id);
                              }}
                              className="p-1.5 text-white/30 hover:text-red-400 hover:bg-white/5 rounded-lg transition-colors cursor-pointer"
                              title="Delete stage"
                            >
                              <span className="material-symbols-outlined text-[16px]">close</span>
                            </button>
                          </div>
                        </div>
                      </div>

                      {/* Active Execution Progress Bar */}
                      {isCurrentActive && (
                        <div className="w-full bg-white/5 h-1 rounded-b-2xl overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-[#C9A86A] to-[#4ADE80] transition-all duration-300"
                            style={{ width: `${executionProgress}%` }}
                          ></div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Selected Stage Detail Inspector */}
          {selectedStage && (
            <div className="bg-[#111111] border border-white/10 rounded-3xl p-6 shadow-xl space-y-5">
              <div className="flex items-center justify-between pb-3 border-b border-white/10">
                <div className="flex items-center gap-2.5">
                  <span className="material-symbols-outlined text-[20px] text-[#C9A86A]">tune</span>
                  <h3 className="text-sm font-medium text-white">
                    Stage Config Inspector: <span className="text-[#C9A86A] font-light">{selectedStage.title}</span>
                  </h3>
                </div>
                <div className="font-code-sm text-xs text-white/40">
                  ID: <span className="text-white">{selectedStage.id}</span>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Title */}
                <div>
                  <label className="block text-[11px] font-code-sm text-white/50 uppercase tracking-wider mb-1.5">
                    Stage Title
                  </label>
                  <input
                    type="text"
                    value={selectedStage.title}
                    onChange={(e) => handleUpdateStageProp('title', e.target.value)}
                    className="w-full bg-[#161616] border border-white/10 rounded-xl px-3.5 py-2 text-xs font-code-sm text-white focus:outline-none focus:border-[#C9A86A]"
                  />
                </div>

                {/* Stage Role */}
                <div>
                  <label className="block text-[11px] font-code-sm text-white/50 uppercase tracking-wider mb-1.5">
                    Stage Role Category
                  </label>
                  <select
                    value={selectedStage.stageType}
                    onChange={(e) => handleUpdateStageProp('stageType', e.target.value as AgentRoleType)}
                    className="w-full bg-[#161616] border border-white/10 rounded-xl px-3.5 py-2 text-xs font-code-sm text-white focus:outline-none focus:border-[#C9A86A] cursor-pointer"
                  >
                    <option value="planning">Planning (Architecture & Spec)</option>
                    <option value="building">Building (Code Implementation)</option>
                    <option value="reviewing">Reviewing (Security & AST Review)</option>
                    <option value="qa">QA (Testing & Regressions)</option>
                    <option value="deployment">Deployment (Container Release)</option>
                  </select>
                </div>

                {/* Output Artifact */}
                <div>
                  <label className="block text-[11px] font-code-sm text-white/50 uppercase tracking-wider mb-1.5">
                    Generated Output Artifact Name
                  </label>
                  <input
                    type="text"
                    value={selectedStage.outputArtifactName || ''}
                    onChange={(e) => handleUpdateStageProp('outputArtifactName', e.target.value)}
                    placeholder="e.g. bundle.ts or spec.md"
                    className="w-full bg-[#161616] border border-white/10 rounded-xl px-3.5 py-2 text-xs font-code-sm text-white focus:outline-none focus:border-[#C9A86A]"
                  />
                </div>

                {/* Assigned Agent Select */}
                <div>
                  <label className="block text-[11px] font-code-sm text-white/50 uppercase tracking-wider mb-1.5">
                    Assigned Execution Agent
                  </label>
                  <select
                    value={selectedStage.assignedAgentId}
                    onChange={(e) => {
                      const agent = AVAILABLE_AGENTS.find((a) => a.id === e.target.value);
                      if (agent) {
                        handleUpdateStageProp('assignedAgentId', agent.id);
                        handleUpdateStageProp('agentName', agent.name);
                        handleUpdateStageProp('agentModel', agent.model);
                        handleUpdateStageProp('agentColor', agent.color);
                      }
                    }}
                    className="w-full bg-[#161616] border border-white/10 rounded-xl px-3.5 py-2 text-xs font-code-sm text-white focus:outline-none focus:border-[#C9A86A] cursor-pointer"
                  >
                    {AVAILABLE_AGENTS.map((agent) => (
                      <option key={agent.id} value={agent.id}>
                        {agent.name} ({agent.model}) — [{agent.role.toUpperCase()}]
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Description */}
              <div>
                <label className="block text-[11px] font-code-sm text-white/50 uppercase tracking-wider mb-1.5">
                  Stage Goal & Operational Description
                </label>
                <textarea
                  rows={2}
                  value={selectedStage.description}
                  onChange={(e) => handleUpdateStageProp('description', e.target.value)}
                  className="w-full bg-[#161616] border border-white/10 rounded-xl px-3.5 py-2 text-xs font-code-sm text-white focus:outline-none focus:border-[#C9A86A] resize-none"
                />
              </div>

              {/* Toggles */}
              <div className="flex flex-wrap items-center gap-6 pt-2">
                <label className="flex items-center gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedStage.autoHandoff}
                    onChange={(e) => handleUpdateStageProp('autoHandoff', e.target.checked)}
                    className="w-4 h-4 rounded bg-[#161616] border-white/20 text-[#C9A86A] focus:ring-[#C9A86A]"
                  />
                  <span className="text-xs font-code-sm text-white/80">Auto-handoff to next stage on pass</span>
                </label>

                <label className="flex items-center gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedStage.requiredApproval}
                    onChange={(e) => handleUpdateStageProp('requiredApproval', e.target.checked)}
                    className="w-4 h-4 rounded bg-[#161616] border-white/20 text-amber-500 focus:ring-amber-500"
                  />
                  <span className="text-xs font-code-sm text-white/80">Require Human Operator Gate Approval</span>
                </label>
              </div>
            </div>
          )}

          {/* Real-Time Workflow Event Log Stream */}
          <div className="bg-[#0e0e0e] border border-white/10 rounded-3xl p-5 shadow-lg space-y-3 font-code-sm text-xs">
            <div className="flex items-center justify-between border-b border-white/5 pb-2 text-white/40 uppercase tracking-wider text-[10px]">
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-[#4ADE80] animate-ping"></span>
                Live Workflow Execution Stream
              </span>
              <span>Sub-millisecond Orchestration</span>
            </div>

            <div className="space-y-1.5 max-h-36 overflow-y-auto pr-2">
              {simulatedLogs.length === 0 ? (
                <div className="text-white/30 italic py-2">
                  No active workflow runs. Click "Execute Workflow" to start automated stage execution.
                </div>
              ) : (
                simulatedLogs.map((entry, idx) => (
                  <div key={idx} className="text-white/80 flex items-start gap-2">
                    <span className="text-[#C9A86A]">&gt;</span>
                    <span>{entry}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Draggable Agent Pool Deck */}
        {isAgentDrawerOpen && (
          <div className="xl:col-span-4 space-y-6">
            <div className="bg-[#111111] border border-white/10 rounded-3xl p-6 shadow-xl space-y-5">
              <div className="flex items-center justify-between pb-3 border-b border-white/10">
                <div className="flex items-center gap-2.5">
                  <span className="material-symbols-outlined text-[20px] text-[#C9A86A]">smart_toy</span>
                  <div>
                    <h3 className="text-sm font-medium text-white">Agent Pool</h3>
                    <p className="text-[10px] font-code-sm text-white/40">Drag agent card onto any workflow stage</p>
                  </div>
                </div>
                <span className="px-2.5 py-0.5 rounded-full bg-white/5 text-[10px] font-code-sm text-white/60">
                  {filteredAgents.length} Ready
                </span>
              </div>

              {/* Search & Filter */}
              <div className="space-y-2">
                <input
                  type="text"
                  placeholder="Filter agents by model/prompt..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full bg-[#161616] border border-white/10 rounded-full px-3.5 py-1.5 text-xs font-code-sm text-white focus:outline-none focus:border-[#C9A86A] placeholder:text-white/30"
                />

                <div className="flex items-center gap-1 overflow-x-auto pb-1">
                  {['ALL', 'planning', 'building', 'reviewing', 'qa', 'deployment'].map((roleKey) => (
                    <button
                      key={roleKey}
                      onClick={() => setFilterRole(roleKey)}
                      className={`px-2.5 py-1 rounded-full text-[10px] font-code-sm uppercase tracking-wider whitespace-nowrap transition-colors cursor-pointer ${
                        filterRole === roleKey
                          ? 'bg-[#C9A86A] text-black font-semibold'
                          : 'bg-white/5 text-white/50 hover:text-white'
                      }`}
                    >
                      {roleKey}
                    </button>
                  ))}
                </div>
              </div>

              {/* Draggable Agent Cards */}
              <div className="space-y-3 max-h-[640px] overflow-y-auto pr-1">
                {filteredAgents.map((agent) => {
                  const roleMeta = ROLE_META[agent.role];
                  return (
                    <div
                      key={agent.id}
                      draggable
                      onDragStart={(e) => handleAgentDragStart(e, agent)}
                      className="p-4 bg-[#161616] border border-white/5 rounded-2xl hover:border-white/20 transition-all cursor-grab active:cursor-grabbing hover:bg-white/[0.03] group relative shadow-md"
                    >
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <div className="flex items-center gap-2.5">
                          <div
                            className="w-8 h-8 rounded-xl flex items-center justify-center font-bold text-xs shadow-sm"
                            style={{ backgroundColor: `${agent.color}22`, color: agent.color, border: `1px solid ${agent.color}44` }}
                          >
                            <span className="material-symbols-outlined text-[18px]">{agent.avatarIcon}</span>
                          </div>
                          <div>
                            <h4 className="font-medium text-white text-xs group-hover:text-[#C9A86A] transition-colors">
                              {agent.name}
                            </h4>
                            <div className="text-[10px] font-code-sm text-white/40">{agent.model}</div>
                          </div>
                        </div>

                        <div
                          className={`px-2 py-0.5 rounded-full text-[9px] font-code-sm uppercase font-semibold border ${roleMeta.bg} ${roleMeta.border}`}
                          style={{ color: roleMeta.color }}
                        >
                          {roleMeta.label}
                        </div>
                      </div>

                      <p className="text-[11px] font-code-sm text-white/60 line-clamp-2 leading-relaxed mb-3">
                        {agent.systemPrompt}
                      </p>

                      {/* Agent performance metric chips */}
                      {agent.metrics && (
                        <div className="grid grid-cols-3 gap-1.5 pt-2 border-t border-white/5 text-[9px] font-code-sm text-center">
                          <div className="bg-[#111111] p-1 rounded-lg">
                            <span className="text-white/40 block">LATENCY</span>
                            <span className="text-white font-medium">{agent.metrics.avgLatency}</span>
                          </div>
                          <div className="bg-[#111111] p-1 rounded-lg">
                            <span className="text-white/40 block">BURN</span>
                            <span className="text-[#C9A86A] font-medium">{agent.metrics.tokenBurn}</span>
                          </div>
                          <div className="bg-[#111111] p-1 rounded-lg">
                            <span className="text-white/40 block">SUCCESS</span>
                            <span className="text-[#4ADE80] font-medium">{agent.metrics.successRate}</span>
                          </div>
                        </div>
                      )}

                      {/* Drag hint overlay */}
                      <div className="absolute right-3 top-3 opacity-0 group-hover:opacity-100 transition-opacity">
                        <span className="material-symbols-outlined text-[16px] text-white/40">drag_pan</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
