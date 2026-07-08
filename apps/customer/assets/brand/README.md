# 브랜드 타이틀 이미지

이 폴더에 **`greenit_title.png`** 파일을 넣으면 앱의 모든 화면 상단 타이틀이
그 이미지(그린잇 워드마크)로 표시됩니다.

- 파일명: `greenit_title.png` (정확히 이 이름)
- 권장: 가로로 긴 워드마크, 배경 투명(PNG), 높이 기준 최소 120px 이상
- 파일이 없으면 자동으로 "그린잇" 텍스트 워드마크로 대체 표시됩니다.

사용 위젯: `BrandTitle` (apps/customer/lib/main.dart)
`assets/brand/` 폴더는 pubspec.yaml 에 이미 등록되어 있어, 파일만 넣으면 됩니다.
