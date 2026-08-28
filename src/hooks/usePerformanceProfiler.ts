import { useState, useEffect, useRef } from 'react';
import {
  PerformanceProfiler,
  ApiPerformanceEntry,
  ComponentRenderMetric,
  PerformanceMarkMetric,
  CoreWebVitals,
  MemoryStats,
} from '../utils/performanceProfiler';

export function usePerformanceProfiler() {
  const [apiEntries, setApiEntries] = useState<ApiPerformanceEntry[]>(PerformanceProfiler.getApiEntries());
  const [componentMetrics, setComponentMetrics] = useState<ComponentRenderMetric[]>(
    PerformanceProfiler.getComponentMetrics()
  );
  const [customMarks, setCustomMarks] = useState<PerformanceMarkMetric[]>(
    PerformanceProfiler.getCustomMarks()
  );
  const [isRecording, setIsRecording] = useState(PerformanceProfiler.isRecording());
  const [coreVitals, setCoreVitals] = useState<CoreWebVitals>(PerformanceProfiler.getCoreWebVitals());
  const [memoryStats, setMemoryStats] = useState<MemoryStats>(PerformanceProfiler.getMemoryStats());
  const [fps, setFps] = useState(60);
  const [isProbing, setIsProbing] = useState(false);

  // Subscribe to profiler updates
  useEffect(() => {
    const unsubscribe = PerformanceProfiler.subscribe(() => {
      setApiEntries(PerformanceProfiler.getApiEntries());
      setComponentMetrics(PerformanceProfiler.getComponentMetrics());
      setCustomMarks(PerformanceProfiler.getCustomMarks());
      setIsRecording(PerformanceProfiler.isRecording());
    });
    return unsubscribe;
  }, []);

  // Update Core Web Vitals and Memory periodically
  useEffect(() => {
    const timer = setInterval(() => {
      setCoreVitals(PerformanceProfiler.getCoreWebVitals());
      setMemoryStats(PerformanceProfiler.getMemoryStats());
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  // Live FPS Monitor using requestAnimationFrame
  useEffect(() => {
    let frameCount = 0;
    let lastTime = performance.now();
    let animId: number;

    const calcFps = (now: number) => {
      frameCount++;
      if (now - lastTime >= 1000) {
        setFps(Math.min(60, Math.round((frameCount * 1000) / (now - lastTime))));
        frameCount = 0;
        lastTime = now;
      }
      animId = requestAnimationFrame(calcFps);
    };

    animId = requestAnimationFrame(calcFps);
    return () => cancelAnimationFrame(animId);
  }, []);

  // Background automated probe every 5 seconds if recording
  useEffect(() => {
    if (!isRecording) return;
    const interval = setInterval(() => {
      PerformanceProfiler.runApiLatencyProbe();
    }, 5000);
    return () => clearInterval(interval);
  }, [isRecording]);

  const triggerProbe = async (endpointName?: string) => {
    setIsProbing(true);
    await PerformanceProfiler.runApiLatencyProbe(endpointName);
    setIsProbing(false);
  };

  const triggerMultiBenchmark = async () => {
    setIsProbing(true);
    const endpoints = [
      'GET /api/v2/telemetry/heartbeat',
      'POST /api/v2/inferences/stream',
      'GET /api/v2/mesh/routing',
      'POST /api/v2/knowledge-graph/query',
      'GET /api/v2/system/memory',
    ];
    for (const ep of endpoints) {
      await PerformanceProfiler.runApiLatencyProbe(ep);
    }
    setIsProbing(false);
  };

  const toggleRecording = () => {
    PerformanceProfiler.setRecording(!isRecording);
  };

  const clearMetrics = () => {
    PerformanceProfiler.clear();
  };

  return {
    apiEntries,
    componentMetrics,
    customMarks,
    isRecording,
    coreVitals,
    memoryStats,
    fps,
    isProbing,
    triggerProbe,
    triggerMultiBenchmark,
    toggleRecording,
    clearMetrics,
  };
}

/**
 * Hook to measure component render time with performance.now()
 */
export function useTrackComponentRender(componentName: string) {
  const startTimeRef = useRef<number>(performance.now());
  startTimeRef.current = performance.now();

  useEffect(() => {
    const renderDuration = performance.now() - startTimeRef.current;
    PerformanceProfiler.recordComponentRender(componentName, renderDuration);
  });
}
