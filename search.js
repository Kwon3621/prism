/**
 * Prism v2 - 검색 처리 및 뉴스/키워드 연동 스크립트 (search.js)
 */

document.addEventListener("DOMContentLoaded", () => {
    initSearchBehavior();
    renderSearchSuggestions(); // 페이지 로드 시 기본 추천 키워드 로드
});

// 1. 검색창 이벤트 처리 (즉시 이동 대신 결과 노출)
function initSearchBehavior() {
    const searchForms = document.querySelectorAll('[data-search-form]');
    
    searchForms.forEach(form => {
        const input = form.querySelector('input');
        const button = form.querySelector('button[type="submit"]');
        // 결과 뉴스나 키워드를 보여줄 컨테이너 (HTML에 <div id="search-results"></div> 구조 필요)
        const resultsContainer = document.getElementById('search-results') || createResultsContainer(form);

        if (!input || !button) return;

        // 입력값 감지 후 버튼 활성화/비활성화
        const checkInput = () => {
            button.disabled = input.value.trim().length < 1;
        };
        input.addEventListener('input', checkInput);
        checkInput();

        // 검색 Submit 이벤트
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const query = input.value.trim();
            if (!query) return;

            button.disabled = true;
            button.textContent = '검색 중...';

            // [핵심 변경] 바로 페이지 이동을 하지 않고, 관련 뉴스 및 키워드를 검색해 띄웁니다.
            await fetchAndRenderSearchResults(query, resultsContainer);

            button.disabled = false;
            button.textContent = '검색';
        });
    });
}

// 결과를 표시할 컨테이너가 없을 경우 동적 생성
function createResultsContainer(form) {
    const container = document.createElement('div');
    container.id = 'search-results';
    container.style.marginTop = '15px';
    form.parentNode.insertBefore(container, form.nextSibling);
    return container;
}

// 2. 검색어에 맞는 관련 뉴스 및 연관 키워드 매칭 및 렌더링
async function fetchAndRenderSearchResults(query, container) {
    try {
        const response = await fetch("./data/issue.json"); // 실제 서버 API가 있다면 해당 주소로 변경
        if (!response.ok) throw new Error("데이터를 가져올 수 없습니다.");
        
        const data = await response.json();
        const issues = data.issues || [];

        // 검색어(query)가 포함된 뉴스 기사(articles) 필터링
        let matchedArticles = [];
        let matchedKeywords = new Set();

        issues.forEach(issue => {
            // 이슈 키워드 체크
            if (issue.keywords && issue.keywords.some(k => k.includes(query))) {
                issue.keywords.forEach(k => matchedKeywords.add(k));
            }

            // 기사 제목, 본문, 키워드 체크
            (issue.articles || []).forEach(art => {
                const inTitle = art.title && art.title.includes(query);
                const inContent = art.content && art.content.includes(query);
                const inKeywords = art.keywords && art.keywords.some(k => k.includes(query));

                if (inTitle || inContent || inKeywords) {
                    matchedArticles.push(art);
                    if (art.keywords) art.keywords.forEach(k => matchedKeywords.add(k));
                }
            });
        });

        // 렌더링 HTML 생성
        if (matchedArticles.length === 0 && matchedKeywords.size === 0) {
            container.innerHTML = `<p class="no-result">"${query}"에 대한 검색 결과가 없습니다.</p>`;
            return;
        }

        const keywordList = [...matchedKeywords].slice(0, 5); // 상위 5개만

        container.innerHTML = `
            <div class="search-results-wrapper" style="background: #f9f9f9; padding: 15px; border-radius: 8px; border: 1px solid #ddd;">
                ${keywordList.length > 0 ? `
                    <div class="related-keywords" style="margin-bottom: 15px;">
                        <strong>연관 키워드:</strong>
                        ${keywordList.map(k => `<button type="button" class="chip" data-go-compare="${k}" style="margin: 2px; padding: 4px 8px; border-radius: 4px; border: 1px solid #ccc; background:#fff; cursor:pointer;">#${k}</button>`).join('')}
                    </div>
                ` : ''}
                
                <div class="related-articles">
                    <strong>관련 뉴스 기사 (선택 시 프레임 비교 진행):</strong>
                    <ul style="list-style: none; padding-left: 0; margin-top: 8px;">
                        ${matchedArticles.map(art => `
                            <li style="margin-bottom: 10px; padding: 10px; background:#fff; border: 1px solid #eee; border-radius: 4px; cursor: pointer; hover: background: #f0f0f0;" data-go-compare="${art.title}">
                                <span style="font-weight: bold; display: block;">${art.title}</span>
                                <small style="color: #666;">${art.press || '언론사'} | ${art.date || ''}</small>
                            </li>
                        `).join('')}
                    </ul>
                </div>
            </div>
        `;

        // 리스트 아이템 클릭 시 비교 페이지(compare.html)로 라우팅 이벤트 바인딩
        container.querySelectorAll('[data-go-compare]').forEach(element => {
            element.addEventListener('click', () => {
                const targetValue = element.dataset.goCompare;
                window.location.href = `compare.html?q=${encodeURIComponent(targetValue)}`;
            });
        });

    } catch (error) {
        console.error("검색 결과 로드 실패:", error);
        container.innerHTML = `<p style="color: red;">검색 중 오류가 발생했습니다.</p>`;
    }
}

// 3. 메인화면 초기 "추천 키워드" 렌더링 함수 (기존 코드 유지 및 예외처리 강화)
async function renderSearchSuggestions() {
    const targets = document.querySelectorAll("[data-search-help]");
    if (!targets.length) return;
  
    try {
        // 상대경로 주의: 메인 index.html 기준 data/issue.json 위치 확인 필요
        const response = await fetch("./data/issue.json");
        if (!response.ok) throw new Error("issue.json 데이터를 찾을 수 없습니다.");
  
        const data = await response.json();
        const suggestions = [];
        
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
                        <button type="button" class="search-suggestion-chip" data-search-keyword="${kw}" style="padding: 4px 8px; border-radius: 12px; border: 1px solid #007bff; background: none; color: #007bff; cursor: pointer;">
                            #${kw}
                        </button>
                    `).join("")}
                </div>
            `;
        });
  
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
            target.textContent = "추천 키워드 로딩 실패 (데이터 경로를 확인하세요)";
        });
    }
}