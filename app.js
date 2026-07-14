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
      window.location.href = `search-results.html?q=${encodeURIComponent(keyword)}`;
    });
  });
}

function renderFeatured() {
  const root = document.querySelector('[data-featured-issues]');
  if (!root) return;

  root.innerHTML = `
    <article class="card">
      <span class="eyebrow">${issue.category}</span>
      <h3>${issue.title}</h3>
      <p>${issue.summary}</p>
      <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px;">
        ${issue.tags.map(t => `<span class="badge blue">#${t}</span>`).join('')}
      </div>
      <div class="card-footer" style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
        <small style="color: #94a3b8;">분석 매체: ${issue.mediaNames.join(', ')}</small>
        <a class="btn btn-secondary btn-sm" href="issue.html?id=${issue.id}">분석 보기</a>
      </div>
    </article>
  `;
}

function renderSaved() {
  const root = document.querySelector('[data-saved-list]');
  if (!root) return; 
  
  const isLoggedIn = localStorage.getItem("isLoggedIn") === "true";
  
  if (!isLoggedIn) {
    root.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 60px 20px; background: #fff; border-radius: 12px; border: 1px dashed #ddd;">
        <h3 style="margin-bottom: 8px; color: #333;">로그인이 필요합니다.</h3>
        <p style="color: #666; font-size: 14px; margin-bottom: 20px;">로그인하시면 내가 저장한 이슈들을 이곳에서 모아볼 수 있습니다.</p>
        <button class="btn btn-primary" onclick="document.getElementById('login-modal').style.display='flex'">로그인하기</button>
      </div>`;
    return;
  }

  const saved = JSON.parse(localStorage.getItem('prism-saved-issues') || '[]');
  if (!saved.length) {
    root.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 40px 20px; background: #fff; border-radius: 8px; border: 1px dashed #ddd;">
        <h3 style="margin-bottom: 8px; color: #333;">저장한 이슈가 없습니다.</h3>
        <p style="color: #666; font-size: 14px; margin-bottom: 16px;">관심 있는 이슈를 저장하면 이곳에서 다시 볼 수 있습니다.</p>
        <a class="btn btn-primary" href="#live-news">이슈 둘러보기</a>
      </div>`;
    return;
  }

  root.innerHTML = saved.map(item => `
    <article class="issue-card">
      <div class="card-body">
        <span class="category">${item.category}</span>
        <h3 class="card-title">${item.title}</h3>
        <p class="card-desc">${item.summary}</p>
        <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px;">
          ${item.tags.map(t => `<span class="badge" style="background: #eef2f6; color: #4b5563; font-size: 12px; padding: 4px 8px; border-radius: 4px;">#${t}</span>`).join('')}
        </div>
        <div class="card-footer" style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #f1f5f9; padding-top: 12px; margin-top: auto;">
          <small class="media-info" style="color: #64748b; font-size: 12px;">분석 매체: ${item.mediaNames ? item.mediaNames.join(', ') : ''}</small>
          <a class="btn btn-secondary btn-sm" href="issue.html?id=${item.id}">분석 보기</a>
        </div>
      </div>
    </article>
  `).join('');
}

function initLiveNews() {
  const root = document.querySelector('[data-live-news-list]');
  if (!root) return;

  const liveIssues = [
    {
      id: 'medical-strike',
      category: '사회 · 정책',
      title: '의대 정원 증원 및 의료계 집단 행동',
      summary: '정부의 의대 증원 추진과 이에 맞선 전공의 사직 등 의료계 파업을 다루는 보수/진보 매체의 논조를 분석합니다.',
      tags: ['의대 증원', '의료 공백', '응급실 마비', '수가 조정'],
      mediaNames: ['조선일보', '한겨레', 'JTBC']
    },
    {
      id: 'semiconductor-subsidy',
      category: '경제 · 산업',
      title: '반도체 보조금 지원 법안 통과',
      summary: '국내 반도체 대기업 지원을 위한 보조금 특별법 통과와 관련된 언론사들의 세제 혜택 vs 특혜 논란 프레임을 비교합니다.',
      tags: ['반도체 특별법', '국가 보조금', '대기업 혜택', '글로벌 공급망'],
      mediaNames: ['동아일보', '경향신문', '매일경제']
    },
    {
      id: 'ai-copyright',
      category: 'IT · 문화',
      title: '생성형 AI 학습 데이터 저작권 가이드라인',
      summary: '문화체육관광부의 AI 학습 저작물 보상 기준 발표를 둘러싼 창작자 협회와 테크 기업 간의 대립 구도를 다룹니다.',
      tags: ['AI 저작권', '공정 이용', '창작자 권리', '데이터 라벨링'],
      mediaNames: ['중앙일보', '한국일보', '블로터']
    }
  ];

  root.innerHTML = liveIssues.map(item => `
    <article class="issue-card">
      <div class="card-body">
        <span class="category">${item.category}</span>
        <h3 class="card-title">${item.title}</h3>
        <p class="card-desc">${item.summary}</p>
        <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px;">
          ${item.tags.map(t => `<span class="badge" style="background: #eef2f6; color: #4b5563; font-size: 12px; padding: 4px 8px; border-radius: 4px;">#${t}</span>`).join('')}
        </div>
        <div class="card-footer" style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #f1f5f9; padding-top: 12px; margin-top: auto;">
          <small class="media-info" style="color: #64748b; font-size: 12px;">분석 매체: ${item.mediaNames.join(', ')}</small>
          <a class="btn btn-secondary btn-sm" href="issue.html?id=${item.id}">분석 보기</a>
        </div>
      </div>
    </article>
  `).join('');
}

function initAuth() {
  const modal = document.getElementById('login-modal');
  const btnLoginNav = document.getElementById('btn-login-nav');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnSwitchAuth = document.getElementById('btn-switch-auth');
  const authForm = document.getElementById('auth-form');
  
  const title = document.getElementById('auth-modal-title');
  const desc = document.getElementById('auth-modal-desc');
  const signupFields = document.getElementById('signup-only-fields');
  const submitBtn = document.getElementById('btn-auth-submit');
  const switchText = document.getElementById('auth-switch-text');

  let isSignupMode = false;

  if (!modal || !btnLoginNav) return;

  function updateAuthUI() {
    const isLoggedIn = localStorage.getItem('isLoggedIn') === 'true';
    if (isLoggedIn) {
      btnLoginNav.textContent = '로그아웃';
      btnLoginNav.className = 'btn btn-secondary';
    } else {
      btnLoginNav.textContent = '로그인';
      btnLoginNav.className = 'btn btn-secondary';
    }
  }

  btnLoginNav.addEventListener('click', () => {
    const isLoggedIn = localStorage.getItem('isLoggedIn') === 'true';
    if (isLoggedIn) {
      if (confirm('로그아웃 하시겠습니까?')) {
        localStorage.removeItem('isLoggedIn');
        alert('로그아웃 되었습니다.');
        updateAuthUI();
        renderSaved();
      }
    } else {
      isSignupMode = false;
      signupFields.style.display = 'none';
      title.textContent = '로그인';
      desc.textContent = 'Prism 계정으로 로그인하여 나만의 맞춤 뉴스 분석을 저장해보세요.';
      submitBtn.textContent = '로그인';
      switchText.textContent = '아직 계정이 없으신가요?';
      btnSwitchAuth.textContent = '회원가입';
      modal.style.display = 'flex';
    }
  });

  if (btnCloseModal) {
    btnCloseModal.addEventListener('click', () => {
      modal.style.display = 'none';
    });
  }

  if (btnSwitchAuth) {
    btnSwitchAuth.addEventListener('click', () => {
      isSignupMode = !isSignupMode;
      if (isSignupMode) {
        signupFields.style.display = 'block';
        title.textContent = '회원가입';
        desc.textContent = 'Prism 회원이 되어 원하시는 실시간 뉴스를 모아보고 맞춤형 분석 리포트를 받아보세요.';
        submitBtn.textContent = '가입하기';
        switchText.textContent = '이미 계정이 있으신가요?';
        btnSwitchAuth.textContent = '로그인';
      } else {
        signupFields.style.display = 'none';
        title.textContent = '로그인';
        desc.textContent = 'Prism 계정으로 로그인하여 나만의 맞춤 뉴스 분석을 저장해보세요.';
        submitBtn.textContent = '로그인';
        switchText.textContent = '아직 계정이 없으신가요?';
        btnSwitchAuth.textContent = '회원가입';
      }
    });
  }

  if (authForm) {
    authForm.addEventListener('submit', (e) => {
      e.preventDefault();
      localStorage.setItem('isLoggedIn', 'true');
      alert(isSignupMode ? '성공적으로 회원가입 되었습니다!' : '성공적으로 로그인 되었습니다!');
      modal.style.display = 'none';
      updateAuthUI();
      renderSaved();
    });
  }

  updateAuthUI();
}

document.addEventListener('DOMContentLoaded', () => {
  initMenu();
  initSearch();
  renderFeatured();
  renderSaved();
  initLiveNews();
  initAuth();
});