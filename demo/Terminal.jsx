import { useCurrentFrame, useVideoConfig, interpolate } from 'remotion';

const C = {
  bg: '#0a0f1a',
  green: '#22c55e',
  red: '#ef4444',
  amber: '#f59e0b',
  purple: '#a5b4fc',
  muted: '#64748b',
  white: '#f1f5f9',
  dim: '#94a3b8',
  cyan: '#67e8f9',
  blue: '#60a5fa',
};

const LINES = [
  // User prompt
  { text: 'you > Fix the login bug in auth.ts', color: C.blue, delay: 0, bold: true },
  { text: '', delay: 8 },

  // Claude tries to edit without reading
  { text: 'claude > I\'ll fix the validateToken function...', color: C.dim, delay: 14 },
  { text: '', delay: 20 },
  { text: '  [Edit] src/auth.ts', color: C.cyan, delay: 24 },
  { text: '', delay: 28 },
  { text: '  BLOCKED  Cannot edit src/auth.ts', color: C.red, delay: 32, bold: true },
  { text: '           Read it first. (violation #1)', color: C.red, delay: 36 },
  { text: '', delay: 42 },

  // Claude reads, then edits
  { text: 'claude > Let me read the file first.', color: C.dim, delay: 48 },
  { text: '  [Read] src/auth.ts', color: C.cyan, delay: 54 },
  { text: '  [Edit] src/auth.ts', color: C.cyan, delay: 62 },
  { text: '         Edit allowed', color: C.green, delay: 66 },
  { text: '', delay: 72 },

  // Commit blocked — untested
  { text: 'claude > Done. Committing the fix.', color: C.dim, delay: 78 },
  { text: '  [Bash] git commit -m "fix token validation"', color: C.cyan, delay: 84 },
  { text: '', delay: 88 },
  { text: '  BLOCKED  Changed files have no test coverage.', color: C.red, delay: 92, bold: true },
  { text: '           x src/auth.ts', color: C.red, delay: 96 },
  { text: '             expected: auth.test.ts', color: C.muted, delay: 100 },
  { text: '', delay: 106 },

  // Runs tests, commits
  { text: 'claude > Running auth tests first.', color: C.dim, delay: 112 },
  { text: '  [Bash] npx jest auth.test.ts', color: C.cyan, delay: 118 },
  { text: '         PASS  3 passed', color: C.green, delay: 124 },
  { text: '  [Bash] git commit -m "fix token validation"', color: C.cyan, delay: 132 },
  { text: '         Commit allowed (1 file covered)', color: C.green, delay: 138 },
  { text: '', delay: 146 },

  // Scorecard
  { text: '  +------------------------------------------------+', color: C.purple, delay: 156 },
  { text: '  |  AGENT SCORECARD          Score: 8.0 / 10      |', color: C.purple, delay: 160, bold: true },
  { text: '  +------------------------------------------------+', color: C.purple, delay: 162 },
  { text: '  |  x Edits read first:   1 / 2          50%      |', color: C.white, delay: 166 },
  { text: '  |  + Commits with tests: 1 / 1         100%      |', color: C.white, delay: 170 },
  { text: '  |  Violations blocked:   2                        |', color: C.amber, delay: 174 },
  { text: '  +------------------------------------------------+', color: C.purple, delay: 178 },
  { text: '', delay: 186 },
  { text: '  blackbox  github.com/cgallic/blackbox', color: C.muted, delay: 192 },
];

function TerminalLine({ text, color, bold, frame, delay }) {
  if (frame < delay) return null;
  if (!text) return <div style={{ height: 20 }} />;

  let displayText = text;
  if (delay === 0 && frame < delay + 20) {
    const chars = Math.floor(interpolate(frame, [delay, delay + 20], [0, text.length], { extrapolateRight: 'clamp' }));
    displayText = text.slice(0, chars);
  }

  return (
    <div style={{
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      fontSize: 13,
      lineHeight: '20px',
      color: color || C.dim,
      fontWeight: bold ? 700 : 400,
      whiteSpace: 'pre',
    }}>
      {displayText}
    </div>
  );
}

export function GateDemo() {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const opacity = interpolate(frame, [0, 8], [0, 1], { extrapolateRight: 'clamp' });

  return (
    <div style={{ width, height, background: C.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', opacity }}>
      <div style={{ width: 660, borderRadius: 12, overflow: 'hidden', boxShadow: '0 32px 80px rgba(0,0,0,0.8)', border: '1px solid rgba(255,255,255,0.09)' }}>
        <div style={{ background: '#161b2e', padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 8, borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
          <div style={{ width: 12, height: 12, borderRadius: 6, background: '#ff5f57' }} />
          <div style={{ width: 12, height: 12, borderRadius: 6, background: '#febc2e' }} />
          <div style={{ width: 12, height: 12, borderRadius: 6, background: '#28c840' }} />
          <span style={{ marginLeft: 'auto', fontSize: 11, color: '#475569', fontFamily: 'monospace' }}>blackbox -- claude code</span>
        </div>
        <div style={{ background: '#0d1117', padding: '16px 20px 22px', minHeight: 440 }}>
          {LINES.map((line, i) => <TerminalLine key={i} frame={frame} {...line} />)}
        </div>
      </div>
    </div>
  );
}
