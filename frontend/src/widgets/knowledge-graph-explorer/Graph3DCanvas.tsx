import { useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { KnowledgeGraphEdge } from "@/shared/api/types";
import {
  edgeKey,
  formatPercent,
  GRAPH_HEIGHT,
  GRAPH_WIDTH,
  type ExplorerNode,
  type GraphLayout,
} from "./knowledgeGraphExplorerShared";
import { disposeGraphResources, graphFitDistance } from "./graph3dScene";
import styles from "./graph-3d-canvas.module.css";

export interface Graph3DControls {
  fit: () => void;
  exportPng: () => void;
}

interface Graph3DCanvasProps {
  controlsRef?: React.Ref<Graph3DControls>;
  layout: GraphLayout | null;
  selectedNodeId: string | null;
  selectedEdgeKey: string | null;
  activeCollectionId: string;
  selectedNeighborIds: Set<string>;
  connectionCountByNode: Map<string, number>;
  hasGraphData: boolean;
  onSelectNode: (nodeId: string) => void;
  onSelectEdge: (edge: KnowledgeGraphEdge) => void;
  onOpenGuide: () => void;
  viewMode: "3d" | "2d";
  onViewModeChange: (mode: "3d" | "2d") => void;
}

interface HoverTooltipState {
  x: number;
  y: number;
  title: string;
  meta: string;
  tip?: string;
}

function createTextSprite(text: string, isSelected: boolean, isConnected: boolean): THREE.Sprite {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  const fontSize = 22;
  const paddingX = 14;
  const paddingY = 6;
  const font = `600 ${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;

  if (ctx) {
    ctx.font = font;
    const textMetrics = ctx.measureText(text);
    canvas.width = Math.ceil(textMetrics.width + paddingX * 2);
    canvas.height = Math.ceil(fontSize + paddingY * 2);

    ctx.font = font;
    ctx.textBaseline = "middle";

    const w = canvas.width;
    const h = canvas.height;
    const r = Math.min(6, h / 2);

    ctx.beginPath();
    ctx.moveTo(r, 0);
    ctx.lineTo(w - r, 0);
    ctx.quadraticCurveTo(w, 0, w, r);
    ctx.lineTo(w, h - r);
    ctx.quadraticCurveTo(w, h, w - r, h);
    ctx.lineTo(r, h);
    ctx.quadraticCurveTo(0, h, 0, h - r);
    ctx.lineTo(0, r);
    ctx.quadraticCurveTo(0, 0, r, 0);
    ctx.closePath();

    ctx.fillStyle = isSelected
      ? "rgba(99, 102, 241, 0.95)"
      : isConnected
      ? "rgba(30, 41, 59, 0.92)"
      : "rgba(15, 23, 42, 0.82)";
    ctx.fill();

    ctx.strokeStyle = isSelected
      ? "#a5b4fc"
      : isConnected
      ? "#818cf8"
      : "rgba(255, 255, 255, 0.18)";
    ctx.lineWidth = 1.5;
    ctx.stroke();

    ctx.fillStyle = isSelected ? "#ffffff" : isConnected ? "#f8fafc" : "#e2e8f0";
    ctx.fillText(text, paddingX, h / 2);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  const material = new THREE.SpriteMaterial({ map: texture, depthTest: false });
  const sprite = new THREE.Sprite(material);
  const scaleFactor = 0.22;
  sprite.scale.set(canvas.width * scaleFactor, canvas.height * scaleFactor, 1);
  return sprite;
}

function createBeamMesh(
  p1: THREE.Vector3,
  p2: THREE.Vector3,
  weight: number,
  isSelected: boolean,
  isDimmed: boolean,
): THREE.Mesh {
  const midpoint = p1.clone().add(p2).multiplyScalar(0.5);
  const offset = new THREE.Vector3().subVectors(p2, p1).cross(new THREE.Vector3(0, 0, 1));
  if (offset.lengthSq() < 0.001) offset.set(1, 0, 0);
  midpoint.addScaledVector(offset.normalize(), Math.min(p1.distanceTo(p2) * 0.12, 32));
  const curve = new THREE.QuadraticBezierCurve3(p1, midpoint, p2);
  const geometry = new THREE.TubeGeometry(curve, 24, isSelected ? 1.1 : 0.4 + weight * 0.35, 5, false);
  const material = new THREE.MeshBasicMaterial({
    color: isSelected ? 0xffffff : weight >= 0.7 ? 0x55aaff : 0xc5c7bf,
    transparent: true,
    opacity: isDimmed ? 0.1 : isSelected ? 1 : 0.55,
  });
  const mesh = new THREE.Mesh(geometry, material);

  return mesh;
}

export function Graph3DCanvas({
  controlsRef: externalControlsRef,
  layout,
  selectedNodeId,
  selectedEdgeKey,
  activeCollectionId,
  selectedNeighborIds,
  connectionCountByNode,
  hasGraphData,
  onSelectNode,
  onSelectEdge,
  onOpenGuide,
  viewMode,
  onViewModeChange,
}: Graph3DCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const animationFrameRef = useRef<number | null>(null);

  // Mesh registries for Raycasting
  const nodeMeshMapRef = useRef<Map<THREE.Object3D, ExplorerNode>>(new Map());
  const edgeMeshMapRef = useRef<Map<THREE.Object3D, KnowledgeGraphEdge>>(new Map());
  const selectedHaloMeshRef = useRef<THREE.Mesh | null>(null);

  // Drag tracking to distinguish click vs orbit rotate
  const pointerDownPosRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // Tooltip
  const [tooltip, setTooltip] = useState<HoverTooltipState | null>(null);

  const [showLabels, setShowLabels] = useState(false);

  // Helper: Fit camera to current nodes
  const fitCameraToNodes = useCallback((nodes: ExplorerNode[]) => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls || nodes.length === 0) return;

    const box = new THREE.Box3();
    nodes.forEach((n) => {
      const position = new THREE.Vector3(n.x - GRAPH_WIDTH / 2, -(n.y - GRAPH_HEIGHT / 2), n.z);
      const padding = new THREE.Vector3().setScalar(n.radius + 20);
      box.expandByPoint(position.clone().sub(padding));
      box.expandByPoint(position.clone().add(padding));
    });
    const center = new THREE.Vector3();
    box.getCenter(center);
    const size = new THREE.Vector3();
    box.getSize(size);
    const cameraZ = graphFitDistance(size, camera.aspect, camera.fov);
    controls.maxDistance = Math.max(2400, cameraZ * 2);
    camera.far = Math.max(4000, cameraZ * 4);
    camera.updateProjectionMatrix();

    controls.target.copy(center);
    camera.position.set(center.x, center.y, center.z + cameraZ);
    camera.lookAt(center);
    controls.update();
  }, []);

  // Initialize Three.js scene
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 560;

    // 1. Scene
    const scene = new THREE.Scene();
    sceneRef.current = scene;

    // 2. Camera
    const camera = new THREE.PerspectiveCamera(50, width / height, 1, 4000);
    camera.position.set(0, 40, 680);
    cameraRef.current = camera;

    // 3. Renderer
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      onViewModeChange("2d");
      return;
    }
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x0a0b12, 1);
    container.appendChild(renderer.domElement);
    renderer.domElement.className = styles.webglViewport;
    rendererRef.current = renderer;

    // 4. OrbitControls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 120;
    controls.maxDistance = 2400;
    controls.maxPolarAngle = Math.PI - 0.04;
    controls.rotateSpeed = 0.85;
    controls.panSpeed = 0.85;
    controls.zoomSpeed = 1.0;
    controlsRef.current = controls;

    // 5. Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.85);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.3);
    dirLight.position.set(300, 500, 400);
    scene.add(dirLight);

    const pointLightIndigo = new THREE.PointLight(0x818cf8, 2.2, 1200);
    pointLightIndigo.position.set(0, 250, 200);
    scene.add(pointLightIndigo);

    const pointLightCyan = new THREE.PointLight(0x38bdf8, 1.6, 1200);
    pointLightCyan.position.set(-260, -180, -150);
    scene.add(pointLightCyan);

    // 7. Render Animation Loop
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let isRunning = true;
    const animate = () => {
      if (!isRunning) return;
      animationFrameRef.current = requestAnimationFrame(animate);

      controls.update();

      // Animate selected halo orbital ring if active
      if (selectedHaloMeshRef.current && !reducedMotion.matches) {
        selectedHaloMeshRef.current.rotation.z += 0.015;
        selectedHaloMeshRef.current.rotation.x += 0.008;
      }

      renderer.render(scene, camera);
    };
    animate();

    // 8. ResizeObserver
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width: w, height: h } = entry.contentRect;
        if (w > 0 && h > 0) {
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
          renderer.setSize(w, h);
        }
      }
    });
    resizeObserver.observe(container);

    // Cleanup
    return () => {
      isRunning = false;
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      resizeObserver.disconnect();
      controls.dispose();
      disposeGraphResources(scene);
      sceneRef.current = null;
      rendererRef.current = null;
      cameraRef.current = null;
      controlsRef.current = null;
      renderer.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  // Update Scene Graph Nodes & Edges when layout or selections change
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    // Clear previous dynamic meshes (nodes, beams, sprites, halo)
    const objectsToRemove: THREE.Object3D[] = [];
    scene.children.forEach((child) => {
      if (child.userData.isDynamicGraphObject) {
        objectsToRemove.push(child);
      }
    });

    objectsToRemove.forEach((obj) => {
      scene.remove(obj);
      disposeGraphResources(obj);
    });

    nodeMeshMapRef.current.clear();
    edgeMeshMapRef.current.clear();
    selectedHaloMeshRef.current = null;

    if (!layout) return;

    const nodePositionMap = new Map<string, THREE.Vector3>();

    // 1. Create Node Spheres & Text Sprites
    layout.nodes.forEach((node) => {
      const x = node.x - GRAPH_WIDTH / 2;
      const y = -(node.y - GRAPH_HEIGHT / 2);
      const z = node.z;
      const position = new THREE.Vector3(x, y, z);
      nodePositionMap.set(node.id, position);

      const isSelected = selectedNodeId === node.id || activeCollectionId === node.id;
      const isConnected = selectedNeighborIds.has(node.id);
      const isDimmed = selectedNodeId != null && !isSelected && !isConnected;

      const connections = connectionCountByNode.get(node.id) ?? 0;


      // Sphere radius & geometry
      const r = Math.max(8, node.radius * 0.65);
      const geometry = new THREE.SphereGeometry(r, 32, 32);

      // Sphere material
      const baseColor = new THREE.Color(connections === 0 ? 0xffb32c : node.documentCount > 1 ? 0xad8cff : 0x249dff);

      const emissiveColor = isSelected
        ? new THREE.Color(0x818cf8)
        : isConnected
        ? new THREE.Color(0x6366f1)
        : baseColor;
      const emissiveIntensity = isSelected ? 0.85 : isConnected ? 0.35 : 0.15;
      const opacity = isDimmed ? 0.22 : 0.95;

      const material = new THREE.MeshStandardMaterial({
        color: baseColor,
        emissive: emissiveColor,
        emissiveIntensity,
        roughness: 0.25,
        metalness: 0.15,
        transparent: true,
        opacity,
      });

      const sphere = new THREE.Mesh(geometry, material);
      sphere.position.copy(position);
      sphere.userData = { isDynamicGraphObject: true, nodeId: node.id };
      scene.add(sphere);
      nodeMeshMapRef.current.set(sphere, node);

      // Selected Node Halo Ring
      if (isSelected) {
        const torusGeom = new THREE.TorusGeometry(r * 1.55, 0.75, 16, 48);
        const torusMat = new THREE.MeshStandardMaterial({
          color: 0x38bdf8,
          emissive: 0x38bdf8,
          emissiveIntensity: 0.9,
          roughness: 0.2,
          transparent: true,
          opacity: 0.9,
        });
        const halo = new THREE.Mesh(torusGeom, torusMat);
        halo.position.copy(position);
        halo.userData = { isDynamicGraphObject: true };
        scene.add(halo);
        selectedHaloMeshRef.current = halo;
      }

      // Billboard Text Sprite
      const sprite = createTextSprite(node.label.slice(0, 65), isSelected, isConnected);
      sprite.visible = showLabels || isSelected || isConnected;
      sprite.position.set(x, y - r - 10, z);
      sprite.userData = { isDynamicGraphObject: true };
      scene.add(sprite);
    });

    // 2. Create Relationship Beams (Edges)
    layout.links.forEach((edge) => {
      const p1 = nodePositionMap.get(edge.source);
      const p2 = nodePositionMap.get(edge.target);
      if (!p1 || !p2) return;

      const key = edgeKey(edge);
      const isSelected = selectedEdgeKey === key;
      const isDimmed =
        selectedNodeId != null && edge.source !== selectedNodeId && edge.target !== selectedNodeId;

      const beam = createBeamMesh(p1, p2, edge.weight, isSelected, isDimmed);
      beam.userData = { isDynamicGraphObject: true, edgeKey: key };
      scene.add(beam);
      edgeMeshMapRef.current.set(beam, edge);
    });
  }, [
    showLabels,
    activeCollectionId,
    connectionCountByNode,
    layout,
      selectedEdgeKey,
    selectedNeighborIds,
    selectedNodeId,
  ]);

  // Initial fit camera when layout loads
  useEffect(() => {
    if (layout && layout.nodes.length > 0) {
      fitCameraToNodes(layout.nodes);
    }
  }, [fitCameraToNodes, layout]);

  // Pointer Interaction (Hover Tooltip, Click Selection, Drag Detection)
  const handlePointerDown = (e: React.PointerEvent) => {
    pointerDownPosRef.current = { x: e.clientX, y: e.clientY };
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (e.target !== rendererRef.current?.domElement || e.buttons !== 0) {
      setTooltip(null);
      return;
    }
    const container = containerRef.current;
    const camera = cameraRef.current;
    const scene = sceneRef.current;
    if (!container || !camera || !scene) return;

    const rect = container.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );

    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, camera);

    // Test node spheres
    const nodeMeshes = Array.from(nodeMeshMapRef.current.keys());
    const nodeHits = raycaster.intersectObjects(nodeMeshes, false);

    if (nodeHits.length > 0) {
      const hitObj = nodeHits[0].object;
      const node = nodeMeshMapRef.current.get(hitObj);
      if (node) {
        const connections = connectionCountByNode.get(node.id) ?? 0;
        setTooltip({
          x: e.clientX - rect.left,
          y: e.clientY - rect.top,
          title: node.label,
          meta: `${node.chunkCount} excerpts • ${connections} links`,
          tip: "Click to inspect citations & topic",
        });
        return;
      }
    }

    // Test edge beams
    const edgeMeshes = Array.from(edgeMeshMapRef.current.keys());
    const edgeHits = raycaster.intersectObjects(edgeMeshes, false);

    if (edgeHits.length > 0) {
      const hitObj = edgeHits[0].object;
      const edge = edgeMeshMapRef.current.get(hitObj);
      if (edge) {
        const sourceLabel = layout?.nodes.find((n) => n.id === edge.source)?.label ?? edge.source;
        const targetLabel = layout?.nodes.find((n) => n.id === edge.target)?.label ?? edge.target;
        setTooltip({
          x: e.clientX - rect.left,
          y: e.clientY - rect.top,
          title: `${sourceLabel} ➔ ${targetLabel}`,
          meta: `${formatPercent(edge.weight)} match affinity`,
          tip: "Click to inspect correlation breakdown",
        });
        return;
      }
    }

    setTooltip(null);
  };

  const handlePointerUp = (e: React.PointerEvent) => {
    if (e.button !== 0 || e.target !== rendererRef.current?.domElement) return;
    const dx = Math.abs(e.clientX - pointerDownPosRef.current.x);
    const dy = Math.abs(e.clientY - pointerDownPosRef.current.y);

    // If dragged more than 5px, user was orbiting/panning -> do not trigger click
    if (dx > 5 || dy > 5) return;

    const container = containerRef.current;
    const camera = cameraRef.current;
    if (!container || !camera) return;

    const rect = container.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );

    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, camera);

    // Check node hits first
    const nodeMeshes = Array.from(nodeMeshMapRef.current.keys());
    const nodeHits = raycaster.intersectObjects(nodeMeshes, false);

    if (nodeHits.length > 0) {
      const hitObj = nodeHits[0].object;
      const node = nodeMeshMapRef.current.get(hitObj);
      if (node) {
        onSelectNode(node.id);
        return;
      }
    }

    // Check edge hits
    const edgeMeshes = Array.from(edgeMeshMapRef.current.keys());
    const edgeHits = raycaster.intersectObjects(edgeMeshes, false);

    if (edgeHits.length > 0) {
      const hitObj = edgeHits[0].object;
      const edge = edgeMeshMapRef.current.get(hitObj);
      if (edge) {
        onSelectEdge(edge);
      }
    }
  };

  // Double click to focus camera on topic
  const handleDoubleClick = (e: React.MouseEvent) => {
    if (e.target !== rendererRef.current?.domElement) return;
    const container = containerRef.current;
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!container || !camera || !controls) return;

    const rect = container.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );

    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, camera);
    const nodeMeshes = Array.from(nodeMeshMapRef.current.keys());
    const nodeHits = raycaster.intersectObjects(nodeMeshes, false);

    if (nodeHits.length > 0) {
      const hitObj = nodeHits[0].object;
      const node = nodeMeshMapRef.current.get(hitObj);
      if (node) {
        const targetPos = new THREE.Vector3(
          node.x - GRAPH_WIDTH / 2,
          -(node.y - GRAPH_HEIGHT / 2),
          node.z,
        );
        controls.target.copy(targetPos);
        camera.position.set(targetPos.x, targetPos.y + 20, targetPos.z + 240);
        controls.update();
      }
    } else {
      if (layout) fitCameraToNodes(layout.nodes);
    }
  };

  useImperativeHandle(externalControlsRef, () => ({
    fit: () => { if (layout) fitCameraToNodes(layout.nodes); },
    exportPng: () => {
      const renderer = rendererRef.current;
      if (!renderer || !sceneRef.current || !cameraRef.current) return;
      renderer.render(sceneRef.current, cameraRef.current);
      const link = document.createElement("a");
      link.download = "knowledge-graph-3d.png";
      link.href = renderer.domElement.toDataURL("image/png");
      link.click();
    },
  }), [fitCameraToNodes, layout]);

  // HUD Button Handlers
  const handleZoomIn = () => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls) return;
    const dir = new THREE.Vector3().subVectors(controls.target, camera.position).normalize();
    camera.position.addScaledVector(dir, Math.min(120, Math.max(0, camera.position.distanceTo(controls.target) - controls.minDistance)));
    controls.update();
  };

  const handleZoomOut = () => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls) return;
    const dir = new THREE.Vector3().subVectors(camera.position, controls.target).normalize();
    camera.position.addScaledVector(dir, Math.min(120, Math.max(0, controls.maxDistance - camera.position.distanceTo(controls.target))));
    controls.update();
  };

  const handleResetView = () => {
    if (layout) fitCameraToNodes(layout.nodes);
  };

  return (
    <div
      className={styles.canvas3dContainer}
      onDoubleClick={handleDoubleClick}
      onPointerDown={handlePointerDown}
      onPointerLeave={() => setTooltip(null)}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      ref={containerRef}
    >
      {/* Floating HUD Dock */}
      <div className={styles.hudDock} onDoubleClick={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()} onPointerUp={(event) => event.stopPropagation()}>
        <button type="button" className={styles.hudButton} aria-pressed={showLabels} onClick={() => setShowLabels(!showLabels)}>Labels</button>
        <div className={styles.viewToggleGroup}>
          <button
            aria-pressed={viewMode === "3d"}
            className={`${styles.viewToggleButton} ${viewMode === "3d" ? styles.viewToggleButtonActive : ""}`}
            onClick={() => onViewModeChange("3d")}
            title="Interactive 3D graph"
            type="button"
          >
            3D
          </button>
          <button
            aria-pressed={viewMode === "2d"}
            className={`${styles.viewToggleButton} ${viewMode === "2d" ? styles.viewToggleButtonActive : ""}`}
            onClick={() => onViewModeChange("2d")}
            title="2D graph"
            type="button"
          >
            2D
          </button>
        </div>

        <div className={styles.dockDivider} />

        <button
          aria-label="Zoom In"
          className={styles.hudButton}
          onClick={handleZoomIn}
          title="Zoom In"
          type="button"
        >
          +
        </button>
        <button
          aria-label="Zoom Out"
          className={styles.hudButton}
          onClick={handleZoomOut}
          title="Zoom Out"
          type="button"
        >
          –
        </button>
        <button
          aria-label="Fit to View"
          className={styles.hudButton}
          onClick={handleResetView}
          title="Fit &amp; Center Constellation"
          type="button"
        >
          ⛶
        </button>

        <div className={styles.dockDivider} />

        <button
          aria-label="Explorer Guide"
          className={`${styles.hudButton} ${styles.guideHudButton}`}
          onClick={onOpenGuide}
          title="Open 3D Navigation Guide"
          type="button"
        >
          Guide
        </button>
      </div>

      {/* Floating Tooltip Card */}
      {tooltip && (
        <div
          className={styles.floatingTooltip}
          style={{ left: `${tooltip.x}px`, top: `${tooltip.y}px` }}
        >
          <div className={styles.tooltipTitle}>{tooltip.title}</div>
          <div className={styles.tooltipMeta}>{tooltip.meta}</div>
          {tooltip.tip && <div className={styles.tooltipTip}>{tooltip.tip}</div>}
        </div>
      )}

      {/* Bottom Floating Legend & Gesture Reminder */}
      <div className={styles.bottomOverlay}>
        <div className={styles.legendPanel}>
          <span><i style={{ background: "#249dff" }} /> Single-document topic</span>
          <span><i style={{ background: "#ad8cff" }} /> Cross-document topic</span>
          <span><i style={{ background: "#ffb32c" }} /> Isolated topic</span>
          <span>Size = excerpts</span>
        </div>

        <div className={styles.controlsHint}>
          Left-click: Orbit • Right-click: Pan • Scroll: Zoom • Dbl-click: Focus
        </div>
      </div>

      {/* Empty State */}
      {!layout && (
        <div className={styles.emptyOverlay}>
          <h2 className={styles.emptyTitle}>{hasGraphData ? "No topics match this view" : "No topics yet"}</h2>
          <p className={styles.emptySubtitle}>
            {hasGraphData
              ? "Clear the search or lower the strength filter to bring topics back into the constellation."
              : "Re-cluster indexed PDFs in the pipeline to build the 3D knowledge constellation."}
          </p>
        </div>
      )}
    </div>
  );
}
