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

async function renderSearchResults() {
  const root = document.querySelector("[data-search-results]");
  if (!root) return;

  const params = new URLSearchParams(window.location.search);
  const q = (params.get("q") || "").trim();

  const title = document.querySelector("[data-search-title]");
  if (title) {
    title.textContent = q ? `“${q}” 검색 결과` : "검색 결과";
  }

  if (!q) {
    root.innerHTML = `
      <div class="empty-state">
        <h3>검색어를 입력해 주세요.</h3>
        <p>비교하고 싶은 이슈나 키워드를 입력하면 관련 이슈를 보여드립니다.</p>
      </div>
    `;
    return;
  }

  try {
    const response = await fetch("./data/issue.json");

    if (!response.ok) {
      throw new Error("issue.json을 불러오지 못했습니다.");
    }

    const data = await response.json();

    const keyword = q.toLowerCase();

    const results = (data.issues || []).filter(issue => {
      const text = [
        issue.title,
        issue.category,
        issue.summary,
        ...(issue.common_facts || []),
        ...(issue.articles || []).flatMap(article => [
          article.title,
          ...(article.keywords || []),
          ...(article.people || [])
        ])
      ]
        .join(" ")
        .toLowerCase();

      return text.includes(keyword);
    });

    if (!results.length) {
      root.innerHTML = `
        <div class="empty-state">
          <h3>검색 결과가 없습니다.</h3>
          <p>다른 키워드로 검색해 보세요.</p>
          <a class="btn btn-secondary" href="index.html">
            메인으로 돌아가기
          </a>
        </div>
      `;
      return;
    }

    root.innerHTML = results.map(issue => `
      <article class="card">
        <span class="eyebrow">${issue.category}</span>

        <h3>${issue.title}</h3>

        <p>${issue.summary}</p>

        <div class="card-footer">
          <small>
            ${issue.articles.map(a => a.publisher).join(" · ")}
          </small>

          <a
            class="btn btn-primary"
            href="issue.html?id=${issue.issue_id}"
          >
            비교 보기
          </a>
        </div>
      </article>
    `).join("");

  } catch (err) {
    console.error(err);

    root.innerHTML = `
      <div class="empty-state">
        <h3>검색 결과를 불러오지 못했습니다.</h3>
      </div>
    `;
  }
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
async function renderLiveNews() {
  const root = document.querySelector("[data-live-news]");
  if (!root) return;

  try {
    const response = await fetch("./data/news.json");

    if (!response.ok) {
      throw new Error(`HTTP 오류: ${response.status}`);
    }

    const newsItems = await response.json();

    const INITIAL_COUNT = 4; 
    let visibleCount = INITIAL_COUNT;

    function render() {
      const visibleNews = newsItems.slice(0, visibleCount);

      root.innerHTML = visibleNews
        .map(
          (item) => `
        <article class="card">
          <span class="eyebrow">${item.publisher}</span>
          <h3>${item.title}</h3>
          <p>${item.summary || item.description || ""}</p>

          <div class="card-footer">
            <small>RSS 수집 기사</small>

            <a
              class="btn btn-secondary"
              href="${item.link}"
              target="_blank"
              rel="noopener noreferrer"
            >
              원문 보기
            </a>
          </div>
        </article>
      `
        )
        .join("");

      
      if (newsItems.length > INITIAL_COUNT) {
        const wrapper = document.createElement("div");
        wrapper.className = "load-more-wrap";
        wrapper.style.gridColumn = "1 / -1";
        wrapper.style.textAlign = "center";
        wrapper.style.marginTop = "24px";
        wrapper.style.display = "flex";
        wrapper.style.justifyContent = "center";
        wrapper.style.gap = "12px";

      
        if (visibleCount < newsItems.length) {
          const loadMoreBtn = document.createElement("button");
          loadMoreBtn.className = "btn btn-primary";
          loadMoreBtn.textContent = "더보기 ▾";
          
          loadMoreBtn.addEventListener("click", () => {
            visibleCount += 4;
            render();
          });
          
          wrapper.appendChild(loadMoreBtn);
        }

        
        if (visibleCount > INITIAL_COUNT) {
          const shrinkBtn = document.createElement("button");
          shrinkBtn.className = "btn btn-secondary";
          shrinkBtn.textContent = "줄이기 ▴";
          
          shrinkBtn.addEventListener("click", () => {
            visibleCount = INITIAL_COUNT;
            render();
            
            
            root.scrollIntoView({ behavior: "smooth", block: "start" });
          });
          
          wrapper.appendChild(shrinkBtn);
        }

        root.appendChild(wrapper);
      }
    }

    render();
  } catch (error) {
    console.error(error);

    root.innerHTML = `
      <div class="empty-state">
        <h3>뉴스를 불러오지 못했습니다.</h3>
        <p>잠시 후 다시 확인해 주세요.</p>
      </div>
    `;
  }
}
async function renderIssuePage() {
  const page = document.querySelector('[data-issue-page]');
  if (!page) return;

  try {
    const response = await fetch('./data/issue.json');

    if (!response.ok) {
      throw new Error(`HTTP 오류: ${response.status}`);
    }

    const issueData = await response.json();

    const params = new URLSearchParams(window.location.search);
    const requestedIssueId = params.get('id');

    const data =
      issueData.issues?.find(
      item => item.issue_id === requestedIssueId
      ) ||
      issueData.issues?.[0];

    if (!data) {
      throw new Error('표시할 이슈가 없습니다.');
    }

    document.querySelector('[data-issue-category]').textContent =
      data.category || '자동 분석';

    document.querySelector('[data-issue-title]').textContent =
      data.title || '이슈 제목 없음';

    document.querySelector('[data-issue-summary]').textContent =
      data.summary || '';

    const commonFacts = document.querySelector('[data-common-facts]');
    commonFacts.innerHTML = `
      <strong>공통으로 확인된 사실</strong><br>
      ${(data.common_facts || []).join('<br>')}
    `;

    const articlesRoot = document.querySelector('[data-issue-articles]');

    articlesRoot.innerHTML = (data.articles || []).map(article => `
      <article class="card media-card">
        <div class="media-name">
          <strong>${article.publisher}</strong>
        </div>

        <div class="compare-block">
          <span class="compare-label">핵심 키워드</span>
          <div class="meta">
            ${(article.keywords || []).map(keyword =>
              `<span class="badge blue">${keyword}</span>`
            ).join('')}
          </div>
        </div>

        <div class="compare-block">
          <span class="compare-label">주요 인물 및 기관</span>
          <div class="meta">
            ${(article.people || []).map(person =>
              `<span class="badge purple">${person}</span>`
            ).join('')}
          </div>
        </div>

        <div class="compare-block">
          <span class="compare-label">강조된 내용</span>
          <p class="compare-text">${article.focus || '명확한 차이를 확인하기 어려움'}</p>
        </div>

        <div class="compare-block">
          <span class="compare-label">표현 요약</span>
          <p class="compare-text">${article.expression_summary || ''}</p>
        </div>

        <div class="compare-block">
          <span class="compare-label">분석 한계</span>
          <p class="compare-text">${article.evidence_limit || ''}</p>
        </div>
      </article>
    `).join('');

    const sourcesRoot = document.querySelector('[data-issue-sources]');

    sourcesRoot.innerHTML = (data.articles || []).map(article => `
      <div class="source-item">
        <strong>${article.publisher}</strong>
        <a
          href="${article.link}"
          target="_blank"
          rel="noopener noreferrer"
        >
          ${article.title}
        </a>
      </div>
    `).join('');

  } catch (error) {
    console.error(error);

    document.querySelector('[data-issue-title]').textContent =
      '비교 결과를 불러오지 못했습니다.';

    document.querySelector('[data-common-facts]').textContent =
      '잠시 후 다시 확인해 주세요.';
  }
}

async function renderFeaturedIssue() {
  const root = document.querySelector("[data-featured-issues]");
  if (!root) return;

  try {
    const response = await fetch("./data/issue.json");

    if (!response.ok) {
      throw new Error("issue.json을 불러오지 못했습니다.");
    }

    const issueData = await response.json();

    const issues = issueData.issues || [];

    if (!issues.length) {
      root.innerHTML = `
        <div class="empty-state">
          <h3>비교 가능한 이슈가 없습니다.</h3>
        </div>
      `;
      return;
    }

    root.innerHTML = issues.map(issue => `
      <article class="card">

        <span class="eyebrow">${issue.category}</span>

        <h3>${issue.title}</h3>

        <p>${issue.summary}</p>

        <div class="meta">
          <span class="badge blue">
            ${issue.articles.length}개 기사 비교
          </span>
        </div>

        <div class="card-footer">
          <small>${issue.issue_id}</small>

          <a
            class="btn btn-primary"
            href="issue.html?id=${issue.issue_id}"
          >
            프레임 비교 보기
          </a>

        </div>

      </article>
    `).join("");

  } catch (error) {
    console.error(error);

    root.innerHTML = `
      <div class="empty-state">
        <h3>이슈를 불러오지 못했습니다.</h3>
      </div>
    `;
  }
}

async function renderSearchSuggestions() {
  const targets = document.querySelectorAll("[data-search-help]");
  if (!targets.length) return;

  try {
    const response = await fetch("./data/issue.json");

    if (!response.ok) {
      throw new Error("issue.json을 불러오지 못했습니다.");
    }

    const data = await response.json();

    const keywords = (data.issues || [])
      .flatMap(issue =>
        (issue.articles || []).flatMap(article => article.keywords || [])
      )
      .map(keyword => String(keyword).trim())
      .filter(Boolean);

    const uniqueKeywords = [...new Set(keywords)].slice(0, 5);

    if (!uniqueKeywords.length) {
      targets.forEach(target => {
        target.textContent = "추천 검색어가 없습니다.";
      });
      return;
    }

    targets.forEach(target => {
      target.innerHTML = `
        <span class="search-suggestion-label">추천 검색어</span>

        <div class="search-suggestion-list">
          ${uniqueKeywords.map(keyword => `
            <button
              type="button"
              class="search-suggestion-chip"
              data-search-keyword="${keyword}"
            >
              ${keyword}
            </button>
          `).join("")}
        </div>
      `;
    });

    document.querySelectorAll("[data-search-keyword]").forEach(button => {
      button.addEventListener("click", () => {
        const keyword = button.dataset.searchKeyword;
        if (!keyword) return;

        window.location.href =
          `search.html?q=${encodeURIComponent(keyword)}`;
      });
    });

  } catch (error) {
    console.error(error);

    targets.forEach(target => {
      target.textContent = "추천 검색어를 불러오지 못했습니다.";
    });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initMenu();
  initSearch();
  initSaveButtons();
  initShare();
  renderSearchResults();
  renderSearchSuggestions();
  renderSaved();
  renderLiveNews();
  renderIssuePage();
  renderFeaturedIssue();
});



document.addEventListener("DOMContentLoaded", () => {
  const loginNavBtn = document.getElementById("btn-login-nav");
  const loginModal = document.getElementById("login-modal");
  const closeModalBtn = document.getElementById("btn-close-modal");
  const authForm = document.getElementById("auth-form");
  
  const modalTitle = document.getElementById("modal-title");
  const modalDesc = document.getElementById("modal-desc");
  const fieldName = document.getElementById("field-name");
  const authNameInput = document.getElementById("auth-name");
  const authEmailInput = document.getElementById("auth-email");
  const authPasswordInput = document.getElementById("auth-password");
  const btnAuthSubmit = document.getElementById("btn-auth-submit");
  const switchText = document.getElementById("switch-text");
  const linkSwitchAuth = document.getElementById("link-switch-auth");

  if (!loginNavBtn || !loginModal) return;

  let isLoginMode = true; 
  let isLoggedIn = localStorage.getItem("isLoggedIn") === "true";

  updateLoginUI();

  loginNavBtn.addEventListener("click", () => {
    if (isLoggedIn) {
      localStorage.removeItem("isLoggedIn");
      isLoggedIn = false;
      alert("로그아웃 되었습니다.");
      updateLoginUI();
    } else {
      setAuthMode(true);
      loginModal.style.display = "flex";
    }
  });

  linkSwitchAuth.addEventListener("click", (e) => {
    e.preventDefault();
    setAuthMode(!isLoginMode);
  });

  function setAuthMode(toLoginMode) {
    isLoginMode = toLoginMode;
    authForm.reset(); 

    if (isLoginMode) {
      modalTitle.textContent = "Prism 로그인";
      modalDesc.textContent = "서비스 이용을 위해 로그인을 진행해 주세요.";
      fieldName.style.display = "none";
      authNameInput.removeAttribute("required");
      btnAuthSubmit.textContent = "로그인";
      switchText.textContent = "아직 계정이 없으신가요?";
      linkSwitchAuth.textContent = "회원가입";
    } else {
      modalTitle.textContent = "Prism 회원가입";
      modalDesc.textContent = "계정을 생성하고 나만의 이슈를 저장해 보세요.";
      fieldName.style.display = "block";
      authNameInput.setAttribute("required", "required");
      btnAuthSubmit.textContent = "회원가입 완료";
      switchText.textContent = "이미 계정이 있으신가요?";
      linkSwitchAuth.textContent = "로그인";
    }
  }

  closeModalBtn.addEventListener("click", () => loginModal.style.display = "none");
  loginModal.addEventListener("click", (e) => {
    if (e.target === loginModal) loginModal.style.display = "none";
  });


  authForm.addEventListener("submit", (e) => {
    e.preventDefault();

    const email = authEmailInput.value;
    const password = authPasswordInput.value;

    if (!isLoginMode) {
      const name = authNameInput.value;
      
    
      localStorage.setItem("user_email", email);
      localStorage.setItem("user_password", password);
      localStorage.setItem("user_name", name);

      alert(`${name}님, 회원가입이 완료되었습니다! 로그인해 주세요.`);
      setAuthMode(true); 
    } else {
    
      const savedEmail = localStorage.getItem("user_email");
      const savedPassword = localStorage.getItem("user_password");
      const savedName = localStorage.getItem("user_name");

    
      if (email === savedEmail && password === savedPassword) {
        localStorage.setItem("isLoggedIn", "true");
        isLoggedIn = true;
        alert(`반갑습니다, ${savedName || '사용자'}님! 성공적으로 로그인되었습니다.`);
        loginModal.style.display = "none";
        updateLoginUI();
      } else {
        alert("아이디(이메일) 또는 비밀번호가 일치하지 않습니다. 먼저 회원가입을 해주세요!");
      }
    }
  });

  function updateLoginUI() {
    if (isLoggedIn) {
      const savedName = localStorage.getItem("user_name") || "사용자";
      loginNavBtn.textContent = `${savedName}님 (로그아웃)`;
      loginNavBtn.classList.remove("btn-secondary");
      loginNavBtn.classList.add("btn-primary");
    } else {
      loginNavBtn.textContent = "로그인";
      loginNavBtn.classList.remove("btn-primary");
      loginNavBtn.classList.add("btn-secondary");
    }
  }
});