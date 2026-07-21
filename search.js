/**
 * Prism v2 - 검색 처리 및 뉴스/키워드 연동 스크립트 (search.js)
 */

window.__PRISM_INLINE_SEARCH__ = true;

document.addEventListener("DOMContentLoaded", () => {
    initSearchBehavior();

    // 다른 페이지(홈 등)에서 ?q=검색어 로 넘어온 경우 자동으로 검색을 실행한다.
    const queryFromUrl = new URLSearchParams(window.location.search).get("q");
    if (queryFromUrl) {
        runSearchOnPage(queryFromUrl);
    }
});
// 0. 공용 유틸

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function goToIssue(candidate) {
    sessionStorage.setItem('prism-selected-issue', JSON.stringify(candidate));
    window.location.href = `compare.html?issue_id=${encodeURIComponent(candidate.issue_id)}`;
}

// 1. 검색창 이벤트 처리 (즉시 이동 대신 결과 노출)
function initSearchBehavior() {
    const searchForms = document.querySelectorAll('[data-search-form]');

    searchForms.forEach(form => {
        const input = form.querySelector('input');
        const button = form.querySelector('button[type="submit"]');
        const resultsContainer = document.getElementById('search-results') || createResultsContainer(form);

        if (!input || !button) return;

        const checkInput = () => {
            button.disabled = input.value.trim().length < 1;
        };
        input.addEventListener('input', checkInput);
        checkInput();

        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const query = input.value.trim();
            if (!query) return;

            button.disabled = true;
            button.textContent = '검색 중...';

            await fetchAndRenderSearchResults(query, resultsContainer);

            button.disabled = false;
            button.textContent = '검색';
        });

        // 추천 키워드 칩 등 다른 곳에서도 같은 폼으로 검색을 실행할 수 있도록 저장해둔다.
        form.dataset.searchBound = "true";
        form.__prismRunSearch = async (query) => {
            input.value = query;
            checkInput();
            await fetchAndRenderSearchResults(query, resultsContainer);
            resultsContainer.scrollIntoView({ behavior: "smooth", block: "start" });
        };
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

// 페이지에 있는 검색 폼을 찾아 검색을 실행한다. (추천 키워드 칩에서 사용)
function runSearchOnPage(query) {
    const form = document.querySelector('[data-search-form][data-search-bound="true"]');
    if (form && typeof form.__prismRunSearch === "function") {
        form.__prismRunSearch(query);
        return true;
    }
    return false;
}

// 2. 검색어를 사건·쟁점 단위 이슈 후보(Event Group)로 묶어서 매칭
async function fetchAndRenderSearchResults(query, container) {
    // 검색 결과가 채워지면 hero의 고정 하단 여백(82px)을 줄여
    // 콘텐츠 길이에 맞게 자동으로 조정되도록 한다.
    const heroSection = container.closest('.hero');
    if (heroSection) {
        heroSection.classList.add('has-search-results');
    }

    container.innerHTML = `
    <div class="search-loading" style="text-align:center; padding: 60px 20px; color: var(--muted);">
        <div class="search-loading-spinner"></div>
        <p style="margin:12px 0 0; font-weight:600;">분류중입니다...</p>
    </div>
    `;
    try {
        const response = await fetch(
            `/api/issue-candidates?q=${encodeURIComponent(query)}`
        );

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(
                data.error || "관련 이슈를 가져올 수 없습니다."
            );
        }

        const candidates = Array.isArray(data.candidates)
            ? data.candidates
            : [];

        const keywords = Array.isArray(data.expanded_queries)
            ? data.expanded_queries.filter(
                keyword => keyword !== query
            )
            : [];

        renderIssueCandidatesUI(container, {
            query: data.query || query,
            keywords,
            candidates,
        });

    } catch (error) {
        console.error("이슈 후보 로드 실패:", error);

        container.innerHTML = `
            <p class="no-result">
                검색 중 오류가 발생했습니다.
                ${escapeHtml(error.message)}
            </p>
        `;
    }
}

// 2-1. 이슈 후보 카드 렌더링 (사건당 최대 5개뿐이므로 페이지네이션/뷰토글 불필요)
function renderIssueCandidatesUI(container, { query, keywords, candidates }) {
    if (candidates.length === 0 && keywords.length === 0) {
        container.innerHTML = `<p class="no-result">"${escapeHtml(query)}"에 대한 검색 결과가 없습니다.</p>`;
        return;
    }

    container.innerHTML = `
        <div class="search-results-wrapper">
            ${keywords.length > 0 ? `
                <div class="related-keywords">
                    <strong>연관 키워드</strong>
                    <div class="chip-row">
                        ${keywords.slice(0, 6).map(k => `
                            <button type="button" class="chip" data-run-search="${escapeHtml(k)}">#${escapeHtml(k)}</button>
                        `).join("")}
                    </div>
                </div>
            ` : ""}

            <div class="search-results-toolbar">
                <span class="search-results-count">관련 이슈 ${candidates.length}건</span>
            </div>

            <div class="search-results-grid is-card">
                ${candidates.map(renderIssueCandidateItem).join("")}
            </div>
        </div>
    `;

    container.querySelectorAll("[data-go-issue]").forEach((el, index) => {
        el.addEventListener("click", () => {
            goToIssue(candidates[index]);
        });
        el.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                goToIssue(candidates[index]);
            }
        });
    });

    container.querySelectorAll("[data-run-search]").forEach(el => {
        el.addEventListener("click", () => {
            runSearchOnPage(el.dataset.runSearch);
        });
    });
}

function renderIssueCandidateItem(candidate) {
    const title = escapeHtml(candidate.issue_title || "");
    const summary = escapeHtml((candidate.summary || "").slice(0, 90));
    const isTruncated = (candidate.summary || "").length > 90;
    const publishers = (candidate.publishers || []).map(p => p.publisher);
    const publisherPreview = publishers.slice(0, 4).join(", ") + (publishers.length > 4 ? " 외" : "");

    return `
        <article
            class="search-result-card"
            data-go-issue
            tabindex="0"
            role="button"
            aria-label="${title} 언론사별 비교 보기"
        >
            <div class="search-result-card-body">
                <span class="badge blue">${publishers.length}개 언론사</span>
                <h3>${title}</h3>
                <p>${summary}${isTruncated ? "…" : ""}</p>
            </div>
            <div class="search-result-card-footer">
                <small>${escapeHtml(publisherPreview)}</small>
                <span class="link-arrow" aria-hidden="true">언론사별 비교 →</span>
            </div>
        </article>
    `;
}

// 3. 메인화면 초기 "추천 키워드" 렌더링
async function renderSearchSuggestions() {
    const targets = document.querySelectorAll("[data-search-help]");
    if (!targets.length) return;

    try {
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
                        <button type="button" class="search-suggestion-chip" data-search-keyword="${escapeHtml(kw)}" style="padding: 4px 8px; border-radius: 12px; border: 1px solid #007bff; background: none; color: #007bff; cursor: pointer;">
                            #${escapeHtml(kw)}
                        </button>
                    `).join("")}
                </div>
            `;
        });

        // [변경] 클릭 시 compare.html로 바로 이동하지 않고, 같은 페이지의 검색 결과 목록으로 표시한다.
        document.querySelectorAll("[data-search-keyword]").forEach(button => {
            button.addEventListener("click", () => {
                const keyword = button.dataset.searchKeyword;
                if (!keyword) return;

                const handled = runSearchOnPage(keyword);
                if (!handled) {
                    // 검색 폼이 없는 페이지(예: 홈)라면 검색 페이지로 이동해 결과를 보여준다.
                    window.location.href = `search.html?q=${encodeURIComponent(keyword)}`;
                }
            });
        });

    } catch (error) {
        console.error("추천 키워드 로드 실패:", error);
        targets.forEach(target => {
            target.textContent = "추천 키워드 로딩 실패 (데이터 경로를 확인하세요)";
        });
    }
}