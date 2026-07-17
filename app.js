// [v2 개편 안전장치] ?mode=legacy 주소로 들어오면 옛날 데이터(issue.json)를 보여줍니다.
function isLegacyMode() {
  const params = new URLSearchParams(window.location.search);
  return params.get('mode') === 'legacy';
}

let currentIssue = null;
const SAVED_ISSUES_KEY = 'prism-saved-issues';

// 배열 요소를 무작위로 섞어주는 유틸리티 함수
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

// 뷰 토글 버튼 바인딩 함수 (중복 등록 방지 처리 완료)
function initViewToggles() {
  document.querySelectorAll('[data-view-toggle]').forEach(group => {
    const sectionKey = group.dataset.viewToggle; // 'live-news', 'featured', 'saved'
    const buttons = group.querySelectorAll('[data-view]');
    
    buttons.forEach(btn => {
      // 기존에 붙어있을 수 있는 중복 이벤트를 방지하기 위해 clone 생성 후 대체하는 안전 코드
      const newBtn = btn.cloneNode(true);
      btn.parentNode.replaceChild(newBtn, btn);

      newBtn.addEventListener('click', () => {
        const selectedView = newBtn.dataset.view; // 'card' or 'list'
        
        // 상태 변경 및 해당 섹션 즉시 재렌더링
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
        group.querySelectorAll('[data-view]').forEach(b => {
          if (b.dataset.view === selectedView) {
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
      window.location.href = `compare.html?q=${encodeURIComponent(keyword)}`;
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

      const isLoggedIn = localStorage.getItem('isLoggedIn') === 'true';

      if (!isLoggedIn) {
        showToast('로그인 후 이슈를 저장할 수 있습니다.');
        return;
      }

      const savedIssues = readSavedIssues();
      const alreadySaved = savedIssues.some(item => item.id === currentIssue.id);

      const nextSavedIssues = alreadySaved
        ? savedIssues.filter(item => item.id !== currentIssue.id)
        : [...savedIssues, currentIssue];

      localStorage.setItem(SAVED_ISSUES_KEY, JSON.stringify(nextSavedIssues));

      syncSaveButtons();
      renderSaved();

      showToast(alreadySaved ? '저장을 취소했습니다.' : '이슈를 저장했습니다.');
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
            <a class="btn btn-secondary btn-sm" href="compare.html?q=${item.title}" style="white-space: nowrap;">분석 보기</a>
          </div>
        </article>
      `).join('');
    } else {
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
            <a class="btn btn-secondary btn-sm" href="compare.html?q=${item.title}">분석 보기</a>
          </div>
        </article>
      `).join('');
    }

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

function formatPublishedTime(value) {
  if (!value) return '발행 시간 정보 없음';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '발행 시간 정보 없음';
  return date.toLocaleString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  });
}

async function renderLiveNews() {
  const root = document.querySelector("[data-live-news]");
  if (!root) return;

  try {
    const response = await fetch("./data/issue.json");
    if (!response.ok) throw new Error(`HTTP 오류: ${response.status}`);

    const rawData = await response.json();
    const newsItems = [];

    // [v2 뉴스 연동] issue.json의 하위 기사 데이터를 모아 실시간 뉴스로 띄워줍니다.
    (rawData.issues || []).forEach(issue => {
      (issue.articles || []).forEach(art => {
        newsItems.push({
          publisher: art.publisher,
          title: art.title,
          link: art.link,
          published: art.published_times ? art.published_times[0] : ''
        });
      });
    });

    const shuffledNews = shuffleArray(newsItems);
    const INITIAL_COUNT = 4;
    let visibleCount = INITIAL_COUNT;

    const publishers = [...new Set(shuffledNews.map(item => item.publisher))];
    let selectedPublishers = new Set(publishers);

    function renderPublisherFilters() {
      const filterRoot = document.querySelector('[data-publisher-checkboxes]');
      if (!filterRoot) return;

      filterRoot.innerHTML = publishers.map(publisher => `
        <label class="filter-checkbox-item">
          <input type="checkbox" value="${publisher}" checked data-publisher-checkbox>
          <span>${publisher}</span>
        </label>
      `).join('');

      const checkboxes = filterRoot.querySelectorAll('[data-publisher-checkbox]');
      checkboxes.forEach(checkbox => {
        checkbox.addEventListener('change', () => {
          if (checkbox.checked) {
            selectedPublishers.add(checkbox.value);
          } else {
            selectedPublishers.delete(checkbox.value);
          }
          visibleCount = INITIAL_COUNT;
          render();
        });
      });

      const selectAllBtn = document.querySelector('[data-select-all]');
      const deselectAllBtn = document.querySelector('[data-deselect-all]');

      if (selectAllBtn) {
        selectAllBtn.onclick = () => {
          selectedPublishers = new Set(publishers);
          checkboxes.forEach(checkbox => { checkbox.checked = true; });
          visibleCount = INITIAL_COUNT;
          render();
        };
      }

      if (deselectAllBtn) {
        deselectAllBtn.onclick = () => {
          selectedPublishers = new Set();
          checkboxes.forEach(checkbox => { checkbox.checked = false; });
          visibleCount = INITIAL_COUNT;
          render();
        };
      }
    }
    
    function render() {
      const filteredNews = shuffledNews.filter(item => selectedPublishers.has(item.publisher));
      const visibleNews = filteredNews.slice(0, visibleCount);
      const viewMode = viewModes.liveNews;

      if (!filteredNews.length) {
        root.className = "";
        root.style.display = "";
        root.innerHTML = `
          <div class="empty-state">
            <h3>선택한 언론사의 뉴스가 없습니다.</h3>
            <p>다른 언론사를 선택해 보세요.</p>
          </div>
        `;
        return;
      }

      if (viewMode === 'list') {
        root.className = "";
        root.style.display = "flex";
        root.style.flexDirection = "column";
        root.style.gap = "12px";

        root.innerHTML = visibleNews.map(item => `
          <article class="list-item" style="display: flex; align-items: center; justify-content: space-between; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 20px; gap: 16px;">
            <div style="flex: 1; min-width: 0;">
              <span class="eyebrow" style="margin-bottom: 4px; display: inline-block; font-size: 11px;">${item.publisher}</span>
              <h3 style="font-size: 15px; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600;">${item.title}</h3>
              <small class="live-news-time">${formatPublishedTime(item.published)}</small>
            </div>
            <div style="flex-shrink: 0;">
              <a class="btn btn-secondary btn-sm" href="${item.link}" target="_blank" rel="noopener noreferrer" style="white-space: nowrap; padding: 6px 12px; font-size: 13px;">
                원문 보기
              </a>
            </div>
          </article>
        `).join("");
      } else {
        root.style.display = "";
        root.className = "grid-2";

        root.innerHTML = visibleNews.map(item => `
          <article class="card">
            <span class="eyebrow">${item.publisher}</span>
            <h3>${item.title}</h3>
            <small class="live-news-time">${formatPublishedTime(item.published)}</small>
            <div class="card-footer" style="margin-top: auto; padding-top: 16px;">
              <a class="btn btn-secondary" href="${item.link}" target="_blank" rel="noopener noreferrer">
                원문 보기
              </a>
            </div>
          </article>
        `).join("");
      }

      if (filteredNews.length > INITIAL_COUNT) {
        const wrapper = document.createElement("div");
        wrapper.className = "load-more-wrap";
        wrapper.style.width = "100%";
        wrapper.style.gridColumn = "1 / -1";
        wrapper.style.textAlign = "center";
        wrapper.style.marginTop = "24px";
        wrapper.style.display = "flex";
        wrapper.style.justifyContent = "center";
        wrapper.style.gap = "12px";

        if (visibleCount < filteredNews.length) {
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

    renderPublisherFilters();
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

// [이슈 비교 결과 페이지] 렌더링 함수 - v2 compare.html 동적 연동 전담
async function renderComparePage() {
  const page = document.querySelector('[data-compare-page]');
  if (!page) return; 

  const params = new URLSearchParams(window.location.search);
  const q = (params.get('q') || '').trim();

  const titleEl = document.getElementById('compare-query-title');
  const summaryEl = document.getElementById('compare-query-summary');
  const categoryEl = document.getElementById('compare-query-category');
  const keywordContainer = document.getElementById('expanded-keywords-container');

  if (!q) {
    if (titleEl) titleEl.textContent = "비교할 검색어가 없습니다.";
    if (summaryEl) summaryEl.textContent = "메인 화면에서 궁금한 이슈를 검색해 주세요.";
    return;
  }

  if (titleEl) titleEl.textContent = `“${q}” 비교 분석 결과`;

  try {
    const response = await fetch('./data/issue.json');
    if (!response.ok) throw new Error("분석 DB를 불러올 수 없습니다.");
    
    const db = await response.json();
    const issues = db.issues || [];

    // [유사도 매칭 시뮬레이션]
    const matchedIssue = issues.find(issue => {
      const textPool = [
        issue.title,
        issue.summary,
        (issue.common_facts || []).join(' '),
        (issue.keywords || []).join(' ')
      ].join(' ').toLowerCase();
      return textPool.includes(q.toLowerCase());
    }) || issues[0]; 

    if (!matchedIssue) {
      if (summaryEl) summaryEl.textContent = "유사한 이슈 정보를 찾을 수 없습니다.";
      return;
    }

    // 전역 currentIssue 업데이트 (저장용)
    currentIssue = {
      id: matchedIssue.issue_id,
      category: matchedIssue.category || '자동 분석',
      title: matchedIssue.title || '이슈 제목 없음',
      summary: matchedIssue.summary || '',
      tags: matchedIssue.keywords || [],
      mediaNames: [...new Set((matchedIssue.articles || []).map(art => art.publisher))]
    };

    syncSaveButtons();

    if (categoryEl) categoryEl.textContent = matchedIssue.category || "종합 분석";
    if (summaryEl) summaryEl.textContent = matchedIssue.summary || "이슈 요약 정보가 존재하지 않습니다.";

    if (keywordContainer && matchedIssue.keywords) {
      const chipsHtml = matchedIssue.keywords.map(kw => `
        <span class="badge blue" style="font-size: 13px; padding: 6px 12px;">#${kw}</span>
      `).join('');
      keywordContainer.innerHTML = `
        <span style="font-size: 14px; color: var(--muted); font-weight: bold; align-self: center; margin-right: 10px;">확장된 검색 키워드:</span>
        ${chipsHtml}
      `;
    }

    const articles = matchedIssue.articles || [];
    const publishers = [...new Set(articles.map(art => art.publisher))];
    const selectedPublishers = new Set(publishers); 

    const filterContainer = document.getElementById('compare-publisher-checkboxes');
    
    function renderFilters() {
      if (!filterContainer) return;
      filterContainer.innerHTML = publishers.map(pub => `
        <label class="filter-checkbox-item">
          <input type="checkbox" value="${pub}" checked data-compare-checkbox>
          <span>${pub}</span>
        </label>
      `).join('');

      filterContainer.querySelectorAll('[data-compare-checkbox]').forEach(cb => {
        cb.addEventListener('change', () => {
          if (cb.checked) {
            selectedPublishers.add(cb.value);
          } else {
            selectedPublishers.delete(cb.value);
          }
          updateCompareDisplay(articles, selectedPublishers, matchedIssue);
        });
      });
    }

    const selectAllBtn = document.getElementById('compare-select-all');
    const deselectAllBtn = document.getElementById('compare-deselect-all');

    if (selectAllBtn) {
      selectAllBtn.onclick = () => {
        publishers.forEach(pub => selectedPublishers.add(pub));
        filterContainer.querySelectorAll('[data-compare-checkbox]').forEach(cb => cb.checked = true);
        updateCompareDisplay(articles, selectedPublishers, matchedIssue);
      };
    }

    if (deselectAllBtn) {
      deselectAllBtn.onclick = () => {
        selectedPublishers.clear();
        filterContainer.querySelectorAll('[data-compare-checkbox]').forEach(cb => cb.checked = false);
        updateCompareDisplay(articles, selectedPublishers, matchedIssue);
      };
    }

    renderFilters();
    updateCompareDisplay(articles, selectedPublishers, matchedIssue);

  } catch (error) {
    console.error("비교 분석 로드 오류:", error);
  }
}

function updateCompareDisplay(articles, selectedPublishers, matchedIssue) {
  const gridContainer = document.getElementById('compare-grid-container');
  const commonSummaryEl = document.getElementById('ai-common-summary');
  const focusDiffEl = document.getElementById('ai-focus-diff');

  const filteredArticles = articles.filter(art => selectedPublishers.has(art.publisher));

  if (!gridContainer) return;

  if (filteredArticles.length === 0) {
    gridContainer.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <h3>비교할 언론사가 선택되지 않았습니다.</h3>
        <p>위 필터에서 하나 이상의 언론사를 선택해 주세요.</p>
      </div>
    `;
    if (commonSummaryEl) commonSummaryEl.textContent = "선택된 언론사가 없습니다.";
    if (focusDiffEl) focusDiffEl.textContent = "선택된 언론사가 없습니다.";
    return;
  }

  // 대조표 카드 렌더링
  gridContainer.innerHTML = filteredArticles.map(art => `
    <article class="card" style="align-self: start; height: auto;">
      <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 12px;">
        <strong style="font-size: 20px; color: var(--primary);">${art.publisher}</strong>
      </div>
      <div class="compare-block">
        <span class="compare-label">🔑 핵심 관점</span>
        <p class="compare-text" style="font-size: 14.5px; line-height: 1.5; font-weight: 500;">
          ${art.focus || '일반 사실 보도.'}
        </p>
      </div>
      <div class="compare-block" style="margin-top: 14px;">
        <span class="compare-label">🧩 강조된 원인 및 배경</span>
        <p class="compare-text" style="font-size: 14px; color: var(--text-2);">
          ${art.expression_summary || '일반적 전달.'}
        </p>
      </div>
      <div class="compare-block" style="margin-top: 14px;">
        <span class="compare-label">🏷️ 핵심 키워드</span>
        <div class="meta" style="margin: 6px 0;">
          ${(art.keywords || []).map(kw => `<span class="badge blue" style="font-size: 11px;">#${kw}</span>`).join(' ')}
        </div>
      </div>
      <div class="compare-block" style="margin-top: 14px;">
        <span class="compare-label">👥 관계 인물 및 기관</span>
        <div class="meta" style="margin: 6px 0;">
          ${(art.people || []).map(p => `<span class="badge purple" style="font-size: 11px;">${p}</span>`).join(' ')}
          ${(art.organizations || []).map(o => `<span class="badge teal" style="font-size: 11px;">${o}</span>`).join(' ')}
        </div>
      </div>
      <div class="compare-block" style="margin-top: 14px; border-top: 1px solid var(--border); padding-top: 14px;">
        <span class="compare-label">🔗 원문 기사 참조</span>
        <a href="${art.link || '#'}" target="_blank" rel="noopener noreferrer" style="font-size: 13.5px; color: var(--primary); font-weight: bold; text-decoration: underline;">
          기사 원문 보기 ↗
        </a>
      </div>
    </article>
  `).join('');

  if (commonSummaryEl) {
    commonSummaryEl.innerHTML = `
      <strong>[공통 내용 요약]</strong><br>
      <ul style="margin: 10px 0 0 18px; padding: 0;">
        ${(matchedIssue.common_facts || []).map(fact => `<li style="margin-bottom: 6px;">${fact}</li>`).join('')}
      </ul>
    `;
  }

  if (focusDiffEl) {
    const focusDetails = filteredArticles.map(art => `<strong>${art.publisher}</strong>: ${art.focus || '사실 기반 보도.'}`).join('<br><br>');
    focusDiffEl.innerHTML = `
      선택된 언론사들의 핵심 보도 관점 대조 내용입니다.<br><br>
      ${focusDetails}
    `;
  }
}

// [이슈 비교 목록] 렌더링 함수 - 핫토픽 연동 및 v2 규격화
async function renderFeaturedIssue() {
  const root = document.querySelector("[data-featured-issues]");
  if (!root) return; 

  try {
    const response = await fetch("./data/issue.json");
    if (!response.ok) throw new Error("파일을 불러오는데 실패했습니다.");

    const db = await response.json();
    const issues = db.issues || [];

    if (!issues.length) {
      root.innerHTML = `<div class="empty-state"><h3>비교 가능한 이슈가 없습니다.</h3></div>`;
      return;
    }

    const INITIAL_COUNT = 4;
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
              <span class="eyebrow" style="margin-bottom: 4px; display: inline-block; font-size: 11px;">${issue.category || '종합'}</span>
              <h3 style="font-size: 16px; margin: 0 0 4px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600;">${issue.title}</h3>
              <p style="font-size: 13px; color: #64748b; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${issue.summary || '요약 준비 중입니다.'}</p>
            </div>
            <div style="flex-shrink: 0;">
              <a class="btn btn-primary btn-sm" href="compare.html?q=${issue.title}" style="white-space: nowrap;">
                프레임 비교 보기
              </a>
            </div>
          </article>
        `).join("");
      } else {
        root.style.display = "";
        root.className = "grid-2"; 

        root.innerHTML = visibleIssues.map(issue => `
          <article class="card">
            <span class="eyebrow">${issue.category || '종합'}</span>
            <h3>${issue.title}</h3>
            <p>${issue.summary || '요약 준비 중입니다.'}</p>
            <div class="card-footer">
              <a class="btn btn-primary" href="compare.html?q=${issue.title}">
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
            window.featuredVisibleCount += 2;
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
    root.innerHTML = `<div class="empty-state"><h3>이슈를 불러오지 못했습니다.</h3></div>`;
  }
}

// 📌 모든 기능 초기화 및 순차 렌더링 시작
document.addEventListener('DOMContentLoaded', () => {
  initMenu();
  initSearch();
  initViewToggles(); 
  initSaveButtons();
  initShare();
  
  const isComparePage = document.querySelector('[data-compare-page]');
  const isMainPage = document.querySelector('[data-live-news]');

  if (isComparePage) {
    renderComparePage();
  } else if (isMainPage) {
    renderLiveNews();
    renderFeaturedIssue();
    renderSaved();
  }
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
        location.reload();
      } else {
        setAuthMode(true);
        loginModal.style.display = "flex";
      }
    });
  }

  if (closeModalBtn) {
    closeModalBtn.addEventListener("click", () => { loginModal.style.display = "none"; });
  }

  loginModal.addEventListener("click", (e) => {
    if (e.target === loginModal) loginModal.style.display = "none";
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
          location.reload();
        } else {
          alert("아이디(이메일) 또는 비밀번호가 일치하지 않습니다.");
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
  if (event.key === 'prism-saved-issues' || event.key === 'isLoggedIn') {
    renderSaved();
    syncSaveButtons();
  }
});