// Плавная, но быстрая прокрутка: 0,4–0,9 секунды в зависимости от расстояния
function smoothScrollTo(y) {
  const max = document.documentElement.scrollHeight - window.innerHeight;
  const from = window.scrollY;
  const to = Math.max(0, Math.min(y, max));
  const dist = to - from;
  if (Math.abs(dist) < 2 || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    window.scrollTo(0, to);
    return;
  }
  const dur = Math.min(900, 400 + Math.abs(dist) * 0.08);
  const ease = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
  const t0 = performance.now();
  let stopped = false;
  // Пользователь крутит колесо или касается экрана: отдаём ему управление
  const stop = () => { stopped = true; };
  window.addEventListener('wheel', stop, { passive: true, once: true });
  window.addEventListener('touchstart', stop, { passive: true, once: true });
  const step = (now) => {
    if (stopped) return;
    const p = Math.min((now - t0) / dur, 1);
    window.scrollTo(0, from + dist * ease(p));
    if (p < 1) requestAnimationFrame(step);
    else {
      window.removeEventListener('wheel', stop);
      window.removeEventListener('touchstart', stop);
    }
  };
  requestAnimationFrame(step);
}

function scrollToEl(el, block = 'start') {
  if (!el) return;
  const r = el.getBoundingClientRect();
  const offset = block === 'center' ? (window.innerHeight - r.height) / 2 : 0;
  smoothScrollTo(r.top + window.scrollY - offset);
}

// Ссылки-якоря на странице прокручиваем плавно и переводим фокус к разделу
document.addEventListener('click', (e) => {
  const a = e.target.closest && e.target.closest('a[href^="#"]');
  if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
  const el = document.getElementById(a.getAttribute('href').slice(1));
  if (!el) return;
  e.preventDefault();
  scrollToEl(el);
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1');
  el.focus({ preventScroll: true });
});

document.addEventListener('alpine:init', () => {
  // Выбор модели: одна разметка из <template id="tpl-model"> в шапке и в форме
  const tpl = document.getElementById('tpl-model');
  document.querySelectorAll('[data-model-slot]').forEach((slot) => slot.appendChild(tpl.content.cloneNode(true)));

  window.Alpine.data('modelPicker', (uid) => ({
    uid,
    open: false,
    active: 0,

    init() {
      this.$watch('loading', (v) => { if (v) this.open = false; });
    },

    show() {
      if (this.loading || !this.models.length) return;
      this.active = Math.max(0, this.models.findIndex((m) => m.provider === this.selected));
      this.open = true;
      this.$nextTick(() => this.$refs.list.focus());
    },

    hide(focusButton = true) {
      this.open = false;
      if (focusButton) this.$nextTick(() => this.$refs.btn.focus());
    },

    pick(m) {
      this.selected = m.provider;
      this.hide();
    },

    key(e) {
      const n = this.models.length;
      if (!n) return;
      const keys = {
        ArrowDown: () => { this.active = (this.active + 1) % n; },
        ArrowUp: () => { this.active = (this.active - 1 + n) % n; },
        Home: () => { this.active = 0; },
        End: () => { this.active = n - 1; },
        Enter: () => this.pick(this.models[this.active]),
        ' ': () => this.pick(this.models[this.active]),
        Escape: () => this.hide(),
      };
      if (e.key === 'Tab') { this.hide(false); return; }
      if (!keys[e.key]) return;
      e.preventDefault();
      keys[e.key]();
    },
  }));
});

function matcher() {
  const MAX_PDF_MB = 10;
  return {
    tones: ['Профессиональный', 'Уверенный / Стартап', 'Краткий и по делу'],
    tone: 'Профессиональный',
    resumeMode: 'pdf',
    jobMode: 'text',
    file: null,
    resumeText: '',
    jobText: '',
    jobUrl: '',
    dragging: false,
    demoLoading: false,
    loading: false,
    stage: 0,
    stages: [
      'Читаем PDF-резюме...',
      'Извлекаем ключевые требования ATS...',
      'Формируем рекомендации и Cover Letter...',
    ],
    categories: [
      { key: 'hard_skills_score', label: 'Hard Skills — стек и технологии' },
      { key: 'experience_score', label: 'Опыт и проекты' },
      { key: 'ats_readability_score', label: 'ATS-читаемость и ключевые слова' },
    ],
    error: '',
    result: null,
    letter: '',
    copied: '',
    models: [],
    selected: '',
    showAllBullets: false,
    shownScore: 0,
    barsOn: false,
    circumference: 2 * Math.PI * 54,
    _stageTimer: null,

    init() {
      this.$watch('resumeMode', () => this.icons());
      this.$watch('jobMode', () => this.icons());
      this.$watch('file', () => this.icons());
      this.$watch('loading', () => this.icons());
      this.$watch('result', () => this.icons());
      this.$watch('error', () => this.icons());
      this.icons();
      fetch('/api/health').then((r) => r.json()).then((d) => {
        if (!Array.isArray(d.models)) return;
        this.models = d.models;
        let saved = '';
        try { saved = localStorage.getItem('ats-model') || ''; } catch (e) { /* без сохранения */ }
        this.selected = this.models.some((m) => m.provider === saved) ? saved : (this.models[0] ? this.models[0].provider : '');
        this.$watch('selected', (v) => { try { localStorage.setItem('ats-model', v); } catch (e) { /* без сохранения */ } });
        this.icons();
      }).catch(() => {});
    },

    get selectedModel() {
      return this.models.find((m) => m.provider === this.selected) || { label: '', vendor: '', note: '', eta: '' };
    },

    // Цветная метка поставщика модели в списке выбора
    mark(provider) {
      // Логотипы: Яндекс, Gemini и DeepSeek из lobe-icons (MIT), GigaChat с официального сайта giga.chat
      const marks = {
        yandex: { bg: '#fc3f1d', svg: '<svg viewBox="0 0 24 24" fill="#fff" fill-rule="evenodd" aria-hidden="true"><path d="M16.376 12.644L21 2h-3.842l-4.624 10.644h3.842zM13.915 24v-3.733c0-2.822-.352-3.64-1.407-5.988L6.933 2H3l7.124 15.709V24h3.79z"></path></svg>' },
        gemini: { bg: '#ffffff', svg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.616 10.835a14.147 14.147 0 01-4.45-3.001 14.111 14.111 0 01-3.678-6.452.503.503 0 00-.975 0 14.134 14.134 0 01-3.679 6.452 14.155 14.155 0 01-4.45 3.001c-.65.28-1.318.505-2.002.678a.502.502 0 000 .975c.684.172 1.35.397 2.002.677a14.147 14.147 0 014.45 3.001 14.112 14.112 0 013.679 6.453.502.502 0 00.975 0c.172-.685.397-1.351.677-2.003a14.145 14.145 0 013.001-4.45 14.113 14.113 0 016.453-3.678.503.503 0 000-.975 13.245 13.245 0 01-2.003-.678z" fill="#3186FF"></path><path d="M20.616 10.835a14.147 14.147 0 01-4.45-3.001 14.111 14.111 0 01-3.678-6.452.503.503 0 00-.975 0 14.134 14.134 0 01-3.679 6.452 14.155 14.155 0 01-4.45 3.001c-.65.28-1.318.505-2.002.678a.502.502 0 000 .975c.684.172 1.35.397 2.002.677a14.147 14.147 0 014.45 3.001 14.112 14.112 0 013.679 6.453.502.502 0 00.975 0c.172-.685.397-1.351.677-2.003a14.145 14.145 0 013.001-4.45 14.113 14.113 0 016.453-3.678.503.503 0 000-.975 13.245 13.245 0 01-2.003-.678z" fill="url(#lobe-icons-gemini-0-_R_0_)"></path><path d="M20.616 10.835a14.147 14.147 0 01-4.45-3.001 14.111 14.111 0 01-3.678-6.452.503.503 0 00-.975 0 14.134 14.134 0 01-3.679 6.452 14.155 14.155 0 01-4.45 3.001c-.65.28-1.318.505-2.002.678a.502.502 0 000 .975c.684.172 1.35.397 2.002.677a14.147 14.147 0 014.45 3.001 14.112 14.112 0 013.679 6.453.502.502 0 00.975 0c.172-.685.397-1.351.677-2.003a14.145 14.145 0 013.001-4.45 14.113 14.113 0 016.453-3.678.503.503 0 000-.975 13.245 13.245 0 01-2.003-.678z" fill="url(#lobe-icons-gemini-1-_R_0_)"></path><path d="M20.616 10.835a14.147 14.147 0 01-4.45-3.001 14.111 14.111 0 01-3.678-6.452.503.503 0 00-.975 0 14.134 14.134 0 01-3.679 6.452 14.155 14.155 0 01-4.45 3.001c-.65.28-1.318.505-2.002.678a.502.502 0 000 .975c.684.172 1.35.397 2.002.677a14.147 14.147 0 014.45 3.001 14.112 14.112 0 013.679 6.453.502.502 0 00.975 0c.172-.685.397-1.351.677-2.003a14.145 14.145 0 013.001-4.45 14.113 14.113 0 016.453-3.678.503.503 0 000-.975 13.245 13.245 0 01-2.003-.678z" fill="url(#lobe-icons-gemini-2-_R_0_)"></path><defs><linearGradient gradientUnits="userSpaceOnUse" id="lobe-icons-gemini-0-_R_0_" x1="7" x2="11" y1="15.5" y2="12"><stop stop-color="#08B962"></stop><stop offset="1" stop-color="#08B962" stop-opacity="0"></stop></linearGradient><linearGradient gradientUnits="userSpaceOnUse" id="lobe-icons-gemini-1-_R_0_" x1="8" x2="11.5" y1="5.5" y2="11"><stop stop-color="#F94543"></stop><stop offset="1" stop-color="#F94543" stop-opacity="0"></stop></linearGradient><linearGradient gradientUnits="userSpaceOnUse" id="lobe-icons-gemini-2-_R_0_" x1="3.5" x2="17.5" y1="13.5" y2="12"><stop stop-color="#FABC12"></stop><stop offset=".46" stop-color="#FABC12" stop-opacity="0"></stop></linearGradient></defs></svg>' },
        gigachat: { bg: '#ffffff', svg: '<svg class="mark-full" viewBox="44 44 424 424" aria-hidden="true"><path fill="#080808" fill-rule="evenodd" d="M256 44c117.076 0 212 94.908 212 212s-94.924 212-212 212S44 373.076 44 256 138.924 44 256 44m174.562 160.622c-5.358 37.156-24.245 67.817-40.003 87.77-24.32 29.958-56.902 55.894-94.291 75.06-36.983 18.963-76.989 30.481-115.685 33.309-6.549.377-12.632.563-18.334.563-6.785 0-13.04-.271-18.978-.805 31.029 24.305 70.125 38.796 112.591 38.796l-.023-.023c100.941 0 182.786-81.833 182.786-182.774-.001-17.517-2.471-34.453-7.074-50.493-.33-.471-.659-.948-.989-1.403M282.005 63.334c-62.448 0-119.214 25.754-151.845 68.861l-.208.253c-14.106 17.186-23.483 36.04-27.098 54.53-2.058 11.249-1.677 21.581 1.151 30.583v-.023c6.708 20.141 23.025 36.293 41.532 41.038 7.698 1.917 15.099 2.718 21.98 2.404l1.817-.161c46.787-3.77 88.507-33.257 123.15-61.615 21.679-18.145 42.417-42.152 43.752-57.658-30.227 14.658-61.431 33.73-97.408 59.51-3.991 2.844-9.43 2.048-12.399-1.817-17.863-23.126-33.417-41.906-48.986-59.061-1.694-1.885-2.54-4.413-2.289-6.925a9 9 0 0 1 3.566-6.348c47.696-35.773 95.141-56.042 141.172-60.316-12.346-2.167-25.007-3.254-37.887-3.255" clip-rule="evenodd"/></svg>' },
        deepseek: { bg: '#4d6bfe', svg: '<svg viewBox="0 0 24 24" fill="#fff" fill-rule="evenodd" aria-hidden="true"><path d="M23.748 4.482c-.254-.124-.364.113-.512.234-.051.039-.094.09-.137.136-.372.397-.806.657-1.373.626-.829-.046-1.537.214-2.163.848-.133-.782-.575-1.248-1.247-1.548-.352-.156-.708-.311-.955-.65-.172-.241-.219-.51-.305-.774-.055-.16-.11-.323-.293-.35-.2-.031-.278.136-.356.276-.313.572-.434 1.202-.422 1.84.027 1.436.633 2.58 1.838 3.393.137.093.172.187.129.323-.082.28-.18.552-.266.833-.055.179-.137.217-.329.14a5.526 5.526 0 01-1.736-1.18c-.857-.828-1.631-1.742-2.597-2.458a11.365 11.365 0 00-.689-.471c-.985-.957.13-1.743.388-1.836.27-.098.093-.432-.779-.428-.872.004-1.67.295-2.687.684a3.055 3.055 0 01-.465.137 9.597 9.597 0 00-2.883-.102c-1.885.21-3.39 1.102-4.497 2.623C.082 8.606-.231 10.684.152 12.85c.403 2.284 1.569 4.175 3.36 5.653 1.858 1.533 3.997 2.284 6.438 2.14 1.482-.085 3.133-.284 4.994-1.86.47.234.962.327 1.78.397.63.059 1.236-.03 1.705-.128.735-.156.684-.837.419-.961-2.155-1.004-1.682-.595-2.113-.926 1.096-1.296 2.746-2.642 3.392-7.003.05-.347.007-.565 0-.845-.004-.17.035-.237.23-.256a4.173 4.173 0 001.545-.475c1.396-.763 1.96-2.015 2.093-3.517.02-.23-.004-.467-.247-.588zM11.581 18c-2.089-1.642-3.102-2.183-3.52-2.16-.392.024-.321.471-.235.763.09.288.207.486.371.739.114.167.192.416-.113.603-.673.416-1.842-.14-1.897-.167-1.361-.802-2.5-1.86-3.301-3.307-.774-1.393-1.224-2.887-1.298-4.482-.02-.386.093-.522.477-.592a4.696 4.696 0 011.529-.039c2.132.312 3.946 1.265 5.468 2.774.868.86 1.525 1.887 2.202 2.891.72 1.066 1.494 2.082 2.48 2.914.348.292.625.514.891.677-.802.09-2.14.11-3.054-.614zm1-6.44a.306.306 0 01.415-.287.302.302 0 01.2.288.306.306 0 01-.31.307.303.303 0 01-.304-.308zm3.11 1.596c-.2.081-.399.151-.59.16a1.245 1.245 0 01-.798-.254c-.274-.23-.47-.358-.552-.758a1.73 1.73 0 01.016-.588c.07-.327-.008-.537-.239-.727-.187-.156-.426-.199-.688-.199a.559.559 0 01-.254-.078c-.11-.054-.2-.19-.114-.358.028-.054.16-.186.192-.21.356-.202.767-.136 1.146.016.352.144.618.408 1.001.782.391.451.462.576.685.914.176.265.336.537.445.848.067.195-.019.354-.25.452z"></path></svg>' },
      };
      return marks[provider] || { ch: '•', bg: 'var(--violet)' };
    },

    markHtml(provider) {
      const m = this.mark(provider);
      return m.svg || m.ch;
    },

    icons() {
      this.$nextTick(() => window.lucide && window.lucide.createIcons());
    },

    get fileSize() {
      if (!this.file) return '';
      const kb = this.file.size / 1024;
      return kb > 1024 ? (kb / 1024).toFixed(1) + ' МБ' : Math.round(kb) + ' КБ';
    },

    get resumeReady() {
      return this.resumeMode === 'pdf' ? !!this.file : this.resumeText.trim().length > 0;
    },

    get jobReady() {
      return this.jobMode === 'text' ? this.jobText.trim().length > 0 : this.jobUrl.trim().length > 0;
    },

    get visibleBullets() {
      const all = (this.result && this.result.bullet_improvements) || [];
      return this.showAllBullets ? all : all.slice(0, 2);
    },

    get canSubmit() {
      return this.resumeReady && this.jobReady && !this.loading;
    },

    scoreTone(score) {
      if (score >= 75) return { text: 't-ok', bg: 'b-ok', label: 'Сильное совпадение' };
      if (score >= 50) return { text: 't-mid', bg: 'b-mid', label: 'Среднее совпадение' };
      return { text: 't-bad', bg: 'b-bad', label: 'Слабое совпадение' };
    },

    onDrop(e) {
      this.dragging = false;
      this.onFile(e.dataTransfer.files[0]);
    },

    onFile(f) {
      if (!f) return;
      this.error = '';
      if (!/\.pdf$/i.test(f.name) && f.type !== 'application/pdf') {
        this.error = 'Нужен файл в формате PDF';
        return;
      }
      if (f.size > MAX_PDF_MB * 1024 * 1024) {
        this.error = `PDF больше ${MAX_PDF_MB} МБ`;
        return;
      }
      this.file = f;
    },

    scrollToForm(block = 'start') {
      this.$nextTick(() => scrollToEl(document.getElementById(block === 'start' ? 'check' : 'submit-area'), block));
    },

    async loadDemo() {
      this.demoLoading = true;
      this.error = '';
      try {
        const res = await fetch('/api/demo');
        const data = await res.json();
        this.file = null;
        this.resumeMode = 'text';
        this.resumeText = data.resume_text;
        this.jobMode = 'text';
        this.jobText = data.job_text;
        this.jobUrl = '';
      } catch (e) {
        this.error = 'Не удалось загрузить демо-данные';
      } finally {
        this.demoLoading = false;
      }
    },

    startStages() {
      this.stage = 0;
      clearInterval(this._stageTimer);
      this._stageTimer = setInterval(() => {
        if (this.stage < this.stages.length - 1) this.stage++;
      }, 3500);
      if (this.resumeMode !== 'pdf') this.stage = 1;
    },

    async submit() {
      if (!this.canSubmit) return;
      this.error = '';
      this.loading = true;
      window.scrollTo({ top: 0 });
      this.startStages();

      const fd = new FormData();
      fd.append('tone', this.tone);
      if (this.selected) fd.append('model', this.selected);
      if (this.resumeMode === 'pdf') fd.append('resume_file', this.file);
      else fd.append('resume_text', this.resumeText);
      if (this.jobMode === 'text') fd.append('job_text', this.jobText);
      else fd.append('job_url', this.jobUrl.trim());

      try {
        const res = await fetch('/api/analyze', { method: 'POST', body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `Ошибка сервера (${res.status})`);
        this.showResult(data);
      } catch (e) {
        this.error = e instanceof TypeError ? 'Нет связи с сервером. Проверьте подключение.' : e.message;
      } finally {
        clearInterval(this._stageTimer);
        this.loading = false;
        if (this.error) this.scrollToForm('center');
      }
    },

    showResult(data) {
      this.result = data;
      this.letter = data.cover_letter;
      this.showAllBullets = false;
      this.shownScore = 0;
      this.barsOn = false;
      window.scrollTo({ top: 0 });
      this.$nextTick(() => {
        setTimeout(() => {
          this.barsOn = true;
          // Высоту письма считаем, когда отчёт уже виден на экране
          document.querySelectorAll('textarea.letter').forEach((t) => this.autosize(t));
        }, 100);
        const target = data.overall_match_score;
        const start = performance.now();
        const dur = 1200;
        const tick = (now) => {
          const p = Math.min((now - start) / dur, 1);
          this.shownScore = target * (1 - Math.pow(1 - p, 3));
          if (p < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      });
    },

    reset() {
      this.result = null;
      this.error = '';
      this.scrollToForm();
    },

    autosize(el) {
      if (!el.offsetParent) return; // скрытое поле: высоту не посчитать, оставляем минимальную из CSS
      el.style.height = 'auto';
      el.style.height = el.scrollHeight + 4 + 'px';
    },

    async copy(text, key) {
      try {
        await navigator.clipboard.writeText(text);
      } catch (e) {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
      }
      this.copied = key;
      setTimeout(() => { if (this.copied === key) this.copied = ''; }, 2000);
    },

    buildMarkdown() {
      const r = this.result;
      const c = r.category_scores;
      const lines = [
        '# Отчёт AI Resume & ATS Matcher',
        '',
        `## Общее совпадение: ${r.overall_match_score}%`,
        '',
        r.llm ? `Разбор выполнила модель: ${r.llm.label} (${r.llm.vendor})${r.llm.fallback ? ', резервная' : ''}` : '',
        '',
        `- Hard Skills: ${c.hard_skills_score}%`,
        `- Опыт и проекты: ${c.experience_score}%`,
        `- ATS-читаемость: ${c.ats_readability_score}%`,
        '',
        '## Вердикт AI-рекрутера',
        '',
        r.executive_summary,
        '',
        '## Matched Skills',
        '',
        r.matched_keywords.map((k) => `\`${k}\``).join(', ') || '—',
        '',
        '## Missing Keywords (ATS Alert)',
        '',
        r.missing_keywords.map((k) => `\`${k}\``).join(', ') || '—',
        '',
        '## Улучшение резюме',
        '',
      ];
      r.bullet_improvements.forEach((b, i) => {
        lines.push(
          `### ${i + 1}.`,
          `**Было:** ${b.original_or_weak_point}`,
          '',
          `**Стало:** ${b.improved_bullet}`,
          '',
          `_Почему работает:_ ${b.why_it_works}`,
          ''
        );
      });
      lines.push('## Сопроводительное письмо', '', this.letter, '');
      return lines.join('\n');
    },

    exportMarkdown() {
      const blob = new Blob([this.buildMarkdown()], { type: 'text/markdown;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'ats-report.md';
      a.click();
      URL.revokeObjectURL(a.href);
    },

    printReport() {
      this.showAllBullets = true;
      this.$nextTick(() => {
        document.querySelectorAll('textarea').forEach((t) => this.autosize(t));
        window.print();
      });
    },
  };
}
