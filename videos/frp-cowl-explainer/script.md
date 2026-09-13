# FRP 카울 30초 세로 영상 — 스크립트 & 스토리보드

- **포맷:** 9:16 세로 (1080×1920), 30fps, 30초
- **플랫폼:** YouTube Shorts / Instagram Reels / TikTok
- **타깃:** 모터사이클은 알지만 "서킷용 FRP 카울"이 왜 필요한지는 모르는 일반 라이더·비라이더
- **핵심 메시지:** 순정 카울(ABS)은 넘어지면 **산산조각**이 나서 날카로운 파편이 트랙에 흩어지고, 뒤따르는 라이더를 위험하게 만든다. FRP(유리섬유) 카울은 섬유가 서로 붙잡고 있어 **깨져서 튀지 않고 갈려 나간다.**
- **제작 방식:** 프로그래매틱 모션그래픽(HTML/CSS/JS → Playwright 프레임 캡처 → ffmpeg). 실사가 필요하면 아래 AI B-roll 프롬프트로 대체 가능.

---

## 타임라인 (30초)

| 구간 | 화면 (비주얼) | 자막 (온스크린) | 나레이션 |
|---|---|---|---|
| **0–3.5s 훅** | 어두운 아스팔트 배경. 카울 아이콘이 살짝 흔들리며 등장 | `FRP 카울, 30초 설명` / **서킷 라이더들은 왜 / 순정 카울을 떼어낼까?** | "서킷 라이더들은 왜 멀쩡한 순정 카울을 떼어낼까요?" |
| **3.5–9.5s 문제** | 순정 카울이 트랙에 떨어지며 **산산조각**. 파편이 사방으로 튀어 트랙 위에 흩어짐. 임팩트 플래시 + 카메라 흔들림 | `순정 카울 = ABS 플라스틱` → **넘어지는 순간, 산산조각** → **날카로운 파편이 트랙 위로** | "순정 카울은 ABS 플라스틱. 넘어지는 순간 산산조각이 나고, 날카로운 파편이 트랙 위로 흩어집니다." |
| **9.5–15.5s 위험** | 파편이 남은 트랙 위로 뒤따르는 바이크(🏍️)가 진입 → 파편을 밟고 휘청, ⚠️ 표시. 이어서 🚩 적기 등장 | `문제는 뒤에 오는 라이더` → **파편 = 펑크 · 슬립 · 전도** → **세션 전체가 적기로 중단** | "문제는 뒤에 오는 라이더. 파편 하나가 펑크, 슬립, 전도로 이어지고, 세션 전체가 적기로 멈춥니다." |
| **15.5–22.5s 해결** | FRP 카울이 아스팔트 위를 **미끄러지며** 스파크·먼지를 내고 바닥면만 갈려 나감. 형태는 한 덩어리 유지. 우측에 유리섬유 직조 확대 인서트 | `그래서 FRP 카울` / `유리섬유(Fiberglass) + 수지` → **깨져서 튀지 않고, 갈려 나갑니다** → **섬유가 서로 붙잡아 한 덩어리로** | "그래서 FRP 카울. 유리섬유가 서로를 붙잡고 있어서, 깨져서 튀지 않고 갈려 나갑니다. 한 덩어리 그대로요." |
| **22.5–27s 보너스** | 3개 카드가 순서대로 팝업 | `게다가` → 🪶 **가볍다** / 🔧 **갈려도 수리 가능** (레진·퍼티로 메우고 다시 탄다) / 🏠 **순정은 집에** (비싼 순정 카울은 그대로 보존) | "게다가 가볍고, 갈린 부분은 레진으로 메워 다시 탈 수 있고, 비싼 순정 카울은 집에 안전하게." |
| **27–30s CTA** | 카울 아이콘 + 큰 타이틀 | **서킷에선 FRP 카울** / 나를 위해, 그리고 뒤에 오는 라이더를 위해 / `저장하고 라이딩 친구에게 공유` | "서킷에선 FRP 카울. 나를 위해, 그리고 뒤에 오는 라이더를 위해." |

---

## 나레이션 전문 (TTS/녹음용, 약 28초)

> 서킷 라이더들은 왜 멀쩡한 순정 카울을 떼어낼까요?
> 순정 카울은 ABS 플라스틱. 넘어지는 순간 산산조각이 나고, 날카로운 파편이 트랙 위로 흩어집니다.
> 문제는 뒤에 오는 라이더. 파편 하나가 펑크, 슬립, 전도로 이어지고, 세션 전체가 적기로 멈춥니다.
> 그래서 FRP 카울. 유리섬유가 서로를 붙잡고 있어서, 깨져서 튀지 않고 갈려 나갑니다. 한 덩어리 그대로요.
> 게다가 가볍고, 갈린 부분은 레진으로 메워 다시 탈 수 있고, 비싼 순정 카울은 집에 안전하게.
> 서킷에선 FRP 카울. 나를 위해, 그리고 뒤에 오는 라이더를 위해.

- 톤: 담담하고 빠른 설명체(정보성 쇼츠). 여성/남성 무관, 저음 권장.
- 렌더된 MP4는 **무음(빈 오디오 트랙)** 입니다. 위 문장을 TTS(네이버 클로바, ElevenLabs 등) 또는 직접 녹음해 얹고, 저음 BGM(엔진 룸톤 계열)을 -18dB 정도로 깔면 완성.

---

## 캡션/제목/해시태그

- **제목:** 서킷 바이크는 왜 카울을 갈아 끼울까? FRP 카울 30초 설명
- **설명:** 순정 카울은 넘어지면 산산조각 → 뒤차에게 흉기. FRP는 깨지지 않고 갈려 나갑니다. 서킷 가기 전에 꼭 알아야 할 이유.
- **해시태그:** #FRP카울 #서킷주행 #모터사이클 #트랙데이 #레이싱카울 #바이크상식 #오토바이

---

## 실사 버전용 AI B-roll 프롬프트 (Veo 3 / Kling / Runway)

텍스트는 AI 영상에 넣지 말고 위 자막을 프로그래매틱 오버레이로 얹을 것.

1. **훅 (0–3.5s)**
   `Vertical 9:16. Low-angle tracking shot of a sportbike with bare race fairings leaning through a corner on a racetrack, morning light, motion blur on the asphalt, cinematic color grading, no text.`
2. **순정 카울 파손 (3.5–9.5s)**
   `Vertical 9:16. Slow-motion macro of a glossy black ABS plastic motorcycle fairing panel hitting asphalt and shattering into sharp fragments that scatter across the track, dramatic side lighting, 120fps, shallow depth of field, no text.`
3. **뒤차 위험 (9.5–15.5s)**
   `Vertical 9:16. POV from a following motorcycle on a racetrack, sharp plastic debris scattered on the racing line ahead, front tire approaching the debris, tense handheld feel, overcast light, no text.`
4. **FRP 슬라이딩 (15.5–22.5s)**
   `Vertical 9:16. Slow-motion close-up of a white fiberglass race fairing sliding along asphalt, edge grinding away with fine dust and small sparks, panel stays in one piece, dramatic rim lighting, 120fps, no text.`
5. **유리섬유 확대 (인서트)**
   `Vertical 9:16. Extreme macro of woven fiberglass cloth with resin, camera slowly pushes in, fibers catching light, clean studio lighting, no text.`
6. **CTA (27–30s)**
   `Vertical 9:16. A rider in leathers pulls into the pit lane on a race-fairing sportbike and flips up the visor, golden hour, cinematic, slight slow motion, no text.`

---

## 렌더 방법

```bash
cd videos/frp-cowl-explainer
NODE_PATH=$(npm root -g) node render.js          # frames/ 에 900장 캡처 후 frp-cowl-30s.mp4 생성
```

- `frp-cowl.html` 이 애니메이션 원본입니다. `seek(t)` 함수가 시간 `t`(초)에 맞춰 모든 요소를 배치하므로, 자막·타이밍은 파일 상단의 `TL` 상수와 각 장면 함수만 고치면 됩니다.
- 한글 폰트: Noto Sans KR (variable). 시스템에 없으면 `render.js` 의 `FONT_PATH` 로 경로를 지정하세요.
