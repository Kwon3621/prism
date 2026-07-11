# Prism Frontend

별도 설치 없이 실행 가능한 정적 프론트엔드입니다.

## 실행 방법

### 가장 간단한 방법
`index.html`을 브라우저로 엽니다.

### 로컬 서버 실행
프로젝트 폴더에서 아래 명령을 실행합니다.

```bash
python -m http.server 8000
```

브라우저에서 `http://localhost:8000`으로 접속합니다.

## 포함 페이지
- `index.html`: 메인 페이지
- `search.html`: 검색 결과
- `issue.html`: 이슈 상세 비교
- `saved.html`: 저장한 이슈
- `methodology.html`: 분석 방식

## 기능
- 반응형 레이아웃
- 검색 라우팅
- 검색 결과 상태
- localStorage 기반 이슈 저장
- 링크 공유
- 모바일 메뉴

실제 서비스 연동 시 `assets/app.js`의 임시 데이터를 API 응답으로 교체하면 됩니다.
