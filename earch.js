[1mdiff --cc search.js[m
[1mindex 1a2c6a6,4b4fdfe..0000000[m
[1m--- a/search.js[m
[1m+++ b/search.js[m
[36m@@@ -2,10 -2,47 +2,50 @@@[m
   * Prism v2 - 검색 처리 및 뉴스/키워드 연동 스크립트 (search.js)[m
   */[m
  [m
[32m+ const SEARCH_PAGE_SIZE = 6;[m
[32m+ window.__PRISM_INLINE_SEARCH__ = true;[m
[32m+ [m
  document.addEventListener("DOMContentLoaded", () => {[m
      initSearchBehavior();[m
[32m++<<<<<<< HEAD[m
[32m++=======[m
[32m+     renderSearchSuggestions(); // 페이지 로드 시 기본 추천 키워드 로드[m
[32m+ [m
[32m+     // 다른 페이지(홈 등)에서 ?q=검색어 로 넘어온 경우 자동으로 검색을 실행한다.[m
[32m+     const queryFromUrl = new URLSearchParams(window.location.search).get("q");[m
[32m+     if (queryFromUrl) {[m
[32m+         runSearchOnPage(queryFromUrl);[m
[32m+     }[m
[32m++>>>>>>> origin/main[m
  });[m
  [m
[32m+ // 0. 공용 유틸[m
[32m+ [m
[32m+ function escapeHtml(value) {[m
[32m+     return String(value ?? "")[m
[32m+         .replace(/&/g, "&amp;")[m
[32m+         .replace(/</g, "&lt;")[m
[32m+         .replace(/>/g, "&gt;")[m
[32m+         .replace(/"/g, "&quot;")[m
[32m+         .replace(/'/g, "&#39;");[m
[32m+ }[m
[32m+ [m
[32m+ function formatDate(value) {[m
[32m+     if (!value) return "";[m
[32m+     const parsed = new Date(value);[m
[32m+     if (Number.isNaN(parsed.getTime())) return String(value);[m
[32m+ [m
[32m+     return parsed.toLocaleDateString("ko-KR", {[m
[32m+         year: "numeric",[m
[32m+         month: "2-digit",[m
[32m+         day: "2-digit",[m
[32m+     });[m
[32m+ }[m
[32m+ [m
[32m+ function goToCompare(query) {[m
[32m+     window.location.href = `compare.html?q=${encodeURIComponent(query)}`;[m
[32m+ }[m
[32m+ [m
  // 1. 검색창 이벤트 처리 (즉시 이동 대신 결과 노출)[m
  function initSearchBehavior() {[m
      const searchForms = document.querySelectorAll('[data-search-form]');[m
