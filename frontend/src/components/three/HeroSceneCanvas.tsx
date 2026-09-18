// frontend/src/components/three/HeroSceneCanvas.tsx
// AIRP -- landing hero 3D scene (B10)
//
// The actual react-three-fiber content, isolated into its own module so
// HeroScene.tsx can React.lazy()-import it -- three.js/@react-three/
// fiber/@react-three/drei only ever enter the bundle (and the browser)
// for a visitor whose device actually renders them (see HeroScene.tsx's
// capability gate), never as part of the initial page load's JS payload.
//
// Deliberately simple: one low-poly icosahedron with drei's <Float> for
// a gentle idle bob/rotation, lit by two plain directional lights plus
// ambient fill -- no HDRI environment map (drei's <Environment> presets
// fetch a texture from a third-party CDN at runtime, an external network
// dependency this landing page's core render path should never depend
// on) and no texture assets at all. This is a finance product, not a
// game; the brief is "tasteful", not "elaborate", and a light scene
// keeps frame time low on integrated GPUs, per the work order's
// "must degrade gracefully on low-end/mobile" constraint.

import { Float } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";

/** Matches tailwind.config.ts's brand.500 -- kept as a literal since three.js materials take raw colour values, not CSS classes. */
const BRAND_COLOR = "#7C3AED";
const ACCENT_LIGHT_COLOR = "#AD98F7";

function IcosahedronMesh(): JSX.Element {
  return (
    <Float speed={1.4} rotationIntensity={0.6} floatIntensity={0.8}>
      <mesh>
        <icosahedronGeometry args={[1.6, 1]} />
        <meshStandardMaterial color={BRAND_COLOR} roughness={0.35} metalness={0.15} />
      </mesh>
    </Float>
  );
}

/** The landing hero's 3D scene: one gently floating icosahedron. Lazily mounted by HeroScene.tsx. */
export default function HeroSceneCanvas(): JSX.Element {
  return (
    <Canvas
      camera={{ position: [0, 0, 5], fov: 40 }}
      dpr={[1, 1.5]}
      gl={{ antialias: true, alpha: true }}
    >
      <ambientLight intensity={0.7} />
      <directionalLight position={[3, 4, 3]} intensity={1.4} />
      <directionalLight position={[-3, -2, -3]} intensity={0.3} color={ACCENT_LIGHT_COLOR} />
      <IcosahedronMesh />
    </Canvas>
  );
}
