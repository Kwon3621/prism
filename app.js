let currentIssue = null;

const SAVED_ISSUES_KEY = 'prism-saved-issues';

function shuffleArray(array) {
  const result = [...array];
  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}

// 뷰 스타일 상태 관리 (기본값은 'card')
const viewModes = {
  liveNews: 'card',
  featured: 'card',
  saved: 'card'
};
// 뷰 토글 버튼 바인딩 함수
function initViewToggles() {
  document.querySelectorAll('[data-view-toggle]').forEach(group => {
    const sectionKey = group.dataset.viewToggle; // 'live-news', 'featured', 'saved'
    const buttons = group.querySelectorAll('[data-view]');
    
    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        const selectedView = btn.dataset.view; // 'card' or 'list'
        
        // 상태 변경
        if (sectionKey === 'live-news') {
          viewModes.liveNews = selectedView;
          renderLiveNews();
        } else if (sectionKey === 'featured') {
          viewModes.featured = selectedView;
          renderFeaturedIssue();
        } else if (sectionKey === 'saved') {
          viewModes.saved = selectedView;
          renderSaved();
        }
        // 활성화 스타일 클래스 업데이트
        buttons.forEach(b => {
          if (b === btn) {
            b.classList.add('active');
            b.style.background = '#fff';
            b.style.color = '#333';
            b.style.fontWeight = 'bold';
            b.style.boxShadow = '0 1px 3px rgba(0,0,0,0.1)';
          } else {
            b.classList.remove('active');
            b.style.background = 'transparent';
            b.style.color = '#666';
            b.style.fontWeight = 'normal';
            b.style.boxShadow = 'none';
          }
        });
      });
    });
  });
}

function readSavedIssues() {
  try {
    return JSON.parse(localStorage.getItem(SAVED_ISSUES_KEY) || '[]');
  } catch (error) {
    console.error('저장된 이슈를 읽지 못했습니다.', error);
    return [];
  }
}

function syncSaveButtons() {
  document.querySelectorAll('[data-save-issue]').forEach(btn => {
    if (!currentIssue) {
      btn.disabled = true;
      btn.textContent = '이슈 불러오는 중';
      return;
    }

    const isSaved = readSavedIssues().some(
      item => item.id === currentIssue.id
    );

    btn.disabled = false;
    btn.dataset.saved = String(isSaved);
    btn.textContent = isSaved ? '저장됨' : '이 이슈 저장';
  });
}

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
  document.querySelectorAll('[data-save-issue]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (!currentIssue) {
        showToast('이슈 정보를 아직 불러오고 있습니다.');
        return;
      }

      const isLoggedIn =
        localStorage.getItem('isLoggedIn') === 'true';

      if (!isLoggedIn) {
        showToast('로그인 후 이슈를 저장할 수 있습니다.');
        return;
      }

      const savedIssues = readSavedIssues();

      const alreadySaved = savedIssues.some(
        item => item.id === currentIssue.id
      );

      const nextSavedIssues = alreadySaved
        ? savedIssues.filter(item => item.id !== currentIssue.id)
        : [...savedIssues, currentIssue];

      localStorage.setItem(
        SAVED_ISSUES_KEY,
        JSON.stringify(nextSavedIssues)
      );

      syncSaveButtons();
      renderSaved();

      showToast(
        alreadySaved
          ? '저장을 취소했습니다.'
          : '이슈를 저장했습니다.'
      );
    });
  });

  syncSaveButtons();
}

function initShare() {
  document.querySelectorAll('[data-share]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const url = window.location.href;
      try {
        if (navigator.share) {
          await navigator.share({ title: document.title, url });
        } else {
          await navigator.clipboard.writeText(url);
          showToast('링크가 복사되었습니다.');
        }
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
          <a class="btn btn-primary" href="issue.html?id=${issue.issue_id}">
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

// 1. [내가 저장한 이슈] 렌더링 함수 - 더보기/줄이기
function renderSaved() {
  const root = document.querySelector('[data-saved-list]');
  if (!root) return; 
  
  const isLoggedIn = localStorage.getItem("isLoggedIn") === "true";
  
  // 미로그인 상태 처리
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
  
  // 저장된 리스트가 없는 경우 처리
  if (!saved.length) {
    root.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 60px 20px; background: #fff; border-radius: 12px; border: 1px dashed #ddd;">
        <h3 style="margin-bottom: 8px; color: #333;">저장한 이슈가 없습니다.</h3>
        <p style="color: #666; font-size: 14px; margin-bottom: 20px;">관심 있는 이슈를 저장하면 이곳에서 편리하게 모아볼 수 있습니다.</p>
        <a class="btn btn-primary" href="#topics">이슈 둘러보기</a>
      </div>`;
    return;
  }

  const INITIAL_COUNT = 3;
  if (typeof window.savedVisibleCount === 'undefined') {
    window.savedVisibleCount = INITIAL_COUNT;
  }

  const renderSavedCards = () => {
    const visibleSaved = saved.slice(0, window.savedVisibleCount);
    const viewMode = viewModes.saved;

    // 뷰 모드 상태에 따라 CSS Grid / Flex 구조 조절
    if (viewMode === 'list') {
      root.style.display = "flex";
      root.style.flexDirection = "column";
      root.style.gap = "12px";

      root.innerHTML = visibleSaved.map(item => `
        <article class="list-item" style="display: flex; align-items: center; justify-content: space-between; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; gap: 20px;">
          <div style="flex: 1; min-width: 0;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
              <span class="eyebrow" style="margin: 0; font-size: 12px;">${item.category}</span>
              <div class="meta" style="display: flex; gap: 4px;">
                ${(item.tags || []).map(t => `<span class="badge blue" style="font-size: 11px; padding: 2px 6px;">#${t}</span>`).join('')}
              </div>
            </div>
            <h3 style="font-size: 16px; margin: 0 0 4px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${item.title}</h3>
            <p style="font-size: 13px; color: #64748b; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${item.summary}</p>
          </div>
          <div style="display: flex; align-items: center; gap: 16px; flex-shrink: 0;">
            <small style="color: #94a3b8; font-size: 12px; display: block; text-align: right;">분석 매체: ${(item.mediaNames || []).join(', ')}</small>
            <a class="btn btn-secondary btn-sm" href="issue.html?id=${item.id}" style="white-space: nowrap;">분석 보기</a>
          </div>
        </article>
      `).join('');
    } else {
      // 기존 카드 뷰 레이아웃 복원
      root.style.display = "grid";
      root.style.gridTemplateColumns = "repeat(auto-fill, minmax(300px, 1fr))";
      root.style.gap = "24px";

      root.innerHTML = visibleSaved.map(item => `
        <article class="card">
          <span class="eyebrow">${item.category}</span>
          <h3>${item.title}</h3>
          <p>${item.summary}</p>
          <div class="meta" style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px;">
            ${(item.tags || []).map(t => `<span class="badge blue">#${t}</span>`).join('')}
          </div>
          <div class="card-footer" style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
            <small style="color: #94a3b8;">분석 매체: ${(item.mediaNames || []).join(', ')}</small>
            <a class="btn btn-secondary btn-sm" href="issue.html?id=${item.id}">분석 보기</a>
          </div>
        </article>
      `).join('');
    }

    // 더보기 / 줄이기 버튼 마크업
    if (saved.length > INITIAL_COUNT) {
      const wrapper = document.createElement("div");
      wrapper.className = "load-more-wrap";
      wrapper.style.gridColumn = "1 / -1";
      wrapper.style.width = "100%";
      wrapper.style.textAlign = "center";
      wrapper.style.marginTop = "24px";
      wrapper.style.display = "flex";
      wrapper.style.justifyContent = "center";
      wrapper.style.gap = "12px";

      if (window.savedVisibleCount < saved.length) {
        const loadMoreBtn = document.createElement("button");
        loadMoreBtn.className = "btn btn-primary";
        loadMoreBtn.textContent = "더보기 ▾";
        loadMoreBtn.addEventListener("click", () => {
          window.savedVisibleCount += 3;
          renderSavedCards();
        });
        wrapper.appendChild(loadMoreBtn);
      }

      if (window.savedVisibleCount > INITIAL_COUNT) {
        const shrinkBtn = document.createElement("button");
        shrinkBtn.className = "btn btn-secondary";
        shrinkBtn.textContent = "줄이기 ▴";
        shrinkBtn.addEventListener("click", () => {
          window.savedVisibleCount = INITIAL_COUNT;
          renderSavedCards();
          root.scrollIntoView({ behavior: "smooth", block: "start" });
        });
        wrapper.appendChild(shrinkBtn);
      }

      root.appendChild(wrapper);
    }
  };

  renderSavedCards();
}

// 2. [실시간 수집 뉴스] 렌더링 함수
// 2. [실시간 수집 뉴스] 렌더링 함수
async function renderLiveNews() {
  const root = document.querySelector("[data-live-news]");
  if (!root) return;

  try {
    const response = await fetch("./data/news.json");

    if (!response.ok) {
      throw new Error(`HTTP 오류: ${response.status}`);
    }

    const rawNewsItems = await response.json();
    const newsItems = shuffleArray(rawNewsItems);

    const INITIAL_COUNT = 4; 
    let visibleCount = INITIAL_COUNT;

    function render() {
      const visibleNews = newsItems.slice(0, visibleCount);
      const viewMode = viewModes.liveNews;

      if (viewMode === 'list') {
        root.className = ""; // grid-2 클래스 제거
        root.style.display = "flex";
        root.style.flexDirection = "column";
        root.style.gap = "12px";

        root.innerHTML = visibleNews.map(item => `
          <article class="list-item" style="display: flex; align-items: center; justify-content: space-between; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 20px; gap: 16px;">
            <div style="flex: 1; min-width: 0;">
              <span class="eyebrow" style="margin-bottom: 4px; display: inline-block; font-size: 11px;">${item.publisher}</span>
              <h3 style="font-size: 15px; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600;">${item.title}</h3>
            </div>
            <div style="flex-shrink: 0;">
              <a class="btn btn-secondary btn-sm" href="${item.link}" target="_blank" rel="noopener noreferrer" style="white-space: nowrap; padding: 6px 12px; font-size: 13px;">
                원문 보기
              </a>
            </div>
          </article>
        `).join("");
      } else {
        root.style.display = ""; // flex 제거
        root.className = "grid-2"; // CSS grid 클래스 적용

        root.innerHTML = visibleNews.map(item => `
          <article class="card">
            <span class="eyebrow">${item.publisher}</span>
            <h3>${item.title}</h3>
            <div class="card-footer" style="margin-top: auto; padding-top: 16px;">
              <a class="btn btn-secondary" href="${item.link}" target="_blank" rel="noopener noreferrer">
                원문 보기
              </a>
            </div>
          </article>
        `).join("");
      }

      if (newsItems.length > INITIAL_COUNT) {
        const wrapper = document.createElement("div");
        wrapper.className = "load-more-wrap";
        wrapper.style.width = "100%";
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

// 3. [이슈 비교 결과 페이지] 렌더링 함수
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
    currentIssue = {
      id: data.issue_id,
      category: data.category || '자동 분석',
      title: data.title || '이슈 제목 없음',
      summary: data.summary || '',
      tags: [
        ...new Set(
          (data.articles || []).flatMap(
            article => article.keywords || []
          )
        )
      ].slice(0, 6),
      mediaNames: [
        ...new Set(
          (data.articles || [])
            .map(article => article.publisher)
            .filter(Boolean)
        )
      ]
    };
    
    syncSaveButtons();

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

// 4. [이슈 비교 목록] 렌더링 함수 - 참조 변수 에러 및 구조 완벽 개선
// 4. [이슈 비교 목록] 렌더링 함수 - 참조 변수 에러 및 구조 완벽 개선
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

    const INITIAL_COUNT = 3;
    if (typeof window.featuredVisibleCount === 'undefined') {
      window.featuredVisibleCount = INITIAL_COUNT;
    }

    const renderFeaturedCards = () => {
      const visibleIssues = issues.slice(0, window.featuredVisibleCount);
      const viewMode = viewModes.featured;

      if (viewMode === 'list') {
        root.className = "";
        root.style.display = "flex";
        root.style.flexDirection = "column";
        root.style.gap = "12px";

        root.innerHTML = visibleIssues.map(issue => `
          <article class="list-item" style="display: flex; align-items: center; justify-content: space-between; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; gap: 16px;">
            <div style="flex: 1; min-width: 0;">
              <span class="eyebrow" style="margin-bottom: 4px; display: inline-block; font-size: 11px;">${issue.category}</span>
              <h3 style="font-size: 16px; margin: 0 0 4px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600;">${issue.title}</h3>
              <p style="font-size: 13px; color: #64748b; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${issue.summary}</p>
            </div>
            <div style="flex-shrink: 0;">
              <a class="btn btn-primary btn-sm" href="issue.html?id=${issue.issue_id}" style="white-space: nowrap;">
                프레임 비교 보기
              </a>
            </div>
          </article>
        `).join("");
      } else {
        root.style.display = "";
        root.className = "grid-3";

        root.innerHTML = visibleIssues.map(issue => `
          <article class="card">
            <span class="eyebrow">${issue.category}</span>
            <h3>${issue.title}</h3>
            <p>${issue.summary}</p>
            <div class="card-footer">
              <a class="btn btn-primary" href="issue.html?id=${issue.issue_id}">
                프레임 비교 보기
              </a>
            </div>
          </article>
        `).join("");
      }

      if (issues.length > INITIAL_COUNT) {
        const wrapper = document.createElement("div");
        wrapper.className = "load-more-wrap";
        wrapper.style.width = "100%";
        wrapper.style.gridColumn = "1 / -1";
        wrapper.style.textAlign = "center";
        wrapper.style.marginTop = "24px";
        wrapper.style.display = "flex";
        wrapper.style.justifyContent = "center";
        wrapper.style.gap = "12px";

        if (window.featuredVisibleCount < issues.length) {
          const loadMoreBtn = document.createElement("button");
          loadMoreBtn.className = "btn btn-primary";
          loadMoreBtn.textContent = "더보기 ▾";
          loadMoreBtn.addEventListener("click", () => {
            window.featuredVisibleCount += 3;
            renderFeaturedCards();
          });
          wrapper.appendChild(loadMoreBtn);
        }

        if (window.featuredVisibleCount > INITIAL_COUNT) {
          const shrinkBtn = document.createElement("button");
          shrinkBtn.className = "btn btn-secondary";
          shrinkBtn.textContent = "줄이기 ▴";
          shrinkBtn.addEventListener("click", () => {
            window.featuredVisibleCount = INITIAL_COUNT;
            renderFeaturedCards();
            root.scrollIntoView({ behavior: "smooth", block: "start" });
          });
          wrapper.appendChild(shrinkBtn);
        }

        root.appendChild(wrapper);
      }
    };

    renderFeaturedCards();

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

    const usedKeywords = new Set();
    const uniqueKeywords = [];

    for (const issue of (data.issues || [])) {
      const issueKeywords = (issue.articles || [])
        .flatMap(article => article.keywords || [])
        .map(keyword => String(keyword).trim())
        .filter(Boolean);

      const pick = issueKeywords.find(keyword => !usedKeywords.has(keyword));

      if (pick) {
        usedKeywords.add(pick);
        uniqueKeywords.push(pick);
      }

      if (uniqueKeywords.length >= 3) break;
    }

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
        window.location.href = `search.html?q=${encodeURIComponent(keyword)}`;
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
  initViewToggles(); // 뷰 토글 제어 초기화 추가!
  initSaveButtons();
  initShare();
  renderSearchResults();
  renderSearchSuggestions();
  renderSaved();
  renderLiveNews();
  renderIssuePage();
  renderFeaturedIssue();
  initViewToggles();
});

// 로그인/회원가입 기능 바인딩
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

  if (!loginModal) return;

  let isLoginMode = true;
  let isLoggedIn = localStorage.getItem("isLoggedIn") === "true";

  updateLoginUI();

  if (loginNavBtn) {
    loginNavBtn.addEventListener("click", () => {
      if (isLoggedIn) {
        localStorage.removeItem("isLoggedIn");
        isLoggedIn = false;
        alert("로그아웃 되었습니다.");
        updateLoginUI();
        
        if (window.location.pathname.includes("issue.html")) {
          location.reload();
        }
      } else {
        setAuthMode(true);
        loginModal.style.display = "flex";
      }
    });
  }

  if (closeModalBtn) {
    closeModalBtn.addEventListener("click", () => {
      loginModal.style.display = "none";
    });
  }

  loginModal.addEventListener("click", (e) => {
    if (e.target === loginModal) {
      loginModal.style.display = "none";
    }
  });

  if (linkSwitchAuth) {
    linkSwitchAuth.addEventListener("click", (e) => {
      e.preventDefault();
      setAuthMode(!isLoginMode);
    });
  }

  function setAuthMode(toLoginMode) {
    isLoginMode = toLoginMode;
    if (authForm) authForm.reset();

    if (isLoginMode) {
      if (modalTitle) modalTitle.textContent = "Prism 로그인";
      if (modalDesc) modalDesc.textContent = "서비스 이용을 위해 로그인을 진행해 주세요.";
      if (fieldName) fieldName.style.display = "none";
      if (authNameInput) authNameInput.removeAttribute("required");
      if (btnAuthSubmit) btnAuthSubmit.textContent = "로그인";
      if (switchText) switchText.textContent = "아직 계정이 없으신가요?";
      if (linkSwitchAuth) linkSwitchAuth.textContent = "회원가입";
    } else {
      if (modalTitle) modalTitle.textContent = "Prism 회원가입";
      if (modalDesc) modalDesc.textContent = "계정을 생성하고 나만의 이슈를 저장해 보세요.";
      if (fieldName) fieldName.style.display = "block";
      if (authNameInput) authNameInput.setAttribute("required", "required");
      if (btnAuthSubmit) btnAuthSubmit.textContent = "회원가입 완료";
      if (switchText) switchText.textContent = "이미 계정이 있으신가요?";
      if (linkSwitchAuth) linkSwitchAuth.textContent = "로그인";
    }
  }

  if (authForm) {
    authForm.addEventListener("submit", (e) => {
      e.preventDefault();

      const email = authEmailInput ? authEmailInput.value.trim() : "";
      const password = authPasswordInput ? authPasswordInput.value.trim() : "";

      if (!isLoginMode) {
        const name = authNameInput ? authNameInput.value.trim() : "";
        
        localStorage.setItem("user_email", email);
        localStorage.setItem("user_password", password);
        localStorage.setItem("user_name", name);

        alert(`${name}님, 회원가입이 완료되었습니다! 로그인해 주세요.`);
        setAuthMode(true);
      } else {
        const savedEmail = localStorage.getItem("user_email");
        const savedPassword = localStorage.getItem("user_password");
        const savedName = localStorage.getItem("user_name") || "사용자";

        if (email === savedEmail && password === savedPassword) {
          localStorage.setItem("isLoggedIn", "true");
          isLoggedIn = true;
          alert(`반갑습니다, ${savedName}님! 성공적으로 로그인되었습니다.`);
          loginModal.style.display = "none";
          updateLoginUI();
          
          renderSaved();
          
          if (window.location.pathname.includes("issue.html")) {
            location.reload(); 
          }
        } else {
          alert("아이디(이메일) 또는 비밀번호가 일치하지 않습니다. 회원가입 정보를 확인하거나 가입을 먼저 진행해 주세요!");
        }
      }
    });
  }

  function updateLoginUI() {
    if (!loginNavBtn) return;
    
    const loggedIn = localStorage.getItem("isLoggedIn") === "true";
    if (loggedIn) {
      const savedName = localStorage.getItem("user_name") || "사용자";
      loginNavBtn.textContent = `${savedName}님 (로그아웃)`;
      loginNavBtn.classList.remove("btn-secondary");
      loginNavBtn.classList.add("btn-primary");
    } else {
      loginNavBtn.textContent = "로그인";
      loginNavBtn.classList.remove("btn-primary");
      loginNavBtn.classList.add("btn-secondary");
    }
    
    renderSaved();
  }
});

// 뒤로 가기 및 캐시 복원 대응
window.addEventListener('pageshow', () => {
  renderSaved();
  syncSaveButtons();
});

// 데이터 변화 모니터링 대응
window.addEventListener('storage', event => {
  if (
    event.key === 'prism-saved-issues' ||
    event.key === 'isLoggedIn'
  ) {
    renderSaved();
    syncSaveButtons();
  }
});