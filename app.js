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

// [1단계 + 2단계 + 3단계 통합] compare.html 동적 정밀 비교 분석 엔진
async function renderComparePage() {
  const page = document.querySelector('[data-compare-page]');
  if (!page) return;

  const params = new URLSearchParams(window.location.search);
  const q = (params.get('q') || '').trim();

  const titleEl = document.getElementById('compare-query-title');
  const summaryEl = document.getElementById('compare-query-summary');
  const categoryEl = document.getElementById('compare-query-category');

  if (!q) {
    if (titleEl) titleEl.textContent = "비교할 검색어가 없습니다.";
    return;
  }

  try {
    const response = await fetch('./data/issue.json');
    if (!response.ok) throw new Error("분석 DB를 불러올 수 없습니다.");
    
    const db = await response.json();
    const issues = db.issues || [];

    // 검색어 기반 이슈 동적 매칭
    const matchedIssue = issues.find(issue => {
      const textPool = [
        issue.title,
        issue.summary,
        (issue.keywords || []).join(' ')
      ].join(' ').toLowerCase();
      return textPool.includes(q.toLowerCase());
    }) || issues[0];

    if (!matchedIssue) return;

    // 전역 currentIssue 할당 (상단 저장 버튼 연동 활성화)
    currentIssue = {
      id: matchedIssue.issue_id,
      category: matchedIssue.category || '자동 분석',
      title: matchedIssue.title || '이슈 제목 없음',
      summary: matchedIssue.summary || '',
      tags: matchedIssue.keywords || [],
      mediaNames: [...new Set((matchedIssue.articles || []).map(art => art.publisher))]
    };
    syncSaveButtons();

    // 1단계: 상단 핵심 쟁점 및 공통 내용 요약 바인딩
    if (categoryEl) categoryEl.textContent = matchedIssue.category || "이슈 분석";
    if (titleEl) titleEl.textContent = matchedIssue.title;
    
    if (summaryEl) {
      // 핵심 쟁점 설명과 공통 사실 요약을 깔끔하게 리스트 형태로 결합하여 매핑
      const factsHtml = (matchedIssue.common_facts || []).map(fact => `<li style="margin-top: 6px;">${fact}</li>`).join('');
      summaryEl.innerHTML = `
        <div style="font-weight: 600; margin-bottom: 10px;">[개요] ${matchedIssue.summary}</div>
        <div style="border-top: 1px dashed #cbd5e1; padding-top: 10px; margin-top: 10px;">
          <strong style="color: var(--primary);">✓ 확인된 공통 팩트 요약:</strong>
          <ul style="margin: 6px 0 0 18px; padding: 0; color: var(--text-2); font-size: 14.5px;">${factsHtml}</ul>
        </div>
      `;
    }

    const articles = matchedIssue.articles || [];

    // 2단계: 프레임 그룹화 시각화 작동
    renderFrameGroups(articles);

    // 3단계: 최대 4개 상세 대조표 인터랙션 세팅
    initPublisherSelector(articles, matchedIssue);

  } catch (error) {
    console.error("동적 비교 렌더링 실패:", error);
  }
}

// [2단계 함수] 프레임이 비슷한 그룹끼리 분류하여 시각화 상자 배치
function renderFrameGroups(articles) {
  const container = document.getElementById('frame-group-container');
  if (!container) return;

  const groups = {};
  articles.forEach(art => {
    let key = "중립/사실 전달";
    if (art.focus.includes("특혜") || art.focus.includes("의혹")) key = "의혹 제기 및 집중 보도";
    else if (art.focus.includes("수사") || art.focus.includes("혐의") || art.focus.includes("직권남용")) key = "수사 상황 및 혐의 중심 보도";
    else if (art.focus.includes("내구성") || art.focus.includes("기술")) key = "기술성 및 기능적 개선 중심";
    else if (art.focus.includes("상승") || art.focus.includes("최고치")) key = "지표 상승 추세 및 우려 중심";
    else if (art.focus.includes("경고") || art.focus.includes("주의")) key = "기강 확립 및 행동 지침 중심";

    if (!groups[key]) groups[key] = [];
    groups[key].push(art.publisher);
  });

  container.innerHTML = Object.keys(groups).map((groupTitle, index) => {
    const publishersInGroup = groups[groupTitle];
    const colors = ["#2563eb", "#7c3aed", "#ea580c", "#0f766e"];
    const themeColor = colors[index % colors.length];

    return `
      <div class="card" style="border-top: 5px solid ${themeColor}; background: #fff; padding: 24px; height: auto; box-shadow: var(--shadow); border-radius: 12px;">
        <span class="badge" style="background: ${themeColor}15; color: ${themeColor}; font-weight: 800; font-size: 13px; margin-bottom: 12px; display: inline-block; border-radius: 999px; padding: 4px 12px;">
          논조 분류: ${groupTitle}
        </span>
        <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px;">
        ${publishersInGroup.map(pub => `
          <span class="badge gray" style="font-size: 13px; padding: 6px 12px; background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; font-weight: 700; border-radius: 6px; display: inline-flex; align-items: center;">
            ${getPublisherLogoHtml(pub, 16)}${pub}
          </span>
        `).join('')}
        </div>
        <p style="font-size: 13px; color: #64748b; margin-top: 14px; line-height: 1.5; margin-bottom: 0;">
          ※ 이 매체들은 유사한 어휘 패턴과 주안점을 공유하여 같은 프레임 범주로 자동 인식되었습니다.
        </p>
      </div>
    `;
  }).join('');
}

// [3단계 함수] 최대 4개의 언론사 칩 선택 제어
function initPublisherSelector(articles, matchedIssue) {
  const chipContainer = document.getElementById('compare-publisher-chips');
  if (!chipContainer) return;

  const publishers = [...new Set(articles.map(art => art.publisher))];
  const selected = new Set(publishers.slice(0, 4));

  function renderChips() {
    chipContainer.innerHTML = publishers.map(pub => {
      const isChecked = selected.has(pub);
      const bg = isChecked ? 'var(--primary)' : '#fff';
      const color = isChecked ? '#fff' : 'var(--text)';
      const border = isChecked ? 'var(--primary)' : 'var(--border)';

      return `
        <button type="button" class="btn" data-pub-chip="${pub}" style="min-height: 38px; padding: 0 14px; background: ${bg}; color: ${color}; border: 1px solid ${border}; font-size: 13.5px; border-radius: 30px; display: inline-flex; align-items: center;">
          ${getPublisherLogoHtml(pub, 18)}${pub} ${isChecked ? '✓' : '+'}
        </button>
      `;
    }).join('');

    chipContainer.querySelectorAll('[data-pub-chip]').forEach(btn => {
      btn.onclick = () => {
        const pub = btn.dataset.pubChip;
        if (selected.has(pub)) {
          selected.delete(pub);
        } else {
          if (selected.size >= 4) {
            showToast("상세 비교는 최대 4개 언론사까지만 동시에 선택할 수 있습니다.");
            return;
          }
          selected.add(pub);
        }
        renderChips();
        renderDetailComparison(articles, selected, matchedIssue);
      };
    });
  }

  renderChips();
  renderDetailComparison(articles, selected, matchedIssue);
}

// [3단계 최종 함수] 5대 비교 지표 가로 테이블(Table) 레이아웃 매핑 엔진 (중복 요약 항목 제거)
function renderDetailComparison(articles, selectedSet, matchedIssue) {
  const tableContainer = document.getElementById('detail-compare-table');
  if (!tableContainer) return;

  const filtered = articles.filter(art => selectedSet.has(art.publisher));

  if (filtered.length === 0) {
    tableContainer.innerHTML = `
      <tbody>
        <tr>
          <td style="padding: 40px; text-align: center; color: var(--muted);">
            <strong>선택된 언론사가 없습니다.</strong><br>위의 언론사 버튼을 클릭하여 비교 테이블을 구성해 보세요.
          </td>
        </tr>
      </tbody>
    `;
    return;
  }

  // 1. 테이블 헤더(상단 매체 이름 행) 생성
  let tableHtml = `
    <thead>
      <tr style="background: var(--bg-soft); border-bottom: 2px solid var(--primary);">
        <th style="padding: 16px 20px; font-weight: 800; color: var(--text); width: 190px; word-break: keep-all; border-right: 1px solid var(--border);">비교 항목</th>
        ${filtered.map(art => `
          <th style="padding: 16px 20px; font-weight: 800; color: var(--primary); font-size: 17px; border-right: 1px solid var(--border);">
            ${getPublisherLogoHtml(art.publisher, 24)}${art.publisher}
          </th>
        `).join('')}
      </tr>
    </thead>
    <tbody>
  `;

  // 2. 항목: 핵심 관점 행 생성
  tableHtml += `
    <tr style="border-bottom: 1px solid var(--border);">
      <td style="padding: 16px 20px; font-weight: 700; background: var(--bg-soft); color: var(--keyword); word-break: keep-all; border-right: 1px solid var(--border);">🎯 핵심 관점</td>
      ${filtered.map(art => `
        <td style="padding: 16px 20px; font-size: 14.5px; font-weight: 600; line-height: 1.5; border-right: 1px solid var(--border);">
          ${art.focus || '객관적 사실 전달 중심.'}
        </td>
      `).join('')}
    </tr>
  `;

  // 3. 항목: 강조된 원인/배경 행 생성
  tableHtml += `
    <tr style="border-bottom: 1px solid var(--border);">
      <td style="padding: 16px 20px; font-weight: 700; background: var(--bg-soft); color: var(--context); word-break: keep-all; border-right: 1px solid var(--border);">🧩 강조된 원인/배경</td>
      ${filtered.map(art => `
        <td style="padding: 16px 20px; font-size: 14px; color: var(--text-2); line-height: 1.5; border-right: 1px solid var(--border);">
          ${art.expression_summary || '일반적인 사실 관계 전달.'}
        </td>
      `).join('')}
    </tr>
  `;

  // 4. 항목: 강조한 영향/대상 행 생성
  tableHtml += `
    <tr style="border-bottom: 1px solid var(--border);">
      <td style="padding: 16px 20px; font-weight: 700; background: var(--bg-soft); color: var(--person); word-break: keep-all; border-right: 1px solid var(--border);">👥 강조한 영향/대상</td>
      ${filtered.map(art => {
        const hasTags = (art.people || []).length > 0 || (art.organizations || []).length > 0;
        return `
          <td style="padding: 16px 20px; border-right: 1px solid var(--border);">
            <div class="meta" style="margin: 0; gap: 4px;">
              ${(art.people || []).map(p => `<span class="badge purple" style="font-size: 11px; padding: 2px 8px;">${p}</span>`).join('')}
              ${(art.organizations || []).map(o => `<span class="badge teal" style="font-size: 11px; padding: 2px 8px;">${o}</span>`).join('')}
              ${!hasTags ? '<span style="font-size:13px; color:#94a3b8;">특정 대상 언급 없음</span>' : ''}
            </div>
          </td>
        `;
      }).join('')}
    </tr>
  `;

  // 5. 항목: 보도 태도/근거 행 생성
  tableHtml += `
    <tr style="border-bottom: 1px solid var(--border);">
      <td style="padding: 16px 20px; font-weight: 700; background: var(--bg-soft); color: var(--additional); word-break: keep-all; border-right: 1px solid var(--border);">⚖️ 보도 태도/근거</td>
      ${filtered.map(art => `
        <td style="padding: 16px 20px; font-size: 13.5px; color: var(--text-2); line-height: 1.5; border-right: 1px solid var(--border);">
          ${art.evidence_limit ? `[한계] ${art.evidence_limit}` : '기사 텍스트 본문 인용구 및 정량 데이터 채택.'}
        </td>
      `).join('')}
    </tr>
  `;

  // 6. 항목: 뉴스 원문 참조 링크 행 생성
  tableHtml += `
    <tr>
      <td style="padding: 16px 20px; font-weight: 700; background: var(--bg-soft); color: var(--common); word-break: keep-all; border-right: 1px solid var(--border);">🔗 뉴스 원문 참조</td>
      ${filtered.map(art => `
        <td style="padding: 16px 20px; border-right: 1px solid var(--border);">
          <a href="${art.link || '#'}" target="_blank" rel="noopener noreferrer" style="font-size: 13.5px; color: var(--primary); font-weight: 800; text-decoration: underline;">
            원문 기사 읽기 ↗
          </a>
        </td>
      `).join('')}
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

        root.innerHTML = visibleIssues.map(issue => `
          <article class="list-item" style="display: flex; align-items: center; justify-content: space-between; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; gap: 16px;">
            <div style="flex: 1; min-width: 0;">
              <span class="eyebrow" style="margin-bottom: 4px; display: inline-block; font-size: 11px;">${issue.category || '종합'}</span>
              <h3 style="font-size: 16px; margin: 0 0 4px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600;">${issue.title}</h3>
              <p style="font-size: 13px; color: #64748b; margin: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${issue.summary || '요약 준비 중입니다.'}</p>
            </div>
            <div style="flex-shrink: 0;">
              <a class="btn btn-primary btn-sm" href="compare.html?q=${encodeURIComponent(issue.title)}" style="white-space: nowrap;">
                프레임 비교 보기
              </a>
            </div>
          </article>
        `).join("");
      } else {
        root.style.display = "";
        root.className = "grid-3"; 

        root.innerHTML = visibleIssues.map(issue => `
          <article class="card" style="display: flex; flex-direction: column; height: 100%;">
            <span class="eyebrow">${issue.category || '종합'}</span>
            <h3 style="margin: 12px 0 10px; font-size: 18px; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; min-height: 50px;">${issue.title}</h3>
            <p style="font-size: 14px; color: var(--text-2); line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; min-height: 67px; margin-bottom: 16px;">${issue.summary || '요약 준비 중입니다.'}</p>
            <div class="card-footer" style="margin-top: auto; padding-top: 0; display: flex; justify-content: flex-end;">
              <a class="btn btn-primary" href="compare.html?q=${encodeURIComponent(issue.title)}" style="width: 100%; text-align: center;">
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