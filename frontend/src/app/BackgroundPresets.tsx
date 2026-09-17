import type { CSSProperties } from "react";

/** Геометрия из backgrounds-collection/floating-paths.tsx; движение выполняет CSS. */
export function FloatingPaths() {
  return <svg className="background-svg floating-paths" viewBox="0 0 696 316" preserveAspectRatio="xMidYMid slice" fill="none">
    {Array.from({ length: 36 }, (_, i) => <path key={i}
      d={`M-${380 - i * 5} -${189 + i * 6}C-${380 - i * 5} -${189 + i * 6} -${312 - i * 5} ${216 - i * 6} ${152 - i * 5} ${343 - i * 6}C${616 - i * 5} ${470 - i * 6} ${684 - i * 5} ${875 - i * 6} ${684 - i * 5} ${875 - i * 6}`}
      stroke="currentColor" strokeWidth={0.5 + i * 0.03} opacity={0.1 + i * 0.025}
      pathLength="1" strokeDasharray=".65 .35" style={{ animationDelay: `${-i}s` }} />)}
  </svg>;
}

// Фиксированная раскладка сохраняет рисунок при переключении движения и перерендерах.
const fraction = (i: number, salt: number) => ((i * salt + 37) % 997) / 997;
const nodes = Array.from({ length: 90 }, (_, i) => ({ x: fraction(i, 293) * 1440, y: fraction(i, 439) * 900 }));
const chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ@#$%&*()";

/** ASCII-узлы, связи и восходящие лучи из particle-drift.tsx без оболочки демостраницы. */
export function ParticleDrift() {
  return <svg className="background-svg particle-drift" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice" fill="none">
    <g className="particle-nodes">
      {nodes.flatMap((node, i) => nodes.slice(i + 1).map((other, j) => {
        const distance = Math.hypot(node.x - other.x, node.y - other.y);
        return distance < 120 ? <line key={`${i}-${j}`} x1={node.x} y1={node.y} x2={other.x} y2={other.y}
          stroke="currentColor" strokeWidth=".5" opacity={0.5 * (1 - distance / 120)} /> : null;
      }))}
      {nodes.map((node, i) => <text key={i} x={node.x} y={node.y} fill="currentColor" opacity=".7">{chars[i % chars.length]}</text>)}
    </g>
    {Array.from({ length: 25 }, (_, i) => <path key={i} className="particle-beam"
      d={`M${fraction(i, 173) * 1440} 0v${50 + fraction(i, 317) * 100}`} stroke="currentColor" strokeWidth="1.5"
      opacity={0.3 + fraction(i, 113) * 0.5}
      style={{ "--beam-y": `${fraction(i, 367) * 900}px`, animationDelay: `${-fraction(i, 367) * 30}s` } as CSSProperties} />)}
  </svg>;
}
