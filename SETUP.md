# 연결 및 운영 준비

1. Python 3.11 이상에서 `pip install -r requirements.txt`를 실행합니다.
2. Google Cloud에서 Gmail API를 켜고 웹 OAuth 클라이언트를 만듭니다.
   동의 화면에 Gmail 읽기 권한을 설정하고 테스트 수신자를 등록합니다.
3. HTTPS 주소를 확보하고 `https://실제주소/oauth/callback`을 승인된 리디렉션 URI로 등록합니다.
4. 다음 환경변수를 비공개 설정으로 입력합니다.
   - `PUBLIC_BASE_URL`: 실제 HTTPS 주소
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
   - `TOKEN_ENCRYPTION_KEY`: Fernet 키
   - `ACCESS_DB`: 영속 SQLite 파일 경로
5. 키 생성: `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
6. `flask --app mail_access run --host 127.0.0.1`로 개발 서버를 실행합니다.
   운영 시에는 WSGI 서버, HTTPS 프록시와 접근/속도 제한을 별도로 구성합니다.
7. 동일 환경에서 `python mail_access.py invite 직원주소`를 실행해 7일짜리 초대 주소를 생성합니다.
   실제 메일 버튼은 이 주소의 확인 페이지로 연결합니다. 링크만 열어서는 상태가 변경되지 않습니다.

## 중요한 제약

Google의 Gmail 읽기 권한은 메일함 전체에 적용됩니다. 교육 메일만으로 제한하는 OAuth 범위는 없습니다.
공유 캘린더 제목과 정확히 일치하는 메일만 사용하는 제한은 프로그램이 적용해야 합니다.
외부 공개 시 Google의 제한 범위 검증/보안 평가 요건을 확인해야 합니다.
외부 앱 테스트 모드의 refresh token은 7일 만료될 수 있습니다.
회사 Google 계정은 관리자의 외부 앱 허용이 필요할 수 있습니다.

초대 거절은 기존 연결 철회가 아닙니다. 철회는 Google 계정의 타사 연결 관리에서 할 수 있습니다.
분기 만료 시 이 코드의 `active_token()`은 접근을 차단합니다. 다음 분기에 새 초대가 필요합니다.
토큰 DB와 암호화 키는 따로 보호하고 백업해야 합니다.

## 남은 통합 작업

- 공유 캘린더 읽기 연결과 직원/교육 일정 매핑
- 승인 계정의 `active_token()`으로 Gmail API 조회
- Gmail 검색은 후보 수집일 뿐이며, 본문을 읽기 전에 제목을 정확히 비교
- 취소/시간 변경/중복 처리 및 참석/수료 증빙 구분
- 직원별 문서 생성, 월간 실행, 담당자 메일 첨부 발송
- 중복 발송 방지, 연결 철회/갱신 상태 화면, 보존기간 정책

ChatGPT의 기존 Gmail 커넥터는 이 앱에 저장된 직원 토큰을 자동으로 사용하지 않습니다.
별도 실행 작업과의 통합 없이는 기존 자동화에 직원이 자동 추가되지 않습니다.
