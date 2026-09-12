import assert from "node:assert/strict";
import { test } from "node:test";
import * as THREE from "three";
import { disposeGraphResources, graphFitDistance } from "../src/widgets/knowledge-graph-explorer/graph3dScene";

test("fit keeps all bounds corners inside wide and narrow camera frustums", () => {
  const size = new THREE.Vector3(1000, 500, 200);
  for (const aspect of [0.2, 0.6, 1, 2.4]) {
    const distance = graphFitDistance(size, aspect, 50);
    const camera = new THREE.PerspectiveCamera(50, aspect, 1, distance * 4);
    camera.position.z = distance;
    camera.updateMatrixWorld();
    for (const x of [-500, 500]) for (const y of [-250, 250]) for (const z of [-100, 100]) {
      const point = new THREE.Vector3(x, y, z).project(camera);
      assert.ok(Math.abs(point.x) < 1 && Math.abs(point.y) < 1 && Math.abs(point.z) < 1);
    }
  }
});

test("shared geometry, materials and sprite textures are disposed exactly once", () => {
  const root = new THREE.Group();
  const geometry = new THREE.SphereGeometry();
  const texture = new THREE.Texture();
  const material = new THREE.MeshBasicMaterial({ map: texture });
  const spriteMaterial = new THREE.SpriteMaterial({ map: texture });
  const counts = new Map<object, number>();
  for (const resource of [geometry, texture, material, spriteMaterial]) {
    resource.addEventListener("dispose", () => counts.set(resource, (counts.get(resource) ?? 0) + 1));
  }
  root.add(new THREE.Mesh(geometry, material), new THREE.Mesh(geometry, material), new THREE.Sprite(spriteMaterial));
  disposeGraphResources(root);
  for (const resource of [geometry, texture, material, spriteMaterial]) assert.equal(counts.get(resource), 1);
});

test("degenerate bounds still produce a finite usable camera distance", () => {
  assert.equal(graphFitDistance(new THREE.Vector3(), 1, 50), 420);
  assert.ok(Number.isFinite(graphFitDistance(new THREE.Vector3(100, 100, 100), 0, 50)));
});
