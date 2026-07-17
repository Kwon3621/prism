/**
 * Prism v2 - 검색 처리 및 Solar Embedding 연동 전용 스크립트 (search.js)
 */

document.addEventListener("DOMContentLoaded", () => {
    initSearchRedirect();
  });
  
  // 1. 모든 검색 창의 이벤트를 감지하여 compare.html로 연결
  function initSearchRedirect() {
    const searchForms = document.querySelectorAll('[data-search-form]');
    
    searchForms.forEach(form => {
      const input = form.querySelector('input');
      const button = form.querySelector('button[type="submit"]');
      if (!input || !button) return;
  
      // 실시간 검색 버튼 활성화 제어
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
        button.textContent = '분석 중...';
  
        // v2 개편안: search.html을 사용하지 않고, 검색어를 포함해 compare.html로 바로 보냅니다.
        window.location.href = `compare.html?q=${encodeURIComponent(query)}`;
      });
    });
  }