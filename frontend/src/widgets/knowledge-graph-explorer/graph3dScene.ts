import * as THREE from "three";

/** Dispose resources owned by a graph subtree, once even when shared by meshes. */
export function disposeGraphResources(root: THREE.Object3D) {
  const resources = new Set<{ dispose: () => void }>();
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh || object instanceof THREE.Sprite)) return;
    if (object instanceof THREE.Mesh) resources.add(object.geometry);
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials) {
      resources.add(material);
      if ("map" in material && material.map instanceof THREE.Texture) resources.add(material.map);
    }
  });
  resources.forEach((resource) => resource.dispose());
}

/** Distance from the bounds center required by both horizontal and vertical FOV. */
export function graphFitDistance(size: THREE.Vector3, aspect: number, fovDegrees: number) {
  const verticalTangent = Math.tan(THREE.MathUtils.degToRad(fovDegrees) / 2);
  const horizontalTangent = verticalTangent * Math.max(aspect, 0.01);
  return Math.max(420, 1.2 * Math.max(size.y / (2 * verticalTangent), size.x / (2 * horizontalTangent)) + size.z / 2);
}
