// Живой фон шапки (WebGL-«шёлк», реагирует на курсор) и прокрутка кейсов «Что будет в отчёте»
(function () {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const touch = window.matchMedia('(pointer: coarse)').matches;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

  /* ---------- Шёлк ---------- */
  const FRAG = `
precision highp float;
uniform vec2 uRes;
uniform float uTime;
uniform vec2 uMouse;
uniform vec2 uVel;
uniform float uHover;

float hash(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
  for (int i = 0; i < OCT; i++) { v += a * noise(p); p = m * p; a *= 0.5; }
  return v;
}

void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  float asp = uRes.x / uRes.y;
  vec2 p = (uv - 0.5) * vec2(asp, 1.0);
  vec2 m = (uMouse - 0.5) * vec2(asp, 1.0);

  // Курсор раздвигает и закручивает складки, а движение тянет их за собой
  vec2 d = p - m;
  float infl = exp(-dot(d, d) * 7.0) * uHover;
  p -= d * infl * 0.55;
  p += vec2(-d.y, d.x) * infl * 0.45;
  p -= uVel * infl * 2.2;

  vec2 s = p * 0.8 + vec2(0.0, 0.3);
  float t = uTime * 0.055;
  vec2 q = vec2(fbm(s + vec2(0.0, t)), fbm(s + vec2(5.2, 1.3) - t));
  vec2 r = vec2(fbm(s + 2.4 * q + vec2(1.7, 9.2) + 0.7 * t), fbm(s + 2.4 * q + vec2(8.3, 2.8) - 0.5 * t));
  float f = fbm(s + 2.6 * r);

  // Складки шёлка: яркий тонкий гребень, мягкое свечение и широкий перелив вокруг
  float v = f * 8.0 + r.x * 2.4;
  float band = 1.0 - abs(sin(v * 3.14159));
  float sharp = mix(70.0, 26.0, smoothstep(0.35, 0.85, r.y));
  float core = pow(band, sharp);
  float glow = pow(band, 7.0);
  float sheen = pow(band, 1.6);
  float shown = 0.35 + 0.65 * smoothstep(0.25, 0.62, fbm(s * 0.6 + vec2(t * 0.8, -t)) + 0.15 * q.y);

  vec3 ink = vec3(0.02, 0.01, 0.05);
  vec3 deep = vec3(0.27, 0.05, 0.72);
  vec3 violet = vec3(0.48, 0.2, 1.0);
  float body = smoothstep(0.15, 0.7, f) * (0.6 + 0.4 * smoothstep(0.1, 0.9, uv.x));
  vec3 col = mix(ink, deep, body);
  col += violet * sheen * 0.42 * (0.4 + body);
  col += mix(violet, vec3(0.75, 0.6, 1.0), 0.5) * glow * 0.7 * shown;
  col += vec3(1.0, 0.95, 1.0) * core * 0.95 * shown;
  col += vec3(0.42, 0.2, 0.95) * infl * 0.18;

  // Виньетка и зерно
  col *= 0.7 + 0.3 * smoothstep(1.25, 0.25, length((uv - vec2(0.6, 0.5)) * vec2(asp * 0.7, 1.0)));
  col += (hash(gl_FragCoord.xy + fract(uTime) * 61.0) - 0.5) * 0.025;
  gl_FragColor = vec4(col, 1.0);
}`;
  const VERT = 'attribute vec2 a; void main(){ gl_Position = vec4(a, 0.0, 1.0); }';

  function initSilk() {
    const canvas = document.getElementById('silk');
    if (!canvas) return;
    const gl = canvas.getContext('webgl', { antialias: false, alpha: false, powerPreference: 'low-power', preserveDrawingBuffer: false });
    if (!gl) return; // остаётся CSS-градиент

    const sh = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { console.warn(gl.getShaderInfoLog(s)); return null; }
      return s;
    };
    const vs = sh(gl.VERTEX_SHADER, VERT);
    const fs = sh(gl.FRAGMENT_SHADER, '#define OCT ' + (touch ? 3 : 4) + '\n' + FRAG);
    if (!vs || !fs) return;
    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'a');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = (n) => gl.getUniformLocation(prog, n);
    const uRes = u('uRes'), uTime = u('uTime'), uMouse = u('uMouse'), uVel = u('uVel'), uHover = u('uHover');

    // Рисуем в уменьшенном разрешении: шёлк мягкий, а видеокарта не греется
    const scale = touch ? 0.5 : 0.62;
    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(1, Math.round(canvas.clientWidth * dpr * scale));
      const h = Math.max(1, Math.round(canvas.clientHeight * dpr * scale));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w; canvas.height = h;
        gl.viewport(0, 0, w, h);
      }
    }

    const target = { x: 0.62, y: 0.55 }, mouse = { x: 0.62, y: 0.55 }, vel = { x: 0, y: 0 };
    let hover = 0, hoverTarget = touch ? 0 : 0.35, lastMove = 0;
    function onMove(x, y) {
      target.x = x / window.innerWidth;
      target.y = 1 - y / window.innerHeight;
      hoverTarget = 1;
      lastMove = performance.now();
      wake();
    }
    window.addEventListener('pointermove', (e) => onMove(e.clientX, e.clientY), { passive: true });
    window.addEventListener('touchmove', (e) => { const t = e.touches[0]; if (t) onMove(t.clientX, t.clientY); }, { passive: true });
    document.addEventListener('pointerleave', () => { hoverTarget = 0; });

    let raf = 0, t0 = performance.now(), frozen = 0;
    const visible = () => !document.hidden && window.scrollY < window.innerHeight * 1.05;

    function frame(now) {
      raf = 0;
      resize();
      const k = 0.075;
      const px = mouse.x, py = mouse.y;
      mouse.x += (target.x - mouse.x) * k;
      mouse.y += (target.y - mouse.y) * k;
      vel.x = vel.x * 0.88 + (mouse.x - px) * 0.12 * 8;
      vel.y = vel.y * 0.88 + (mouse.y - py) * 0.12 * 8;
      if (now - lastMove > 1400) hoverTarget = touch ? 0 : 0.35;
      hover += (hoverTarget - hover) * 0.04;

      const time = reduced ? 12 : (now - t0) / 1000;
      gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.uniform1f(uTime, time + 40);
      gl.uniform2f(uMouse, mouse.x, mouse.y);
      gl.uniform2f(uVel, vel.x, vel.y);
      gl.uniform1f(uHover, hover);
      gl.drawArrays(gl.TRIANGLES, 0, 3);

      // При «уменьшить движение» рисуем только пока успокаивается курсор
      if (reduced) {
        frozen = Math.abs(target.x - mouse.x) + Math.abs(target.y - mouse.y) + Math.abs(hoverTarget - hover) < 0.002 ? frozen + 1 : 0;
        if (frozen > 2) return;
      }
      if (visible()) raf = requestAnimationFrame(frame);
    }
    function wake() { if (!raf && visible()) raf = requestAnimationFrame(frame); }

    window.addEventListener('scroll', wake, { passive: true });
    window.addEventListener('resize', wake);
    document.addEventListener('visibilitychange', wake);
    canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); cancelAnimationFrame(raf); raf = 0; });
    raf = requestAnimationFrame(frame);
  }

  /* ---------- Кейсы ---------- */
  function initCases() {
    const sec = document.querySelector('[data-cases]');
    if (!sec) return;
    const cards = [...sec.querySelectorAll('[data-case]')];
    const bgs = [...sec.querySelectorAll('[data-case-bg]')];
    const n = cards.length;
    const num = sec.querySelector('[data-case-num]');
    const title = sec.querySelector('[data-case-title]');
    const sub = sec.querySelector('[data-case-sub]');
    const bar = sec.querySelector('[data-case-progress]');
    const nameBox = title.parentElement;
    bar.style.width = 100 / n + '%';

    let cur = 0, active = -1, raf = 0, inView = false;
    const smooth = (x) => x * x * (3 - 2 * x);

    // Положение прокрутки → номер кейса; у каждого кейса есть «остановка», где он стоит ровно
    function targetPos() {
      const total = sec.offsetHeight - window.innerHeight;
      if (total <= 0) return 0;
      const raw = clamp(-sec.getBoundingClientRect().top / total, 0, 1) * (n - 1);
      const i = Math.min(Math.floor(raw), n - 2);
      const f = raw - i;
      return i + smooth(clamp((f - 0.18) / 0.64, 0, 1));
    }

    function render() {
      const h = cards[0].offsetHeight;
      const gap = h * 0.86 + Math.min(window.innerHeight * 0.05, 40);
      cards.forEach((c, i) => {
        const o = i - cur;
        const a = Math.abs(o);
        const y = o * gap + (o < 0 ? o * h * 0.06 : 0);
        const s = 1 - Math.min(a, 1.6) * 0.13;
        c.style.transform = `translate3d(-50%, calc(-50% + ${y.toFixed(1)}px), 0) scale(${s.toFixed(4)})`;
        c.style.opacity = clamp(1 - a * 0.62, 0, 1).toFixed(3);
        c.style.visibility = a > 1.7 ? 'hidden' : 'visible';
        c.style.zIndex = String(10 - Math.round(a * 2));
        c.style.filter = !touch && a > 0.05 ? `brightness(${(1 - Math.min(a, 1) * 0.35).toFixed(3)})` : '';
      });
      bgs.forEach((b, i) => { b.style.opacity = clamp(1 - Math.abs(i - cur), 0, 1).toFixed(3); });
      bar.style.transform = `translateX(${(cur * 100).toFixed(2)}%)`;

      const idx = clamp(Math.round(cur), 0, n - 1);
      if (idx !== active) {
        active = idx;
        num.textContent = String(idx + 1).padStart(2, '0');
        title.textContent = cards[idx].dataset.title;
        sub.textContent = cards[idx].dataset.sub;
        if (!reduced) { nameBox.classList.remove('case-swap'); void nameBox.offsetWidth; nameBox.classList.add('case-swap'); }
      }
    }

    function frame() {
      raf = 0;
      const t = targetPos();
      cur = reduced ? t : cur + (t - cur) * 0.14;
      if (Math.abs(t - cur) < 0.0005) cur = t;
      render();
      if (inView && cur !== t) raf = requestAnimationFrame(frame);
    }
    const wake = () => { if (!raf && inView) raf = requestAnimationFrame(frame); };

    new IntersectionObserver((es) => { inView = es[0].isIntersecting; wake(); }, { rootMargin: '100px' }).observe(sec);
    window.addEventListener('scroll', wake, { passive: true });
    window.addEventListener('resize', () => { render(); wake(); });


    // Одно движение колеса — один кейс: страница сама доезжает до следующей карточки
    let animUntil = 0, lastWheel = 0;
    const ease = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
    // Шаги по таймеру, а не по rAF: в фоновой вкладке rAF замирает и полёт не завершился бы
    function glide(to) {
      const from = window.scrollY;
      const dist = to - from;
      if (reduced || Math.abs(dist) < 2) { window.scrollTo(0, to); return; }
      const dur = 650;
      const t0 = performance.now();
      animUntil = t0 + dur;
      const step = () => {
        const p = Math.min((performance.now() - t0) / dur, 1);
        window.scrollTo(0, from + dist * ease(p));
        if (p < 1) setTimeout(step, 16);
      };
      step();
    }
    window.addEventListener('wheel', (e) => {
      const r = sec.getBoundingClientRect();
      const total = sec.offsetHeight - window.innerHeight;
      // Перехватываем колесо только пока блок закреплён на экране
      if (e.ctrlKey || total <= 0 || r.top > 0 || r.bottom < window.innerHeight) return;
      const now = performance.now();
      const gap = now - lastWheel;
      lastWheel = now;
      const dir = Math.sign(e.deltaY);
      const base = Math.round(clamp(-r.top / total, 0, 1) * (n - 1));
      const next = base + dir;
      // На первом и последнем кейсе страница прокручивается дальше, как обычно
      if (!dir || next < 0 || next > n - 1) return;
      e.preventDefault();
      // Пока кейс летит, или пока трекпад досыпает инерцию, новые шаги не берём
      if (now < animUntil || gap < 180) return;
      glide(sec.getBoundingClientRect().top + window.scrollY + (total * next) / (n - 1));
    }, { passive: false });

    cur = targetPos();
    render();
  }

  /* ---------- Шапка: подложка после прокрутки ---------- */
  function initHead() {
    const head = document.querySelector('[data-head]');
    if (!head) return;
    const upd = () => head.classList.toggle('is-scrolled', window.scrollY > window.innerHeight * 0.6);
    window.addEventListener('scroll', upd, { passive: true });
    upd();
  }

  function start() { initSilk(); initCases(); initHead(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
