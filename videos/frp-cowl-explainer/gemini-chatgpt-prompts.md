# FRP 카울 30초 영상 — Gemini(Veo 3) / ChatGPT(Sora) 프롬프트

미드저니와 달리 **문장 하나로 바로 영상**이 나오고 **소리(나레이션·효과음)까지 같이 생성**됩니다. 이미지 단계가 없습니다.

## 어느 쪽이 좋은가

| | Gemini (Veo 3) | ChatGPT (Sora) |
|---|---|---|
| 구독 | Google AI Pro/Ultra | ChatGPT Plus/Pro (또는 Sora 앱) |
| 클립 길이 | 8초 고정 | 5·10·15·20초 선택 |
| 세로 9:16 | 지원 (설정에서 선택) | 지원 |
| 소리 | 나레이션·효과음 자동 생성, 한국어 대사 가능 | Sora 2는 소리 생성, 구버전은 무음 |
| 추천 | **1순위.** 한국어 나레이션을 프롬프트에 그대로 넣으면 됨 | 클립을 10초로 뽑아 3개면 30초 |

- 자막(한글 텍스트)은 AI가 자주 틀리므로 **영상에는 넣지 말고** CapCut에서 얹으세요. 프롬프트마다 `no on-screen text` 를 붙였습니다.
- 4개 클립 × 8초 = 32초 → 편집에서 30초로 트림.
- 한 클립 안에 동작은 **하나만** 넣어야 잘 나옵니다. 나레이션이 나머지 설명을 맡습니다.
- 캐릭터·카울 색이 클립마다 달라지면 편집이 어색하니, 순정 카울은 **glossy red**, FRP 카울은 **raw white fiberglass** 로 프롬프트에 매번 고정했습니다.

## Gemini(Veo 3) 사용법
1. Gemini 앱 → 입력창의 **Video** 버튼(또는 "동영상 만들기") 선택.
2. 세로 9:16 선택.
3. 아래 프롬프트를 통째로 붙여넣기. 나레이션 문장은 그대로 두면 한국어 음성이 생성됩니다.
4. 마음에 안 들면 같은 프롬프트로 2~3번 다시 생성해 가장 좋은 것을 고릅니다.

---

## 클립 1 (0–8초) — 훅 + 순정 카울 산산조각

```
Vertical 9:16 video, 8 seconds, stylized 3D CGI look, bright sunny day at a racetrack, clear blue sky, grey asphalt, red and white curbs.
A sportbike with a glossy red stock fairing low-sides in a corner. The red fairing hits the asphalt and shatters into dozens of sharp jagged plastic fragments that scatter across the track in slow motion, with a dust puff. Camera: low angle, slight shake on impact.
Sound: engine, a loud crack on impact, plastic pieces skittering on asphalt.
Korean male voiceover, calm and quick: "서킷 라이더들은 왜 순정 카울을 떼어낼까요? 순정 카울은 넘어지는 순간 산산조각이 나고, 날카로운 파편이 트랙에 흩어집니다."
No on-screen text, no logos.
```

## 클립 2 (8–16초) — 뒤에 오는 라이더 + 적기

```
Vertical 9:16 video, 8 seconds, stylized 3D CGI look, bright sunny day at a racetrack, clear blue sky, grey asphalt, red and white curbs.
First-person view from a following motorcycle. Sharp red plastic fragments lie on the racing line ahead. The front tire rides over a fragment and the handlebars wobble violently. Then a cut to a track marshal waving a large red flag against the blue sky.
Sound: engine, a sharp tire pop, tense music sting.
Korean male voiceover: "문제는 뒤에 오는 라이더. 파편 하나가 펑크, 슬립, 전도로 이어지고, 세션 전체가 적기로 멈춥니다."
No on-screen text, no logos.
```

## 클립 3 (16–24초) — FRP 카울은 갈려 나간다

```
Vertical 9:16 video, 8 seconds, stylized 3D CGI look, bright sunny day at a racetrack, clear blue sky, grey asphalt, red and white curbs.
A raw white fiberglass race fairing slides sideways along the asphalt in slow motion. Its bottom edge grinds down with a trail of fine white dust and a few small sparks, but the panel stays in one solid piece and comes to rest. Camera: ground-level tracking shot. End on an extreme macro of woven fiberglass cloth in clear resin.
Sound: long grinding scrape, dust hiss.
Korean male voiceover: "그래서 FRP 카울. 유리섬유가 서로를 붙잡고 있어서, 깨져서 튀지 않고 갈려 나갑니다. 한 덩어리 그대로요."
No on-screen text, no logos.
```

## 클립 4 (24–30초) — 보너스 + CTA

```
Vertical 9:16 video, 8 seconds, stylized 3D CGI look, late afternoon sunlight at a racetrack pit lane, long shadows.
Quick sequence: a rider lifts a white fiberglass fairing easily with one hand; hands brush resin onto its ground edge on a workbench; a glossy red stock fairing sits safely on a garage shelf. Final shot: the rider on a sportbike with white race fairings rolls into the pit lane and flips up the visor, looking at the camera.
Sound: light workshop ambience, then engine idling down, warm music.
Korean male voiceover: "게다가 가볍고, 갈린 부분은 레진으로 메워 다시 탈 수 있고, 비싼 순정 카울은 집에 안전하게. 서킷에선 FRP 카울. 나를 위해, 그리고 뒤에 오는 라이더를 위해."
No on-screen text, no logos.
```

---

## ChatGPT(Sora)로 만들 때

- Sora에서 세로 9:16, 길이 10초를 선택하고 위 프롬프트를 그대로 붙여넣습니다. `8 seconds` 는 `10 seconds` 로 바꾸세요.
- 클립 1·2·3을 10초씩 뽑으면 30초가 되므로 클립 4의 내용은 클립 3 끝에 붙이거나 편집에서 스틸 이미지로 처리합니다.
- Sora가 한국어 음성을 어색하게 만들면 나레이션 문장을 지우고 무음으로 뽑은 뒤, `script.md` 의 나레이션을 TTS(클로바더빙, ElevenLabs)로 얹으세요.

## 편집 (CapCut)
1. 클립 4개를 순서대로 놓고 30초로 트림.
2. `script.md` 의 온스크린 자막을 얹기. 상단 10%, 하단 20% 안전영역은 피하기.
3. 클립마다 나레이션 톤이 다르면 AI 음성을 끄고 TTS 한 번으로 통일하는 편이 깔끔합니다.
4. 1080×1920, 30fps 로 내보내기.
