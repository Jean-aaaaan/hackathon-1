// ============================================================
// BMAD Live Visualization — Main Application v2
// Canvas room renderer, pathfinding, WebSocket, animations
// Fixed rendering + drama effects + relax room + breaks
// ============================================================

(function () {
  'use strict';

  const { AGENTS, ZONES, FURNITURE, ROOM_COLS, ROOM_ROWS, TILE_SIZE, PIXEL_SCALE, SPRITE_W, SPRITE_H } = window.BMAD;

  // ============================================================
  // Constants
  // ============================================================

  const RENDER_SCALE = 3;
  const CANVAS_W = ROOM_COLS * TILE_SIZE;
  const CANVAS_H = ROOM_ROWS * TILE_SIZE;
  const TYPEWRITER_SPEED = 25;
  const SPEECH_DURATION = 6000;
  const CONFETTI_COUNT = 30;

  // ============================================================
  // State
  // ============================================================

  let activeAgent = null;
  let previousAgent = null;
  let gateStatus = {};
  let ws = null;
  let wsReconnectDelay = 3000;
  let lastEventTs = null;
  let particles = [];
  let now = 0;
  let screenShake = { x: 0, y: 0, intensity: 0 };
  let screenFlash = { color: null, alpha: 0 };
  let breakingAgents = new Set(); // agents currently on break
  let thinkingAgents = {}; // agents showing thinking dots

  // ============================================================
  // Canvas Setup
  // ============================================================

  const canvas = document.getElementById('room-canvas');
  const ctx = canvas.getContext('2d');

  // Set canvas to fixed pixel dimensions
  canvas.width = CANVAS_W * RENDER_SCALE;
  canvas.height = CANVAS_H * RENDER_SCALE;

  // Size canvas element to fit container while maintaining aspect ratio
  function resizeCanvas() {
    const container = document.getElementById('room-container');
    const containerW = container.clientWidth;
    const containerH = container.clientHeight;
    const aspect = CANVAS_W / CANVAS_H;
    let displayW, displayH;

    if (containerW / containerH > aspect) {
      displayH = Math.min(containerH - 20, canvas.height);
      displayW = displayH * aspect;
    } else {
      displayW = Math.min(containerW - 20, canvas.width);
      displayH = displayW / aspect;
    }

    canvas.style.width = displayW + 'px';
    canvas.style.height = displayH + 'px';
  }

  window.addEventListener('resize', resizeCanvas);
  ctx.imageSmoothingEnabled = false;

  // ============================================================
  // Pathfinding Grid
  // ============================================================

  const grid = [];
  for (let y = 0; y < ROOM_ROWS; y++) {
    grid[y] = [];
    for (let x = 0; x < ROOM_COLS; x++) {
      grid[y][x] = 0;
    }
  }

  for (const f of FURNITURE) {
    for (let dy = 0; dy < f.h; dy++) {
      for (let dx = 0; dx < f.w; dx++) {
        const gx = f.x + dx;
        const gy = f.y + dy;
        if (gy >= 0 && gy < ROOM_ROWS && gx >= 0 && gx < ROOM_COLS) {
          grid[gy][gx] = 1;
        }
      }
    }
  }

  // A* pathfinding
  function findPath(sx, sy, ex, ey) {
    sx = Math.max(0, Math.min(ROOM_COLS - 1, Math.round(sx)));
    sy = Math.max(0, Math.min(ROOM_ROWS - 1, Math.round(sy)));
    ex = Math.max(0, Math.min(ROOM_COLS - 1, Math.round(ex)));
    ey = Math.max(0, Math.min(ROOM_ROWS - 1, Math.round(ey)));

    if (grid[ey] && grid[ey][ex] === 1) {
      let best = null, bestDist = Infinity;
      for (let dy = -3; dy <= 3; dy++) {
        for (let dx = -3; dx <= 3; dx++) {
          const nx = ex + dx, ny = ey + dy;
          if (ny >= 0 && ny < ROOM_ROWS && nx >= 0 && nx < ROOM_COLS && grid[ny][nx] === 0) {
            const d = Math.abs(dx) + Math.abs(dy);
            if (d < bestDist) { bestDist = d; best = { x: nx, y: ny }; }
          }
        }
      }
      if (best) { ex = best.x; ey = best.y; }
    }

    if (sx === ex && sy === ey) return [];

    const open = [{ x: sx, y: sy, g: 0, h: 0, f: 0, parent: null }];
    const closed = new Set();
    const key = (x, y) => (x << 16) | y;

    while (open.length > 0) {
      let li = 0;
      for (let i = 1; i < open.length; i++) {
        if (open[i].f < open[li].f) li = i;
      }
      const cur = open.splice(li, 1)[0];

      if (cur.x === ex && cur.y === ey) {
        const path = [];
        let n = cur;
        while (n.parent) { path.unshift({ x: n.x, y: n.y }); n = n.parent; }
        return path;
      }

      closed.add(key(cur.x, cur.y));

      for (const [dx, dy] of [[0,-1],[0,1],[-1,0],[1,0]]) {
        const nx = cur.x + dx, ny = cur.y + dy;
        if (nx < 0 || nx >= ROOM_COLS || ny < 0 || ny >= ROOM_ROWS) continue;
        if (grid[ny][nx] === 1 || closed.has(key(nx, ny))) continue;

        const g = cur.g + 1;
        const h = Math.abs(nx - ex) + Math.abs(ny - ey);
        const existing = open.find(n => n.x === nx && n.y === ny);
        if (!existing || g < existing.g) {
          if (existing) { existing.g = g; existing.f = g + h; existing.parent = cur; }
          else open.push({ x: nx, y: ny, g, h, f: g + h, parent: cur });
        }
      }
    }
    return [];
  }

  // ============================================================
  // Drawing Utilities
  // ============================================================

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  function fillCircle(x, y, r) {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  // ============================================================
  // Room Rendering
  // ============================================================

  const FLOOR_COLORS = ['#E8D5B7', '#E5D2B4'];
  const WALL_COLOR = '#D4C0A0';

  function drawRoom() {
    const s = RENDER_SCALE;

    // Floor tiles
    for (let y = 0; y < ROOM_ROWS; y++) {
      for (let x = 0; x < ROOM_COLS; x++) {
        ctx.fillStyle = FLOOR_COLORS[(x + y) % 2];
        ctx.fillRect(x * TILE_SIZE * s, y * TILE_SIZE * s, TILE_SIZE * s, TILE_SIZE * s);
      }
    }

    // Subtle grid lines
    ctx.strokeStyle = 'rgba(180, 160, 130, 0.15)';
    ctx.lineWidth = 0.5;
    for (let y = 0; y <= ROOM_ROWS; y++) {
      ctx.beginPath();
      ctx.moveTo(0, y * TILE_SIZE * s);
      ctx.lineTo(CANVAS_W * s, y * TILE_SIZE * s);
      ctx.stroke();
    }
    for (let x = 0; x <= ROOM_COLS; x++) {
      ctx.beginPath();
      ctx.moveTo(x * TILE_SIZE * s, 0);
      ctx.lineTo(x * TILE_SIZE * s, CANVAS_H * s);
      ctx.stroke();
    }

    // Zone overlays
    for (const [name, zone] of Object.entries(ZONES)) {
      if (zone.color === 'transparent') continue;
      ctx.fillStyle = zone.color;
      const zw = name === 'relax' ? 8 : 8;
      const zh = name === 'relax' ? 4 : 6;
      ctx.fillRect(
        (zone.x - 3) * TILE_SIZE * s,
        (zone.y - 2) * TILE_SIZE * s,
        zw * TILE_SIZE * s,
        zh * TILE_SIZE * s
      );

      if (zone.label) {
        ctx.fillStyle = 'rgba(74, 55, 40, 0.20)';
        ctx.font = `bold ${7 * s}px "Segoe UI", sans-serif`;
        ctx.textAlign = 'center';
        ctx.fillText(zone.label, (zone.x + 1) * TILE_SIZE * s, (zone.y - 2.5) * TILE_SIZE * s + 8 * s);
      }
    }

    // Walls
    ctx.fillStyle = WALL_COLOR;
    ctx.fillRect(0, 0, CANVAS_W * s, 2 * s);
    ctx.fillRect(0, 0, 2 * s, CANVAS_H * s);
    ctx.fillRect((CANVAS_W - 1) * s - 1, 0, 2 * s, CANVAS_H * s);
    ctx.fillRect(0, (CANVAS_H - 1) * s - 1, CANVAS_W * s, 2 * s);

    drawFurniture(s);
  }

  function drawFurniture(s) {
    for (const f of FURNITURE) {
      const px = f.x * TILE_SIZE * s;
      const py = f.y * TILE_SIZE * s;
      const pw = f.w * TILE_SIZE * s;
      const ph = f.h * TILE_SIZE * s;

      switch (f.type) {
        case 'table':
          ctx.fillStyle = '#B8860B';
          roundRect(px + 2*s, py + 2*s, pw - 4*s, ph - 4*s, 8*s);
          ctx.fill();
          // Table top highlight
          ctx.fillStyle = '#C9972C';
          roundRect(px + 6*s, py + 6*s, pw - 12*s, ph - 12*s, 6*s);
          ctx.fill();
          // Items on table
          ctx.fillStyle = '#FAFAFA';
          fillCircle(px + 18*s, py + 14*s, 3*s); // cup
          fillCircle(px + 55*s, py + 20*s, 3*s);
          fillCircle(px + 38*s, py + 42*s, 3*s);
          ctx.fillStyle = '#5C5C5C';
          ctx.fillRect(px + 28*s, py + 10*s, 12*s, 8*s); // laptop
          ctx.fillRect(px + 65*s, py + 30*s, 12*s, 8*s);
          // Papers
          ctx.fillStyle = '#FFF8DC';
          ctx.fillRect(px + 48*s, py + 12*s, 8*s, 10*s);
          ctx.fillRect(px + 20*s, py + 35*s, 8*s, 10*s);
          break;

        case 'desk':
          ctx.fillStyle = '#A08060';
          ctx.fillRect(px, py, pw, ph);
          ctx.fillStyle = '#8B6914';
          ctx.fillRect(px + 2*s, py + 2*s, pw - 4*s, ph - 4*s);
          break;

        case 'monitor': {
          ctx.fillStyle = '#2C2C2C';
          ctx.fillRect(px + 1*s, py + 1*s, 14*s, 11*s);
          const isCoding = activeAgent === 'Amelia';
          ctx.fillStyle = isCoding ? '#0D2818' : '#2A2A3A';
          ctx.fillRect(px + 2*s, py + 2*s, 12*s, 9*s);
          if (isCoding) {
            ctx.fillStyle = '#4ADE4A';
            for (let i = 0; i < 5; i++) {
              const w = (3 + Math.sin(now / 400 + i * 1.3) * 4) * s;
              ctx.fillRect(px + 3*s, py + (3 + i * 1.6) * s, w, 0.8*s);
            }
            // Cursor blink
            if (Math.sin(now / 300) > 0) {
              ctx.fillStyle = '#4ADE4A';
              ctx.fillRect(px + 10*s, py + 8*s, 1*s, 2*s);
            }
          }
          // Stand
          ctx.fillStyle = '#3C3C3C';
          ctx.fillRect(px + 6*s, py + 12*s, 4*s, 3*s);
          break;
        }

        case 'whiteboard':
          ctx.fillStyle = '#F8F8F8';
          ctx.fillRect(px, py, pw, ph);
          ctx.strokeStyle = '#BBBBBB';
          ctx.lineWidth = 2*s;
          ctx.strokeRect(px, py, pw, ph);
          // Colorful sticky notes
          const stickyColors = ['#FFE066', '#FF9EAA', '#87CEEB', '#98FB98', '#DDA0DD', '#FFB347'];
          for (let i = 0; i < 6; i++) {
            ctx.fillStyle = stickyColors[i];
            ctx.fillRect(px + (i * 24 + 4)*s, py + 2*s, 10*s, 10*s);
          }
          break;

        case 'plant': {
          const sway = Math.sin(now / 1500 + f.x * 7) * 1.5;
          ctx.fillStyle = '#C47A5A';
          ctx.fillRect(px + 3*s, py + 9*s, 10*s, 6*s);
          ctx.fillStyle = '#5BA55B';
          fillCircle(px + 8*s + sway*s, py + 5*s, 6*s);
          ctx.fillStyle = '#4A9A4A';
          fillCircle(px + 5*s + sway*s * 0.7, py + 3*s, 4*s);
          fillCircle(px + 11*s + sway*s * 0.5, py + 4*s, 4*s);
          break;
        }

        case 'bookshelf':
          ctx.fillStyle = '#8B6914';
          ctx.fillRect(px, py, pw, ph);
          ['#C0392B','#2980B9','#27AE60','#8E44AD','#E67E22','#1ABC9C'].forEach((c, i) => {
            ctx.fillStyle = c;
            ctx.fillRect(px + (i * 5 + 1)*s, py + 2*s, 3*s, 10*s);
          });
          break;

        case 'coffee': {
          ctx.fillStyle = '#4A4A4A';
          ctx.fillRect(px + 2*s, py + 3*s, 12*s, 10*s);
          ctx.fillStyle = '#8B4513';
          ctx.fillRect(px + 4*s, py + 5*s, 8*s, 3*s);
          // Animated steam
          const steamPhase = now / 600;
          ctx.fillStyle = 'rgba(200,200,200,0.3)';
          fillCircle(px + 6*s, py + (1 + Math.sin(steamPhase) * 1.5)*s, 2*s);
          fillCircle(px + 10*s, py + (0 + Math.sin(steamPhase + 1) * 1.5)*s, 1.5*s);
          break;
        }

        case 'water': {
          ctx.fillStyle = '#B0D4E8';
          ctx.fillRect(px + 3*s, py + 2*s, 10*s, 12*s);
          ctx.fillStyle = '#6BB5D8';
          ctx.fillRect(px + 4*s, py + 4*s, 8*s, 8*s);
          if (Math.sin(now / 1200 + 2) > 0.6) {
            ctx.fillStyle = 'rgba(255,255,255,0.5)';
            fillCircle(px + 7*s, py + (6 + Math.sin(now / 300) * 2)*s, 1.2*s);
            fillCircle(px + 10*s, py + (5 + Math.sin(now / 400) * 2)*s, 0.8*s);
          }
          break;
        }

        case 'beanbag':
          ctx.fillStyle = '#E8A840';
          fillCircle(px + 8*s, py + 8*s, 6*s);
          ctx.fillStyle = '#D4943A';
          fillCircle(px + 8*s, py + 9*s, 4*s);
          break;

        case 'couch':
          // Comfy pixel couch
          ctx.fillStyle = '#7B68AE';
          roundRect(px + 1*s, py + 2*s, pw - 2*s, ph - 4*s, 4*s);
          ctx.fill();
          ctx.fillStyle = '#6A5A9E';
          roundRect(px + 3*s, py + 4*s, pw - 6*s, ph - 8*s, 3*s);
          ctx.fill();
          // Pillows
          ctx.fillStyle = '#E8A840';
          fillCircle(px + 8*s, py + 6*s, 3*s);
          ctx.fillStyle = '#87CEEB';
          fillCircle(px + pw - 8*s, py + 6*s, 3*s);
          break;

        case 'tv':
          ctx.fillStyle = '#2C2C2C';
          ctx.fillRect(px + 1*s, py + 2*s, 14*s, 10*s);
          // Screen with moving content
          ctx.fillStyle = '#1A1A3A';
          ctx.fillRect(px + 2*s, py + 3*s, 12*s, 8*s);
          // Color bars or show
          const tvPhase = Math.floor(now / 2000) % 3;
          if (tvPhase === 0) {
            ['#FF4444','#44FF44','#4444FF','#FFFF44'].forEach((c, i) => {
              ctx.fillStyle = c;
              ctx.fillRect(px + (2 + i * 3)*s, py + 3*s, 3*s, 8*s);
            });
          } else {
            ctx.fillStyle = '#3A3A6A';
            ctx.fillRect(px + 3*s, py + 4*s, 10*s, 6*s);
          }
          break;

        case 'snacks':
          ctx.fillStyle = '#FFD700';
          ctx.fillRect(px + 2*s, py + 4*s, 12*s, 8*s);
          ctx.fillStyle = '#FF6347';
          fillCircle(px + 5*s, py + 6*s, 2*s);
          ctx.fillStyle = '#4ADE4A';
          fillCircle(px + 8*s, py + 7*s, 2*s);
          ctx.fillStyle = '#87CEEB';
          fillCircle(px + 11*s, py + 6*s, 2*s);
          break;
      }
    }
  }

  // ============================================================
  // Agent Rendering
  // ============================================================

  function drawAgent(agent) {
    const s = RENDER_SCALE;
    const bobY = Math.sin(now * 0.002 + agent.bobOffset) * 1.2 * s;
    const isOnBreak = breakingAgents.has(agent.name);

    // Agent pixel position (interpolated)
    const px = agent.x * TILE_SIZE * s;
    const py = agent.y * TILE_SIZE * s;

    // Glow effect
    if (agent.glowAlpha > 0.01) {
      const grad = ctx.createRadialGradient(
        px + 8*s, py + 8*s + bobY, 2*s,
        px + 8*s, py + 8*s + bobY, 24*s
      );
      const glowColor = isOnBreak ? '155,89,182' : '255,215,0';
      grad.addColorStop(0, `rgba(${glowColor},${agent.glowAlpha * 0.5})`);
      grad.addColorStop(1, `rgba(${glowColor},0)`);
      ctx.fillStyle = grad;
      ctx.fillRect(px - 16*s, py - 16*s + bobY, 48*s, 48*s);
    }

    // Draw sprite
    const sprite = agent.sprite;
    if (!sprite) return;

    const pixSz = s; // 1 sprite pixel = RENDER_SCALE canvas pixels
    const offsetX = px + (TILE_SIZE * s - SPRITE_W * pixSz) / 2;
    const offsetY = py + (TILE_SIZE * s - SPRITE_H * pixSz) / 2 + bobY;

    // Dim inactive agents
    const isInactive = !isOnBreak && agent.state === 'idle' && activeAgent && agent.name !== activeAgent;
    if (isInactive) ctx.globalAlpha = 0.6;
    if (isOnBreak) ctx.globalAlpha = 0.85;

    for (let row = 0; row < SPRITE_H; row++) {
      for (let col = 0; col < SPRITE_W; col++) {
        const val = sprite[row][col];
        if (val === 0) continue;

        let color;
        if (val === 7) color = agent.palette.eyes;
        else color = val; // direct color string

        if (color) {
          ctx.fillStyle = color;
          ctx.fillRect(
            Math.floor(offsetX + col * pixSz),
            Math.floor(offsetY + row * pixSz),
            pixSz + 0.5, // slight overlap to prevent gaps
            pixSz + 0.5
          );
        }
      }
    }

    ctx.globalAlpha = 1;

    // ZZZ for sleeping/break agents
    if (isOnBreak) {
      const zzz = 'zzZ';
      ctx.font = `bold ${6*s}px monospace`;
      ctx.fillStyle = '#9B59B6';
      ctx.textAlign = 'center';
      const floatY = Math.sin(now / 500) * 3 * s;
      ctx.globalAlpha = 0.6 + Math.sin(now / 400) * 0.3;
      ctx.fillText(zzz, px + 8*s, offsetY - 4*s + floatY);
      ctx.globalAlpha = 1;
    }

    // Thinking dots for active thinking agents
    if (thinkingAgents[agent.name]) {
      const dotCount = Math.floor(now / 400) % 4;
      ctx.fillStyle = agent.layerColor;
      for (let i = 0; i < 3; i++) {
        ctx.globalAlpha = i < dotCount ? 0.9 : 0.2;
        fillCircle(px + (4 + i * 4)*s, offsetY - 6*s, 1.5*s);
      }
      ctx.globalAlpha = 1;
    }

    // Name tag
    ctx.font = `bold ${5*s}px "Segoe UI", sans-serif`;
    ctx.textAlign = 'center';
    const tagX = px + 8*s;
    const tagY = offsetY + SPRITE_H * pixSz + 3*s;
    const nameW = ctx.measureText(agent.name).width;

    // Tag background
    const isActive = agent.name === activeAgent || isOnBreak;
    ctx.fillStyle = isActive ? agent.layerColor : 'rgba(255,248,240,0.9)';
    roundRect(tagX - nameW/2 - 3*s, tagY - 1*s, nameW + 6*s, 7*s, 3*s);
    ctx.fill();

    // Outline for active
    if (isActive) {
      ctx.strokeStyle = 'rgba(255,255,255,0.5)';
      ctx.lineWidth = 1;
      roundRect(tagX - nameW/2 - 3*s, tagY - 1*s, nameW + 6*s, 7*s, 3*s);
      ctx.stroke();
    }

    ctx.fillStyle = isActive ? '#FFF' : '#4A3728';
    ctx.fillText(agent.name, tagX, tagY + 4.5*s);

    // Role
    ctx.font = `${3.5*s}px "Segoe UI", sans-serif`;
    ctx.fillStyle = isActive ? 'rgba(255,255,255,0.8)' : '#7A6855';
    ctx.fillText(agent.role, tagX, tagY + 10*s);
  }

  // ============================================================
  // Proximity Halos
  // ============================================================

  function drawProximityHalos() {
    const s = RENDER_SCALE;
    const agents = Object.values(AGENTS);
    for (let i = 0; i < agents.length; i++) {
      for (let j = i + 1; j < agents.length; j++) {
        const a = agents[i], b = agents[j];
        if (a.state === 'idle' && b.state === 'idle') continue;
        const dist = Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
        if (dist <= 3 && dist > 0) {
          const cx = ((a.x + b.x) / 2) * TILE_SIZE * s + 8*s;
          const cy = ((a.y + b.y) / 2) * TILE_SIZE * s + 8*s;
          const grad = ctx.createRadialGradient(cx, cy, 2*s, cx, cy, 28*s);
          grad.addColorStop(0, 'rgba(255,215,0,0.15)');
          grad.addColorStop(1, 'rgba(255,215,0,0)');
          ctx.fillStyle = grad;
          fillCircle(cx, cy, 28*s);
        }
      }
    }
  }

  // ============================================================
  // Particles
  // ============================================================

  function spawnConfetti(x, y, count) {
    const s = RENDER_SCALE;
    const colors = ['#FF6B6B','#FFD93D','#6BCB77','#4D96FF','#9B59B6','#FF9EAA','#FFB347','#00CED1'];
    for (let i = 0; i < (count || CONFETTI_COUNT); i++) {
      particles.push({
        x: x * TILE_SIZE * s + (Math.random() * 16 - 8) * s,
        y: y * TILE_SIZE * s,
        vx: (Math.random() - 0.5) * 5 * s,
        vy: -(Math.random() * 4 + 2) * s,
        gravity: 0.12 * s,
        color: colors[i % colors.length],
        size: (2 + Math.random() * 4) * s,
        life: 1,
        decay: 0.01 + Math.random() * 0.008,
        rotation: Math.random() * Math.PI * 2,
        rotSpeed: (Math.random() - 0.5) * 0.3,
      });
    }
  }

  function spawnFlameParticles(x, y, count) {
    const s = RENDER_SCALE;
    const colors = ['#FF4500','#FF6347','#FFD700','#FF8C00','#FF0000','#FFA500'];
    for (let i = 0; i < (count || 15); i++) {
      particles.push({
        x: x * TILE_SIZE * s + 8*s + (Math.random() - 0.5) * 8*s,
        y: y * TILE_SIZE * s + 4*s,
        vx: (Math.random() - 0.5) * 3 * s,
        vy: -(Math.random() * 3 + 1) * s,
        gravity: -0.03 * s,
        color: colors[i % colors.length],
        size: (1.5 + Math.random() * 3) * s,
        life: 1,
        decay: 0.02 + Math.random() * 0.015,
        rotation: 0,
        rotSpeed: (Math.random() - 0.5) * 0.1,
      });
    }
  }

  function spawnSparkles(x, y) {
    const s = RENDER_SCALE;
    for (let i = 0; i < 12; i++) {
      const angle = (i / 12) * Math.PI * 2;
      particles.push({
        x: x * TILE_SIZE * s + 8*s,
        y: y * TILE_SIZE * s + 8*s,
        vx: Math.cos(angle) * 2.5 * s,
        vy: Math.sin(angle) * 2.5 * s,
        gravity: 0,
        color: '#FFD700',
        size: (1 + Math.random() * 2) * s,
        life: 1,
        decay: 0.025,
        rotation: 0,
        rotSpeed: 0,
      });
    }
  }

  function spawnHearts(x, y) {
    const s = RENDER_SCALE;
    for (let i = 0; i < 5; i++) {
      particles.push({
        x: x * TILE_SIZE * s + 8*s + (Math.random() - 0.5) * 10*s,
        y: y * TILE_SIZE * s,
        vx: (Math.random() - 0.5) * 1.5 * s,
        vy: -(Math.random() * 1.5 + 0.5) * s,
        gravity: -0.01 * s,
        color: '#FF69B4',
        size: (3 + Math.random() * 2) * s,
        life: 1,
        decay: 0.012,
        rotation: 0,
        rotSpeed: 0,
        isHeart: true,
      });
    }
  }

  function updateAndDrawParticles() {
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.x += p.vx;
      p.y += p.vy;
      p.vy += p.gravity;
      p.life -= p.decay;
      p.rotation += p.rotSpeed;

      if (p.life <= 0) { particles.splice(i, 1); continue; }

      ctx.save();
      ctx.globalAlpha = Math.min(1, p.life * 1.5);
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rotation);
      ctx.fillStyle = p.color;

      if (p.isHeart) {
        // Draw pixel heart
        const hs = p.size * 0.4;
        ctx.fillRect(-hs, -hs * 2, hs, hs);
        ctx.fillRect(hs, -hs * 2, hs, hs);
        ctx.fillRect(-hs * 2, -hs, hs, hs);
        ctx.fillRect(hs * 2, -hs, hs, hs);
        ctx.fillRect(-hs * 2, 0, hs * 5, hs);
        ctx.fillRect(-hs, hs, hs * 3, hs);
        ctx.fillRect(0, hs * 2, hs, hs);
      } else {
        ctx.fillRect(-p.size/2, -p.size/2, p.size, p.size);
      }
      ctx.restore();
    }
  }

  // ============================================================
  // Screen Effects
  // ============================================================

  function triggerScreenShake(intensity, duration) {
    screenShake.intensity = intensity || 8;
    screenShake.duration = duration || 500;
    screenShake.start = now;
  }

  function triggerScreenFlash(color, duration) {
    screenFlash.color = color || 'rgba(255,0,0,0.2)';
    screenFlash.alpha = 1;
    screenFlash.duration = duration || 400;
    screenFlash.start = now;
  }

  function updateScreenEffects() {
    const s = RENDER_SCALE;
    const viewport = document.getElementById('room-viewport');

    // Screen shake
    if (screenShake.intensity > 0) {
      const elapsed = now - screenShake.start;
      if (elapsed < screenShake.duration) {
        const decay = 1 - elapsed / screenShake.duration;
        screenShake.x = (Math.random() - 0.5) * screenShake.intensity * decay;
        screenShake.y = (Math.random() - 0.5) * screenShake.intensity * decay;
        viewport.style.transform = `translate(${screenShake.x}px, ${screenShake.y}px)`;
      } else {
        screenShake.intensity = 0;
        viewport.style.transform = '';
      }
    }

    // Screen flash overlay
    if (screenFlash.alpha > 0) {
      const elapsed = now - screenFlash.start;
      if (elapsed < screenFlash.duration) {
        screenFlash.alpha = 1 - elapsed / screenFlash.duration;
        ctx.fillStyle = screenFlash.color.replace(/[\d.]+\)$/, screenFlash.alpha * 0.3 + ')');
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      } else {
        screenFlash.alpha = 0;
      }
    }
  }

  // ============================================================
  // Agent Movement
  // ============================================================

  function moveAgentToZone(agentName, zoneName) {
    const agent = AGENTS[agentName];
    const zone = ZONES[zoneName];
    if (!agent || !zone) return;

    const ox = (Math.random() * 4 - 2) | 0;
    const oy = (Math.random() * 3 - 1) | 0;
    const tx = Math.max(1, Math.min(ROOM_COLS - 2, zone.x + ox));
    const ty = Math.max(1, Math.min(ROOM_ROWS - 2, zone.y + oy));

    agent.path = findPath(Math.round(agent.x), Math.round(agent.y), tx, ty);
    agent.pathIndex = 0;
    if (agent.path.length > 0) {
      agent.state = 'walking';
      agent.walkStartTime = now;
    }
  }

  function updateAgentMovement(agent, dt) {
    if (agent.state !== 'walking' || !agent.path || !agent.path.length) return;

    const speed = agent.walkSpeed * dt / 1000;
    const target = agent.path[agent.pathIndex];
    if (!target) {
      agent.state = agent.name === activeAgent ? 'active' : 'idle';
      agent.path = null;
      return;
    }

    const dx = target.x - agent.x;
    const dy = target.y - agent.y;
    const dist = Math.sqrt(dx * dx + dy * dy);

    if (dist < speed) {
      agent.x = target.x;
      agent.y = target.y;
      agent.pathIndex++;
      if (agent.pathIndex >= agent.path.length) {
        agent.state = agent.name === activeAgent ? 'active' : 'idle';
        agent.path = null;
      }
    } else {
      agent.x += (dx / dist) * speed;
      agent.y += (dy / dist) * speed;
      if (Math.abs(dx) > Math.abs(dy)) {
        agent.facing = dx > 0 ? 'right' : 'left';
      } else {
        agent.facing = dy > 0 ? 'down' : 'up';
      }
    }
  }

  function updateGlows(dt) {
    for (const agent of Object.values(AGENTS)) {
      const isActive = agent.name === activeAgent || breakingAgents.has(agent.name);
      const target = isActive ? 1 : 0;
      const speed = 4 * dt / 1000;
      agent.glowAlpha += (target - agent.glowAlpha) * Math.min(1, speed);
    }
  }

  // ============================================================
  // Speech Bubbles
  // ============================================================

  function showSpeechBubble(agentName, text, style) {
    const overlay = document.getElementById('speech-overlay');
    // Remove old bubbles
    overlay.querySelectorAll('.speech-bubble').forEach(b => {
      b.style.opacity = '0';
      setTimeout(() => b.remove(), 300);
    });

    const agent = AGENTS[agentName];
    if (!agent) return;

    const bubble = document.createElement('div');
    bubble.className = 'speech-bubble' + (style === 'challenge' ? ' challenge' : style === 'break' ? ' break-bubble' : '');
    bubble.style.borderColor = style === 'challenge' ? '#E74C3C' : style === 'break' ? '#9B59B6' : agent.layerColor;

    const header = document.createElement('div');
    header.className = 'bubble-agent';
    header.style.color = agent.layerColor;
    header.textContent = `${agent.name} (${agent.role})`;

    const textEl = document.createElement('div');
    textEl.className = 'bubble-text';

    const cursor = document.createElement('span');
    cursor.className = 'bubble-cursor';

    bubble.appendChild(header);
    bubble.appendChild(textEl);
    bubble.appendChild(cursor);
    overlay.appendChild(bubble);

    // Position relative to canvas
    positionBubble(bubble, agent);

    // Typewriter
    let idx = 0;
    const typeTimer = setInterval(() => {
      if (idx < text.length) {
        textEl.textContent = text.substring(0, ++idx);
        positionBubble(bubble, agent); // reposition as text grows
      } else {
        clearInterval(typeTimer);
        cursor.style.display = 'none';
      }
    }, TYPEWRITER_SPEED);

    // Dismiss
    const dur = Math.max(SPEECH_DURATION, text.length * TYPEWRITER_SPEED + 2500);
    setTimeout(() => {
      bubble.style.opacity = '0';
      bubble.style.transition = 'opacity 0.5s';
      setTimeout(() => bubble.remove(), 500);
    }, dur);
  }

  function positionBubble(bubble, agent) {
    const rect = canvas.getBoundingClientRect();
    const sx = rect.width / (CANVAS_W * RENDER_SCALE);
    const sy = rect.height / (CANVAS_H * RENDER_SCALE);

    const ax = agent.x * TILE_SIZE * RENDER_SCALE * sx + rect.left;
    const ay = agent.y * TILE_SIZE * RENDER_SCALE * sy + rect.top;
    const containerRect = canvas.parentElement.getBoundingClientRect();

    let left = ax - containerRect.left - 20;
    let top = ay - containerRect.top - bubble.offsetHeight - 15;

    // Keep on screen
    left = Math.max(5, Math.min(containerRect.width - 230, left));
    top = Math.max(5, top);

    bubble.style.left = left + 'px';
    bubble.style.top = top + 'px';
  }

  // ============================================================
  // Emotes
  // ============================================================

  function showEmote(agentName, emoji) {
    const agent = AGENTS[agentName];
    if (!agent) return;

    const emote = document.createElement('div');
    emote.className = 'emote';
    emote.textContent = emoji;

    const rect = canvas.getBoundingClientRect();
    const sx = rect.width / (CANVAS_W * RENDER_SCALE);
    const sy = rect.height / (CANVAS_H * RENDER_SCALE);
    const containerRect = canvas.parentElement.getBoundingClientRect();

    emote.style.left = (agent.x * TILE_SIZE * RENDER_SCALE * sx + rect.left - containerRect.left) + 'px';
    emote.style.top = (agent.y * TILE_SIZE * RENDER_SCALE * sy + rect.top - containerRect.top - 20) + 'px';

    document.getElementById('speech-overlay').appendChild(emote);
    setTimeout(() => emote.remove(), 1500);
  }

  // ============================================================
  // Event Handlers
  // ============================================================

  function handleEvent(event) {
    switch (event.type) {
      case 'agent_switch': handleAgentSwitch(event); break;
      case 'gate_pass': handleGatePass(event); break;
      case 'artifact': handleArtifact(event); break;
      case 'challenge': handleChallenge(event); break;
      case 'party_mode': handlePartyMode(event); break;
      case 'ceremony': handleCeremony(event); break;
      case 'break': handleBreak(event); break;
    }
    addActivityCard(event);
    if (event.ts) lastEventTs = event.ts;
  }

  function handleAgentSwitch(event) {
    previousAgent = activeAgent;
    activeAgent = event.agent;

    const agent = AGENTS[event.agent];
    if (!agent) return;

    // Remove from break if switching
    breakingAgents.delete(event.agent);
    agent.state = 'active';

    // Determine target zone
    let targetZone = agent.defaultZone;
    if (event.context) {
      const map = {
        requirements: 'planning', prd: 'planning', architecture: 'planning',
        story: 'warRoom', sprint: 'warRoom', review: 'warRoom',
        code: 'coding', implement: 'coding', develop: 'coding',
        design: 'design', wireframe: 'design', ux: 'design', docs: 'design',
        security: 'security', threat: 'security', pentest: 'security',
        test: 'qaLab', quality: 'qaLab', e2e: 'qaLab',
        deploy: 'ops', release: 'ops', infra: 'ops',
      };
      for (const [k, z] of Object.entries(map)) {
        if (event.context.toLowerCase().includes(k)) { targetZone = z; break; }
      }
    }

    moveAgentToZone(event.agent, targetZone);

    // Show thinking dots briefly, then speech bubble
    thinkingAgents[event.agent] = true;
    setTimeout(() => {
      delete thinkingAgents[event.agent];
      if (event.message) showSpeechBubble(event.agent, event.message);
    }, 600);

    // Sparkle effect on activation
    spawnSparkles(agent.x, agent.y);

    // Previous agent dims
    if (previousAgent && AGENTS[previousAgent]) {
      AGENTS[previousAgent].state = 'idle';
    }
  }

  function handleGatePass(event) {
    const key = String(event.gate);
    gateStatus[key] = true;

    const seg = document.querySelector(`.gate-segment[data-gate="${key}"]`);
    if (seg) {
      seg.classList.add('passed');
      seg.classList.remove('active');
    }

    // Big confetti celebration
    if (event.agent && AGENTS[event.agent]) {
      const a = AGENTS[event.agent];
      spawnConfetti(a.x, a.y, 40);
      showEmote(event.agent, '');
      // Flash green
      triggerScreenFlash('rgba(102,187,106,0.3)', 500);
    }
  }

  function handleArtifact(event) {
    addArtifactItem(event);
    if (event.agent && AGENTS[event.agent]) {
      showEmote(event.agent, '');
    }
  }

  function handleChallenge(event) {
    const challenger = event.agent || 'Rex';
    const target = event.target;

    // DRAMATIC: screen shake + red flash
    triggerScreenShake(12, 600);
    triggerScreenFlash('rgba(231,76,60,0.3)', 400);

    if (target && AGENTS[target]) {
      const targetAgent = AGENTS[target];
      moveAgentToZone(challenger, targetAgent.defaultZone);

      // Delayed dramatic effects
      setTimeout(() => {
        if (AGENTS[challenger]) {
          // Big flame burst
          spawnFlameParticles(AGENTS[challenger].x, AGENTS[challenger].y, 25);
          // Second shake when flames appear
          triggerScreenShake(6, 300);
        }
        // Surprised emote on target
        showEmote(target, '');
        // More flames after a beat
        setTimeout(() => {
          if (AGENTS[challenger]) spawnFlameParticles(AGENTS[challenger].x, AGENTS[challenger].y, 15);
        }, 400);
      }, 800);
    }

    // Challenge speech bubble with dramatic delay
    if (event.message) {
      setTimeout(() => {
        showSpeechBubble(challenger, event.message, 'challenge');
      }, 1200);
    }

    // Verdict with fanfare
    if (event.verdict) {
      setTimeout(() => {
        if (event.verdict === 'sustained') {
          showEmote(challenger, '');
          triggerScreenShake(4, 200);
        } else if (event.verdict === 'withdrawn') {
          showEmote(challenger, '');
          spawnSparkles(AGENTS[target]?.x || 18, AGENTS[target]?.y || 7);
        } else {
          showEmote(challenger, '');
        }
      }, 4000);
    }
  }

  function handlePartyMode(event) {
    const banner = document.getElementById('party-banner');
    banner.classList.remove('hidden');
    banner.style.animation = 'none';
    banner.offsetHeight; // reflow
    banner.style.animation = '';
    setTimeout(() => banner.classList.add('hidden'), 5000);

    // Big screen flash
    triggerScreenFlash('rgba(155,89,182,0.2)', 600);

    // Walk all agents with staggered sparkles
    if (event.agents) {
      event.agents.forEach((name, i) => {
        setTimeout(() => {
          moveAgentToZone(name, 'warRoom');
          if (AGENTS[name]) {
            spawnSparkles(AGENTS[name].x, AGENTS[name].y);
            showEmote(name, '');
          }
        }, i * 400);
      });
    }
  }

  function handleCeremony(event) {
    const banner = document.getElementById('ceremony-banner');
    const names = {
      sprint_planning: 'Sprint Planning',
      sprint_review: 'Sprint Review',
      retrospective: 'Retrospective',
      launch_readiness: 'Launch Readiness Review',
    };
    banner.textContent = (names[event.ceremony] || event.ceremony || 'Team Ceremony') +
      (event.sprint ? ` — Sprint ${event.sprint}` : '');
    banner.classList.remove('hidden');

    // Everyone gathers
    const agentNames = Object.keys(AGENTS);
    agentNames.forEach((name, i) => {
      setTimeout(() => {
        moveAgentToZone(name, 'warRoom');
      }, i * 200);
    });

    // Confetti for ceremonies
    setTimeout(() => spawnConfetti(18, 7, 50), 1500);

    setTimeout(() => banner.classList.add('hidden'), 8000);
  }

  function handleBreak(event) {
    const agents = event.agents || [event.agent];
    agents.forEach((name, i) => {
      setTimeout(() => {
        if (AGENTS[name]) {
          breakingAgents.add(name);
          AGENTS[name].state = 'active'; // so glow works
          moveAgentToZone(name, 'relax');
          spawnHearts(AGENTS[name].x, AGENTS[name].y);
          showEmote(name, '');
        }
      }, i * 300);
    });

    if (event.message) {
      setTimeout(() => {
        showSpeechBubble(agents[0] || 'Bob', event.message, 'break');
      }, 600);
    }
  }

  // ============================================================
  // Sidebar UI
  // ============================================================

  function addActivityCard(event) {
    const log = document.getElementById('activity-log');
    const empty = log.querySelector('.empty-state');
    if (empty) empty.remove();

    const card = document.createElement('div');
    card.className = `activity-card type-${event.type}`;

    const agent = AGENTS[event.agent] || {};
    const badge = document.createElement('div');
    badge.className = 'agent-badge';
    badge.style.background = agent.layerColor || '#999';
    badge.textContent = (event.agent || '?')[0];

    const content = document.createElement('div');
    content.className = 'card-content';

    const nameEl = document.createElement('div');
    nameEl.className = 'card-agent';
    nameEl.textContent = event.agent || 'System';

    const msgEl = document.createElement('div');
    msgEl.className = 'card-message';

    switch (event.type) {
      case 'agent_switch': msgEl.textContent = event.message || `Active`; break;
      case 'gate_pass': msgEl.textContent = `Gate ${event.gate} passed` + (event.story ? ` (${event.story})` : ''); break;
      case 'artifact': msgEl.textContent = `${event.action || 'Created'}: ${event.path || 'file'}`; break;
      case 'challenge': msgEl.textContent = `Challenges ${event.target}: ${event.message || ''}`; break;
      case 'party_mode': msgEl.textContent = `Party: ${(event.agents || []).join(', ')}`; break;
      case 'ceremony': msgEl.textContent = event.message || event.ceremony; break;
      case 'break': msgEl.textContent = event.message || `Taking a break`; break;
      default: msgEl.textContent = event.message || event.type;
    }

    const timeEl = document.createElement('div');
    timeEl.className = 'card-time';
    timeEl.textContent = event.ts ? new Date(event.ts).toLocaleTimeString() : 'now';

    content.appendChild(nameEl);
    content.appendChild(msgEl);
    content.appendChild(timeEl);
    card.appendChild(badge);
    card.appendChild(content);
    log.insertBefore(card, log.firstChild);

    while (log.children.length > 100) log.removeChild(log.lastChild);
  }

  function addArtifactItem(event) {
    const list = document.getElementById('artifact-list');
    const empty = list.querySelector('.empty-state');
    if (empty) empty.remove();

    const item = document.createElement('div');
    item.className = 'artifact-item highlight';

    const icon = document.createElement('span');
    icon.className = 'artifact-icon';
    const p = event.path || '';
    if (p.includes('security') || p.includes('threat')) icon.textContent = '';
    else if (p.includes('test') || p.includes('.spec')) icon.textContent = '';
    else if (p.endsWith('.md')) icon.textContent = '';
    else if (p.match(/\.(ts|js|py|tsx)$/)) icon.textContent = '';
    else icon.textContent = '';

    const pathEl = document.createElement('span');
    pathEl.className = 'artifact-path';
    pathEl.textContent = p.split('/').pop() || p;
    pathEl.title = p;

    const agentEl = document.createElement('span');
    agentEl.className = 'artifact-agent';
    agentEl.textContent = event.agent || '';

    item.appendChild(icon);
    item.appendChild(pathEl);
    item.appendChild(agentEl);
    list.insertBefore(item, list.firstChild);

    setTimeout(() => item.classList.remove('highlight'), 600);
  }

  // ============================================================
  // WebSocket
  // ============================================================

  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}`);

    ws.onopen = () => {
      const dot = document.getElementById('connection-status');
      dot.className = 'status-dot connected';
      dot.title = 'Connected';
      wsReconnectDelay = 3000;
      if (lastEventTs) {
        ws.send(JSON.stringify({ type: 'replay', last_ts: lastEventTs }));
      }
    };

    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (data.type === 'init' || data.type === 'events') {
          for (const event of data.events) handleEvent(event);
        }
      } catch (e) { console.warn('Bad message:', e); }
    };

    ws.onclose = () => {
      const dot = document.getElementById('connection-status');
      dot.className = 'status-dot disconnected';
      dot.title = 'Disconnected — reconnecting...';
      setTimeout(connectWS, wsReconnectDelay);
      wsReconnectDelay = Math.min(wsReconnectDelay * 1.5, 30000);
    };

    ws.onerror = () => ws.close();
  }

  // ============================================================
  // Main Loop
  // ============================================================

  let lastTime = 0;

  function gameLoop(timestamp) {
    now = timestamp;
    const dt = Math.min(timestamp - lastTime, 100);
    lastTime = timestamp;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    drawRoom();
    drawProximityHalos();

    // Sort by Y for depth ordering
    const sorted = Object.values(AGENTS).sort((a, b) => a.y - b.y);
    for (const agent of sorted) {
      updateAgentMovement(agent, dt);
      drawAgent(agent);
    }
    updateGlows(dt);

    updateAndDrawParticles();
    updateScreenEffects();

    requestAnimationFrame(gameLoop);
  }

  // ============================================================
  // Init
  // ============================================================

  function init() {
    resizeCanvas();
    connectWS();
    requestAnimationFrame(gameLoop);
    console.log('BMAD Live Viz v2 initialized');
    console.log(`Room: ${ROOM_COLS}x${ROOM_ROWS}, Canvas: ${canvas.width}x${canvas.height}`);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
