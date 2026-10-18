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
    model: 'Gemini 3.8 Flash',
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
        if (d.model) this.model = d.model.split('-').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
      }).catch(() => {});
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
      if (score >= 75) return { text: 'text-green-400', bg: 'bg-green-400', label: 'Сильное совпадение' };
      if (score >= 50) return { text: 'text-yellow-300', bg: 'bg-yellow-300', label: 'Среднее совпадение' };
      return { text: 'text-red-400', bg: 'bg-red-400', label: 'Слабое совпадение' };
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
      this.startStages();

      const fd = new FormData();
      fd.append('tone', this.tone);
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
      }
    },

    showResult(data) {
      this.result = data;
      this.letter = data.cover_letter;
      this.showAllBullets = false;
      this.shownScore = 0;
      this.barsOn = false;
      window.scrollTo({ top: 0, behavior: 'smooth' });
      this.$nextTick(() => {
        setTimeout(() => (this.barsOn = true), 100);
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
      window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    autosize(el) {
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
