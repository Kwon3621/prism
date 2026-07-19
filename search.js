/**
 * Prism v2 - 검색 처리 및 뉴스/키워드 연동 스크립트 (search.js)
 */

window.__PRISM_INLINE_SEARCH__ = true;

document.addEventListener("DOMContentLoaded", () => {
    initSearchBehavior();
    restoreSearchStepFromLocation();
});

// 뒤로가기/앞으로가기(같은 문서 안에서 history가 바뀐 경우)도 같은 방식으로 복원한다.
window.addEventListener("popstate", () => {
    restoreSearchStepFromLocation();
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

// 0-1. 검색 → 키워드 선택 → 카드 목록 단계별 뒤로가기 지원
//
// Solar 호출은 느리고(요청당 여러 초) 결과도 호출마다 조금씩 달라지므로,
// 뒤로가기를 눌렀을 때 "다시 검색"하면 안 되고 방금 봤던 화면을 그대로
// 복원해야 한다. 그래서 단계가 바뀔 때마다(①검색 결과/키워드 목록 노출,
// ②키워드 하나 선택) history.pushState로 진짜 히스토리 항목을 만들고,
// 그 시점에 렌더링한 데이터를 sessionStorage에 같이 저장해 둔다.
// popstate가 발생하면 재요청 없이 저장된 데이터로 그대로 다시 그린다.
// 세션(탭) 동안만 유지하면 충분하다고 판단해 별도 만료 시간은 두지 않았다
// — sessionStorage 자체가 탭을 닫으면 사라진다.
function createSearchStepToken() {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function saveSearchStep(token, stepData) {
    try {
        sessionStorage.setItem(`prism-search-step-${token}`, JSON.stringify(stepData));
    } catch (error) {
        // sessionStorage 용량 초과 등은 무시한다 — 뒤로가기 복원만 못 할 뿐,
        // 검색 자체는 정상 동작해야 하므로 여기서 실패를 전파하지 않는다.
        console.warn("검색 단계 저장 실패:", error);
    }
}

function loadSearchStep(token) {
    try {
        const raw = sessionStorage.getItem(`prism-search-step-${token}`);
        return raw ? JSON.parse(raw) : null;
    } catch (error) {
        return null;
    }
}

// 새 단계를 히스토리에 쌓는다. URL에 검색어와 단계 토큰을 실어 두면,
// (bfcache 없이) 완전히 새로 로드되는 경우에도 같은 토큰으로 sessionStorage를
// 조회해 복원할 수 있다.
function pushSearchStep(query, stepData) {
    const token = createSearchStepToken();
    saveSearchStep(token, stepData);

    const url = new URL(window.location.href);
    url.searchParams.set("q", query);
    url.searchParams.set("step", token);
    history.pushState({ prismSearchStep: token }, "", url);
}

// 현재 URL(?q=, &step=)을 보고 검색 결과 화면을 복원한다.
// - step 토큰이 있고 캐시가 살아있으면: 재요청 없이 그대로 복원
// - step은 없지만 q만 있으면(외부 링크 등): 새로 검색
// - 둘 다 없으면: 검색 전 초기 상태
function restoreSearchStepFromLocation() {
    const form = document.querySelector('[data-search-form][data-search-bound="true"]');
    const container = form && form.__prismResultsContainer;

    if (!container) return;

    const params = new URLSearchParams(window.location.search);
    const token = params.get("step");
    const query = params.get("q");

    if (token) {
        const cached = loadSearchStep(token);
        if (cached) {
            renderSearchStep(container, cached);
            return;
        }
    }

    if (query) {
        // 캐시가 없다(세션 만료, storage 초기화 등) — 새로 검색하되 히스토리에
        // 새 항목을 또 쌓지는 않는다(이미 이 URL 위치로 이동해 온 상태이므로).
        fetchAndRenderSearchResults(query, container, { push: false });
        return;
    }

    container.innerHTML = "";
    const heroSection = container.closest('.hero');
    if (heroSection) {
        heroSection.classList.remove('has-search-results');
    }
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
        // 뒤로가기 복원(restoreSearchStepFromLocation)도 이 컨테이너를 그대로 써야
        // 검색 폼과 항상 같은 자리에 결과가 그려진다.
        form.dataset.searchBound = "true";
        form.__prismResultsContainer = resultsContainer;
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
// push=false는 popstate 복원 중 캐시가 없어서 재검색할 때 쓴다 — 이미
// 이 URL 위치로 이동해 온 상태라 히스토리에 또 새 항목을 쌓으면 안 된다.
async function fetchAndRenderSearchResults(query, container, { push = true } = {}) {
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

        const stepData = {
            query: data.query || query,
            mode: data.mode === "keywords" && candidates.length > 1 ? "keywords" : "candidates",
            candidates,
        };

        if (push) {
            pushSearchStep(query, stepData);
        }

        renderSearchStep(container, stepData);

    } catch (error) {
        console.error("이슈 후보 로드 실패:", error);

        container.innerHTML = `
            <p class="no-result">
                검색하신 키워드에 대한 기사를 찾을 수 없거나, 일시적인 오류가 발생했습니다.<br>
                다른 키워드로 검색하거나 잠시 후 다시 시도해 주세요.
            </p>
        `;
    }
}

// 2-0. 넓은 검색어("정치"/"경제"/"정청래" 등)로 여러 사건이 섞여 나올 때,
// 비교 카드를 바로 보여주지 않고 구체적인 키워드부터 고르게 한다.
// 후보(candidates)는 이미 API 응답에 다 들어있으므로, 칩을 클릭해도
// 새로 요청하지 않고 그중 하나만 골라서 보여준다.

// 검색 결과 한 단계(step)를 실제로 화면에 그린다 — 새 요청이든(fetch 직후)
// 복원이든(popstate) 이 함수 하나로 렌더링해서 두 경로의 결과 화면이
// 항상 똑같게 만든다. 히스토리/sessionStorage는 건드리지 않는다.
function renderSearchStep(container, { query, mode, candidates }) {
    if (mode === "keywords" && candidates.length > 1) {
        renderKeywordSelectionUI(container, { query, candidates });
        return;
    }

    renderIssueCandidatesUI(container, { query, candidates });
}

function renderKeywordSelectionUI(container, { query, candidates }) {
    container.innerHTML = `
        <div class="search-results-wrapper">
            <div class="keyword-select-guide">
                <p>
                    '${escapeHtml(query)}' 검색 결과와 관련된 키워드입니다.
                    원하는 키워드를 선택하거나, 검색어를 더 구체적으로 입력해 보세요.
                </p>
                <div class="chip-row">
                    ${candidates.map((candidate, index) => `
                        <button
                            type="button"
                            class="chip"
                            data-select-keyword="${index}"
                        >#${escapeHtml(candidate.keyword || candidate.issue_title || "")}</button>
                    `).join("")}
                </div>
            </div>
        </div>
    `;

    container.querySelectorAll("[data-select-keyword]").forEach(el => {
        el.addEventListener("click", () => {
            const index = Number(el.dataset.selectKeyword);
            const selected = candidates[index];

            if (!selected) return;

            // 키워드를 고른 것도 하나의 새 단계다 — 여기서 뒤로가기를 누르면
            // (재요청 없이) 방금 봤던 키워드 선택 화면으로 돌아가야 한다.
            const stepData = {
                query,
                mode: "candidates",
                candidates: [selected],
            };
            pushSearchStep(query, stepData);
            renderSearchStep(container, stepData);
        });
    });
}

// 2-1. 이슈 후보 카드 렌더링 (사건당 최대 5개뿐이므로 페이지네이션/뷰토글 불필요)
// 카드마다 그 카드에 해당하는 키워드 하나만 배지로 붙인다(renderIssueCandidateItem).
// 카드와 무관할 수 있는 "연관 키워드" 추천 목록은 더 이상 보여주지 않는다 —
// 키워드 선택 화면을 거치든 바로 카드로 넘어오든 항상 "카드 + 그 카드 고유의
// 키워드"만 보이도록 일관되게 맞춘 것.
function renderIssueCandidatesUI(container, { query, candidates }) {
    if (candidates.length === 0) {
        container.innerHTML = `<p class="no-result">"${escapeHtml(query)}"에 대한 검색 결과가 없습니다.</p>`;
        return;
    }

    container.innerHTML = `
        <div class="search-results-wrapper">
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