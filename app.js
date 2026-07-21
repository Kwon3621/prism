// [v2 개편 안전장치] ?mode=legacy 주소로 들어오면 옛날 데이터(issue.json)를 보여줍니다.
function isLegacyMode() {
  const params = new URLSearchParams(window.location.search);
  return params.get('mode') === 'legacy';
}

let currentIssue = null;
const SAVED_ISSUES_KEY = 'prism-saved-issues';
// 언론사 로고 매핑 (assets/logos 폴더 기준)
const PUBLISHER_LOGOS = {
  "조선일보": "chosun.svg",
  "한겨레": "hani.png",
  "한국경제": "hankyung.jpg",
  "동아일보": "donga.png",
  "매일경제": "mk.png",
  "SBS": "sbs.png",
};

// 언론사 이름을 받아 로고 <img> HTML을 반환. 로고가 없거나 로드 실패 시 이니셜 아바타로 대체
function getPublisherLogoHtml(publisherName, size = 20) {
  const fileName = PUBLISHER_LOGOS[publisherName] || "";
  const initial = (publisherName || "?").charAt(0);
  const colors = ["#2563eb", "#7c3aed", "#ea580c", "#0f766e", "#be185d", "#4338ca"];
  const colorIndex = (publisherName || "").length % colors.length;
  const bg = colors[colorIndex];

  const fallbackHtml = `<span class="publisher-logo-fallback" style="display:${fileName ? 'none' : 'inline-flex'}; width:${size}px; height:${size}px; border-radius:50%; background:${bg}; color:#fff; font-size:${Math.floor(size * 0.5)}px; font-weight:800; align-items:center; justify-content:center; margin-right:6px; vertical-align:middle;">${initial}</span>`;

  if (!fileName) return fallbackHtml;

  return `<img src="./assets/logos/${fileName}" alt="${publisherName}" style="width:${size}px; height:${size}px; object-fit:contain; border-radius:4px; vertical-align:middle; margin-right:6px; background:#fff; border:1px solid var(--border);" onerror="this.style.display='none'; this.nextElementSibling.style.display='inline-flex';" />${fallbackHtml}`;
}

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
  featured: 'card',
  saved: 'card'
};

// 뷰 토글 버튼 바인딩 함수
function initViewToggles() {
  document.querySelectorAll('[data-view-toggle]').forEach(group => {
    const sectionKey = group.dataset.viewToggle; // 'featured', 'saved'
    const buttons = group.querySelectorAll('[data-view]');
    
    buttons.forEach(btn => {
      const newBtn = btn.cloneNode(true);
      btn.parentNode.replaceChild(newBtn, btn);

      newBtn.addEventListener('click', () => {
        const selectedView = newBtn.dataset.view; // 'card' or 'list'
        
        // 상태 변경 및 해당 섹션 즉시 재렌더링
        if (sectionKey === 'featured') {
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
  // search.js가 로드된 페이지(검색 결과 페이지)는 자체적으로
  // 검색 폼을 처리하므로, 여기서 중복으로 리스너를 걸지 않는다.
  if (window.__PRISM_INLINE_SEARCH__) return;

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
      // 홈 등 다른 페이지의 검색창은 이제 프레임 비교로 바로 가지 않고
      // 검색 결과 목록 페이지로 이동한다.
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
            </div>
            <h3 style="font-size: 16px; margin: 0 0 4px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${item.title}</h3>
            <p style="font-size: 13px; color: #64748b; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${item.summary}</p>
          </div>
          <div style="display: flex; align-items: center; gap: 16px; flex-shrink: 0;">
            <small style="color: #94a3b8; font-size: 12px; display: block; text-align: right;">분석 매체: ${(item.mediaNames || []).join(', ')}</small>
            <a class="btn btn-secondary btn-sm" href="compare.html?q=${encodeURIComponent(item.title)}" style="white-space: nowrap;">분석 보기</a>
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
          <div class="card-footer" style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
            <small style="color: #94a3b8;">분석 매체: ${(item.mediaNames || []).join(', ')}</small>
            <a class="btn btn-secondary btn-sm" href="compare.html?q=${encodeURIComponent(item.title)}">분석 보기</a>
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

// [0단계] compare.html 진입 시 어떤 이슈를 분석할지 결정
// search.js에서 이슈 카드를 클릭하면 sessionStorage에 후보 전체가 담겨
// issue_id와 함께 넘어온다. issue_id만 있고 sessionStorage가 비어 있으면
// (직접 링크 방문 등) q로 이슈 후보를 다시 조회해서 1개면 바로 진행하고,
// 여러 개면 이 페이지 안에서 선택 화면을 보여준다.
async function renderComparePage() {
  const page = document.querySelector('[data-compare-page]');
  if (!page) return;

  const params = new URLSearchParams(window.location.search);
  const q = (params.get('q') || '').trim();
  const issueIdParam = (params.get('issue_id') || '').trim();

  const titleEl = document.getElementById('compare-query-title');
  const summaryEl = document.getElementById('compare-query-summary');
  const candidateSection = document.getElementById('issue-candidate-section');
  const candidateList = document.getElementById('issue-candidate-list');
  const analysisSections = document.getElementById('issue-analysis-sections');

  if (analysisSections) analysisSections.style.display = 'none';
  if (candidateSection) candidateSection.style.display = 'none';

  let handoffCandidate = null;

  if (issueIdParam) {
    try {
      const stored = JSON.parse(sessionStorage.getItem('prism-selected-issue') || 'null');
      if (stored && stored.issue_id === issueIdParam) {
        handoffCandidate = stored;
      }
    } catch (error) {
      handoffCandidate = null;
    }
  }

  if (handoffCandidate) {
    if (analysisSections) analysisSections.style.display = '';
    await runIssueAnalysis(handoffCandidate);
    return;
  }

  if (!q) {
    if (titleEl) titleEl.textContent = "비교할 검색어가 없습니다.";
    return;
  }

  if (titleEl) titleEl.textContent = "관련 이슈를 찾는 중입니다...";
  if (summaryEl) summaryEl.textContent = "";

  try {
    const response = await fetch(`/api/issue-candidates?q=${encodeURIComponent(q)}`);
    const data = await response.json();

    if (!response.ok || !data.success) {
      throw new Error(data.error || "관련 이슈를 찾지 못했습니다.");
    }

    const candidates = data.candidates || [];

    // 공유 링크로 들어온 경우: sessionStorage 핸드오프가 없어도
    // 재검색 결과에서 원래 이슈(issue_id)를 그대로 찾아 바로 보여준다.
    if (issueIdParam) {
      const exactMatch = candidates.find(candidate => candidate.issue_id === issueIdParam);
      if (exactMatch) {
        if (analysisSections) analysisSections.style.display = '';
        await runIssueAnalysis(exactMatch);
        return;
      }
    }

    if (candidates.length === 1) {
      if (analysisSections) analysisSections.style.display = '';
      await runIssueAnalysis(candidates[0]);
      return;
    }

    // 사건이 여러 개면 사용자가 고를 때까지 분석을 미루고 선택 화면을 보여준다
    if (titleEl) titleEl.textContent = `"${q}" 관련 이슈를 선택해 주세요`;
    if (summaryEl) {
      summaryEl.textContent = `검색어와 관련된 서로 다른 사건 ${candidates.length}건을 찾았습니다. 아래에서 하나를 선택하면 그 이슈만 분석합니다.`;
    }
    renderIssueCandidatePicker(candidateSection, candidateList, candidates);

  } catch (error) {
    console.error("이슈 후보 조회 실패:", error);
    if (titleEl) titleEl.textContent = "이슈 분석에 실패했습니다.";
    if (summaryEl) summaryEl.textContent = error.message || "이 검색어로는 비교할 이슈를 찾지 못했습니다.";
  }
}

// [0단계 함수] 이슈 후보가 여러 개일 때 compare.html 안에서 보여줄 선택 카드
function renderIssueCandidatePicker(section, listEl, candidates) {
  if (!section || !listEl) return;

  section.style.display = '';

  listEl.innerHTML = candidates.map((candidate, index) => {
    const publisherNames = (candidate.publishers || []).map(p => p.publisher);

    return `
      <div class="card" data-pick-issue="${index}" role="button" tabindex="0"
        style="cursor: pointer; background: #fff; padding: 24px; border-radius: 12px; box-shadow: var(--shadow); border: 1px solid var(--border);">
        <span class="badge blue" style="margin-bottom: 10px; display: inline-block;">${publisherNames.length}개 언론사</span>
        <h3 style="font-size: 17px; margin: 6px 0; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; word-break: keep-all; overflow-wrap: break-word;">${candidate.issue_title || ''}</h3>
        <p style="font-size: 13.5px; color: var(--text-2); line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; word-break: keep-all; overflow-wrap: break-word; min-height: calc(1.5em * 3);">${candidate.summary || ''}</p>
        <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px;">
          ${publisherNames.map(name => `<span class="badge gray" style="font-size: 12px; padding: 4px 10px;">${name}</span>`).join('')}
        </div>
      </div>
    `;
  }).join('');

  listEl.querySelectorAll('[data-pick-issue]').forEach(el => {
    const pick = () => {
      const candidate = candidates[Number(el.dataset.pickIssue)];

      sessionStorage.setItem('prism-selected-issue', JSON.stringify(candidate));
      window.history.replaceState(null, '', `compare.html?issue_id=${encodeURIComponent(candidate.issue_id)}`);

      section.style.display = 'none';

      const analysisSections = document.getElementById('issue-analysis-sections');
      if (analysisSections) analysisSections.style.display = '';

      runIssueAnalysis(candidate);
    };

    el.addEventListener('click', pick);
    el.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        pick();
      }
    });
  });
}

// [1단계 + 2단계 + 3단계 통합] 선택된 이슈 후보 하나를 실제로 분석·렌더링
// 언론사별 분석(analysis.py)과 그룹화 결과를 POST /api/issue에서 받아오고,
// 선택 비교는 POST /api/compare에서 받아온다.
async function runIssueAnalysis(candidate) {
  const titleEl = document.getElementById('compare-query-title');
  const summaryEl = document.getElementById('compare-query-summary');
  const categoryEl = document.getElementById('compare-query-category');

  if (titleEl) titleEl.textContent = candidate.issue_title || "이슈를 분석하는 중입니다...";
  if (summaryEl) summaryEl.textContent = "언론사별 분석과 그룹화를 진행하고 있습니다. 잠시만 기다려 주세요.";

  try {
    const response = await fetch('/api/issue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(candidate)
    });

    const data = await response.json();

    if (!response.ok || !data.success) {
      throw new Error(data.error || "이슈 분석에 실패했습니다.");
    }

    const publisherAnalyses = data.publisher_analyses || [];
    const groups = (data.publisher_grouping && data.publisher_grouping.groups) || [];

    // 전역 currentIssue 할당 (상단 저장 버튼 연동 활성화)
    currentIssue = {
      id: data.issue_id,
      category: '자동 분석',
      title: data.issue_title || candidate.issue_title,
      summary: data.query || candidate.query || '',
      tags: [],
      mediaNames: [...new Set(publisherAnalyses.map(item => item.publisher))]
    };
    syncSaveButtons();

    // 1단계: 상단 공통 내용 요약 + 보도 경향 그룹 개요 바인딩
    // 공통 내용은 사용자가 아래에서 고르는 언론사 조합과 무관하게,
    // 이 이슈 묶음 전체 언론사를 기준으로 한 번만 계산해 고정 표시한다
    // (renderOverallCommonSummary 참고. 선택 조합별 비교는 상세 대조표에서 별도로 처리).
    if (categoryEl) categoryEl.textContent = "이슈 분석";
    if (titleEl) titleEl.textContent = data.issue_title || candidate.issue_title;

    if (summaryEl) {
      const groupsHtml = groups.map(group => `
        <li style="margin-top: 6px;"><strong>${group.label}</strong> — ${group.summary || ''}</li>
      `).join('');

      summaryEl.innerHTML = `
        <div id="compare-overall-common-summary" style="font-size: 14.5px; color: var(--text-2); line-height: 1.6;">
          공통 내용을 분석하고 있습니다...
        </div>
        <div style="border-top: 1px dashed #cbd5e1; padding-top: 10px; margin-top: 16px;">
          <strong style="color: var(--primary);"><span style="display: inline-block; width: 20px;">✓</span>보도 경향 그룹 개요:</strong>
          <ul style="margin: 6px 0 0 18px; padding: 0; color: var(--text-2); font-size: 14.5px;">${groupsHtml}</ul>
        </div>
      `;
    }

    // 2단계: 프레임 그룹화 시각화 작동 (서버가 계산한 그룹을 그대로 렌더링)
    renderFrameGroups(groups, publisherAnalyses);

    // 이슈 묶음 전체 언론사 기준 공통 내용 (사용자의 상세 비교 선택과 무관하게 고정)
    renderOverallCommonSummary(publisherAnalyses);

    // 3단계: 최대 4개 상세 대조표 인터랙션 세팅
    initPublisherSelector(publisherAnalyses);

  } catch (error) {
    console.error("이슈 분석 렌더링 실패:", error);
    if (titleEl) titleEl.textContent = "이슈 분석에 실패했습니다.";
    if (summaryEl) summaryEl.textContent = error.message || "이 이슈를 분석하지 못했습니다.";
  }
}

// [1단계 보조 함수] "AI 공통 내용 요약" 카드에 이슈 묶음 전체 언론사 기준 공통 내용을 채운다.
// /api/compare는 한 번에 최대 4개 언론사만 받으므로, 4개를 넘으면 대표로 앞 4개만 사용한다.
async function renderOverallCommonSummary(publisherAnalyses) {
  const container = document.getElementById('compare-overall-common-summary');
  if (!container) return;

  if (publisherAnalyses.length < 2) {
    container.textContent = "공통 내용을 분석할 언론사가 부족합니다.";
    return;
  }

  try {
    const response = await fetch('/api/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ publisher_analyses: publisherAnalyses.slice(0, 4) })
    });

    const data = await response.json();

    if (!response.ok || !data.success) {
      throw new Error(data.error || "공통 내용 분석에 실패했습니다.");
    }

    container.textContent = data.common_summary || "공통 내용을 찾지 못했습니다.";

  } catch (error) {
    console.error("전체 공통 내용 렌더링 실패:", error);
    container.textContent = "공통 내용을 불러오지 못했습니다.";
  }
}

// [2단계 함수] Publisher Grouping(analysis.py:group_publishers) 결과를 그대로 렌더링
// 프레임 그룹명 비교를 위한 문자열 정리
function normalizeFrameGroupLabel(label) {
  return String(label || "").trim();
}


// "미분류" 그룹인지 확인
function isUnclassifiedFrameGroup(label) {
  return normalizeFrameGroupLabel(label) === "미분류";
}


// HEX 색상을 투명도가 포함된 rgba 문자열로 변환
function hexToRgba(hex, alpha) {
  const normalizedHex = String(hex || "").replace("#", "");

  if (!/^[0-9a-fA-F]{6}$/.test(normalizedHex)) {
    return `rgba(37, 99, 235, ${alpha})`;
  }

  const red = parseInt(normalizedHex.slice(0, 2), 16);
  const green = parseInt(normalizedHex.slice(2, 4), 16);
  const blue = parseInt(normalizedHex.slice(4, 6), 16);

  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}


// HSL 색상을 HEX 색상으로 변환
function hslToHex(hue, saturation, lightness) {
  const s = saturation / 100;
  const l = lightness / 100;

  const chroma = (1 - Math.abs(2 * l - 1)) * s;
  const section = hue / 60;
  const secondComponent = chroma * (1 - Math.abs((section % 2) - 1));

  let red = 0;
  let green = 0;
  let blue = 0;

  if (section >= 0 && section < 1) {
    red = chroma;
    green = secondComponent;
  } else if (section >= 1 && section < 2) {
    red = secondComponent;
    green = chroma;
  } else if (section >= 2 && section < 3) {
    green = chroma;
    blue = secondComponent;
  } else if (section >= 3 && section < 4) {
    green = secondComponent;
    blue = chroma;
  } else if (section >= 4 && section < 5) {
    red = secondComponent;
    blue = chroma;
  } else if (section >= 5 && section < 6) {
    red = chroma;
    blue = secondComponent;
  }

  const match = l - chroma / 2;

  const toHex = value => {
    return Math.round((value + match) * 255)
      .toString(16)
      .padStart(2, "0");
  };

  return `#${toHex(red)}${toHex(green)}${toHex(blue)}`;
}


// 분류명별 색상표 생성
function createFrameGroupColorMap(groups) {
  // 회색 계열을 제외한 정상 분류 전용 팔레트
  const baseColors = [
    "#2563eb",
    "#7c3aed",
    "#ea580c",
    "#0f766e",
    "#be123c",
    "#0891b2",
    "#65a30d",
    "#c026d3",
    "#d97706",
    "#4f46e5",
    "#059669",
    "#e11d48",
  ];

  // 미분류는 이 회색으로만 표시
  const unclassifiedColor = "#94a3b8";

  const normalLabels = [
    ...new Set(
      groups
        .map(group => normalizeFrameGroupLabel(group.label))
        .filter(label => label && !isUnclassifiedFrameGroup(label))
    ),
  ].sort((left, right) => left.localeCompare(right, "ko"));

  const colorMap = new Map();
  const usedColors = new Set();

  normalLabels.forEach((label, index) => {
    let color;

    if (index < baseColors.length) {
      color = baseColors[index];
    } else {
      /*
       * 기본 팔레트보다 분류가 많으면 황금각을 이용해 추가 색상을 생성한다.
       * 채도와 명도를 일정 범위로 유지하여 회색처럼 보이지 않도록 한다.
       */
      let colorIndex = index - baseColors.length;
      let attempt = 0;

      do {
        const hue = (colorIndex * 137.508 + attempt * 29) % 360;
        color = hslToHex(hue, 68, 44);
        attempt += 1;
      } while (
        usedColors.has(color.toLowerCase()) ||
        color.toLowerCase() === unclassifiedColor.toLowerCase()
      );
    }

    colorMap.set(label, color);
    usedColors.add(color.toLowerCase());
  });

  colorMap.set("미분류", unclassifiedColor);

  return colorMap;
}


// [2단계 함수] Publisher Grouping 결과를 분류별 고유 색상으로 렌더링
function renderFrameGroups(groups, publisherAnalyses) {
  const container = document.getElementById("frame-group-container");
  if (!container) return;

  if (!Array.isArray(groups) || groups.length === 0) {
    container.innerHTML = `
      <p style="color: var(--muted);">
        보도 경향 그룹화 결과가 없습니다.
      </p>
    `;
    return;
  }

  const publisherNameById = new Map(
    publisherAnalyses.map(item => [
      item.publisher_id,
      item.publisher,
    ])
  );

  /*
   * 분류명 → 색상 매핑을 렌더링 전에 한 번만 만든다.
   * 카드와 이후 범례가 생기더라도 이 매핑을 함께 사용해야 한다.
   */
  const frameColorMap = createFrameGroupColorMap(groups);

  container.innerHTML = groups.map(group => {
    const rawLabel = normalizeFrameGroupLabel(group.label);
    const displayLabel = rawLabel || "미분류";

    const themeColor = isUnclassifiedFrameGroup(displayLabel)
      ? frameColorMap.get("미분류")
      : frameColorMap.get(displayLabel);

    const publisherNames = (group.publisher_ids || []).map(
      publisherId => publisherNameById.get(publisherId) || publisherId
    );

    return `
      <div
        class="card"
        data-frame-group="${displayLabel}"
        style="
          border-top: 5px solid ${themeColor};
          background: #fff;
          padding: 24px;
          height: auto;
          box-shadow: var(--shadow);
          border-radius: 12px;
        "
      >
        <span
          class="badge"
          style="
            background: ${hexToRgba(themeColor, 0.1)};
            color: ${themeColor};
            font-weight: 800;
            font-size: 13px;
            margin-bottom: 12px;
            display: inline-block;
            border-radius: 999px;
            padding: 4px 12px;
          "
        >
          ${displayLabel}
        </span>

        <p
          style="
            font-size: 13.5px;
            color: var(--text-2);
            margin: 10px 0 0;
            line-height: 1.5;
          "
        >
          ${group.summary || ""}
        </p>

        <div
          style="
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
          "
        >
          ${publisherNames.map(name => `
            <span
              class="badge"
              style="
                font-size: 13px;
                padding: 6px 12px;
                background: ${hexToRgba(themeColor, 0.07)};
                color: #334155;
                border: 1px solid ${hexToRgba(themeColor, 0.28)};
                font-weight: 700;
                border-radius: 6px;
                display: inline-flex;
                align-items: center;
              "
            >
              ${getPublisherLogoHtml(name, 16)}${name}
            </span>
          `).join("")}
        </div>
      </div>
    `;
  }).join("");
}

// [3단계 함수] 최대 4개의 언론사 칩 선택 제어
function initPublisherSelector(publisherAnalyses) {
  const chipContainer = document.getElementById('compare-publisher-chips');
  if (!chipContainer) return;

  const publisherById = new Map(
    publisherAnalyses.map(item => [item.publisher_id, item])
  );
  const publisherIds = publisherAnalyses.map(item => item.publisher_id);
  const selected = new Set(publisherIds.slice(0, 4));

  function renderChips() {
    chipContainer.innerHTML = publisherIds.map(id => {
      const item = publisherById.get(id);
      const isChecked = selected.has(id);
      const bg = isChecked ? 'var(--primary)' : '#fff';
      const color = isChecked ? '#fff' : 'var(--text)';
      const border = isChecked ? 'var(--primary)' : 'var(--border)';

      return `
        <button type="button" class="btn" data-pub-chip="${id}" style="min-height: 38px; padding: 0 14px; background: ${bg}; color: ${color}; border: 1px solid ${border}; font-size: 13.5px; border-radius: 30px; display: inline-flex; align-items: center;">
          ${getPublisherLogoHtml(item.publisher, 18)}${item.publisher} ${isChecked ? '✓' : '+'}
        </button>
      `;
    }).join('');

    chipContainer.querySelectorAll('[data-pub-chip]').forEach(btn => {
      btn.onclick = () => {
        const id = btn.dataset.pubChip;
        if (selected.has(id)) {
          selected.delete(id);
        } else {
          if (selected.size >= 4) {
            showToast("상세 비교는 최대 4개 언론사까지만 동시에 선택할 수 있습니다.");
            return;
          }
          selected.add(id);
        }
        renderChips();
        renderDetailComparison(publisherAnalyses, selected);
      };
    });
  }

  renderChips();
  renderDetailComparison(publisherAnalyses, selected);
}

// 언론사 조합별 /api/compare 결과를 브라우저 메모리에 기억해 둔다.
// 백엔드(compare.py)는 이미 (issue_id + 언론사 조합) 단위로 캐싱하지만,
// 프론트는 매번 "비교 분석 중입니다..." placeholder를 띄운 뒤 새로
// fetch하는 구조라, 서버가 즉시 응답해도 화면에는 짧게라도 로딩이
// 깜빡였다. 이미 본 조합은 요청 자체 없이 바로 렌더링한다.
const detailComparisonCache = new Map();

function makeDetailComparisonCacheKey(issueId, selectedAnalyses) {
  const sortedPublisherIds = selectedAnalyses
    .map(item => item.publisher_id)
    .sort()
    .join(",");

  return `${issueId}|${sortedPublisherIds}`;
}

// [3단계 함수] 선택된 언론사 조합으로 /api/compare 호출 후 4대 항목 + 발행시각 테이블 렌더링
async function renderDetailComparison(publisherAnalyses, selectedSet) {
  const tableContainer = document.getElementById('detail-compare-table');
  if (!tableContainer) return;

  const selectedAnalyses = publisherAnalyses.filter(
    item => selectedSet.has(item.publisher_id)
  );

  if (selectedAnalyses.length < 2) {
    tableContainer.innerHTML = `
      <tbody>
        <tr>
          <td style="padding: 40px; text-align: center; color: var(--muted);">
            <strong>언론사를 2개 이상 선택해 주세요.</strong><br>위의 언론사 버튼을 클릭하여 비교 테이블을 구성해 보세요.
          </td>
        </tr>
      </tbody>
    `;
    return;
  }

  const cacheKey = makeDetailComparisonCacheKey(
    selectedAnalyses[0].issue_id,
    selectedAnalyses
  );
  const cached = detailComparisonCache.get(cacheKey);

  if (cached) {
    renderDetailComparisonTable(tableContainer, cached);
    return;
  }

  tableContainer.innerHTML = `
    <tbody>
      <tr>
        <td style="padding: 40px; text-align: center; color: var(--muted);">비교 분석 중입니다...</td>
      </tr>
    </tbody>
  `;

  try {
    const response = await fetch('/api/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ publisher_analyses: selectedAnalyses })
    });

    const data = await response.json();

    if (!response.ok || !data.success) {
      throw new Error(data.error || "비교 분석에 실패했습니다.");
    }

    detailComparisonCache.set(cacheKey, data);
    renderDetailComparisonTable(tableContainer, data);

  } catch (error) {
    console.error("상세 비교 렌더링 실패:", error);
    tableContainer.innerHTML = `
      <tbody>
        <tr>
          <td style="padding: 40px; text-align: center; color: var(--muted);">
            ${error.message || "비교 분석에 실패했습니다."}
          </td>
        </tr>
      </tbody>
    `;
  }
}

// [3단계 최종 함수] compare.py 비교 결과를 4대 비교 지표 + 발행시각 가로 테이블로 매핑
// "공통 내용"은 상단 "AI 공통 내용 요약" 카드(renderOverallCommonSummary)가 이슈 묶음
// 전체 기준으로 이미 보여주므로, 여기서는 선택 조합별로 달라지는 4개 지표만 표로 그린다.
function renderDetailComparisonTable(tableContainer, data) {
  const publishers = data.selected_publishers || [];
  const comparisons = data.comparisons || [];
  const sourceLinks = data.source_links || [];
  const sourceLinkByPublisher = new Map(
    sourceLinks.map(link => [link.publisher_id, link])
  );

  // 1. 테이블 헤더(상단 매체 이름 행) 생성
  let tableHtml = `
    <thead>
      <tr style="background: var(--bg-soft); border-bottom: 2px solid var(--primary);">
        <th style="padding: 16px 20px; font-weight: 800; color: var(--text); width: 190px; word-break: keep-all; border-right: 1px solid var(--border);">비교 항목</th>
        ${publishers.map(pub => `
          <th style="padding: 16px 20px; font-weight: 800; color: var(--primary); font-size: 17px; border-right: 1px solid var(--border);">
            ${getPublisherLogoHtml(pub.publisher, 24)}${pub.publisher}
          </th>
        `).join('')}
      </tr>
    </thead>
    <tbody>
  `;

  // 2. 4대 비교 항목(핵심 관점/원인·배경/영향·대상/보도 태도) 행 생성
  // - "공통 내용"은 상단 "AI 공통 내용 요약" 카드에서 이슈 전체 기준으로 이미 보여주므로 제외
  // - "대조" 보조 행은 핵심 관점 항목에서만 표시
  comparisons
    .filter(comparison => comparison.dimension !== '공통 내용')
    .forEach(comparison => {
      const detailByPublisher = new Map(
        (comparison.publisher_details || []).map(detail => [detail.publisher_id, detail])
      );

      tableHtml += `
        <tr style="border-bottom: 1px solid var(--border);">
          <td style="padding: 16px 20px; font-weight: 700; background: var(--bg-soft); color: var(--keyword); word-break: keep-all; border-right: 1px solid var(--border);">
            ${comparison.dimension}
          </td>
          ${publishers.map(pub => {
            const detail = detailByPublisher.get(pub.publisher_id);
            // 근거(evidence)는 "보도 태도·근거" 항목에만 붙인다 — 백엔드가
            // 이미 다른 항목엔 evidence를 비워서 주지만, 예전 캐시 결과
            // 등에 대비해 프론트에서도 한 번 더 항목을 확인한다.
            const evidence = comparison.dimension === '보도 태도·근거'
              ? ((detail && detail.evidence) || [])
              : [];
            const evidenceHtml = evidence.length ? `
              <div style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border); font-size: 12.5px; color: var(--muted); line-height: 1.5;">
                근거: ${evidence.join(' · ')}
              </div>
            ` : '';
            return `
              <td style="padding: 16px 20px; font-size: 14px; color: var(--text-2); line-height: 1.5; border-right: 1px solid var(--border); word-break: keep-all; overflow-wrap: break-word;">
                ${(detail && detail.summary) || '분석 내용 없음'}
                ${evidenceHtml}
              </td>
            `;
          }).join('')}
        </tr>
      `;

      if (comparison.dimension === '핵심 관점' && comparison.contrast_statement) {
        tableHtml += `
          <tr style="border-bottom: 1px solid var(--border);">
            <td style="padding: 8px 20px; font-size: 12.5px; color: var(--muted); background: var(--bg-soft); border-right: 1px solid var(--border);">대조</td>
            <td colspan="${publishers.length}" style="padding: 8px 20px; font-size: 13px; color: var(--muted); font-style: italic; word-break: keep-all; overflow-wrap: break-word;">
              ${comparison.contrast_statement}
            </td>
          </tr>
        `;
      }
  });

  // 3. 발행 시각 행 (핸드오프 5-4: formatPublishedTime을 실제로 호출하는 지점)
  tableHtml += `
    <tr style="border-bottom: 1px solid var(--border);">
      <td style="padding: 16px 20px; font-weight: 700; background: var(--bg-soft); color: var(--keyword); word-break: keep-all; border-right: 1px solid var(--border);">발행 시각</td>
      ${publishers.map(pub => {
        const link = sourceLinkByPublisher.get(pub.publisher_id);
        return `
          <td style="padding: 16px 20px; font-size: 13.5px; color: var(--text-2); border-right: 1px solid var(--border);">
            ${formatPublishedTime(link && link.published_at)}
          </td>
        `;
      }).join('')}
    </tr>
  `;

  // 4. 뉴스 원문 참조 링크 행
  tableHtml += `
    <tr>
      <td style="padding: 16px 20px; font-weight: 700; background: var(--bg-soft); color: var(--additional); word-break: keep-all; border-right: 1px solid var(--border);">🔗 뉴스 원문 참조</td>
      ${publishers.map(pub => {
        const link = sourceLinkByPublisher.get(pub.publisher_id);
        return `
          <td style="padding: 16px 20px; border-right: 1px solid var(--border);">
            <a href="${(link && link.link) || '#'}" target="_blank" rel="noopener noreferrer" style="font-size: 13.5px; color: var(--primary); font-weight: 800; text-decoration: underline;">
              원문 기사 읽기 ↗
            </a>
          </td>
        `;
      }).join('')}
    </tr>
  `;

  tableHtml += `</tbody>`;
  tableContainer.innerHTML = tableHtml;
}

// [이슈 비교 목록] 렌더링 함수 - 핫토픽 연동 및 v2 규격화 (최대 3개 노출로 변경)
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

        root.innerHTML = visibleIssues.map((issue, idx) => `
          <article class="list-item" style="display: flex; align-items: center; justify-content: space-between; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; gap: 16px;">
            <div style="flex: 1; min-width: 0;">
              <span class="eyebrow" style="margin-bottom: 4px; display: inline-block; font-size: 11px;">${issue.category || '종합'}</span>
              <h3 style="font-size: 16px; margin: 0 0 4px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600;">${issue.issue_title}</h3>
              <p style="font-size: 13px; color: #64748b; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${issue.summary || '요약 준비 중입니다.'}</p>
            </div>
            <div style="flex-shrink: 0;">
              <a class="btn btn-primary btn-sm" data-featured-issue-index="${idx}" href="compare.html?issue_id=${encodeURIComponent(issue.issue_id)}&q=${encodeURIComponent(issue.issue_title)}" style="white-space: nowrap;">
                프레임 비교 보기
              </a>
            </div>
          </article>
        `).join("");
      } else {
        root.style.display = "";
        root.className = "grid-3";

        root.innerHTML = visibleIssues.map((issue, idx) => `
          <article class="card" style="display: flex; flex-direction: column; height: 100%;">
            <span class="eyebrow">${issue.category || '종합'}</span>
            <h3 style="margin: 12px 0 10px; font-size: 18px; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; word-break: keep-all; overflow-wrap: break-word; min-height: 50px;">${issue.issue_title}</h3>
            <p style="font-size: 14px; color: var(--text-2); line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; word-break: keep-all; overflow-wrap: break-word; min-height: 67px; margin-bottom: 16px;">${issue.summary || '요약 준비 중입니다.'}</p>
            <div class="card-footer" style="margin-top: auto; padding-top: 0; display: flex; justify-content: flex-end;">
              <a class="btn btn-primary" data-featured-issue-index="${idx}" href="compare.html?issue_id=${encodeURIComponent(issue.issue_id)}&q=${encodeURIComponent(issue.issue_title)}" style="width: 100%; text-align: center;">
                프레임 비교 보기
              </a>
            </div>
          </article>
        `).join("");
      }

      // 홈 카드는 이미 만들어둔 event group(candidate)을 그대로 들고 가서,
      // compare.html에서 재검색 없이 곧바로 그 이슈 하나만 분석하게 한다.
      // (재검색하면 Solar Event Grouping이 다시 돌면서 여러 사건으로
      // 갈라져 "관련 이슈 여러 건" 선택 화면이 튀어나올 수 있다.)
      root.querySelectorAll('[data-featured-issue-index]').forEach(link => {
        link.addEventListener('click', () => {
          const issue = visibleIssues[Number(link.dataset.featuredIssueIndex)];
          if (issue) {
            sessionStorage.setItem('prism-selected-issue', JSON.stringify(issue));
          }
        });
      });

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
  const isMainPage = document.querySelector('[data-featured-issues]');

  if (isComparePage) {
    renderComparePage();
  } else if (isMainPage) {
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