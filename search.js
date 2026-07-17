/**
 * Prism v2 - 검색 처리 및 Solar Embedding 연동 전용 스크립트 (search.js)
 */

document.addEventListener("DOMContentLoaded", () => {
    initSearchRedirect();
    renderSearchSuggestions();
  });
  
  // 1. 모든 검색 창의 이벤트를 감지하여 compare.html로 연결
  function initSearchRedirect() {
    const searchForms = document.querySelectorAll('[data-search-form]');
    
    searchForms.forEach(form => {
      const input = form.querySelector('input');
      const button = form.querySelector('button[type="submit"]');
      if (!input || !button) return;
  
      // 입력값 감지 후 실시간 검색 버튼 상태 조절
      const checkInput = () => {
        button.disabled = input.value.trim().length < 1;
      };
      input.addEventListener('input', checkInput);
      checkInput();
  
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        const query = input.value.trim();
        if (!query) return;
  
        button.disabled = true;
        button.textContent = '의도 확장 중...';
  
        // v2 핵심: 검색어를 포함하여 compare.html로 즉시 라우팅
        window.location.href = `compare.html?q=${encodeURIComponent(query)}`;
      });
    });
  }
  
  // 2. 메인/검색 영역의 "추천 검색어" 렌더링 함수
  async function renderSearchSuggestions() {
    const targets = document.querySelectorAll("[data-search-help]");
    if (!targets.length) return;
  
    try {
      const response = await fetch("./data/issue.json");
      if (!response.ok) throw new Error("issue.json 데이터를 찾을 수 없습니다.");
  
      const data = await response.json();
      const suggestions = [];
      
      // 데이터 중 직관적이고 핫한 키워드 4개만 추출
      const issues = data.issues || [];
      issues.forEach(issue => {
        if (issue.keywords && issue.keywords.length > 0) {
          suggestions.push(...issue.keywords);
        }
        (issue.articles || []).forEach(art => {
          if (art.keywords) suggestions.push(...art.keywords);
        });
      });
  
      const uniqueSuggestions = [...new Set(suggestions)].slice(0, 4);
  
      targets.forEach(target => {
        if (uniqueSuggestions.length === 0) {
          target.textContent = "추천 키워드를 준비 중입니다.";
          return;
        }
  
        target.innerHTML = `
          <span class="search-suggestion-label">추천 키워드</span>
          <div class="search-suggestion-list" style="display: flex; gap: 8px; margin-top: 6px;">
            ${uniqueSuggestions.map(kw => `
              <button type="button" class="search-suggestion-chip" data-search-keyword="${kw}">
                #${kw}
              </button>
            `).join("")}
          </div>
        `;
      });
  
      // 추천 키워드 클릭 시 해당 키워드로 동적 비교 페이지 이동 이벤트 주입
      document.querySelectorAll("[data-search-keyword]").forEach(button => {
        button.addEventListener("click", () => {
          const keyword = button.dataset.searchKeyword;
          if (!keyword) return;
          window.location.href = `compare.html?q=${encodeURIComponent(keyword)}`;
        });
      });
  
    } catch (error) {
      console.error("추천 키워드 로드 실패:", error);
      targets.forEach(target => {
        target.textContent = "추천 키워드 로딩 실패";
      });
    }
  }