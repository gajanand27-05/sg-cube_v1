import { Canvas, useFrame } from "@react-three/fiber";
import { Text } from "@react-three/drei";
import { EffectComposer, Bloom } from "@react-three/postprocessing";
import { useMemo, useRef } from "react";
import * as THREE from "three";

const CYAN = "#22d3ee";
const CYAN_GLOW = "#67e8f9";
const CYAN_DIM = "#0891b2";
const NAVY = "rgba(10, 28, 50, 0.75)";
const NAVY_STROKE = "rgba(34, 211, 238, 0.35)";

const CX = 200;
const CY = 200;

function polar(r: number, deg: number): [number, number] {
  const a = (deg * Math.PI) / 180;
  return [CX + r * Math.cos(a), CY + r * Math.sin(a)];
}

function arcSegment(rIn: number, rOut: number, startDeg: number, endDeg: number) {
  const [x1o, y1o] = polar(rOut, startDeg);
  const [x2o, y2o] = polar(rOut, endDeg);
  const [x1i, y1i] = polar(rIn, endDeg);
  const [x2i, y2i] = polar(rIn, startDeg);
  const large = endDeg - startDeg > 180 ? 1 : 0;
  return `M ${x1o} ${y1o} A ${rOut} ${rOut} 0 ${large} 1 ${x2o} ${y2o} L ${x1i} ${y1i} A ${rIn} ${rIn} 0 ${large} 0 ${x2i} ${y2i} Z`;
}

function donutPath(rIn: number, rOut: number) {
  return (
    `M ${CX + rOut} ${CY} A ${rOut} ${rOut} 0 1 0 ${CX - rOut} ${CY} A ${rOut} ${rOut} 0 1 0 ${CX + rOut} ${CY} Z ` +
    `M ${CX + rIn} ${CY} A ${rIn} ${rIn} 0 1 1 ${CX - rIn} ${CY} A ${rIn} ${rIn} 0 1 1 ${CX + rIn} ${CY} Z`
  );
}

interface ArcRingProps {
  count: number;
  rIn: number;
  rOut: number;
  arcDeg: number;
  gapDeg: number;
  fill: string;
  phase?: number;
}
function ArcSegments({ count, rIn, rOut, arcDeg, gapDeg, fill, phase = 0 }: ArcRingProps) {
  const step = arcDeg + gapDeg;
  return (
    <g fill={fill}>
      {Array.from({ length: count }, (_, i) => {
        const start = i * step + phase;
        return <path key={i} d={arcSegment(rIn, rOut, start, start + arcDeg)} />;
      })}
    </g>
  );
}

function DotsRing({
  count,
  r,
  dotR,
  fill,
  opacity = 1,
}: {
  count: number;
  r: number;
  dotR: number;
  fill: string;
  opacity?: number;
}) {
  return (
    <g fill={fill} opacity={opacity}>
      {Array.from({ length: count }, (_, i) => {
        const [x, y] = polar(r, (i / count) * 360);
        return <circle key={i} cx={x} cy={y} r={dotR} />;
      })}
    </g>
  );
}

function BarcodeTicks({ angle }: { angle: number }) {
  const offsets = [-14, -10, -6, -2, 2, 6, 10, 14];
  return (
    <g transform={`rotate(${angle} ${CX} ${CY})`} fill={CYAN}>
      {offsets.map((o) => (
        <rect key={o} x={CX + o - 0.5} y={5} width={1} height={11} opacity={0.85} />
      ))}
    </g>
  );
}

function CardinalArrow({ angle }: { angle: number }) {
  return (
    <g transform={`rotate(${angle} ${CX} ${CY})`}>
      <polygon points={`${CX - 5},22 ${CX + 5},22 ${CX},32`} fill={CYAN_GLOW} />
    </g>
  );
}

function HUDRings() {
  const spinStyle = { transformBox: "fill-box", transformOrigin: "center" } as const;

  return (
    <svg
      className="absolute inset-0 w-full h-full pointer-events-none"
      viewBox="0 0 400 400"
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <radialGradient id="rimGlow" cx="50%" cy="50%" r="50%">
          <stop offset="72%" stopColor="rgba(34,211,238,0)" />
          <stop offset="100%" stopColor="rgba(34,211,238,0.18)" />
        </radialGradient>
      </defs>

      {/* Outer rim soft glow */}
      <circle cx={CX} cy={CY} r={198} fill="url(#rimGlow)" />

      {/* --- STATIC OUTER SHELL --- */}
      <g>
        {/* Dark navy band with subtle cyan edges */}
        <path
          d={donutPath(168, 190)}
          fill={NAVY}
          fillRule="evenodd"
          stroke={NAVY_STROKE}
          strokeWidth={0.5}
        />
        {/* Barcode tick clusters at cardinals */}
        <BarcodeTicks angle={0} />
        <BarcodeTicks angle={90} />
        <BarcodeTicks angle={180} />
        <BarcodeTicks angle={270} />
        {/* Cardinal arrows pointing inward */}
        <CardinalArrow angle={0} />
        <CardinalArrow angle={180} />
      </g>

      {/* --- LAYER 1: outer thick arc segments (CW slow) --- */}
      <g className="animate-spin-slow" style={spinStyle}>
        <ArcSegments
          count={4}
          rIn={148}
          rOut={165}
          arcDeg={62}
          gapDeg={28}
          fill="rgba(34,211,238,0.85)"
        />
      </g>

      {/* --- LAYER 2: outer dots ring (CW medium) --- */}
      <g className="animate-spin-medium" style={spinStyle}>
        <DotsRing count={72} r={132} dotR={2} fill="#e0f2fe" opacity={0.95} />
      </g>

      {/* --- LAYER 3: inner thick arc segments (CCW slow) --- */}
      <g className="animate-spin-slow-reverse" style={spinStyle}>
        <ArcSegments
          count={4}
          rIn={102}
          rOut={118}
          arcDeg={55}
          gapDeg={35}
          fill="rgba(34,211,238,0.85)"
          phase={22}
        />
      </g>

      {/* --- LAYER 4: inner dots ring (CCW medium) --- */}
      <g className="animate-spin-medium-reverse" style={spinStyle}>
        <DotsRing count={54} r={88} dotR={1.6} fill="#67e8f9" opacity={0.9} />
      </g>

      {/* --- LAYER 5: small inner accent segments (CCW fast) --- */}
      <g className="animate-spin-fast-reverse" style={spinStyle}>
        <ArcSegments
          count={2}
          rIn={72}
          rOut={78}
          arcDeg={40}
          gapDeg={140}
          fill="rgba(103,232,249,0.7)"
        />
      </g>
    </svg>
  );
}

function Cube() {
  const group = useRef<THREE.Group>(null!);
  useFrame((_, delta) => {
    group.current.rotation.y += delta * 0.3;
    group.current.rotation.x += delta * 0.12;
  });

  return (
    <group ref={group}>
      <mesh>
        <boxGeometry args={[2, 2, 2]} />
        <meshBasicMaterial color={CYAN_DIM} transparent opacity={0.04} />
      </mesh>

      <lineSegments>
        <wireframeGeometry args={[new THREE.BoxGeometry(2, 2, 2, 3, 3, 3)]} />
        <lineBasicMaterial color={CYAN} transparent opacity={0.35} />
      </lineSegments>

      <lineSegments>
        <edgesGeometry args={[new THREE.BoxGeometry(2, 2, 2)]} />
        <lineBasicMaterial color={CYAN_GLOW} transparent opacity={1} />
      </lineSegments>

      <Text
        fontSize={0.8}
        color={CYAN_GLOW}
        anchorX="center"
        anchorY="middle"
        letterSpacing={-0.05}
        outlineWidth={0.02}
        outlineColor={CYAN}
      >
        SG
      </Text>
    </group>
  );
}

function Particles({ count = 80 }: { count?: number }) {
  const points = useRef<THREE.Points>(null!);
  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const r = 1.3 + Math.random() * 1.2;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      arr[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      arr[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      arr[i * 3 + 2] = r * Math.cos(phi);
    }
    return arr;
  }, [count]);
  useFrame((_, delta) => {
    points.current.rotation.y += delta * 0.05;
  });
  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} count={count} />
      </bufferGeometry>
      <pointsMaterial color={CYAN_GLOW} size={0.03} transparent opacity={0.7} sizeAttenuation />
    </points>
  );
}

export function CubeVisualization() {
  return (
    <div className="relative w-full h-full min-h-[260px] flex items-center justify-center">
      <HUDRings />
      <Canvas
        className="relative"
        camera={{ position: [3.8, 2.6, 4.4], fov: 45 }}
        gl={{ alpha: true, antialias: true }}
        dpr={[1, 2]}
      >
        <ambientLight intensity={0.4} />
        <pointLight position={[4, 4, 4]} color={CYAN} intensity={3} />
        <pointLight position={[-4, -3, -4]} color={CYAN} intensity={1.5} />
        <Cube />
        <Particles />
        <EffectComposer>
          <Bloom
            intensity={1.4}
            luminanceThreshold={0.15}
            luminanceSmoothing={0.85}
            mipmapBlur
          />
        </EffectComposer>
      </Canvas>
    </div>
  );
}
