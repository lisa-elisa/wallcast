"use strict";

const SCREEN_W = 1920;
const SCREEN_H = 1080;

// ── Beam particle — parallel_to_floor ────────────────────────────────────────
// Fast streaks shooting from fingertips along hand axis.
class BeamParticle {
  constructor(x, y, dirX, dirY, spread = 0.18) {
    const angle  = Math.atan2(dirY, dirX) + (Math.random() - 0.5) * spread;
    const speed  = 12 + Math.random() * 22;
    this.x  = x; this.y  = y;
    this.vx = Math.cos(angle) * speed;
    this.vy = Math.sin(angle) * speed;
    this.life  = 1.0;
    this.decay = 0.007 + Math.random() * 0.007;
    this.size  = 1 + Math.random() * 2;
    this.hue   = 175 + Math.random() * 55; // cyan → blue → white
  }

  update() {
    this.x += this.vx;
    this.y += this.vy;
    this.vx *= 0.996;
    this.vy *= 0.996;
    this.life -= this.decay;
  }

  draw(ctx) {
    if (this.life <= 0) return;
    const a   = Math.max(0, this.life);
    const spd = Math.hypot(this.vx, this.vy);
    const ang = Math.atan2(this.vy, this.vx);
    const len = spd * 3.5;

    ctx.save();
    ctx.globalAlpha = a;
    ctx.strokeStyle = `hsl(${this.hue}, 100%, ${60 + a * 35}%)`;
    ctx.lineWidth   = this.size * a;
    ctx.lineCap     = "round";
    ctx.beginPath();
    ctx.moveTo(this.x, this.y);
    ctx.lineTo(this.x - Math.cos(ang) * len, this.y - Math.sin(ang) * len);
    ctx.stroke();
    ctx.restore();
  }
}

// ── Cloud particle — facing_camera ───────────────────────────────────────────
// Slow glowing orbs expanding from palm, fading near the ring edge.
class CloudParticle {
  constructor(x, y, ringR) {
    this.x  = x; this.y  = y;
    const angle = Math.random() * Math.PI * 2;
    const speed = 0.4 + Math.random() * 2.2;
    this.vx = Math.cos(angle) * speed;
    this.vy = Math.sin(angle) * speed;
    this.life  = 1.0;
    this.decay = 0.010 + Math.random() * 0.018;
    this.size  = 4 + Math.random() * 7;
    this.hue   = 20 + Math.random() * 55;
  }

  update() {
    this.x += this.vx;
    this.y += this.vy;
    this.vx *= 0.975;
    this.vy *= 0.975;
    this.life -= this.decay;
  }

  draw(ctx) {
    if (this.life <= 0) return;
    const a = Math.max(0, this.life);
    const r = this.size * a;
    ctx.save();
    ctx.globalAlpha = a * 0.85;
    ctx.fillStyle   = `hsl(${this.hue}, 100%, ${50 + a * 42}%)`;
    ctx.beginPath();
    ctx.arc(this.x, this.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
}

// ── Gold spark — parallel_to_floor muzzle glow ───────────────────────────────
// Tiny golden sparks that jitter near the beam origin and fade quickly.
class GoldSpark {
  constructor(x, y) {
    this.x = x; this.y = y;
    const angle = Math.random() * Math.PI * 2;
    const speed = 0.2 + Math.random() * 0.8;
    this.vx = Math.cos(angle) * speed;
    this.vy = Math.sin(angle) * speed;
    this.life  = 1.0;
    this.decay = 0.03 + Math.random() * 0.03;
    this.size  = 1.5 + Math.random() * 2.5;
    this.hue   = 38 + Math.random() * 22;
  }

  update() {
    this.x += this.vx;
    this.y += this.vy;
    this.vx *= 0.90;
    this.vy *= 0.90;
    this.life -= this.decay;
  }

  draw(ctx) {
    if (this.life <= 0) return;
    const a = Math.max(0, this.life);
    const r = this.size * (0.6 + 0.4 * a);
    ctx.save();
    ctx.globalAlpha = a * 0.95;
    ctx.fillStyle = `hsl(${this.hue}, 100%, ${55 + a * 35}%)`;
    ctx.shadowBlur = 6 * a;
    ctx.shadowColor = `hsl(${this.hue}, 100%, 60%)`;
    ctx.beginPath();
    ctx.arc(this.x, this.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
}

// ── Main App ─────────────────────────────────────────────────────────────────
class App {
  constructor() {
    this.canvas   = document.getElementById("canvas");
    this.ctx      = this.canvas.getContext("2d", { alpha: false });
    this.statusEl = document.getElementById("status");

    this._resize();
    window.addEventListener("resize", () => this._resize());

    this.ws             = null;
    this.reconnectTimer = null;
    this.connected      = false;
    this.particles      = [];
    this.handState      = null;
    this.currentSpell    = null;
    this.lastSpellSpawn  = 0;
    this.prevSpellOrigin = null;

    this._connect();
    this._loop();
  }

  _resize() {
    this.canvas.width  = window.innerWidth;
    this.canvas.height = window.innerHeight;
    this.scaleX = this.canvas.width  / SCREEN_W;
    this.scaleY = this.canvas.height / SCREEN_H;
  }

  _toCanvas(x, y) { return [x * this.scaleX, y * this.scaleY]; }

  // ── WebSocket ───────────────────────────────────────────────────────────────
  _connect() {
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
    this.statusEl.textContent = "Connecting…";
    this.ws = new WebSocket("ws://localhost:8765");

    this.ws.onopen = () => {
      this.connected = true;
      this.statusEl.textContent = "Connected";
      setTimeout(() => { this.statusEl.style.opacity = "0"; }, 1500);
    };
    this.ws.onmessage = (ev) => {
      try { this._onMessage(JSON.parse(ev.data)); } catch (_) {}
    };
    this.ws.onclose = () => {
      this.connected = false;
      this.statusEl.style.opacity = "1";
      this.statusEl.textContent   = "Disconnected — retrying in 2 s";
      this.reconnectTimer = setTimeout(() => this._connect(), 2000);
    };
    this.ws.onerror = () => { this.ws.close(); };
  }

  _onMessage(msg) {
    if (msg.type !== "hand") return;
    this.handState   = msg.hand || null;
    this.currentSpell = msg.spell || null;
  }

  // ── Beam ray ────────────────────────────────────────────────────────────────
  _drawBeam(tx, ty, dx, dy, charge = 1.0) {
    const far = Math.hypot(SCREEN_W, SCREEN_H);
    const ex  = tx + dx * far * this.scaleX;
    const ey  = ty + dy * far * this.scaleY;
    const vis = Math.sqrt(charge);               // low charge more visible

    // Wide soft glow
    const g1 = this.ctx.createLinearGradient(tx, ty, ex, ey);
    g1.addColorStop(0,    `rgba(160, 240, 255, ${0.85 * vis})`);
    g1.addColorStop(0.12, `rgba(80,  200, 255, ${0.55 * vis})`);
    g1.addColorStop(0.45, `rgba(40,  140, 255, ${0.18 * vis})`);
    g1.addColorStop(1,    `rgba(0,   80,  200, 0)`);
    this.ctx.save();
    this.ctx.strokeStyle = g1;
    this.ctx.lineWidth   = 14 * vis;
    this.ctx.lineCap     = "round";
    this.ctx.beginPath();
    this.ctx.moveTo(tx, ty);
    this.ctx.lineTo(ex, ey);
    this.ctx.stroke();

    // Bright tight core
    const g2 = this.ctx.createLinearGradient(tx, ty, ex, ey);
    g2.addColorStop(0,    `rgba(255, 255, 255, ${0.95 * vis})`);
    g2.addColorStop(0.07, `rgba(200, 240, 255, ${0.60 * vis})`);
    g2.addColorStop(0.25, `rgba(120, 200, 255, 0)`);
    g2.addColorStop(1,    `rgba(0,   0,   0,   0)`);
    this.ctx.strokeStyle = g2;
    this.ctx.lineWidth   = 3 * vis;
    this.ctx.stroke();
    this.ctx.restore();
  }

  // ── Pulsating ring ──────────────────────────────────────────────────────────
  _drawPulsingRing(cx, cy, charge = 1.0) {
    const t     = performance.now() / 1000;
    const pulse = 0.5 + 0.5 * Math.sin(t * Math.PI * 2.4); // ~2.4 Hz
    const baseR = 216 * this.scaleX;
    const R     = baseR * (0.82 + 0.18 * pulse);
    const vis   = Math.sqrt(charge);               // low charge more visible
    const alpha = (0.22 + 0.38 * pulse) * vis;

    this.ctx.save();

    // Outer soft halo
    this.ctx.globalAlpha = alpha * 0.45;
    this.ctx.strokeStyle = `hsl(35, 100%, 65%)`;
    this.ctx.lineWidth   = 18 * vis;
    this.ctx.beginPath(); this.ctx.arc(cx, cy, R * 1.15, 0, Math.PI * 2); this.ctx.stroke();

    // Main ring
    this.ctx.globalAlpha = alpha;
    this.ctx.strokeStyle = `hsl(45, 100%, 78%)`;
    this.ctx.lineWidth   = 3 * vis;
    this.ctx.beginPath(); this.ctx.arc(cx, cy, R, 0, Math.PI * 2); this.ctx.stroke();

    // Inner bright ring
    this.ctx.globalAlpha = alpha * 0.55;
    this.ctx.strokeStyle = `hsl(60, 100%, 92%)`;
    this.ctx.lineWidth   = 1.5 * vis;
    this.ctx.beginPath(); this.ctx.arc(cx, cy, R * 0.55, 0, Math.PI * 2); this.ctx.stroke();

    this.ctx.restore();
  }

  // ── Hand overlay ────────────────────────────────────────────────────────────
  _drawHand() {
    if (!this.handState) return;
    const { palm_center, fingertips, gesture, orientation, hand_dir } = this.handState;
    if (!palm_center) return;

    const [cx, cy] = this._toCanvas(palm_center[0], palm_center[1]);
    const charge = this.currentSpell ? this.currentSpell.charge : 0;

    if (gesture === "open" && charge > 0 && orientation) {
      if (orientation === "parallel_to_floor" && hand_dir && this.currentSpell) {
        const [tx, ty] = this._toCanvas(this.currentSpell.origin[0], this.currentSpell.origin[1]);
        this._drawBeam(tx, ty, hand_dir[0], hand_dir[1], charge);
      } else if (orientation === "facing_camera") {
        this._drawPulsingRing(cx, cy, charge);
      }
    }

    // Subtle cursor
    this.ctx.save();
    this.ctx.strokeStyle = "rgba(200, 200, 200, 0.15)";
    this.ctx.lineWidth   = 1;
    this.ctx.beginPath(); this.ctx.arc(cx, cy, 10, 0, Math.PI * 2); this.ctx.stroke();
    this.ctx.restore();
  }

  // ── Render loop ─────────────────────────────────────────────────────────────
  _loop() {
    // Shift cloud particles so they follow the hand
    if (this.currentSpell && this.prevSpellOrigin) {
      const dx = (this.currentSpell.origin[0] - this.prevSpellOrigin[0]) * this.scaleX;
      const dy = (this.currentSpell.origin[1] - this.prevSpellOrigin[1]) * this.scaleY;
      for (const p of this.particles) {
        if (p instanceof CloudParticle) { p.x += dx; p.y += dy; }
      }
    }
    this.prevSpellOrigin = this.currentSpell ? [...this.currentSpell.origin] : null;

    // Update + cull dead particles
    for (let i = this.particles.length - 1; i >= 0; i--) {
      this.particles[i].update();
      if (this.particles[i].life <= 0) this.particles.splice(i, 1);
    }

    // Spawn new particles based on active spell charge
    if (this.currentSpell && this.currentSpell.charge > 0) {
      const now = performance.now();
      const [ox, oy] = this._toCanvas(this.currentSpell.origin[0], this.currentSpell.origin[1]);
      const [dx, dy] = this.currentSpell.direction;

      if (this.currentSpell.orientation === "parallel_to_floor") {
        // Dense spawn: strict parallel beam sparks + golden muzzle glow
        const interval = 50 / (0.2 + 0.8 * this.currentSpell.charge);
        if (!this.lastSpellSpawn || (now - this.lastSpellSpawn) > interval) {
          this.lastSpellSpawn = now;
          // Beam direction = hand axis (wrist → fingers), NOT velocity
          const [hdx, hdy] = (this.handState && this.handState.hand_dir)
            ? this.handState.hand_dir : [dx, dy];
          const beamCount = Math.max(10, Math.ceil(40 * this.currentSpell.charge));
          for (let i = 0; i < beamCount; i++) this.particles.push(new BeamParticle(ox, oy, hdx, hdy, 0));
          const goldCount = Math.max(8, Math.ceil(30 * this.currentSpell.charge));
          for (let i = 0; i < goldCount; i++) this.particles.push(new GoldSpark(ox, oy));
        }
      } else {
        const interval = 180 / (0.15 + 0.85 * this.currentSpell.charge);
        if (!this.lastSpellSpawn || (now - this.lastSpellSpawn) > interval) {
          this.lastSpellSpawn = now;
          const count = Math.ceil(1 + 6 * this.currentSpell.charge);
          const ringR = 75 * this.scaleX;
          for (let i = 0; i < count; i++) this.particles.push(new CloudParticle(ox, oy, ringR));
        }
      }
    }

    this.ctx.fillStyle = "#000";
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

    for (const p of this.particles) p.draw(this.ctx);
    this._drawHand();

    requestAnimationFrame(() => this._loop());
  }
}

window.addEventListener("DOMContentLoaded", () => new App());
