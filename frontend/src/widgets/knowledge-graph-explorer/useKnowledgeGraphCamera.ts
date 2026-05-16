import { useCallback, useEffect, useRef, useState, type PointerEvent, type WheelEvent } from "react";
import {
  CAMERA_ANIM_MS,
  GRAPH_HEIGHT,
  GRAPH_WIDTH,
  MAX_ZOOM,
  MIN_ZOOM,
  clamp,
  type ExplorerNode,
  type GraphLayout,
} from "./knowledgeGraphExplorerShared";

interface UseKnowledgeGraphCameraOptions {
  interactiveSelector: string;
}

function easeOutCubic(t: number) {
  return 1 - Math.pow(1 - t, 3);
}

export function useKnowledgeGraphCamera({ interactiveSelector }: UseKnowledgeGraphCameraOptions) {
  const [zoom, setZoom] = useState(1);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [isPanning, setIsPanning] = useState(false);
  const [containerSize, setContainerSize] = useState({ width: GRAPH_WIDTH, height: GRAPH_HEIGHT });
  const panStartRef = useRef({ x: 0, y: 0, panX: 0, panY: 0 });
  const svgRef = useRef<SVGSVGElement | null>(null);
  const containerRef = useRef<HTMLElement | null>(null);
  const animRef = useRef<number>(0);

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setContainerSize({ width: entry.contentRect.width, height: entry.contentRect.height });
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const animateCameraTo = useCallback(
    (targetPanX: number, targetPanY: number, targetZoom: number) => {
      cancelAnimationFrame(animRef.current);
      const startPanX = panX;
      const startPanY = panY;
      const startZoom = zoom;
      const startTime = performance.now();
      function step(now: number) {
        const t = Math.min((now - startTime) / CAMERA_ANIM_MS, 1);
        const eased = easeOutCubic(t);
        setPanX(startPanX + (targetPanX - startPanX) * eased);
        setPanY(startPanY + (targetPanY - startPanY) * eased);
        setZoom(startZoom + (targetZoom - startZoom) * eased);
        if (t < 1) animRef.current = requestAnimationFrame(step);
      }
      animRef.current = requestAnimationFrame(step);
    },
    [panX, panY, zoom],
  );

  const centerOnNode = useCallback(
    (node: ExplorerNode) => {
      const targetZoom = Math.max(zoom, 1.2);
      const targetPanX = containerSize.width / targetZoom / 2 - node.x;
      const targetPanY = containerSize.height / targetZoom / 2 - node.y;
      animateCameraTo(targetPanX, targetPanY, targetZoom);
    },
    [animateCameraTo, containerSize.height, containerSize.width, zoom],
  );

  const resetView = useCallback(() => {
    animateCameraTo(0, 0, 1);
  }, [animateCameraTo]);

  const fitToView = useCallback(
    (layout: GraphLayout | null) => {
      if (!layout) return;
      const pad = 60;
      const minX = Math.min(...layout.nodes.map((n) => n.x - n.radius)) - pad;
      const minY = Math.min(...layout.nodes.map((n) => n.y - n.radius)) - pad;
      const maxX = Math.max(...layout.nodes.map((n) => n.x + n.radius)) + pad;
      const maxY = Math.max(...layout.nodes.map((n) => n.y + n.radius)) + pad;
      const graphWidth = maxX - minX;
      const graphHeight = maxY - minY;
      if (graphWidth < 10 || graphHeight < 10) {
        animateCameraTo(0, 0, 1);
        return;
      }
      const targetZoom = clamp(
        Math.min(containerSize.width / graphWidth, containerSize.height / graphHeight) * 0.9,
        MIN_ZOOM,
        MAX_ZOOM,
      );
      const centerX = (minX + maxX) / 2;
      const centerY = (minY + maxY) / 2;
      animateCameraTo(containerSize.width / targetZoom / 2 - centerX, containerSize.height / targetZoom / 2 - centerY, targetZoom);
    },
    [animateCameraTo, containerSize.height, containerSize.width],
  );

  useEffect(() => {
    return () => cancelAnimationFrame(animRef.current);
  }, []);

  const handlePointerDown = useCallback(
    (event: PointerEvent<SVGSVGElement>) => {
      if ((event.target as Element).closest(interactiveSelector)) return;
      setIsPanning(true);
      panStartRef.current = { x: event.clientX, y: event.clientY, panX, panY };
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    [interactiveSelector, panX, panY],
  );

  const handlePointerMove = useCallback(
    (event: PointerEvent<SVGSVGElement>) => {
      if (!isPanning) return;
      setPanX(panStartRef.current.panX + (event.clientX - panStartRef.current.x) / zoom);
      setPanY(panStartRef.current.panY + (event.clientY - panStartRef.current.y) / zoom);
    },
    [isPanning, zoom],
  );

  const handlePointerUp = useCallback(() => {
    setIsPanning(false);
  }, []);

  const handleWheel = useCallback((event: WheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    setZoom((current) => clamp(current * Math.pow(0.999, event.deltaY), MIN_ZOOM, MAX_ZOOM));
  }, []);

  const exportAsPng = useCallback(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const svgData = new XMLSerializer().serializeToString(svgEl);
    const canvas = document.createElement("canvas");
    canvas.width = containerSize.width * 2;
    canvas.height = containerSize.height * 2;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const img = new Image();
    img.onload = () => {
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      const link = document.createElement("a");
      link.download = "knowledge-graph.png";
      link.href = canvas.toDataURL("image/png");
      link.click();
    };
    img.src = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svgData)))}`;
  }, [containerSize.height, containerSize.width]);

  const viewBox = `${-panX} ${-panY} ${containerSize.width / zoom} ${containerSize.height / zoom}`;

  return {
    zoom,
    panX,
    panY,
    isPanning,
    containerSize,
    svgRef,
    containerRef,
    viewBox,
    animateCameraTo,
    centerOnNode,
    resetView,
    fitToView,
    handlePointerDown,
    handlePointerMove,
    handlePointerUp,
    handleWheel,
    exportAsPng,
  };
}
