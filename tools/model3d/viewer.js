// LootAdvisor 3D viewer (three.js r170 from cdn.jsdelivr.net, GLTFLoader + OrbitControls + RoomEnvironment).
// window.LootAdvisor3D.mount(container, setId) shows window.LA3D_MODELS[setId] (a data: URL or plain URL of a GLB)
// in the container. ONE renderer is shared: re-mounting moves its canvas, so re-renders never leak WebGL contexts.
// If the sets page is present (window.LootAdvisorSets), the adapter hooks its model slot via mountModel().
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const MODELS = window.LA3D_MODELS || {};
let V = null;                       // the shared viewer
const cache = {};                   // setId -> Promise<gltf scene>

function css() {
  if (document.getElementById("la3d-css")) return;
  const st = document.createElement("style");
  st.id = "la3d-css";
  st.textContent = ".la3d-host>img{display:none}.la3d-host{position:absolute;inset:0}" +
    ".la3d-canvas{position:absolute;inset:0;display:block;touch-action:none;cursor:grab}.la3d-canvas:active{cursor:grabbing}";
  document.head.appendChild(st);
}

function makeViewer() {
  css();
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.55;
  const camera = new THREE.PerspectiveCamera(28, 1, 0.05, 50);
  // game-like lighting: warm key from the upper front-left, cool rim from behind, dim warm fill
  scene.add(new THREE.HemisphereLight(0xffe2c0, 0x1a1410, 0.55));
  const key = new THREE.DirectionalLight(0xffe0b8, 2.4);
  key.position.set(1.6, 3.2, -2.6);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, { left: -1.2, right: 1.2, top: 2.4, bottom: -0.2, near: 0.5, far: 8 });
  key.shadow.bias = -0.0005;
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x9fb6ff, 1.6);
  rim.position.set(-2.0, 2.6, 2.8);
  scene.add(rim);
  const fill = new THREE.DirectionalLight(0xffc89a, 0.45);
  fill.position.set(-2.5, 1.2, -1.5);
  scene.add(fill);
  const floor = new THREE.Mesh(new THREE.CircleGeometry(1.3, 48), new THREE.ShadowMaterial({ opacity: 0.45 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.enablePan = false;
  controls.minDistance = 0.6;
  controls.maxDistance = 6;
  controls.minPolarAngle = 0.25;
  controls.maxPolarAngle = Math.PI / 2 + 0.05;
  const v = { renderer, scene, camera, controls, model: null, setId: null, box: null, container: null };
  const ro = new ResizeObserver(() => resize(v));
  v.ro = ro;
  function loop() {
    requestAnimationFrame(loop);
    if (!v.container || !v.container.isConnected) return;
    controls.update();
    renderer.render(scene, camera);
  }
  loop();
  return v;
}

function resize(v) {
  const el = v.container;
  if (!el) return;
  const w = Math.max(el.clientWidth, 50), h = Math.max(el.clientHeight, 50);
  v.renderer.setSize(w, h, false);
  v.renderer.domElement.style.width = "100%";
  v.renderer.domElement.style.height = "100%";
  v.camera.aspect = w / h;
  v.camera.updateProjectionMatrix();
}

function load(setId) {
  if (!cache[setId]) {
    const src = MODELS[setId];
    cache[setId] = fetch(src).then((r) => r.arrayBuffer()).then((buf) => new Promise((ok, bad) =>
      new GLTFLoader().parse(buf, "", (g) => ok(g.scene), bad)));
  }
  return cache[setId];
}

// the character faces -Z in the game's bind pose: "front" looks from -Z
const VIEWS = {
  front: { az: 0, el: 0.08, zoom: 1, y: 0.5 },
  side: { az: Math.PI / 2, el: 0.08, zoom: 1, y: 0.5 },
  back: { az: Math.PI, el: 0.1, zoom: 1, y: 0.5 },
  threequarter: { az: 0.6, el: 0.12, zoom: 1, y: 0.5 },
  armour: { az: 0.35, el: 0.1, zoom: 0.48, y: 0.66 },
  head: { az: 0.25, el: 0.05, zoom: 0.24, y: 0.9 },
};

function setView(name) {
  const v = V;
  if (!v || !v.box) return;
  const s = VIEWS[name] || VIEWS.front;
  const size = v.box.getSize(new THREE.Vector3());
  const h = size.y;
  const target = new THREE.Vector3((v.box.min.x + v.box.max.x) / 2, v.box.min.y + h * s.y, (v.box.min.z + v.box.max.z) / 2);
  const fov = THREE.MathUtils.degToRad(v.camera.fov);
  const fit = Math.max(h * s.zoom / 2 / Math.tan(fov / 2), (size.x * s.zoom / 2) / Math.tan(fov / 2) / Math.max(v.camera.aspect, 0.3)) * 1.12;
  const dir = new THREE.Vector3(Math.sin(s.az) * Math.cos(s.el), Math.sin(s.el), -Math.cos(s.az) * Math.cos(s.el));
  v.camera.position.copy(target).addScaledVector(dir, fit);
  v.controls.target.copy(target);
  v.controls.update();
}

async function mount(container, setId, view) {
  if (!MODELS[setId]) return false;
  if (!V) V = makeViewer();
  const v = V;
  if (v.container !== container) {
    if (v.container) v.ro.unobserve(v.container);
    v.container = container;
    container.appendChild(v.renderer.domElement);
    v.renderer.domElement.classList.add("la3d-canvas");
    v.ro.observe(container);
    resize(v);
  }
  if (v.setId !== setId) {
    v.setId = setId;
    container.classList.add("la3d-loading");
    const scene = await load(setId);
    if (v.setId !== setId) return true;
    if (v.model) v.scene.remove(v.model);
    scene.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
    v.model = scene;
    v.scene.add(scene);
    v.box = new THREE.Box3().setFromObject(scene);
    container.classList.remove("la3d-loading");
    setView(view || "front");
  }
  window.LA3D_READY = setId;
  return true;
}

window.LootAdvisor3D = { mount, setView, models: MODELS, views: Object.keys(VIEWS) };

// optional adapter for the sets page model slot
if (window.LootAdvisorSets && window.LootAdvisorSets.mountModel) {
  window.LootAdvisorSets.mountModel(function (media, setId) {
    if (!MODELS[setId]) {   // the hook marks every slot "has"; keep the capture placeholder where no model exists
      queueMicrotask(function () { var f = media.closest("figure"); if (f && !media.querySelector("img:not(.ghost)")) f.classList.remove("has"); });
      return;
    }
    media.classList.add("la3d-host");
    mount(media, setId, "front");
  });
}
document.dispatchEvent(new Event("la3d-ready"));
