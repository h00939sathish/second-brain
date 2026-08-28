import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { GraphNode } from '../types';
import { useTrackComponentRender } from '../hooks/usePerformanceProfiler';

interface KnowledgeGraphViewProps {
  nodes: GraphNode[];
  onSelectNode?: (node: GraphNode) => void;
  onUpdateNodes?: (nodes: GraphNode[]) => void;
}

export const KnowledgeGraphView: React.FC<KnowledgeGraphViewProps> = ({
  nodes: initialNodes,
  onSelectNode,
  onUpdateNodes,
}) => {
  useTrackComponentRender('KnowledgeGraphView');

  // Internal Nodes state (allows interactive dragging, repositioning, and adding nodes)
  const [nodesList, setNodesList] = useState<GraphNode[]>(initialNodes);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Canvas Pan & Zoom state
  const [zoomLevel, setZoomLevel] = useState<number>(1);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 30, y: 20 });
  const [isPanning, setIsPanning] = useState<boolean>(false);
  const [panStart, setPanStart] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  // Node Dragging state
  const [draggedNodeId, setDraggedNodeId] = useState<string | null>(null);
  const [dragStartPos, setDragStartPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [nodeInitialPos, setNodeInitialPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  // Modal for adding a new Truth Claim / Spec node
  const [isAddNodeOpen, setIsAddNodeOpen] = useState(false);
  const [newNodeTitle, setNewNodeTitle] = useState('');
  const [newNodeType, setNewNodeType] = useState<'spec' | 'task' | 'claim'>('claim');
  const [newNodeProject, setNewNodeProject] = useState('Project TITAN');
  const [newNodeSource, setNewNodeSource] = useState('ADR / Pytest');
  const [newNodeConfidence, setNewNodeConfidence] = useState('99.0%');
  const [newNodeConnections, setNewNodeConnections] = useState<string[]>([]);
  const [copySuccess, setCopySuccess] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);

  // Synchronize internal state when prop changes, ensuring selectedNodeId is valid
  useEffect(() => {
    if (initialNodes && initialNodes.length > 0) {
      setNodesList((prev) => {
        // preserve current dragged x/y if IDs match
        const posMap = new Map<string, { x: number; y: number }>(
          prev.map((n) => [n.id, { x: n.x, y: n.y }])
        );
        return initialNodes.map((n) => ({
          ...n,
          x: posMap.get(n.id)?.x ?? n.x,
          y: posMap.get(n.id)?.y ?? n.y,
        }));
      });
    }
  }, [initialNodes]);

  // Ensure an active valid node is always selected on startup
  useEffect(() => {
    if (nodesList.length > 0) {
      if (!selectedNodeId || !nodesList.some((n) => n.id === selectedNodeId)) {
        setSelectedNodeId(nodesList[0].id);
      }
    }
  }, [nodesList, selectedNodeId]);

  const selectedNode = useMemo(
    () => nodesList.find((n) => n.id === selectedNodeId),
    [nodesList, selectedNodeId]
  );

  // Incoming connections lookup
  const incomingConnections = useMemo(() => {
    if (!selectedNodeId) return [];
    return nodesList.filter((n) => n.connections && n.connections.includes(selectedNodeId));
  }, [nodesList, selectedNodeId]);

  // Filtered nodes
  const filteredNodes = useMemo(() => {
    return nodesList.filter((n) => {
      const matchesType = filterType === 'ALL' || n.type === filterType.toLowerCase();
      const matchesSearch =
        !searchQuery.trim() ||
        n.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
        n.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (n.meta &&
          Object.values(n.meta).some((val) =>
            String(val).toLowerCase().includes(searchQuery.toLowerCase())
          ));
      return matchesType && matchesSearch;
    });
  }, [nodesList, filterType, searchQuery]);

  // Related node IDs for active highlighting
  const activeConnectedIds = useMemo(() => {
    const activeId = hoveredNodeId || selectedNodeId;
    if (!activeId) return new Set<string>();
    const node = nodesList.find((n) => n.id === activeId);
    const set = new Set<string>();
    set.add(activeId);
    if (node && node.connections) {
      node.connections.forEach((c) => set.add(c));
    }
    // Add nodes that connect TO this node
    nodesList.forEach((n) => {
      if (n.connections && n.connections.includes(activeId)) {
        set.add(n.id);
      }
    });
    return set;
  }, [nodesList, hoveredNodeId, selectedNodeId]);

  // Auto-arrange in clean topological tiers
  const handleAutoArrange = useCallback(() => {
    const specs = nodesList.filter((n) => n.type === 'spec');
    const tasks = nodesList.filter((n) => n.type === 'task');
    const claims = nodesList.filter((n) => n.type === 'claim');

    const totalWidth = 920;
    const startX = 140;

    const arrangeRow = (items: GraphNode[], y: number) => {
      const step = items.length > 1 ? (totalWidth - startX) / (items.length - 1) : 0;
      return items.map((item, idx) => ({
        ...item,
        x: items.length === 1 ? totalWidth / 2 : startX + idx * step,
        y,
      }));
    };

    const updated = [
      ...arrangeRow(specs, 120),
      ...arrangeRow(tasks, 280),
      ...arrangeRow(claims, 440),
    ];

    setNodesList(updated);
    onUpdateNodes?.(updated);
    setPan({ x: 30, y: 20 });
    setZoomLevel(1);
  }, [nodesList, onUpdateNodes]);

  // Center & focus on a specific node
  const handleFocusNode = useCallback((node: GraphNode) => {
    setSelectedNodeId(node.id);
    onSelectNode?.(node);
    if (containerRef.current) {
      const containerWidth = containerRef.current.clientWidth || 700;
      const containerHeight = containerRef.current.clientHeight || 500;
      setPan({
        x: containerWidth / 2 - node.x * zoomLevel,
        y: containerHeight / 2 - node.y * zoomLevel,
      });
    }
  }, [zoomLevel, onSelectNode]);

  // Canvas Mouse / Touch Handlers for Pan
  const handleMouseDownCanvas = (e: React.MouseEvent) => {
    if (draggedNodeId) return;
    setIsPanning(true);
    setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  };

  const handleMouseMoveCanvas = (e: React.MouseEvent) => {
    if (draggedNodeId) {
      const deltaX = (e.clientX - dragStartPos.x) / zoomLevel;
      const deltaY = (e.clientY - dragStartPos.y) / zoomLevel;
      const newX = Math.round(nodeInitialPos.x + deltaX);
      const newY = Math.round(nodeInitialPos.y + deltaY);

      setNodesList((prev) =>
        prev.map((n) => (n.id === draggedNodeId ? { ...n, x: newX, y: newY } : n))
      );
      return;
    }

    if (isPanning) {
      setPan({
        x: e.clientX - panStart.x,
        y: e.clientY - panStart.y,
      });
    }
  };

  const handleMouseUpCanvas = () => {
    if (draggedNodeId) {
      setDraggedNodeId(null);
      onUpdateNodes?.(nodesList);
    }
    setIsPanning(false);
  };

  // Node Drag Initiator
  const handleNodeMouseDown = (e: React.MouseEvent, node: GraphNode) => {
    e.stopPropagation();
    setSelectedNodeId(node.id);
    onSelectNode?.(node);
    setDraggedNodeId(node.id);
    setDragStartPos({ x: e.clientX, y: e.clientY });
    setNodeInitialPos({ x: node.x, y: node.y });
  };

  // Wheel Zoom
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
    setZoomLevel((prev) => Math.min(Math.max(prev * zoomFactor, 0.45), 2.2));
  };

  // Fit all nodes into screen view
  const handleFitView = () => {
    if (nodesList.length === 0) return;
    const minX = Math.min(...nodesList.map((n) => n.x));
    const maxX = Math.max(...nodesList.map((n) => n.x));
    const minY = Math.min(...nodesList.map((n) => n.y));
    const maxY = Math.max(...nodesList.map((n) => n.y));

    const width = maxX - minX + 240;
    const height = maxY - minY + 240;

    const containerWidth = containerRef.current?.clientWidth || 800;
    const containerHeight = containerRef.current?.clientHeight || 550;

    const scaleX = containerWidth / width;
    const scaleY = containerHeight / height;
    const newScale = Math.min(Math.max(Math.min(scaleX, scaleY) * 0.9, 0.5), 1.4);

    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;

    setZoomLevel(newScale);
    setPan({
      x: containerWidth / 2 - centerX * newScale,
      y: containerHeight / 2 - centerY * newScale,
    });
  };

  // Add new Truth Claim / Node handler
  const handleCreateNode = () => {
    if (!newNodeTitle.trim()) return;

    const newId = `${newNodeType === 'spec' ? 'spec' : newNodeType === 'task' ? 't' : 'c'}-${Date.now().toString(36)}`;
    const yPos = newNodeType === 'spec' ? 120 : newNodeType === 'task' ? 280 : 440;
    const xPos = 200 + (nodesList.length % 5) * 140;

    const createdNode: GraphNode = {
      id: newId,
      label: newNodeTitle.trim(),
      type: newNodeType,
      x: xPos,
      y: yPos,
      status: newNodeType === 'claim' ? 'complete' : 'in_progress',
      connections: newNodeConnections,
      meta: {
        project: newNodeProject,
        source: newNodeSource,
        confidence: newNodeConfidence,
        status: newNodeType === 'claim' ? 'Verified' : 'Active',
      },
    };

    const updated = [...nodesList, createdNode];
    setNodesList(updated);
    setSelectedNodeId(newId);
    onUpdateNodes?.(updated);
    setIsAddNodeOpen(false);
    setNewNodeTitle('');
    setNewNodeConnections([]);
  };

  const copyNodeId = (id: string) => {
    navigator.clipboard?.writeText(id);
    setCopySuccess(true);
    setTimeout(() => setCopySuccess(false), 2000);
  };

  // Stats Calculations
  const stats = useMemo(() => {
    const total = nodesList.length;
    const specs = nodesList.filter((n) => n.type === 'spec').length;
    const tasks = nodesList.filter((n) => n.type === 'task').length;
    const claims = nodesList.filter((n) => n.type === 'claim').length;
    const totalConnections = nodesList.reduce((acc, n) => acc + (n.connections?.length || 0), 0);
    const verifiedClaims = nodesList.filter((n) => n.type === 'claim' && n.status === 'complete').length;
    const coverage = claims > 0 ? Math.round((verifiedClaims / claims) * 100) : 100;
    return { total, specs, tasks, claims, totalConnections, coverage };
  }, [nodesList]);

  return (
    <div className="space-y-6 pb-12 select-none">
      {/* Top Banner & Stats Overview Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl md:text-3xl font-light tracking-tight text-white">
              Knowledge Graph & Truth Mapping
            </h1>
            <span className="px-2.5 py-0.5 rounded-full bg-[#C9A86A]/20 text-[#C9A86A] text-[10px] uppercase font-bold tracking-widest border border-[#C9A86A]/30">
              Interactive Topology
            </span>
          </div>
          <p className="font-code-sm text-xs text-white/40 mt-1">
            Explore topological relationships between system specifications, autonomous agent tasks, and verifiable truth claims. Drag nodes or canvas freely.
          </p>
        </div>

        {/* Global Action Controls */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setIsAddNodeOpen(true)}
            className="px-3.5 py-1.5 bg-[#C9A86A] hover:bg-[#dfc188] text-black font-semibold rounded-full text-xs uppercase tracking-wider flex items-center gap-1.5 shadow-[0_0_15px_rgba(201,168,106,0.25)] cursor-pointer transition-all active:scale-95"
          >
            <span className="material-symbols-outlined text-[16px]">add_circle</span>
            Add Truth Claim / Spec
          </button>

          <button
            onClick={handleAutoArrange}
            className="px-3 py-1.5 bg-[#161616] hover:bg-white/10 text-white/80 hover:text-white border border-white/10 rounded-full text-xs font-code-sm flex items-center gap-1.5 cursor-pointer transition-all"
            title="Auto-arrange graph in tiered hierarchy"
          >
            <span className="material-symbols-outlined text-[15px] text-[#C9A86A]">account_tree</span>
            Auto-Arrange
          </button>

          <button
            onClick={handleFitView}
            className="px-3 py-1.5 bg-[#161616] hover:bg-white/10 text-white/80 hover:text-white border border-white/10 rounded-full text-xs font-code-sm flex items-center gap-1.5 cursor-pointer transition-all"
            title="Fit graph to canvas"
          >
            <span className="material-symbols-outlined text-[15px] text-[#06b6d4]">center_focus_strong</span>
            Fit View
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3.5 bg-[#111111] border border-white/10 rounded-3xl font-code-sm text-xs">
        <div className="flex items-center gap-3 px-3 py-1.5 border-r border-white/10">
          <div className="w-8 h-8 rounded-full bg-[#C9A86A]/10 border border-[#C9A86A]/30 flex items-center justify-center text-[#C9A86A]">
            <span className="material-symbols-outlined text-[18px]">hub</span>
          </div>
          <div>
            <div className="text-[10px] text-white/40 uppercase tracking-widest">Total Nodes</div>
            <div className="text-white font-medium text-sm flex items-center gap-1.5">
              {stats.total}
              <span className="text-[10px] text-[#C9A86A]">({stats.totalConnections} edges)</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3 px-3 py-1.5 border-r border-white/10">
          <div className="w-8 h-8 rounded-full bg-white/10 border border-white/20 flex items-center justify-center text-white">
            <span className="material-symbols-outlined text-[18px]">description</span>
          </div>
          <div>
            <div className="text-[10px] text-white/40 uppercase tracking-widest">Specs & Tasks</div>
            <div className="text-white font-medium text-sm">
              {stats.specs} Specs • {stats.tasks} Tasks
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3 px-3 py-1.5 border-r border-white/10">
          <div className="w-8 h-8 rounded-full bg-[#4ADE80]/10 border border-[#4ADE80]/30 flex items-center justify-center text-[#4ADE80]">
            <span className="material-symbols-outlined text-[18px]">verified</span>
          </div>
          <div>
            <div className="text-[10px] text-white/40 uppercase tracking-widest">Truth Claims</div>
            <div className="text-[#4ADE80] font-medium text-sm">
              {stats.claims} Claims ({stats.coverage}% Verified)
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3 px-3 py-1.5">
          <div className="w-8 h-8 rounded-full bg-[#06b6d4]/10 border border-[#06b6d4]/30 flex items-center justify-center text-[#06b6d4]">
            <span className="material-symbols-outlined text-[18px]">alt_route</span>
          </div>
          <div>
            <div className="text-[10px] text-white/40 uppercase tracking-widest">Topology Phase</div>
            <div className="text-[#06b6d4] font-medium text-sm">Phase 2 (Active)</div>
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 bg-[#111111] p-2.5 rounded-3xl border border-white/10">
        {/* Category Filters */}
        <div className="flex flex-wrap items-center gap-1.5 font-code-sm text-xs">
          <button
            onClick={() => setFilterType('ALL')}
            className={`px-3 py-1 rounded-full transition-all cursor-pointer ${
              filterType === 'ALL'
                ? 'bg-[#C9A86A] text-black font-semibold shadow-[0_0_8px_rgba(201,168,106,0.3)]'
                : 'text-white/40 hover:text-white hover:bg-white/5'
            }`}
          >
            All ({nodesList.length})
          </button>
          <button
            onClick={() => setFilterType('spec')}
            className={`px-3 py-1 rounded-full flex items-center gap-1.5 transition-all cursor-pointer ${
              filterType === 'spec'
                ? 'bg-[#C9A86A] text-black font-semibold shadow-[0_0_8px_rgba(201,168,106,0.3)]'
                : 'text-white/40 hover:text-white hover:bg-white/5'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-[#C9A86A]"></span>
            Specs ({stats.specs})
          </button>
          <button
            onClick={() => setFilterType('task')}
            className={`px-3 py-1 rounded-full flex items-center gap-1.5 transition-all cursor-pointer ${
              filterType === 'task'
                ? 'bg-white text-black font-semibold shadow-[0_0_8px_rgba(255,255,255,0.3)]'
                : 'text-white/40 hover:text-white hover:bg-white/5'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-white"></span>
            Tasks ({stats.tasks})
          </button>
          <button
            onClick={() => setFilterType('claim')}
            className={`px-3 py-1 rounded-full flex items-center gap-1.5 transition-all cursor-pointer ${
              filterType === 'claim'
                ? 'bg-[#4ADE80] text-black font-semibold shadow-[0_0_8px_rgba(74,222,128,0.3)]'
                : 'text-white/40 hover:text-white hover:bg-white/5'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-[#4ADE80]"></span>
            Truth Claims ({stats.claims})
          </button>
        </div>

        {/* Live Search Input */}
        <div className="relative flex items-center min-w-[220px]">
          <span className="material-symbols-outlined text-white/40 text-[16px] absolute left-3 pointer-events-none">
            search
          </span>
          <input
            type="text"
            placeholder="Search nodes, specs, claims..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-[#181818] border border-white/10 focus:border-[#C9A86A]/60 rounded-full pl-9 pr-8 py-1.5 text-xs font-code-sm text-white focus:outline-none placeholder:text-white/30 transition-colors"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-2.5 text-white/40 hover:text-white cursor-pointer"
            >
              <span className="material-symbols-outlined text-[14px]">close</span>
            </button>
          )}
        </div>
      </div>

      {/* Main Grid: 2/3 Interactive Graph Canvas, 1/3 Node Inspector & Truth Verification */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Graph Canvas Container (Spans 2 cols on xl) */}
        <div
          ref={containerRef}
          onMouseDown={handleMouseDownCanvas}
          onMouseMove={handleMouseMoveCanvas}
          onMouseUp={handleMouseUpCanvas}
          onMouseLeave={handleMouseUpCanvas}
          onWheel={handleWheel}
          className={`xl:col-span-2 bg-[#080808] border border-white/10 rounded-3xl relative min-h-[580px] h-[600px] flex flex-col overflow-hidden select-none transition-colors ${
            isPanning ? 'cursor-grabbing' : 'cursor-grab'
          }`}
          style={{
            backgroundImage: `radial-gradient(circle at 1px 1px, rgba(255, 255, 255, 0.08) 1px, transparent 0)`,
            backgroundSize: '24px 24px',
          }}
        >
          {/* Canvas Floating Top Info */}
          <div className="absolute top-4 left-4 z-20 flex items-center gap-2 bg-[#111111]/90 backdrop-blur-md border border-white/10 rounded-full px-3.5 py-1.5 text-xs font-code-sm shadow-lg pointer-events-none">
            <span className="w-2 h-2 rounded-full bg-[#C9A86A] animate-pulse"></span>
            <span className="text-[#C9A86A] font-medium">Topology:</span>
            <span className="text-white/80">
              {filteredNodes.length}/{nodesList.length} Nodes
            </span>
            {searchQuery && (
              <span className="text-[10px] text-[#4ADE80] border-l border-white/10 pl-2">
                Filter: "{searchQuery}"
              </span>
            )}
          </div>

          {/* Canvas Floating Controls (Zoom / Center / Reset) */}
          <div className="absolute top-4 right-4 z-20 flex items-center gap-1 bg-[#111111]/90 backdrop-blur-md border border-white/10 rounded-full p-1 shadow-lg">
            <button
              onClick={(e) => {
                e.stopPropagation();
                setZoomLevel((z) => Math.min(z + 0.15, 2.2));
              }}
              className="p-1.5 text-white/60 hover:text-white hover:bg-white/10 rounded-full cursor-pointer transition-colors"
              title="Zoom In"
            >
              <span className="material-symbols-outlined text-[16px]">add</span>
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setZoomLevel(1);
                setPan({ x: 30, y: 20 });
              }}
              className="px-2 text-xs font-code-sm text-white/60 hover:text-white cursor-pointer font-medium"
              title="Reset Zoom to 100%"
            >
              {Math.round(zoomLevel * 100)}%
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setZoomLevel((z) => Math.max(z - 0.15, 0.45));
              }}
              className="p-1.5 text-white/60 hover:text-white hover:bg-white/10 rounded-full cursor-pointer transition-colors"
              title="Zoom Out"
            >
              <span className="material-symbols-outlined text-[16px]">remove</span>
            </button>
            <div className="h-4 w-px bg-white/10 mx-0.5" />
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleFitView();
              }}
              className="p-1.5 text-[#C9A86A] hover:bg-[#C9A86A]/20 rounded-full cursor-pointer transition-colors"
              title="Fit Graph"
            >
              <span className="material-symbols-outlined text-[16px]">fit_screen</span>
            </button>
          </div>

          {/* Interactive SVG Canvas */}
          <svg className="w-full h-full absolute inset-0 overflow-visible pointer-events-auto">
            <defs>
              {/* Directed Arrowhead Markers */}
              <marker
                id="arrow-gold"
                viewBox="0 0 10 10"
                refX="26"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 1 L 10 5 L 0 9 z" fill="#C9A86A" />
              </marker>
              <marker
                id="arrow-cyan"
                viewBox="0 0 10 10"
                refX="26"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 1 L 10 5 L 0 9 z" fill="#06b6d4" />
              </marker>
              <marker
                id="arrow-emerald"
                viewBox="0 0 10 10"
                refX="26"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 1 L 10 5 L 0 9 z" fill="#4ADE80" />
              </marker>
              <marker
                id="arrow-muted"
                viewBox="0 0 10 10"
                refX="26"
                refY="5"
                markerWidth="5"
                markerHeight="5"
                orient="auto-start-reverse"
              >
                <path d="M 0 1 L 10 5 L 0 9 z" fill="rgba(255,255,255,0.25)" />
              </marker>

              {/* Glowing Filter */}
              <filter id="glow-selected" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            {/* Transform Group for Pan and Zoom */}
            <g
              transform={`translate(${pan.x}, ${pan.y}) scale(${zoomLevel})`}
              className="transition-transform duration-75"
            >
              {/* 1. Render Connection Lines */}
              {nodesList.map((sourceNode) => {
                if (!sourceNode.connections || sourceNode.connections.length === 0) return null;

                return sourceNode.connections.map((targetId) => {
                  const targetNode = nodesList.find((n) => n.id === targetId);
                  if (!targetNode) return null;

                  const isSourceSelected = selectedNodeId === sourceNode.id;
                  const isTargetSelected = selectedNodeId === targetNode.id;
                  const isHighlighted = isSourceSelected || isTargetSelected;
                  const isConnectedInHover =
                    hoveredNodeId === sourceNode.id || hoveredNodeId === targetNode.id;

                  // Dynamic Curvature between nodes
                  const deltaX = targetNode.x - sourceNode.x;
                  const deltaY = targetNode.y - sourceNode.y;
                  const midX = (sourceNode.x + targetNode.x) / 2;
                  const controlY =
                    Math.abs(deltaY) > 40
                      ? (sourceNode.y + targetNode.y) / 2
                      : sourceNode.y - deltaX * 0.15;

                  const pathData = `M ${sourceNode.x} ${sourceNode.y} Q ${midX} ${controlY} ${targetNode.x} ${targetNode.y}`;

                  let strokeColor = 'rgba(255, 255, 255, 0.12)';
                  let strokeWidth = 1.5;
                  let markerUrl = 'url(#arrow-muted)';

                  if (isHighlighted || isConnectedInHover) {
                    strokeColor = isSourceSelected ? '#C9A86A' : '#06b6d4';
                    strokeWidth = 2.5;
                    markerUrl = isSourceSelected ? 'url(#arrow-gold)' : 'url(#arrow-cyan)';
                  }

                  return (
                    <g key={`edge-${sourceNode.id}-${targetId}`}>
                      {/* Ambient background glow line when selected */}
                      {isHighlighted && (
                        <path
                          d={pathData}
                          fill="none"
                          stroke={strokeColor}
                          strokeWidth={6}
                          strokeOpacity={0.25}
                          className="animate-pulse"
                        />
                      )}

                      <path
                        d={pathData}
                        fill="none"
                        stroke={strokeColor}
                        strokeWidth={strokeWidth}
                        strokeDasharray={
                          sourceNode.type === 'claim' || targetNode.type === 'claim'
                            ? '5 4'
                            : undefined
                        }
                        markerEnd={markerUrl}
                        className="transition-colors duration-200"
                      />
                    </g>
                  );
                });
              })}

              {/* 2. Render Node Elements */}
              {filteredNodes.map((node) => {
                const isSelected = selectedNodeId === node.id;
                const isHovered = hoveredNodeId === node.id;
                const isConnected = activeConnectedIds.has(node.id);
                const isBeingDragged = draggedNodeId === node.id;

                const nodeColor =
                  node.type === 'spec'
                    ? '#C9A86A'
                    : node.type === 'task'
                    ? '#FFFFFF'
                    : '#4ADE80';

                const iconName =
                  node.type === 'spec'
                    ? 'description'
                    : node.type === 'task'
                    ? 'task_alt'
                    : 'verified_user';

                return (
                  <g
                    key={node.id}
                    transform={`translate(${node.x}, ${node.y})`}
                    className={`cursor-pointer transition-transform ${
                      isBeingDragged ? 'scale-110' : ''
                    }`}
                    onMouseDown={(e) => handleNodeMouseDown(e, node)}
                    onMouseEnter={() => setHoveredNodeId(node.id)}
                    onMouseLeave={() => setHoveredNodeId(null)}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedNodeId(node.id);
                      onSelectNode?.(node);
                    }}
                  >
                    {/* Active Selected Pulse Beacon */}
                    {isSelected && (
                      <>
                        <circle
                          r={32}
                          fill="none"
                          stroke={nodeColor}
                          strokeWidth="2"
                          strokeDasharray="4 4"
                          className="animate-spin opacity-40"
                          style={{ animationDuration: '8s' }}
                        />
                        <circle
                          r={26}
                          fill={nodeColor}
                          fillOpacity={0.15}
                          className="animate-pulse"
                        />
                      </>
                    )}

                    {/* Connected highlight ring */}
                    {!isSelected && isConnected && (
                      <circle
                        r={24}
                        fill="none"
                        stroke={nodeColor}
                        strokeWidth="1.5"
                        strokeOpacity={0.5}
                      />
                    )}

                    {/* Outer Circle Container */}
                    <circle
                      r={18}
                      fill="#121212"
                      stroke={nodeColor}
                      strokeWidth={isSelected ? 3 : isHovered ? 2.5 : 1.5}
                      className="transition-all duration-200 shadow-md"
                    />

                    {/* Inner Core Icon Marker */}
                    <circle
                      r={10}
                      fill={nodeColor}
                      fillOpacity={isSelected ? 1 : 0.8}
                    />

                    {/* Category Glyph */}
                    <text
                      textAnchor="middle"
                      dominantBaseline="central"
                      className="fill-black font-bold text-[10px] select-none pointer-events-none"
                    >
                      {node.type === 'spec' ? 'S' : node.type === 'task' ? 'T' : 'C'}
                    </text>

                    {/* Node Label Card Background Pill */}
                    <g transform="translate(0, 30)">
                      <rect
                        x={-Math.min(node.label.length * 4.2 + 16, 110)}
                        y={-2}
                        width={Math.min(node.label.length * 8.4 + 32, 220)}
                        height={24}
                        rx={12}
                        fill="#141414"
                        stroke={isSelected ? nodeColor : 'rgba(255,255,255,0.15)'}
                        strokeWidth={isSelected ? 1.5 : 1}
                        className="transition-colors shadow-lg"
                      />

                      <text
                        x={0}
                        y={14}
                        textAnchor="middle"
                        className={`font-code-sm text-[10px] select-none pointer-events-none ${
                          isSelected ? 'fill-white font-semibold' : 'fill-white/85'
                        }`}
                      >
                        {node.label.length > 28 ? node.label.slice(0, 26) + '...' : node.label}
                      </text>
                    </g>

                    {/* Status Sub-badge */}
                    <g transform="translate(0, 56)">
                      <text
                        textAnchor="middle"
                        className="font-code-sm text-[9px] fill-white/40 uppercase tracking-wider select-none pointer-events-none"
                      >
                        {node.type} • {node.status.replace('_', ' ')}
                      </text>
                    </g>
                  </g>
                );
              })}
            </g>
          </svg>

          {/* Bottom Canvas Helper Hint */}
          <div className="absolute bottom-4 left-4 z-20 flex items-center gap-3 bg-[#111111]/80 backdrop-blur border border-white/10 px-3.5 py-1.5 rounded-full text-[10px] font-code-sm text-white/50 pointer-events-none">
            <span className="flex items-center gap-1">
              <span className="material-symbols-outlined text-[14px] text-[#C9A86A]">drag_pan</span>
              Drag canvas to pan
            </span>
            <span>•</span>
            <span className="flex items-center gap-1">
              <span className="material-symbols-outlined text-[14px] text-[#4ADE80]">touch_app</span>
              Drag nodes to reposition
            </span>
            <span>•</span>
            <span>Scroll to zoom</span>
          </div>
        </div>

        {/* Right Sidebar: Selected Node Details & Phased Truth Roadmap */}
        <div className="space-y-4">
          {/* Selected Node Details Card */}
          {selectedNode ? (
            <div className="bg-[#111111] border border-white/10 rounded-3xl p-5 shadow-xl animate-in fade-in duration-200">
              <div className="flex items-center justify-between pb-3.5 mb-3.5 border-b border-white/10">
                <div className="flex items-center gap-2">
                  <span
                    className={`w-2.5 h-2.5 rounded-full ${
                      selectedNode.type === 'spec'
                        ? 'bg-[#C9A86A] shadow-[0_0_8px_#C9A86A]'
                        : selectedNode.type === 'task'
                        ? 'bg-white shadow-[0_0_8px_#FFFFFF]'
                        : 'bg-[#4ADE80] shadow-[0_0_8px_#4ADE80]'
                    }`}
                  />
                  <span className="text-[11px] text-[#C9A86A] uppercase tracking-[0.2em] font-medium">
                    Node Inspector
                  </span>
                </div>

                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => copyNodeId(selectedNode.id)}
                    className="flex items-center gap-1 font-code-sm text-[10px] px-2 py-0.5 rounded-full bg-white/10 hover:bg-white/20 text-white/80 cursor-pointer transition-colors"
                    title="Copy Node ID"
                  >
                    <span>{selectedNode.id}</span>
                    <span className="material-symbols-outlined text-[12px]">
                      {copySuccess ? 'check' : 'content_copy'}
                    </span>
                  </button>
                </div>
              </div>

              {/* Title & Type Header */}
              <div className="space-y-3 font-code-sm text-xs">
                <div>
                  <div className="text-[10px] text-white/40 uppercase tracking-wider mb-1">
                    Label & Title
                  </div>
                  <div className="text-white font-medium text-sm leading-snug bg-[#161616] p-2.5 rounded-xl border border-white/5">
                    {selectedNode.label}
                  </div>
                </div>

                {/* Metadata Grid */}
                <div className="grid grid-cols-2 gap-2.5 pt-1">
                  <div className="p-2.5 bg-[#161616] rounded-xl border border-white/5">
                    <span className="text-[10px] text-white/40 uppercase block">Category</span>
                    <span className="text-[#C9A86A] font-semibold uppercase text-[11px]">
                      {selectedNode.type}
                    </span>
                  </div>

                  <div className="p-2.5 bg-[#161616] rounded-xl border border-white/5">
                    <span className="text-[10px] text-white/40 uppercase block">Status</span>
                    <span className="text-[#4ADE80] capitalize text-[11px] font-semibold">
                      {selectedNode.status.replace('_', ' ')}
                    </span>
                  </div>

                  {selectedNode.meta?.project && (
                    <div className="p-2.5 bg-[#161616] rounded-xl border border-white/5 col-span-2">
                      <span className="text-[10px] text-white/40 uppercase block">Project Scope</span>
                      <span className="text-white font-medium">{selectedNode.meta.project}</span>
                    </div>
                  )}

                  {selectedNode.meta?.source && (
                    <div className="p-2.5 bg-[#161616] rounded-xl border border-white/5 col-span-2">
                      <span className="text-[10px] text-white/40 uppercase block">Truth Source / Evidence</span>
                      <span className="text-[#4ADE80] font-medium">{selectedNode.meta.source}</span>
                    </div>
                  )}

                  {selectedNode.meta?.confidence && (
                    <div className="p-2.5 bg-[#161616] rounded-xl border border-white/5 col-span-2">
                      <span className="text-[10px] text-white/40 uppercase block">Verification Confidence</span>
                      <span className="text-[#4ADE80] font-semibold">{selectedNode.meta.confidence}</span>
                    </div>
                  )}
                </div>

                {/* Outgoing Connections (Dependencies) */}
                <div className="pt-2">
                  <div className="text-[10px] text-white/40 uppercase tracking-wider mb-1.5 flex items-center justify-between">
                    <span>Dependencies & Outgoing Links ({selectedNode.connections?.length || 0})</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedNode.connections && selectedNode.connections.length > 0 ? (
                      selectedNode.connections.map((targetId) => {
                        const targetNode = nodesList.find((n) => n.id === targetId);
                        return (
                          <button
                            key={targetId}
                            onClick={() => {
                              if (targetNode) handleFocusNode(targetNode);
                              else setSelectedNodeId(targetId);
                            }}
                            className="px-2.5 py-1 bg-[#161616] hover:bg-[#C9A86A]/20 border border-white/10 hover:border-[#C9A86A]/40 text-[#C9A86A] rounded-full text-[11px] flex items-center gap-1.5 cursor-pointer transition-all active:scale-95"
                          >
                            <span className="material-symbols-outlined text-[13px]">arrow_forward</span>
                            <span className="truncate max-w-[150px]">
                              {targetNode?.label || targetId}
                            </span>
                          </button>
                        );
                      })
                    ) : (
                      <div className="text-white/30 text-[11px] italic">No outgoing dependencies</div>
                    )}
                  </div>
                </div>

                {/* Incoming Connections (Referenced By) */}
                <div className="pt-2">
                  <div className="text-[10px] text-white/40 uppercase tracking-wider mb-1.5">
                    Referenced By ({incomingConnections.length})
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {incomingConnections.length > 0 ? (
                      incomingConnections.map((inc) => (
                        <button
                          key={inc.id}
                          onClick={() => handleFocusNode(inc)}
                          className="px-2.5 py-1 bg-[#161616] hover:bg-[#06b6d4]/20 border border-white/10 hover:border-[#06b6d4]/40 text-[#06b6d4] rounded-full text-[11px] flex items-center gap-1.5 cursor-pointer transition-all active:scale-95"
                        >
                          <span className="material-symbols-outlined text-[13px]">arrow_back</span>
                          <span className="truncate max-w-[150px]">{inc.label}</span>
                        </button>
                      ))
                    ) : (
                      <div className="text-white/30 text-[11px] italic">Root node (no incoming links)</div>
                    )}
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="pt-3 flex gap-2">
                  <button
                    onClick={() => handleFocusNode(selectedNode)}
                    className="flex-1 py-2 bg-white/10 hover:bg-white/20 text-white rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 cursor-pointer transition-colors"
                  >
                    <span className="material-symbols-outlined text-[16px] text-[#C9A86A]">center_focus_strong</span>
                    Focus in Graph
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-[#111111] border border-white/10 rounded-3xl p-6 text-center text-xs font-code-sm text-white/40">
              Select any node on the graph canvas to inspect its details and relationships.
            </div>
          )}

          {/* Phased Roadmap & Truth Verification Engine Card */}
          <div className="bg-[#111111] border border-white/10 rounded-3xl p-5 shadow-xl">
            <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/10">
              <span className="text-[10px] text-white/60 uppercase tracking-[0.2em] font-medium flex items-center gap-2">
                <span className="material-symbols-outlined text-[16px] text-[#C9A86A]">alt_route</span>
                Truth Verification Roadmap
              </span>
              <span className="font-code-sm text-xs text-[#4ADE80]">Phase 2 Active</span>
            </div>

            <div className="space-y-3 font-code-sm text-xs">
              {/* Phase 1 */}
              <div className="p-3.5 bg-[#161616] border border-[#4ADE80]/30 rounded-2xl flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-1.5 text-[#4ADE80] font-semibold">
                    <span className="material-symbols-outlined text-[16px]">check_circle</span>
                    Phase 1: Truth Foundation
                  </div>
                  <p className="text-[11px] text-white/40 mt-1">
                    Atomic markdown claims, ADR release gates, SHA-256 verification.
                  </p>
                </div>
                <span className="text-[11px] font-semibold text-[#4ADE80]">100%</span>
              </div>

              {/* Phase 2 */}
              <div className="p-3.5 bg-[#161616] border border-[#C9A86A]/40 rounded-2xl shadow-[0_0_12px_rgba(201,168,106,0.1)]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-[#C9A86A] font-semibold">
                    <span className="material-symbols-outlined text-[16px] animate-spin">sync</span>
                    Phase 2: Topological Graph
                  </div>
                  <span className="text-[11px] font-semibold text-[#C9A86A]">85%</span>
                </div>
                <p className="text-[11px] text-white/60 mt-1">
                  Cross-spec dependency mapping, automated claim linking, daemon state synchronizer.
                </p>
                <div className="w-full bg-white/10 h-1.5 rounded-full overflow-hidden mt-2.5">
                  <div className="bg-[#C9A86A] h-full rounded-full" style={{ width: '85%' }}></div>
                </div>
              </div>

              {/* Phase 3 */}
              <div className="p-3.5 bg-[#161616] border border-white/5 rounded-2xl opacity-60">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-white/40 font-semibold">
                    <span className="material-symbols-outlined text-[16px]">hourglass_empty</span>
                    Phase 3: Autonomous Synthesis
                  </div>
                  <span className="text-[11px] font-semibold text-white/40">0%</span>
                </div>
                <p className="text-[11px] text-white/40 mt-1">
                  Auto-resolving conflicting claims and zero-knowledge verification proofs.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Add Truth Claim / Spec Modal */}
      {isAddNodeOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="w-full max-w-lg bg-[#111111] border border-white/10 rounded-3xl p-6 shadow-2xl space-y-4 animate-in fade-in zoom-in-95 duration-150 font-code-sm">
            <div className="flex items-center justify-between pb-3 border-b border-white/10">
              <div className="flex items-center gap-2 text-white font-medium text-base">
                <span className="material-symbols-outlined text-[#C9A86A]">add_circle</span>
                Add Node to Knowledge Graph
              </div>
              <button
                onClick={() => setIsAddNodeOpen(false)}
                className="text-white/40 hover:text-white cursor-pointer"
              >
                <span className="material-symbols-outlined text-[20px]">close</span>
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="text-white/60 block mb-1">Node Title / Statement</label>
                <input
                  type="text"
                  placeholder="e.g. ADR-033 Multi-Token Routing Protocol"
                  value={newNodeTitle}
                  onChange={(e) => setNewNodeTitle(e.target.value)}
                  className="w-full bg-[#181818] border border-white/10 rounded-xl px-3.5 py-2 text-white focus:border-[#C9A86A] focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-white/60 block mb-1">Category</label>
                  <select
                    value={newNodeType}
                    onChange={(e) => setNewNodeType(e.target.value as 'spec' | 'task' | 'claim')}
                    className="w-full bg-[#181818] border border-white/10 rounded-xl px-3 py-2 text-white focus:border-[#C9A86A] focus:outline-none"
                  >
                    <option value="claim">Truth Claim (Evidence)</option>
                    <option value="spec">Spec (Architecture)</option>
                    <option value="task">Autonomous Task</option>
                  </select>
                </div>

                <div>
                  <label className="text-white/60 block mb-1">Project Scope</label>
                  <input
                    type="text"
                    value={newNodeProject}
                    onChange={(e) => setNewNodeProject(e.target.value)}
                    className="w-full bg-[#181818] border border-white/10 rounded-xl px-3 py-2 text-white focus:border-[#C9A86A] focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="text-white/60 block mb-1">Evidence Source / ADR</label>
                <input
                  type="text"
                  value={newNodeSource}
                  onChange={(e) => setNewNodeSource(e.target.value)}
                  className="w-full bg-[#181818] border border-white/10 rounded-xl px-3 py-2 text-white focus:border-[#C9A86A] focus:outline-none"
                />
              </div>

              {/* Select Target Node Connections */}
              <div>
                <label className="text-white/60 block mb-1">Connect to Existing Nodes</label>
                <div className="max-h-32 overflow-y-auto space-y-1 bg-[#181818] p-2 rounded-xl border border-white/10">
                  {nodesList.map((n) => {
                    const isChecked = newNodeConnections.includes(n.id);
                    return (
                      <label
                        key={n.id}
                        className="flex items-center gap-2 p-1.5 hover:bg-white/5 rounded-lg cursor-pointer text-white/80"
                      >
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => {
                            if (isChecked) {
                              setNewNodeConnections((prev) => prev.filter((id) => id !== n.id));
                            } else {
                              setNewNodeConnections((prev) => [...prev, n.id]);
                            }
                          }}
                          className="accent-[#C9A86A]"
                        />
                        <span className="text-[10px] uppercase font-bold text-[#C9A86A]">[{n.type}]</span>
                        <span className="truncate">{n.label}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-white/10">
              <button
                onClick={() => setIsAddNodeOpen(false)}
                className="px-4 py-2 text-white/60 hover:text-white text-xs cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateNode}
                disabled={!newNodeTitle.trim()}
                className="px-5 py-2 bg-[#C9A86A] hover:bg-[#dfc188] disabled:opacity-40 text-black font-semibold rounded-full text-xs uppercase tracking-wider cursor-pointer shadow-[0_0_15px_rgba(201,168,106,0.3)] transition-all"
              >
                Add Node to Graph
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default KnowledgeGraphView;
