// LootAdvisor 3D viewer for ALL sets (three.js r170 from cdn.jsdelivr.net).
// Loads <base>manifest.json and per-piece GLBs <base>parts/<id>.glb (built by tools/model3d/build_parts.py) and
// assembles a set like the game does:
//   - the origin's base (skeleton + head / hair / body) is posed with the stance's idle frame (manifest poses);
//   - every armour piece is a skinned mesh bound by bone NAME to that skeleton (one file serves every origin);
//   - weapons hang on hand / sheath bones (Dummy_R_Hand, Dummy_Sheath_*) with the weapon's own attachment offset;
//   - body / clothing regions hidden by the equipped items (VertexColorMaskSlots) are cut, hair under helmets hidden.
// API: window.LootAdvisor3D.mount(container, setId, view) -> Promise<bool>; setView(name); has(setId).
// Sets page hook: window.LootAdvisorSets.mountModel(fn(media, setId)) is used when the page provides it.
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { clone as cloneSkinned } from "three/addons/utils/SkeletonUtils.js";

const BASE = window.LA3D_BASE || "3d/";
let MAN = null;
const parts = {};
let V = null;

function manifest() {
  if (!MAN) MAN = fetch(BASE + "manifest.json").then((r) => r.json());
  return MAN;
}
function part(id) {
  if (!parts[id]) parts[id] = new Promise((ok, bad) => new GLTFLoader().load(BASE + "parts/" + id + ".glb", ok, undefined, bad));
  return parts[id];
}

function css() {
  if (document.getElementById("la3d-css")) return;
  const st = document.createElement("style");
  st.id = "la3d-css";
  st.textContent = ".la3d-host>img{display:none}.la3d-host{position:absolute;inset:0}" +
    ".la3d-canvas{position:absolute;inset:0;display:block;touch-action:none;cursor:grab}.la3d-canvas:active{cursor:grabbing}" +
    ".la3d-loading::before{content:'Loading model...';position:absolute;inset:0;display:grid;place-items:center;color:#8c7f69;font-size:13px}";
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
  scene.add(new THREE.HemisphereLight(0xffe2c0, 0x1a1410, 0.6));
  const key = new THREE.DirectionalLight(0xffe0b8, 2.4);
  key.position.set(1.6, 3.2, -2.6);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, { left: -1.4, right: 1.4, top: 2.6, bottom: -0.2, near: 0.5, far: 8 });
  key.shadow.bias = -0.0005;
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x9fb6ff, 1.5);
  rim.position.set(-2.0, 2.6, 2.8);
  scene.add(rim);
  const fill = new THREE.DirectionalLight(0xffc89a, 0.5);
  fill.position.set(-2.5, 1.2, -1.5);
  scene.add(fill);
  const floor = new THREE.Mesh(new THREE.CircleGeometry(1.4, 48), new THREE.ShadowMaterial({ opacity: 0.45 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);
  const controls = new OrbitControls(camera, renderer.domElement);
  Object.assign(controls, { enableDamping: true, dampingFactor: 0.08, enablePan: false, minDistance: 0.5, maxDistance: 7,
    minPolarAngle: 0.25, maxPolarAngle: Math.PI / 2 + 0.05 });
  const v = { renderer, scene, camera, controls, model: null, setId: null, box: null, container: null };
  v.ro = new ResizeObserver(() => resize(v));
  (function loop() {
    requestAnimationFrame(loop);
    if (!v.container || !v.container.isConnected) return;
    controls.update();
    renderer.render(scene, camera);
  })();
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

async function assemble(setId) {
  const M = await manifest();
  const s0 = M.sets[setId];
  const s = window.LA3D_BARE ? Object.assign({}, s0, { parts: [], weapons: [], cut: [], hideSlots: [] }) : s0;  // origin only
  const ch = M.chars[s.char];
  const [baseG, ...rest] = await Promise.all([part(ch.base), ...s.parts.map(part), ...s.weapons.map((w) => part(w.part))]);
  const itemG = rest.slice(0, s.parts.length), wpnG = rest.slice(s.parts.length);
  const root = new THREE.Group();
  const base = cloneSkinned(baseG.scene);
  root.add(base);
  const bones = {};
  base.traverse((o) => { if (!o.isMesh && o.name && !bones[o.name]) bones[o.name] = o; });
  // idle pose of the stance
  const pose = (ch.poses[s.stance] || {}).bones || {};
  const m4 = new THREE.Matrix4();
  for (const [name, arr] of Object.entries(pose)) {
    const b = bones[name];
    if (b) { m4.fromArray(arr); m4.decompose(b.position, b.quaternion, b.scale); }
  }
  const hideSlots = new Set(s.hideSlots), cut = new Set(s.cut);
  const meshes = [];
  base.traverse((o) => { if (o.isMesh) meshes.push(o); });
  for (const o of meshes) {
    let slot = null;
    for (let p = o; p && !slot; p = p.parent) slot = p.userData && p.userData.slot;
    if (slot && hideSlots.has(slot)) o.visible = false;
  }
  // armour pieces: rebind every skinned mesh to the origin's bones by name
  for (const g of itemG) {
    const list = [];
    g.scene.traverse((o) => { if (o.isSkinnedMesh) list.push(o); });
    for (const src of list) {
      const o = src.clone();
      const bs = o.skeleton.bones.map((b) => bones[b.name] || bones.Root_M || base);
      o.bind(new THREE.Skeleton(bs, o.skeleton.boneInverses.map((x) => x.clone())), new THREE.Matrix4());
      o.position.set(0, 0, 0); o.quaternion.identity(); o.scale.set(1, 1, 1);
      root.add(o);
      meshes.push(o);
    }
  }
  // weapons on hand / sheath bones
  s.weapons.forEach((w, i) => {
    const grp = new THREE.Group();
    grp.matrixAutoUpdate = false;
    grp.matrix.fromArray(w.offset);
    grp.add(wpnG[i].scene.clone());
    (bones[w.bone] || base).add(grp);
    grp.traverse((o) => { if (o.isMesh) meshes.push(o); });
  });
  for (const o of meshes) {
    const c = o.geometry && o.geometry.userData && o.geometry.userData.cut;
    if (c && c.some((k) => cut.has(k))) o.visible = false;
    o.frustumCulled = false;
    o.castShadow = o.receiveShadow = true;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for (const mt of mats) if (mt && mt.alphaTest > 0) mt.alphaToCoverage = true;
  }
  root.updateMatrixWorld(true);
  const box = new THREE.Box3();
  const pt = new THREE.Vector3();
  for (const b of Object.values(bones)) {
    if (/^(Dummy_|.*FX)/.test(b.name)) continue;
    box.expandByPoint(b.getWorldPosition(pt));
  }
  box.min.y = Math.min(box.min.y, 0);
  box.max.y += 0.12;
  box.expandByVector(new THREE.Vector3(0.12, 0, 0.12));
  const head = bones.Head_M ? bones.Head_M.getWorldPosition(new THREE.Vector3()) : null;
  return { root, box, head };
}

// the character faces -Z: "front" looks from -Z
const VIEWS = {
  front: { az: 0, el: 0.08, zoom: 1, y: 0.5 },
  threequarter: { az: 0.6, el: 0.12, zoom: 1, y: 0.5 },
  side: { az: Math.PI / 2, el: 0.08, zoom: 1, y: 0.5 },
  back: { az: Math.PI, el: 0.1, zoom: 1, y: 0.5 },
  armour: { az: 0.35, el: 0.1, zoom: 0.5, y: 0.64 },
  head: { az: 0.25, el: 0.05, zoom: 0.2, y: 0.9, bone: "head" },
  weapons: { az: 0.5, el: 0.15, zoom: 0.6, y: 0.5 },
};

function setView(name) {
  const v = V;
  if (!v || !v.box) return;
  const s = VIEWS[name] || VIEWS.front;
  const size = v.box.getSize(new THREE.Vector3());
  const h = size.y;
  const target = s.bone && v.head ? v.head.clone().add(new THREE.Vector3(0, 0.06, 0)) :
    new THREE.Vector3((v.box.min.x + v.box.max.x) / 2, v.box.min.y + h * s.y, (v.box.min.z + v.box.max.z) / 2);
  const fov = THREE.MathUtils.degToRad(v.camera.fov);
  const fit = Math.max(h * s.zoom / 2 / Math.tan(fov / 2), (size.x * s.zoom / 2) / Math.tan(fov / 2) / Math.max(v.camera.aspect, 0.3)) * 1.1;
  const dir = new THREE.Vector3(Math.sin(s.az) * Math.cos(s.el), Math.sin(s.el), -Math.cos(s.az) * Math.cos(s.el));
  v.camera.position.copy(target).addScaledVector(dir, fit);
  v.controls.target.copy(target);
  v.controls.update();
}

async function has(setId) {
  const M = await manifest();
  return !!M.sets[setId];
}

async function mount(container, setId, view) {
  const M = await manifest();
  if (!M.sets[setId]) return false;
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
    const r = await assemble(setId);
    if (v.setId !== setId) return true;
    if (v.model) v.scene.remove(v.model);
    v.model = r.root;
    v.box = r.box;
    v.head = r.head;
    v.scene.add(r.root);
    container.classList.remove("la3d-loading");
    setView(view || "front");
  }
  window.LA3D_READY = setId;
  return true;
}

window.LootAdvisor3D = { mount, setView, has, views: Object.keys(VIEWS), manifest };

if (window.LootAdvisorSets && window.LootAdvisorSets.mountModel) {
  window.LootAdvisorSets.mountModel(function (media, setId) {
    has(setId).then((ok) => {
      if (!ok) {   // keep the capture placeholder where no model exists
        const f = media.closest("figure");
        if (f && !media.querySelector("img:not(.ghost)")) f.classList.remove("has");
        return;
      }
      media.classList.add("la3d-host");
      mount(media, setId, "front");
    });
  });
}
document.dispatchEvent(new Event("la3d-ready"));
