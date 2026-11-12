import {
  Suspense, useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import {
  ContactShadows, Html, OrbitControls,
  RoundedBox as DreiRoundedBox, Sparkles,
} from '@react-three/drei';
import * as THREE from 'three';

// Guarantee that browser speech synthesis is permanently silenced
if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
  try {
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak = () => {};
  } catch (_) {}
}

/* ── Config ──────────────────────────────────────────── */
const API_BASE  = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const API_TOKEN = import.meta.env.VITE_API_TOKEN || '';
const ROBOT_ID  = 'nova';

/* ── Actions ─────────────────────────────────────────── */
const ACTIONS = {
  idle:      { icon: '◌', label: 'Idle',      duration: Infinity },
  wave:      { icon: '👋', label: 'Wave',      duration: 2.8 },
  nod:       { icon: '↕',  label: 'Nod',       duration: 1.8 },
  greet:     { icon: '↗',  label: 'Greet',     duration: 3.0 },
  think:     { icon: '◉',  label: 'Think',     duration: 3.5 },
  celebrate: { icon: '✧',  label: 'Celebrate', duration: 2.8 },
  speak:     { icon: '▶',  label: 'Speak',     duration: 7.0 },
  bow:       { icon: '🙇', label: 'Bow',       duration: 2.5 },
  dance:     { icon: '♪',  label: 'Dance',     duration: 4.0 },
  point:     { icon: '👉', label: 'Point',     duration: 2.0 },
  shrug:     { icon: '🤷', label: 'Shrug',     duration: 2.0 },
  attention: { icon: '⚡', label: 'Attention', duration: 2.2 },
};

/* ── API ─────────────────────────────────────────────── */
function authHeaders() {
  return {
    'Content-Type': 'application/json',
    ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}),
  };
}
async function triggerAction(action, extras = {}) {
  const res  = await fetch(`${API_BASE}/api/robots/${ROBOT_ID}/actions`, {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ action, ...extras }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
  return data;
}

/* ── Spring helper ───────────────────────────────────── */
function sp(cur, tgt, vel, k, key, stiff = 180, damp = 18, dt = 0.016) {
  const v0    = k[key] || 0;
  const force = stiff * (tgt - cur) - damp * v0;
  const v1    = v0 + force * dt;
  k[key]      = v1;
  return cur + v1 * dt;
}

/* ── Ground ──────────────────────────────────────────── */
function Ground() {
  return (
    <>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.35, 0]} receiveShadow>
        <planeGeometry args={[120, 120]} />
        <meshStandardMaterial color="#050d18" metalness={0.45} roughness={0.75} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.34, 0]}>
        <ringGeometry args={[0.6, 1.0, 96]} />
        <meshBasicMaterial color="#1acce4" transparent opacity={0.26} side={THREE.DoubleSide} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.345, 0]}>
        <ringGeometry args={[1.05, 1.12, 96]} />
        <meshBasicMaterial color="#0d6b8a" transparent opacity={0.44} side={THREE.DoubleSide} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.346, 0]}>
        <ringGeometry args={[1.28, 1.30, 96]} />
        <meshBasicMaterial color="#07344a" transparent opacity={0.55} side={THREE.DoubleSide} />
      </mesh>
      <gridHelper args={[40, 40, '#0a2535', '#071820']} position={[0, -1.35, 0]} />
    </>
  );
}

/* ── RoundedBox shorthand ────────────────────────────── */
function RBox({ args, radius = 0.1, smoothness = 4, material, ...p }) {
  return <DreiRoundedBox args={args} radius={radius} smoothness={smoothness} material={material} castShadow receiveShadow {...p} />;
}

/* ── Robot ───────────────────────────────────────────── */
function RobotModel({ command, onReady }) {
  const root   = useRef(); const torso       = useRef();
  const head   = useRef(); const leftArm     = useRef();
  const rArm   = useRef(); const lFore       = useRef();
  const rFore  = useRef(); const chestCore   = useRef();
  const eyeL   = useRef(); const eyeR        = useRef();
  const mouth  = useRef(); const antenna     = useRef();

  const k    = useRef({});  // spring velocities
  const anim = useRef({ id: null, action: 'idle', startedAt: 0, speed: 1, side: 'right' });
  const init = useRef(false);

  const mat = useMemo(() => ({
    // Primary shell – satin‑finish pearl white (soft matte)
    body:  new THREE.MeshStandardMaterial({ color: '#f5f5f5', metalness: 0.1, roughness: 0.35 }),
    // Secondary panels – deep charcoal accent
    bodyD: new THREE.MeshStandardMaterial({ color: '#222222', metalness: 0.6, roughness: 0.45 }),
    // Dark internal surfaces (e.g., inside torso)
    dark:  new THREE.MeshStandardMaterial({ color: '#1e2d3d', metalness: 0.8, roughness: 0.28 }),
    // Joint caps – subtle midnight navy
    joint: new THREE.MeshStandardMaterial({ color: '#001f3f', metalness: 0.8, roughness: 0.2 }),
    // Visor glass – dark, low‑specular
    glass: new THREE.MeshPhysicalMaterial({ color: '#060f1a', metalness: 0.22, roughness: 0.1, clearcoat: 1, clearcoatRoughness: 0.06 }),
    // Accent cyan‑teal emission (eyes, antenna orb, chest core)
    cyan:  new THREE.MeshStandardMaterial({ color: '#4fd1e0', emissive: '#7ff0ff', emissiveIntensity: 3.0, metalness: 0.0, roughness: 0.2 }),
    // Optional secondary blue – kept for subtle highlights
    blue:  new THREE.MeshStandardMaterial({ color: '#88aaff', emissive: '#3d66ff', emissiveIntensity: 2.0, metalness: 0.3, roughness: 0.2 }),
    // Eyes – bright cyan with strong emissive punch
    eye:   new THREE.MeshStandardMaterial({ color: '#c2feff', emissive: '#5ef5ff', emissiveIntensity: 4.5, roughness: 0.14 }),
    // Visor – almost black glass
    visor: new THREE.MeshStandardMaterial({ color: '#040d14', metalness: 0.7,  roughness: 0.15 }),
  }), []);

  useEffect(() => {
    if (command?.request_id && anim.current.id !== command.request_id) {
      anim.current = {
        id: command.request_id, action: command.action || 'idle',
        startedAt: 0, speed: Math.max(0.25, Math.min(2, Number(command.params?.speed || 1))),
        side: command.params?.side || 'right',
      };
    }
  }, [command]);

  useEffect(() => { if (!init.current) { init.current = true; onReady?.(); } }, [onReady]);

  useFrame(({ clock }, delta) => {
    const t   = clock.elapsedTime;
    const a   = anim.current;
    const kv  = k.current;
    const dt  = Math.min(delta, 0.05);
    if (!a.startedAt) a.startedAt = t;
    const el  = Math.max(0, t - a.startedAt) * a.speed;
    const act = a.action;

    const c01 = (x) => Math.max(0, Math.min(1, x));
    const eio = (x) => x < 0.5 ? 2*x*x : 1 - Math.pow(-2*x+2,2)/2;
    const sin = (f, amp=1) => Math.sin(t*f)*amp;
    const sab = (f, amp=1) => Math.abs(Math.sin(t*f))*amp;
    const on  = (n) => act === n && el < (ACTIONS[n]?.duration ?? 2.5);
    const pg  = (n) => c01(el / (ACTIONS[n]?.duration ?? 2.5));

    /* Root */
    let rY = -1.25 + sin(1.4, 0.028), rRY = sin(0.4, 0.06);
    if (on('celebrate')) rY  += Math.sin(pg('celebrate') * Math.PI) * 0.22;
    if (on('dance'))   { rY  += Math.sin(el*5.5)*0.085; rRY += Math.sin(el*4.2)*0.22; }
    if (on('attention')) rY  += Math.sin(c01(el/0.4)*Math.PI)*0.18;
    if (on('point'))     rRY += a.side==='left' ? -0.18 : 0.18;
    if (root.current) {
      root.current.position.y = sp(root.current.position.y, rY,  kv, kv, 'ry',  120, 16, dt);
      root.current.rotation.y = sp(root.current.rotation.y, rRY, kv, kv, 'rry', 80,  14, dt);
    }

    /* Head */
    let hX = sin(0.7,0.022), hY = sin(0.5,0.09), hZ = 0;
    if (on('nod')||on('greet')) hX += Math.sin(pg('nod')*Math.PI*3.5)*0.24;
    if (on('think'))  { hX += 0.05; hY += 0.28 + sin(2.5,0.06); }
    if (on('bow'))      hX += Math.sin(pg('bow')*Math.PI)*0.38;
    if (on('dance'))  { hX += sin(5.5,0.06); hZ = sin(4.2,0.06); }
    if (on('celebrate')) hX += sin(9,0.06);
    if (on('attention')) { hY = 0; hX = -0.07; }
    if (on('speak'))   hX += sin(3.5,0.022);
    if (head.current) {
      head.current.rotation.x = sp(head.current.rotation.x, hX, kv, kv, 'hx', 140, 18, dt);
      head.current.rotation.y = sp(head.current.rotation.y, hY, kv, kv, 'hy', 100, 16, dt);
      head.current.rotation.z = sp(head.current.rotation.z, hZ, kv, kv, 'hz', 100, 14, dt);
    }

    /* Torso */
    let tX = 0, tZ = 0;
    if (on('think'))     tX = 0.06;
    if (on('celebrate')) tX = -0.04 + sin(8,0.04);
    if (on('bow'))       tX = Math.sin(pg('bow')*Math.PI)*0.44;
    if (on('dance'))   { tX = sin(5.5,0.06); tZ = sin(3.5,0.045); }
    if (on('shrug'))     tZ = Math.sin(pg('shrug')*Math.PI)*0.06;
    if (on('attention')) tX = -0.04;
    if (torso.current) {
      torso.current.rotation.x = sp(torso.current.rotation.x, tX, kv, kv, 'tx', 100, 15, dt);
      torso.current.rotation.z = sp(torso.current.rotation.z, tZ, kv, kv, 'tz', 90,  14, dt);
    }

    /* Arms */
    const sd   = a.side;
    const wav  = on('wave')||on('greet');
    const wPow = wav ? eio(c01(el/0.35)) : 0;
    const lW   = (act==='wave'&&(sd==='left'||sd==='both'))||act==='greet'||act==='celebrate';
    const rW   = (act==='wave'&&(sd==='right'||sd==='both'))||act==='greet'||act==='celebrate';
    let lAZ=lW?-2.1*wPow:0, rAZ=rW?2.1*wPow:0, lAX=0, rAX=0;

    if (on('celebrate')) { const p=pg('celebrate'); lAZ=-1.9*Math.sin(p*Math.PI); rAZ=1.9*Math.sin(p*Math.PI); lAX=sin(9,0.15); rAX=sin(9,0.15); }
    if (on('shrug'))     { const p=pg('shrug'); lAZ=-Math.sin(p*Math.PI)*0.55; rAZ=Math.sin(p*Math.PI)*0.55; }
    if (on('dance'))     { lAZ=-0.6+sin(5.5,0.5); rAZ=0.6+sin(5.5,-0.5); }
    if (on('point'))     { const p=eio(pg('point')); if(sd==='right'||sd==='both'){rAZ=0.7*p;rAX=-0.55*p;} if(sd==='left'||sd==='both'){lAZ=-0.7*p;lAX=-0.55*p;} }
    if (on('bow'))       { const p=Math.sin(pg('bow')*Math.PI); lAZ=-0.35*p; rAZ=0.35*p; }
    if (on('attention')) { lAZ=-0.1; rAZ=0.1; }

    if (leftArm.current) {
      leftArm.current.rotation.z = sp(leftArm.current.rotation.z, lAZ, kv, kv, 'laz', 130, 18, dt);
      leftArm.current.rotation.x = sp(leftArm.current.rotation.x, lAX, kv, kv, 'lax', 110, 16, dt);
    }
    if (rArm.current) {
      rArm.current.rotation.z = sp(rArm.current.rotation.z, rAZ, kv, kv, 'raz', 130, 18, dt);
      rArm.current.rotation.x = sp(rArm.current.rotation.x, rAX, kv, kv, 'rax', 110, 16, dt);
    }

    /* Forearms */
    let lfZ=0, rfZ=0;
    if (wav&&(sd==='left'||sd==='both'||act==='greet'))  lfZ = sin(11,0.52);
    if (wav&&(sd==='right'||sd==='both'||act==='greet')) rfZ = sin(11,0.52);
    if (on('celebrate')) { lfZ=sin(14,0.5); rfZ=sin(14,-0.5); }
    if (on('dance'))     { lfZ=sin(6,0.4);  rfZ=sin(6,-0.4);  }
    if (on('shrug'))     { const p=Math.sin(pg('shrug')*Math.PI); lfZ=-0.4*p; rfZ=0.4*p; }
    if (lFore.current) lFore.current.rotation.z = sp(lFore.current.rotation.z, lfZ, kv, kv, 'lfz', 150, 20, dt);
    if (rFore.current) rFore.current.rotation.z = sp(rFore.current.rotation.z, rfZ, kv, kv, 'rfz', 150, 20, dt);

    /* Chest */
    if (chestCore.current) {
      let i = 1.8+sin(2.2,0.3);
      if (on('celebrate')) i = 3.5+sab(14,2.0);
      if (on('speak'))     i = 2.2+sab(16,1.2);
      if (on('dance'))     i = 2.5+sab(8,1.0);
      if (on('attention')) i = 4.0+sab(6,1.8);
      chestCore.current.material.emissiveIntensity = i;
    }

    /* Eyes */
    if (eyeL.current && eyeR.current) {
      const blink = (t*0.4)%1 > 0.93;
      let iL = blink?0.3:4.5, iR = blink?0.3:4.5;
      if (on('think'))     iR = sin(0.6,0.8)>0?4.5:0.4;
      if (on('celebrate')) { iL=5.5+sab(12,1.5); iR=5.5+sab(10,1.5); }
      if (on('attention')) { iL=7; iR=7; }
      eyeL.current.material.emissiveIntensity = iL;
      eyeR.current.material.emissiveIntensity = iR;
    }

    /* Mouth */
    if (mouth.current) {
      const spk = on('speak');
      mouth.current.scale.x = spk ? 0.78+sab(18,0.7) : 1.0;
      mouth.current.scale.y = spk ? 0.06+sab(18,0.05) : on('celebrate') ? 0.09 : 0.052;
    }

    /* Antenna */
    if (antenna.current) {
      let i = 2.2+sin(2.8,0.5);
      if (on('think'))     i = 4.5+sab(3,2.0);
      if (on('speak'))     i = 5.0+sab(18,2.5);
      if (on('attention')) i = 6.0+sab(4,2.0);
      antenna.current.material.emissiveIntensity = i;
    }

    /* Auto-idle */
    const dur = ACTIONS[act]?.duration ?? 2.5;
    if (act !== 'idle' && el > dur) { a.action = 'idle'; a.startedAt = t; }
  });

  return (
    <group ref={root} position={[0, -1.25, 0]}>
      {/* Feet */}
      {[-0.3, 0.3].map((x, i) => (
        <group key={i} position={[x, 0.12, 0]}>
          <RBox args={[0.32,0.20,0.52]} radius={0.07} material={mat.dark} position={[0,0,0.07]} />
          <RBox args={[0.20,0.07,0.30]} radius={0.04} material={mat.joint} position={[0,0.1,0.1]} />
          <mesh position={[0,0.02,0.30]} material={mat.cyan}><boxGeometry args={[0.16,0.028,0.016]} /></mesh>
          <RBox args={[0.32,0.07,0.08]} radius={0.03} material={mat.bodyD} position={[0,-0.06,0.25]} />
        </group>
      ))}
      {/* Lower legs */}
      <RBox args={[0.24,0.78,0.26]} radius={0.08} material={mat.body} position={[-0.3,0.66,0]} />
      <RBox args={[0.24,0.78,0.26]} radius={0.08} material={mat.body} position={[ 0.3,0.66,0]} />
      <mesh position={[-0.3,0.58,0.14]} material={mat.dark}><boxGeometry args={[0.12,0.32,0.025]} /></mesh>
      <mesh position={[ 0.3,0.58,0.14]} material={mat.dark}><boxGeometry args={[0.12,0.32,0.025]} /></mesh>
      {/* Knees */}
      {[-0.3, 0.3].map((x, i) => (
        <group key={i} position={[x, 1.06, 0]}>
          <mesh material={mat.joint}><sphereGeometry args={[0.13,24,24]} /></mesh>
          <mesh position={[0,0,0.15]} material={mat.cyan}><torusGeometry args={[0.09,0.018,8,24]} /></mesh>
        </group>
      ))}
      {/* Hip */}
      <RBox args={[0.75,0.20,0.35]} radius={0.07} material={mat.dark} position={[0,1.15,0]} />
      <mesh position={[0,1.15,0.185]} material={mat.cyan}><boxGeometry args={[0.48,0.045,0.012]} /></mesh>
      {/* Torso */}
      <group ref={torso} position={[0,1.28,0]}>
        <RBox args={[1.00,0.98,0.46]} radius={0.18} material={mat.body} />
        <RBox args={[0.72,0.58,0.08]} radius={0.11} material={mat.dark} position={[0,0.06,0.25]} />
        <mesh position={[0,0.1,0.302]} material={mat.glass}><circleGeometry args={[0.2,56]} /></mesh>
        <mesh ref={chestCore} position={[0,0.1,0.316]} material={mat.blue}><circleGeometry args={[0.14,48]} /></mesh>
        <mesh position={[0,0.1,0.330]} material={mat.eye}><circleGeometry args={[0.06,32]} /></mesh>
        {[-0.3,-0.18,0.18,0.3].map((x,i)=>(<mesh key={i} position={[x,-0.25,0.3]} material={mat.cyan}><boxGeometry args={[0.05,0.05,0.014]} /></mesh>))}
        {[-1,1].map((s,i)=>(<group key={i} position={[s*0.52,-0.08,0.05]}>{[0,0.065,0.13].map((dy,j)=>(<mesh key={j} position={[0,dy,0]} material={mat.dark}><boxGeometry args={[0.03,0.03,0.28]} /></mesh>))}</group>))}
        <RBox args={[0.82,0.10,0.12]} radius={0.04} material={mat.dark} position={[0,-0.53,0]} />
      </group>
      {/* Neck */}
      <mesh position={[0,1.84,0]} material={mat.dark}><cylinderGeometry args={[0.19,0.23,0.18,32]} /></mesh>
      <mesh position={[0,1.94,0]} material={mat.cyan}><torusGeometry args={[0.19,0.022,10,40]} /></mesh>
      {/* Shoulders */}
      <mesh position={[-0.67,1.63,0]} material={mat.joint}><sphereGeometry args={[0.2,28,28]} /></mesh>
      <mesh position={[ 0.67,1.63,0]} material={mat.joint}><sphereGeometry args={[0.2,28,28]} /></mesh>
      {/* Left arm */}
      <group ref={leftArm} position={[-0.7,1.63,0]}>
        <RBox args={[0.24,0.52,0.27]} radius={0.09} material={mat.body} position={[0,-0.30,0]} />
        <mesh position={[0,-0.14,0.14]} material={mat.dark}><boxGeometry args={[0.14,0.18,0.022]} /></mesh>
        <mesh position={[0,-0.57,0]} material={mat.joint}><sphereGeometry args={[0.115,22,22]} /></mesh>
        <group ref={lFore} position={[0,-0.63,0]}>
          <RBox args={[0.19,0.44,0.21]} radius={0.07} material={mat.body} position={[0,-0.22,0]} />
          <mesh position={[0,-0.44,0]} material={mat.dark}><sphereGeometry args={[0.1,18,18]} /></mesh>
          <RBox args={[0.24,0.20,0.20]} radius={0.07} material={mat.bodyD} position={[0,-0.55,0.01]} />
          <mesh position={[0,-0.55,0.12]} material={mat.cyan}><boxGeometry args={[0.09,0.022,0.013]} /></mesh>
        </group>
      </group>
      {/* Right arm */}
      <group ref={rArm} position={[0.7,1.63,0]}>
        <RBox args={[0.24,0.52,0.27]} radius={0.09} material={mat.body} position={[0,-0.30,0]} />
        <mesh position={[0,-0.14,0.14]} material={mat.dark}><boxGeometry args={[0.14,0.18,0.022]} /></mesh>
        <mesh position={[0,-0.57,0]} material={mat.joint}><sphereGeometry args={[0.115,22,22]} /></mesh>
        <group ref={rFore} position={[0,-0.63,0]}>
          <RBox args={[0.19,0.44,0.21]} radius={0.07} material={mat.body} position={[0,-0.22,0]} />
          <mesh position={[0,-0.44,0]} material={mat.dark}><sphereGeometry args={[0.1,18,18]} /></mesh>
          <RBox args={[0.24,0.20,0.20]} radius={0.07} material={mat.bodyD} position={[0,-0.55,0.01]} />
          <mesh position={[0,-0.55,0.12]} material={mat.cyan}><boxGeometry args={[0.09,0.022,0.013]} /></mesh>
        </group>
      </group>
      {/* Head */}
      <group ref={head} position={[0,2.3,0.01]}>
        <RBox args={[0.88,0.68,0.60]} radius={0.20} material={mat.body} />
        <RBox args={[0.74,0.38,0.072]} radius={0.14} material={mat.visor} position={[0,-0.03,0.31]} />
        <mesh ref={eyeL} position={[-0.185,0.02,0.358]} material={mat.eye}><sphereGeometry args={[0.077,26,26]} /></mesh>
        <mesh ref={eyeR} position={[ 0.185,0.02,0.358]} material={mat.eye}><sphereGeometry args={[0.077,26,26]} /></mesh>
        <mesh position={[-0.185,0.02,0.435]} material={mat.dark}><circleGeometry args={[0.035,20]} /></mesh>
        <mesh position={[ 0.185,0.02,0.435]} material={mat.dark}><circleGeometry args={[0.035,20]} /></mesh>
        <mesh ref={mouth} position={[0,-0.185,0.363]} material={mat.cyan}><boxGeometry args={[0.20,0.052,0.018]} /></mesh>
        <mesh position={[-0.46,-0.06,0.06]} material={mat.joint}><sphereGeometry args={[0.088,22,22]} /></mesh>
        <mesh position={[ 0.46,-0.06,0.06]} material={mat.joint}><sphereGeometry args={[0.088,22,22]} /></mesh>
        <RBox args={[0.54,0.08,0.42]} radius={0.04} material={mat.dark} position={[0,0.38,0]} />
        <mesh position={[0,0.42,0.1]} material={mat.cyan}><boxGeometry args={[0.32,0.018,0.22]} /></mesh>
        <mesh position={[0,0.42,0]} material={mat.dark}><cylinderGeometry args={[0.024,0.04,0.2,16]} /></mesh>
        <mesh ref={antenna} position={[0,0.57,0]} material={mat.cyan}><sphereGeometry args={[0.068,22,22]} /></mesh>
      </group>
    </group>
  );
}

/* ── Scene lights ────────────────────────────────────── */
function SceneLights() {
  const bRef = useRef(), cRef = useRef();
  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    if (bRef.current) bRef.current.intensity = 22 + Math.sin(t*1.4)*4;
    if (cRef.current) cRef.current.intensity = 18 + Math.sin(t*1.8+1)*3;
  });
  return (
    <>
      <ambientLight intensity={0.75} />
      <hemisphereLight args={['#c8e8ff','#101520',1.1]} />
      <directionalLight position={[4,8,6]} intensity={3.5} castShadow shadow-mapSize={[2048,2048]} shadow-bias={-0.0004} />
      <pointLight ref={bRef} position={[-3.5,1.5,2.5]} color="#2a78ff" intensity={22} distance={8} />
      <pointLight ref={cRef} position={[ 3.5,2.5,-1.5]} color="#12e5ff" intensity={18} distance={7} />
      <pointLight position={[0,-0.5,1.5]} color="#1af5ff" intensity={8} distance={3} />
    </>
  );
}

/* ── 3-D Scene ───────────────────────────────────────── */
function Scene({ command, onReady, energetic }) {
  return (
    <Canvas
      shadows dpr={[1,2]}
      camera={{ position:[0,0.9,5.6], fov:38, near:0.1, far:100 }}
      gl={{ antialias:true, alpha:false, powerPreference:'high-performance',
            toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.15 }}
    >
      <color attach="background" args={['#060d18']} />
      <fog attach="fog" args={['#060d18',10,22]} />
      <SceneLights />
      <Ground />
      <Sparkles
        count={energetic?90:28} scale={[3.5,4.5,3.5]} position={[0,0.5,0]}
        size={energetic?3.5:1.8} speed={energetic?0.5:0.18}
        opacity={energetic?0.65:0.18} color="#4aefff" noise={0.3}
      />
      <Suspense fallback={null}>
        <RobotModel command={command} onReady={onReady} />
      </Suspense>
      <ContactShadows position={[0,-1.34,0]} opacity={0.55} scale={5} blur={3} far={2.5} resolution={512} />
      <OrbitControls makeDefault target={[0,0.3,0]} enablePan={false}
        minDistance={3.5} maxDistance={9}
        minPolarAngle={Math.PI*0.2} maxPolarAngle={Math.PI*0.7}
        rotateSpeed={0.5} />
    </Canvas>
  );
}

/* ── App ─────────────────────────────────────────────── */
export default function App() {
  const [command,       setCommand      ] = useState(null);
  const [currentAction, setCurrentAction] = useState('idle');
  const [busy,          setBusy         ] = useState(false);
  const [robotReady,    setRobotReady   ] = useState(false);
  const [message,       setMessage      ] = useState('Hello! I am Nova.');
  const [panelOpen,     setPanelOpen    ] = useState(false);
  const [speaking,      setSpeaking     ] = useState(false);
  const [audienceOpen,  setAudienceOpen ] = useState(false);
  const [selectedAud,   setSelectedAud  ] = useState(null);
  const [caption,       setCaption      ] = useState(null);

  const wsRef   = useRef(null);
  const retryTm = useRef(null);
  const alive   = useRef(true);

  /* WebSocket */
  useEffect(() => {
    alive.current = true;
    let go = true;
    const wsBase = API_BASE.replace(/^http:/,'ws:').replace(/^https:/,'wss:');
    const connect = () => {
      if (!go) return;
      const q  = API_TOKEN ? `?token=${encodeURIComponent(API_TOKEN)}` : '';
      const ws = new WebSocket(`${wsBase}/ws/robots/${ROBOT_ID}${q}`);
      wsRef.current = ws;
      ws.onopen = () => { if (alive.current) ws.send(JSON.stringify({event:'ping'})); };
      ws.onmessage = ({ data }) => {
        try {
          const p = JSON.parse(data);
          if (p.event === 'action') {
            setCommand(p); setCurrentAction(p.action);
            // Show audience selector when a greet action arrives (pipeline trigger)
            if (p.action === 'greet') {
              setAudienceOpen(true);
              setSelectedAud(null);
              // Auto-close after 5s timeout → default to visitor
              setTimeout(() => {
                setAudienceOpen(prev => {
                  if (prev) {
                    // Still open = no selection made, send visitor
                    fetch(`${API_BASE}/api/robots/${ROBOT_ID}/audience`, {
                      method: 'POST', headers: authHeaders(),
                      body: JSON.stringify({ audience: 'visitor' }),
                    }).catch(() => {});
                    setSelectedAud('visitor');
                  }
                  return false;
                });
              }, 5000);
            }
            if (p.action === 'speak' && p.text) {
              setCaption({ question: p.params?.question || null, answer: p.text });
              // Ensure browser speech synthesis is muted - audio is played exclusively by Kokoro af_bella @ 24kHz via the kiosk speaker sink
              if ('speechSynthesis' in window) {
                window.speechSynthesis.cancel();
              }
              setSpeaking(true);
              setCurrentAction('speak');
              // Animate 3D robot face/speech for answer duration (~360ms/word, 2.5s - 15s)
              const wordCount = p.text.trim().split(/\s+/).length;
              const durationMs = Math.max(2500, Math.min(15000, wordCount * 360));
              setTimeout(() => {
                setSpeaking(false);
                setCurrentAction('idle');
                setTimeout(() => setCaption(null), 2500);
              }, durationMs);
            }
          }
        } catch { /**/ }
      };
      ws.onclose = () => { if (alive.current && go) retryTm.current = setTimeout(connect, 1800); };
    };
    connect();
    return () => {
      alive.current = false; go = false;
      clearTimeout(retryTm.current); wsRef.current?.close();
      if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    };
  }, []);

  /* Initial state */
  useEffect(() => {
    fetch(`${API_BASE}/api/robots/${ROBOT_ID}/state`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(s => { if (s) setCurrentAction(s.last_action||'idle'); })
      .catch(() => {});
  }, []);

  /* Send */
  const send = useCallback(async (action, extras={}) => {
    setBusy(true);
    try { await triggerAction(action, extras); setCurrentAction(action); }
    catch { /**/ }
    finally { setBusy(false); }
  }, []);

  const handleSpeak = (e) => {
    e.preventDefault();
    const text = message.trim();
    if (text) send('speak', { text });
  };

  const handleAudiencePick = async (aud) => {
    setSelectedAud(aud);
    setAudienceOpen(false);
    try {
      await fetch(`${API_BASE}/api/robots/${ROBOT_ID}/audience`, {
        method: 'POST', headers: authHeaders(),
        body: JSON.stringify({ audience: aud }),
      });
    } catch { /**/ }
  };

  const energetic = ['celebrate','dance','attention'].includes(currentAction);
  const actionList = ['greet','wave','nod','think','celebrate','bow','dance','point','shrug','attention','idle'];

  return (
    <div className="shell">
      {/* Full-screen 3D */}
      <div className="canvas-wrap">
        <Scene command={command} onReady={()=>setRobotReady(true)} energetic={energetic} />
      </div>

      {/* Loading */}
      {!robotReady && (
        <div className="loader">
          <div className="loader-ring" />
        </div>
      )}

      {/* Audience selector overlay */}
      {audienceOpen && (
        <div className="audience-overlay">
          <div className="audience-card">
            <h3>Who are you?</h3>
            <div className="audience-grid">
              {[
                { key: 'parent',  icon: '👨‍👩‍👧', label: 'Parent' },
                { key: 'student', icon: '🎒',     label: 'Student' },
                { key: 'teacher', icon: '👩‍🏫', label: 'Teacher' },
                { key: 'visitor', icon: '🏫',     label: 'Visitor' },
              ].map(opt => (
                <button
                  key={opt.key}
                  className={`audience-btn${selectedAud === opt.key ? ' audience-btn--on' : ''}`}
                  onClick={() => handleAudiencePick(opt.key)}
                >
                  <span className="audience-icon">{opt.icon}</span>
                  <span className="audience-lbl">{opt.label}</span>
                </button>
              ))}
            </div>
            <p className="audience-hint">Auto-selects Visitor in 5 seconds</p>
          </div>
        </div>
      )}

      {/* Question & Answer Subtitle Banner */}
      {caption && (
        <div className="qa-banner">
          {caption.question && (
            <div className="qa-question">
              <span className="qa-tag">YOU ASKED</span> {caption.question}
            </div>
          )}
          <div className="qa-answer">
            <span className="qa-tag-robot">NOVA</span> {caption.answer}
          </div>
        </div>
      )}

      {/* Toggle pill */}
      <button className="toggle-pill" onClick={()=>setPanelOpen(v=>!v)} aria-label="Toggle controls">
        {panelOpen ? '✕' : '⚙'}
      </button>

      {/* Floating control drawer */}
      <aside className={`drawer${panelOpen?' drawer--open':''}`}>
        {/* Action grid */}
        <div className="action-grid">
          {actionList.map(key => {
            const def    = ACTIONS[key];
            const active = currentAction === key && key !== 'idle';
            return (
              <button
                key={key}
                className={`act-btn${active?' act-btn--on':''}`}
                disabled={busy}
                onClick={() => send(key)}
                title={def.label}
                aria-label={def.label}
              >
                <span className="act-icon">{def.icon}</span>
                <span className="act-lbl">{def.label}</span>
              </button>
            );
          })}
        </div>

        {/* Speak form */}
        <form className="speak-form" onSubmit={handleSpeak}>
          <input
            value={message}
            maxLength={500}
            onChange={e=>setMessage(e.target.value)}
            placeholder="Say something…"
            autoComplete="off"
          />
          <button type="submit" disabled={busy || speaking} aria-label="Speak">
            {speaking ? '⏸' : '▶'}
          </button>
        </form>
      </aside>
    </div>
  );
}
