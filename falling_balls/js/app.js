/**
 * Wallcast — Falling Balls renderer + WebSocket client
 *
 * Physics:   Matter.js 0.19
 * Canvas:    1920×1080 logical
 * Balls:     yellow spheres spawn every SPAWN_INTERVAL ms at (SPAWN_X, top)
 * Obstacles: red paper polygons streamed over WebSocket from server.py
 */

"use strict";

// ── Constants ────────────────────────────────────────────────────────────────

const SCREEN_W        = 1920;
const SCREEN_H        = 1080;

const BALL_RADIUS     = 20;       // px — visual radius
const SPAWN_INTERVAL  = 500;      // ms between spawns
const SPAWN_X         = 1280;     // border between middle and right thirds
const SPAWN_Y         = -BALL_RADIUS - 5;
const MAX_BALLS       = 20;       // hard cap on concurrent balls (older ones recycle)

// 10g hollow plastic: light, moderately bouncy
const BALL_DENSITY        = 0.0005;
const BALL_RESTITUTION    = 0.62;
const BALL_FRICTION       = 0.08;
const BALL_FRICTION_AIR   = 0.008;
const BALL_SPAWN_SPREAD   = 30;   // px random horizontal spread

// Paper blocks: solid, moderate bounce
const PAPER_RESTITUTION   = 0.45;
const PAPER_FRICTION      = 0.28;

const GRAVITY_Y       = 1.3;      // Matter.js gravity units

const WS_URL          = "ws://localhost:8765";
const WS_RECONNECT_MS = 2000;

// ── Matter.js setup ───────────────────────────────────────────────────────────

const {
  Engine, Render, Runner, Bodies, Body, Composite, World, Events, Vector
} = Matter;

// ── BallCatcher app ───────────────────────────────────────────────────────────

export class BallCatcher {
  constructor() {
    this.canvas   = document.getElementById("canvas");
    this.ctx      = this.canvas.getContext("2d");
    this.statusEl = document.getElementById("status");
    this.countEl  = document.getElementById("ball-count");

    // Fixed logical resolution
    this.canvas.width  = SCREEN_W;
    this.canvas.height = SCREEN_H;

    // Scale canvas to fill window, keep aspect ratio
    this._scaleCanvas();
    window.addEventListener("resize", () => this._scaleCanvas());

    // Physics world
    this.engine = Engine.create();
    this.engine.gravity.y = GRAVITY_Y;

    this.balls        = [];          // active ball bodies
    this.paperBodies  = new Map();   // id → Matter body
    this.ballsSpawned = 0;
    this.spawnTimer   = null;

    this._addWalls();
    this._connectWS();
    this._startSpawning();   // start immediately, not just on WS connect
    this._startLoop();
  }

  // ── Canvas scaling ──────────────────────────────────────────────────────────

  _scaleCanvas() {
    const sx = window.innerWidth  / SCREEN_W;
    const sy = window.innerHeight / SCREEN_H;
    const s  = Math.min(sx, sy);
    this.canvas.style.width   = `${SCREEN_W * s}px`;
    this.canvas.style.height  = `${SCREEN_H * s}px`;
    this.canvas.style.left    = `${(window.innerWidth  - SCREEN_W * s) / 2}px`;
    this.canvas.style.top     = `${(window.innerHeight - SCREEN_H * s) / 2}px`;
  }

  // ── Static boundaries ───────────────────────────────────────────────────────

  _addWalls() {
    const opts = { isStatic: true, label: "wall", restitution: 0.3, friction: 0.5 };
    const THICK = 60;
    Composite.add(this.engine.world, [
      // Left wall
      Bodies.rectangle(-THICK / 2, SCREEN_H / 2, THICK, SCREEN_H * 2, opts),
      // Right wall
      Bodies.rectangle(SCREEN_W + THICK / 2, SCREEN_H / 2, THICK, SCREEN_H * 2, opts),
    ]);
  }

  // ── Ball spawning ───────────────────────────────────────────────────────────

  _spawnBall() {
    if (document.hidden) return;          // tab in background — skip spawn
    if (this.balls.length >= MAX_BALLS) return;  // cap reached — wait for offscreen recycle

    const x = SPAWN_X + (Math.random() - 0.5) * BALL_SPAWN_SPREAD;
    const ball = Bodies.circle(x, SPAWN_Y, BALL_RADIUS, {
      label:       "ball",
      restitution: BALL_RESTITUTION,
      friction:    BALL_FRICTION,
      frictionAir: BALL_FRICTION_AIR,
      density:     BALL_DENSITY,
    });

    Composite.add(this.engine.world, ball);
    this.balls.push(ball);
    this.ballsSpawned++;
    this._updateBallCount();
  }

  _startSpawning() {
    if (this.spawnTimer) return;
    this.ballsSpawned = 0;
    this.spawnTimer = setInterval(() => this._spawnBall(), SPAWN_INTERVAL);
  }

  // ── WebSocket client ────────────────────────────────────────────────────────

  _connectWS() {
    this._setStatus("Connecting...", "#555");
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      this._setStatus("Connected", "#2a7a2a");
    };

    ws.onmessage = (evt) => {
      let data;
      try { data = JSON.parse(evt.data); } catch { return; }
      if (data.type === "obstacles") {
        // Shape guard — matches shared/protocol.schema.json (obstacles variant)
        if (!Array.isArray(data.obstacles)) {
          console.warn("Protocol mismatch: expected obstacles[]", data);
          return;
        }
        this._updatePapers(data.obstacles);
        if (data.screen === "screen_ok")   this._setStatus("Connected  |  screen OK", "#2a7a2a");
        if (data.screen === "screen_lost") this._setStatus("Connected  |  screen lost", "#7a6a00");
        if (data.screen === "no_camera")   this._setStatus("Connected  |  no camera",  "#a00");
      }
    };

    ws.onerror = () => this._setStatus("WS error", "#a00");

    ws.onclose = () => {
      this._setStatus(`Disconnected — retrying in ${WS_RECONNECT_MS / 1000}s`, "#a00");
      setTimeout(() => this._connectWS(), WS_RECONNECT_MS);
    };
  }

  // ── Obstacle management ─────────────────────────────────────────────────────

  _updatePapers(incoming) {
    const incomingIds = new Set(incoming.map(o => o.id));
    const MOVE_THRESHOLD = 15.0;  // px — recreate only on intentional move

    // Remove bodies that disappeared
    for (const [id, body] of this.paperBodies) {
      if (!incomingIds.has(id)) {
        Composite.remove(this.engine.world, body);
        this.paperBodies.delete(id);
      }
    }

    for (const obs of incoming) {
      if (!this.paperBodies.has(obs.id)) {
        // Brand-new paper
        const body = this._makePaperBody(obs);
        if (body) {
          Composite.add(this.engine.world, body);
          this.paperBodies.set(obs.id, body);
        }
      } else {
        // Existing paper: recreate only if it moved significantly
        const body = this.paperBodies.get(obs.id);
        const dx = obs.cx - body.position.x;
        const dy = obs.cy - body.position.y;
        if (Math.abs(dx) > MOVE_THRESHOLD || Math.abs(dy) > MOVE_THRESHOLD) {
          Composite.remove(this.engine.world, body);
          const newBody = this._makePaperBody(obs);
          if (newBody) {
            Composite.add(this.engine.world, newBody);
            this.paperBodies.set(obs.id, newBody);
          } else {
            this.paperBodies.delete(obs.id);
          }
        }
      }
    }
  }

  _makePaperBody(obs) {
    const opts = {
      isStatic:    true,
      label:       "paper",
      restitution: PAPER_RESTITUTION,
      friction:    PAPER_FRICTION,
    };

    if (obs.vertices && obs.vertices.length >= 3) {
      const verts = obs.vertices.map(([x, y]) => ({ x, y }));
      try {
        // Use polygon centroid so fromVertices creates body exactly at vertex positions
        const centroid = Matter.Vertices.centre(verts);
        const body = Bodies.fromVertices(centroid.x, centroid.y, [verts], opts, true);
        return body;
      } catch (e) {
        // fall through
      }
    }

    // Fallback: axis-aligned rectangle
    return Bodies.rectangle(obs.cx, obs.cy, obs.w || 100, obs.h || 20, {
      ...opts,
      angle: (obs.angle || 0) * Math.PI / 180,
    });
  }

  // ── Render loop ─────────────────────────────────────────────────────────────

  _startLoop() {
    let prev = performance.now();

    const tick = (now) => {
      const delta = Math.min(now - prev, 50); // cap at 50ms to avoid spiral of death
      prev = now;

      Engine.update(this.engine, delta);
      this._removeOffscreenBalls();
      this._draw();

      requestAnimationFrame(tick);
    };

    requestAnimationFrame(tick);
  }

  _removeOffscreenBalls() {
    const OUT = SCREEN_H + 150;
    const stale = this.balls.filter(b => b.position.y > OUT || b.position.x < -200 || b.position.x > SCREEN_W + 200);
    stale.forEach(b => Composite.remove(this.engine.world, b));
    this.balls = this.balls.filter(b => !stale.includes(b));
    if (stale.length) this._updateBallCount();
  }

  // ── Drawing ──────────────────────────────────────────────────────────────────

  _draw() {
    const ctx = this.ctx;

    // Dark background — reduces camera overexposure, balls stand out better
    ctx.fillStyle = "#0d1117";
    ctx.fillRect(0, 0, SCREEN_W, SCREEN_H);

    // Thin bright white border — camera uses it to detect screen boundary
    ctx.strokeStyle = "rgba(255,255,255,0.75)";
    ctx.lineWidth = 6;
    ctx.strokeRect(3, 3, SCREEN_W - 6, SCREEN_H - 6);

    this._drawSpawnMarker(ctx);
    this._drawPapers(ctx);
    this._drawBalls(ctx);
  }

  _drawSpawnMarker(ctx) {
    ctx.save();
    ctx.setLineDash([6, 12]);
    ctx.strokeStyle = "rgba(255,255,255,0.08)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(SPAWN_X, 0);
    ctx.lineTo(SPAWN_X, 80);
    ctx.stroke();
    ctx.restore();
  }

  _drawPapers(ctx) {
    // Rendering disabled — obstacles exist only as invisible physics bodies
  }

  _drawBalls(ctx) {
    for (const ball of this.balls) {
      const { x, y } = ball.position;
      const r = BALL_RADIUS;

      // Gradient: warm yellow highlight → gold → dark gold
      const grad = ctx.createRadialGradient(
        x - r * 0.32, y - r * 0.35, r * 0.08,
        x, y, r
      );
      grad.addColorStop(0,   "#FFF176");  // bright highlight
      grad.addColorStop(0.45,"#FFD600");  // main yellow
      grad.addColorStop(0.85,"#F9A825");  // shadow gold
      grad.addColorStop(1,   "#E65100");  // rim shadow (hollow plastic look)

      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();

      // Subtle rim
      ctx.strokeStyle = "rgba(180, 100, 0, 0.4)";
      ctx.lineWidth = 1;
      ctx.stroke();

      // Small specular dot
      ctx.beginPath();
      ctx.arc(x - r * 0.3, y - r * 0.32, r * 0.18, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(255,255,255,0.55)";
      ctx.fill();
    }
  }

  _drawPolygon(ctx, vertices) {
    if (!vertices || vertices.length === 0) return;
    ctx.beginPath();
    ctx.moveTo(vertices[0].x, vertices[0].y);
    for (let i = 1; i < vertices.length; i++) {
      ctx.lineTo(vertices[i].x, vertices[i].y);
    }
    ctx.closePath();
  }

  // ── UI helpers ───────────────────────────────────────────────────────────────

  _setStatus(text, bg) {
    this.statusEl.textContent = text;
    this.statusEl.style.background = bg;
  }

  _updateBallCount() {
    this.countEl.textContent = `Balls: ${this.balls.length} / ${this.ballsSpawned}`;
  }
}

// ── Boot ─────────────────────────────────────────────────────────────────────
// ES modules are defer-by-default; DOM is ready by the time this line runs.

new BallCatcher();
