# 무료 옵션 모니터

Tooja 옵션 API에서 SNDK와 MU 데이터를 자동 수집·비교하고, 큰 변화가 생기면 Telegram으로 알립니다.

## 기능
- 평일 30분 주기 수집
- Spot, Max Pain, ATM IV/감마, Call/Put Wall 추출
- 직전 스냅샷 대비 변화 감지
- JSON 이력 저장
- 정적 대시보드 생성
- Telegram 선택 알림
- Actions 수동 실행

## 설치
1. GitHub에 새 저장소를 만듭니다. 데이터 비공개를 원하면 Private 권장.
2. 이 폴더 전체를 업로드합니다.
3. Actions 탭에서 워크플로를 활성화합니다.
4. `Options monitor`를 한 번 수동 실행합니다.
5. Telegram 알림을 쓰려면 저장소 Settings → Secrets and variables → Actions에 다음을 추가합니다.
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

## 설정
`config.json`에서 종목과 알림 민감도를 바꿀 수 있습니다.

## 해석 주의
- OI 증감만으로 매수·매도 방향을 확정하지 않습니다.
- Max Pain은 목표가가 아니라 만기 구조 참고값입니다.
- API 구조가 바뀌면 파서를 수정해야 합니다.
- GitHub cron은 몇 분 이상 지연될 수 있습니다.
