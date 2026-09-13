# FRP 카울 30초 영상 — 미드저니 3D 영상 프롬프트

미드저니 영상은 **이미지 먼저 → Animate(이미지→영상)** 순서입니다. 장면마다 ① 이미지 프롬프트로 스틸을 뽑고, ② 마음에 드는 컷에서 **Animate → Manual** 을 눌러 모션 프롬프트를 넣습니다. 클립은 기본 5초이고 Extend 로 4초씩 늘릴 수 있습니다. 텍스트(자막)는 미드저니에 넣지 말고 CapCut/프리미어에서 얹으세요.

## 공통 규칙

- **스타일 앵커(모든 프롬프트 끝에 붙임):**
  `stylized 3D render, high-end CGI, octane render, clean geometry, bright daytime racetrack, clear blue sky, hard sunlight with crisp shadows, dry grey asphalt, red and white curbs, shallow depth of field`
- **파라미터:** `--ar 9:16 --v 7 --style raw --s 250 --no text, letters, logo, watermark`
- **일관성:** 장면 1에서 뽑은 바이크/카울 스틸을 `--oref <이미지URL> --ow 200` (V7 옴니 레퍼런스)로 이후 장면에 물려서 같은 카울이 나오게 하세요. 색감은 `--sref <장면1 URL>` 로 통일. 순정 카울 = **glossy red OEM fairing**, FRP 카울 = **raw white gelcoat fiberglass race fairing** 으로 색을 나눠 시청자가 한눈에 구분하도록 합니다.
- **모션 강도:** 카메라만 움직이는 컷은 Low motion, 파편·스파크 컷은 High motion.
- **시간대:** 전 장면 **주간 서킷**(맑은 하늘, 강한 햇빛, 선명한 그림자). 마지막 CTA만 늦은 오후 햇빛으로 마무리 톤을 줍니다.

---

## 장면 1 — 훅 (0–3.5초)

**이미지**
```
low-angle tracking shot of a sportbike with bare race fairings leaning deep into a corner on a sunlit racetrack, knee down, rider in black leathers, bright midday sun, green runoff and gravel trap in the background, motion blur on the asphalt, stylized 3D render, high-end CGI, octane render, clean geometry, bright daytime racetrack, clear blue sky, hard sunlight with crisp shadows, dry grey asphalt, red and white curbs, shallow depth of field --ar 9:16 --v 7 --style raw --s 250 --no text, letters, logo, watermark
```
**모션 (Low)**
```
camera tracks alongside the bike through the corner, subtle parallax on the curbs, heat shimmer on the asphalt, smooth cinematic movement
```

---

## 장면 2 — 순정 카울 산산조각 (3.5–9.5초)

**이미지 A — 낙하 직전**
```
a glossy red OEM motorcycle fairing panel falling toward the asphalt of a racetrack, dramatic side light, frozen mid-air just before impact, extreme close-up, stylized 3D render, high-end CGI, octane render, clean geometry, bright daytime racetrack, clear blue sky, hard sunlight with crisp shadows, dry grey asphalt, red and white curbs, shallow depth of field --ar 9:16 --v 7 --style raw --s 250 --no text, letters, logo, watermark
```
**모션 (High)**
```
the red plastic fairing slams into the asphalt and shatters into dozens of sharp jagged fragments that burst outward toward the camera, slow motion, dust puff and flying debris, camera shake on impact
```

**이미지 B — 파편이 흩어진 트랙**
```
top-down view of a racetrack racing line covered in sharp jagged shards of glossy red ABS plastic, scattered debris glinting in harsh sunlight, ominous mood, stylized 3D render, high-end CGI, octane render, clean geometry, bright daytime racetrack, clear blue sky, hard sunlight with crisp shadows, dry grey asphalt, red and white curbs, shallow depth of field --ar 9:16 --v 7 --style raw --s 250 --no text, letters, logo, watermark
```
**모션 (Low)**
```
slow overhead push-in toward the sharpest fragments, light flickers across the shards, subtle dust settling
```

---

## 장면 3 — 뒤에 오는 라이더 (9.5–15.5초)

**이미지 A — 뒤차 POV**
```
first-person POV from a following motorcycle on a racetrack, handlebars and front fender in frame, sharp red plastic debris scattered on the racing line ahead, front tire about to hit the fragments, tense mood, stylized 3D render, high-end CGI, octane render, clean geometry, bright daytime racetrack, clear blue sky, hard sunlight with crisp shadows, dry grey asphalt, red and white curbs, shallow depth of field --ar 9:16 --v 7 --style raw --s 250 --no text, letters, logo, watermark
```
**모션 (High)**
```
bike rushes forward toward the debris, front tire rides over a sharp fragment, handlebars twitch and wobble violently, camera jolts, fragments kick up
```

**이미지 B — 적기**
```
a track marshal at the edge of a racetrack waving a large red flag against a clear blue sky, motorcycles slowing in the background, dramatic low angle, stylized 3D render, high-end CGI, octane render, clean geometry, bright daytime racetrack, clear blue sky, hard sunlight with crisp shadows, dry grey asphalt, red and white curbs, shallow depth of field --ar 9:16 --v 7 --style raw --s 250 --no text, letters, logo, watermark
```
**모션 (High)**
```
the marshal waves the red flag energetically, fabric ripples, bikes in the background slow down, camera slowly pushes in
```

---

## 장면 4 — FRP 카울은 갈려 나간다 (15.5–22.5초)

**이미지 A — 슬라이딩**
```
a raw white gelcoat fiberglass motorcycle race fairing sliding sideways along racetrack asphalt, bottom edge grinding into the ground with a trail of fine white fiber dust and small sparks, the panel stays in one solid piece, low side angle at ground level, stylized 3D render, high-end CGI, octane render, clean geometry, bright daytime racetrack, clear blue sky, hard sunlight with crisp shadows, dry grey asphalt, red and white curbs, shallow depth of field --ar 9:16 --v 7 --style raw --s 250 --no text, letters, logo, watermark
```
**모션 (High)**
```
the fiberglass fairing slides across the frame from left to right, its edge grinds down in a cloud of white fiber dust and small sparks, the panel stays whole and slowly comes to rest, slow motion, ground-level tracking camera
```

**이미지 B — 유리섬유 직조 확대**
```
extreme macro of woven fiberglass cloth saturated in clear resin, interlocking white fiber strands catching light, a ground edge showing the fibers holding together instead of breaking, studio rim lighting, stylized 3D render, high-end CGI, octane render, clean geometry, shallow depth of field --ar 9:16 --v 7 --style raw --s 250 --no text, letters, logo, watermark
```
**모션 (Low)**
```
slow push-in into the weave, light glides across the fibers, gentle rack focus from the edge to the center
```

---

## 장면 5 — 보너스 3컷 (22.5–27초, 컷당 약 1.5초)

**가볍다**
```
a rider effortlessly lifting a white fiberglass race fairing with one hand in a pit garage, panel looks featherlight, warm workshop light, stylized 3D render, high-end CGI, octane render, clean geometry, shallow depth of field --ar 9:16 --v 7 --style raw --s 250 --no text, letters, logo, watermark
```
모션 (Low): `the rider lifts the panel slightly and turns it, light sweeps across its surface`

**갈려도 수리 가능**
```
close-up of hands applying resin and fiberglass patch to the ground edge of a white race fairing on a workbench, brush and mixing cup, warm workshop light, stylized 3D render, high-end CGI, octane render, clean geometry, shallow depth of field --ar 9:16 --v 7 --style raw --s 250 --no text, letters, logo, watermark
```
모션 (Low): `the brush spreads resin over the ground edge, slow and smooth, subtle camera drift`

**순정은 집에**
```
a glossy red OEM motorcycle fairing set carefully stored on a clean garage shelf under soft light, pristine and untouched, stylized 3D render, high-end CGI, octane render, clean geometry, shallow depth of field --ar 9:16 --v 7 --style raw --s 250 --no text, letters, logo, watermark
```
모션 (Low): `slow dolly past the shelf, soft light shifts on the glossy paint`

---

## 장면 6 — CTA (27–30초)

**이미지**
```
a rider in black leathers rolling into the pit lane on a sportbike with white fiberglass race fairings, flipping up the helmet visor, late afternoon sunlight with long shadows, cinematic hero shot, stylized 3D render, high-end CGI, octane render, clean geometry, bright daylight, shallow depth of field --ar 9:16 --v 7 --style raw --s 250 --no text, letters, logo, watermark
```
**모션 (Low)**
```
bike rolls to a stop, the rider flips up the visor and looks at the camera, gentle slow motion, warm light flare
```

---

## 편집 순서 (CapCut 기준)

1. 장면별 클립을 타임라인 순서로 배치하고 `script.md` 의 시간대에 맞춰 트림합니다. 미드저니 클립은 5초 단위이므로 필요한 만큼만 잘라 씁니다.
2. `script.md` 의 온스크린 자막을 각 구간에 얹습니다. 자막은 화면 세로 중앙 위쪽(상단 10%, 하단 20% 안전영역 밖)에 배치합니다.
3. 나레이션 TTS와 저음 BGM(-18dB)을 깔고, 장면 2 임팩트·장면 4 스파크에 효과음을 넣습니다.
4. 1080×1920, 30fps 로 내보내기. 미드저니 클립 해상도가 낮으면 CapCut 업스케일 또는 Topaz 로 올립니다.
