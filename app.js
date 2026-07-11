const issue = {
  id: 'football-hearing',
  category: '스포츠 · 정치',
  title: '축구협회 청문회 참고인 선정 논란',
  summary: '임오경 의원이 손흥민·황희찬 선수를 참고인으로 신청한 뒤 철회한 사건을 다룬 기사들을 비교합니다.',
  tags: ['참고인 선정', '청문회 적절성', '정치적 비판', '선수 일정'],
  mediaNames: ['연합뉴스', 'SBS 뉴스', '세계일보']
};

function initMenu() {
  const toggle = document.querySelector('[data-menu-toggle]');
  const nav = document.querySelector('[data-nav]');
  if (!toggle || !nav) return;
  toggle.addEventListener('click', () => {
    const open = nav.classList.toggle('open');
    toggle.setAttribute('aria-expanded', String(open));
  });
}

function initSearch() {
  document.querySelectorAll('[data-search-form]').forEach(form => {
    const input = form.querySelector('input');
    const button = form.querySelector('button[type="submit"]');
    if (!input || !button) return;
    const sync = () => { button.disabled = input.value.trim().length < 1; };
    input.addEventListener('input', sync);
    sync();
    form.addEventListener('submit', event => {
      event.preventDefault();
      const keyword = input.value.trim();
      if (!keyword) return;
      button.disabled = true;
      button.textContent = '검색 중';
      window.location.href = `search.html?q=${encodeURIComponent(keyword)}`;
    });
  });
}

function showToast(message) {
  let toast = document.querySelector('.toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.className = 'toast';
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 1800);
}

function initSaveButtons() {
  const key = 'prism-saved-issues';
  const read = () => JSON.parse(localStorage.getItem(key) || '[]');
  const write = data => localStorage.setItem(key, JSON.stringify(data));
  document.querySelectorAll('[data-save-issue]').forEach(btn => {
    const sync = () => {
      const saved = read().some(item => item.id === issue.id);
      btn.dataset.saved = String(saved);
      btn.textContent = saved ? '저장됨' : '이 이슈 저장';
    };
    sync();
    btn.addEventListener('click', () => {
      const saved = read();
      const exists = saved.some(item => item.id === issue.id);
      const next = exists ? saved.filter(item => item.id !== issue.id) : [...saved, issue];
      write(next);
      sync();
      showToast(exists ? '저장을 취소했습니다.' : '이슈를 저장했습니다.');
    });
  });
}

function initShare() {
  document.querySelectorAll('[data-share]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const url = window.location.href;
      try {
        if (navigator.share) await navigator.share({ title: issue.title, url });
        else await navigator.clipboard.writeText(url);
        if (!navigator.share) showToast('링크가 복사되었습니다.');
      } catch (_) {}
    });
  });
}

function renderSearchResults() {
  const root = document.querySelector('[data-search-results]');
  if (!root) return;
  const params = new URLSearchParams(window.location.search);
  const q = (params.get('q') || '').trim();
  const title = document.querySelector('[data-search-title]');
  if (title) title.textContent = q ? `“${q}” 검색 결과` : '검색 결과';

  const haystack = `${issue.title} ${issue.summary} ${issue.tags.join(' ')}`;
  const matched = q && haystack.includes(q);
  if (!q) {
    root.innerHTML = `<div class="empty-state"><h3>검색어를 입력해 주세요.</h3><p>비교하고 싶은 이슈나 키워드를 입력하면 관련 이슈를 보여드립니다.</p></div>`;
    return;
  }
  if (!matched && !['축구','청문회','임오경','손흥민','황희찬','참고인','정치'].some(k => q.includes(k))) {
    root.innerHTML = `<div class="empty-state"><h3>검색 결과가 없습니다.</h3><p>다른 키워드로 시도해 보세요.</p><a class="btn btn-secondary" href="index.html">메인으로 돌아가기</a></div>`;
    return;
  }
  root.innerHTML = issueCardMarkup(issue);
}

function issueCardMarkup(data) {
  return `<article class="card">
    <span class="eyebrow">${data.category}</span>
    <h3>${data.title}</h3>
    <p>${data.summary}</p>
    <div class="meta">${data.tags.map(t => `<span class="badge blue">${t}</span>`).join('')}</div>
    <div class="card-footer"><small>${data.mediaNames.join(' · ')}</small><a class="btn btn-primary" href="issue.html">프레임 비교 보기</a></div>
  </article>`;
}

function renderSaved() {
  const root = document.querySelector('[data-saved-list]');
  if (!root) return;
  const saved = JSON.parse(localStorage.getItem('prism-saved-issues') || '[]');
  if (!saved.length) {
    root.innerHTML = `<div class="saved-empty"><div class="empty-state"><h3>저장한 이슈가 없습니다.</h3><p>관심 있는 이슈를 저장하면 이곳에서 다시 볼 수 있습니다.</p><a class="btn btn-primary" href="index.html#topics">이슈 둘러보기</a></div></div>`;
    return;
  }
  root.innerHTML = saved.map(issueCardMarkup).join('');
}

document.addEventListener('DOMContentLoaded', () => {
  initMenu();
  initSearch();
  initSaveButtons();
  initShare();
  renderSearchResults();
  renderSaved();
});
