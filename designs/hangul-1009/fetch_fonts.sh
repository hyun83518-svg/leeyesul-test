#!/bin/sh
# Google Fonts 파일을 fonts/ 에 내려받는다 (헤드리스 Chromium 이 프록시를 못 써서 로컬 폰트로 렌더링)
cd "$(dirname "$0")" && mkdir -p fonts
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
curl -s -A "$UA" "https://fonts.googleapis.com/css2?family=Black+Han+Sans&family=Anton&family=Noto+Sans+KR:wght@400;500;700;900&family=Playfair+Display:ital,wght@1,900&family=Montserrat:wght@300;500&display=block" -o fonts/remote.css
grep -oE 'https://fonts.gstatic.com[^)]+' fonts/remote.css | sort -u | xargs -P 16 -I{} sh -c 'curl -s -o fonts/$(echo {} | md5sum | cut -c1-16).woff2 {}'
python3 -c "
import re,hashlib
s=open('fonts/remote.css').read()
open('fonts/fonts.css','w').write(re.sub(r'https://fonts.gstatic.com[^)]+',lambda m:hashlib.md5((m.group(0)+'\n').encode()).hexdigest()[:16]+'.woff2',s))"
