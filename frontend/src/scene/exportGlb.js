// Экспорт сцены в .glb (День 16) — для открытия в Blender.
// Сцена доступна через window.__scene (выставляется в MapScene).
// Gizmo-хелпер и узлы редактирования из экспорта исключаем.

import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';

export function exportSceneGLB(filename = 'teploseti-scene.glb') {
  const scene = window.__scene;
  if (!scene) return;

  // Служебные объекты не должны попадать в экспорт.
  const hidden = [];
  for (const obj of [window.__gizmoHelper,
                     scene.getObjectByName('edit-nodes')]) {
    if (obj && obj.parent) {
      hidden.push([obj, obj.parent]);
      obj.parent.remove(obj);
    }
  }

  const exporter = new GLTFExporter();
  exporter.parse(
    scene,
    (result) => {
      const blob = new Blob([result], { type: 'model/gltf-binary' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      URL.revokeObjectURL(a.href);
      // Возвращаем служебные объекты на место.
      for (const [obj, parent] of hidden) parent.add(obj);
    },
    (err) => console.error('GLB export failed:', err),
    { binary: true },
  );
}
