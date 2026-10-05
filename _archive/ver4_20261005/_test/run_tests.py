"""
run_tests.py  (ver2 - 2026.09.30, 스크롤 유지·해설 작성 검사 추가)
dist/ 웹앱을 실제 브라우저(Chromium)로 열어 핵심 흐름을 검사한다.
빌드 후, 템플릿이나 build.py 를 고친 뒤에 실행한다.

필요 패키지: pip install playwright  →  python -m playwright install chromium
기록(localStorage)은 테스트용 임시 브라우저에만 남으므로 실제 기록에 영향 없음.
"""
import asyncio
import time
import os
import sys

from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("  통과 " if ok else "  실패 ") + name + (f"  ({detail})" if detail and not ok else ""))


def url(fn):
    return "file:///" + os.path.join(DIST, fn).replace("\\", "/").lstrip("/")


def check_images():
    """문항 이미지 맨 아래 2행에 글자가 닿으면 아래쪽이 잘린 것 (2026-09-30: 78회 2번 등 단 마지막 문항 잘림).
    세로선(단 구분선)은 제외. 77회는 원본 PDF 가 없어 옛 이미지(쪽 번호 포함)라 제외."""
    from PIL import Image
    import numpy as np
    data = os.path.join(ROOT, "data")
    bad = []
    for r in sorted(x for x in os.listdir(data) if x.isdigit() and x != "77"):
        for n in range(1, 51):
            a = np.asarray(Image.open(os.path.join(data, r, "img", f"q{n:02d}.jpg")).convert("L")) < 120
            a[:, a.mean(axis=0) > 0.5] = False
            if a[-2:, 3:-3].sum() > 3:
                bad.append(f"{r}-{n}")
    check("문항 이미지 아래쪽 잘림 없음", not bad, ", ".join(bad[:20]))


async def launch_browser(p):
    """Playwright 전용 Chromium 이 없으면 PC 에 설치된 Edge → Chrome 순으로 쓴다.
    (2026-09-30: Playwright 업데이트 후 'Executable doesn't exist' 로 테스트가 멈춘 일이 있었음)"""
    for opts, name in (({}, "Playwright Chromium"), ({"channel": "msedge"}, "Microsoft Edge"), ({"channel": "chrome"}, "Chrome")):
        try:
            b = await p.chromium.launch(**opts)
            print(f"  브라우저: {name}")
            return b
        except Exception:
            continue
    print("  실패: 테스트용 브라우저를 찾지 못했습니다. 다음을 실행하세요:  python -m playwright install chromium")
    return None


async def main():
    check_images()
    async with async_playwright() as p:
        b = await launch_browser(p)
        if b is None:
            return 1
        pg = await b.new_page(viewport={"width": 420, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

        # 1. 인덱스
        await pg.goto(url("index.html"))
        cards = await pg.locator(".round-card").count()
        check("인덱스에 회차 카드 표시", cards > 0, f"{cards}개")
        first = await pg.locator(".round-card").first.get_attribute("href")
        check("최신 회차가 맨 앞", first is not None, first or "")

        # 2. 모든 회차 데이터 로드 + 이미지
        for a in await pg.locator(".round-card").all():
            href = await a.get_attribute("href")
            page2 = await b.new_page()
            await page2.goto(url(href))
            n = await page2.evaluate("(window.ROUND_DATA||{problems:[]}).problems.length")
            check(f"{href} 데이터 50문항", n == 50, f"{n}")
            await page2.click("text=1~25번")
            try:
                await page2.wait_for_function("(()=>{const i=document.querySelector('.qimg img');return !!i && i.complete && i.naturalWidth>0})()", timeout=5000)
                ok = True
            except Exception:
                ok = False
            check(f"{href} 1번 이미지 표시", ok)
            await page2.close()

        # 3. 연습 흐름 (첫 회차)
        await pg.goto(url(first))
        await pg.evaluate("localStorage.clear()")
        await pg.reload()
        await pg.click("text=1~25번")
        check("연습 모드에 시계 없음", await pg.locator("#clock").count() == 0)
        ans = await pg.evaluate("ROUND_DATA.problems[0].a")
        await pg.set_viewport_size({"width": 420, "height": 500})
        await pg.wait_for_function("(()=>{const i=document.querySelector('.qimg img');return !!i && i.complete})()", timeout=5000)
        await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await pg.click(f".bub >> nth={ans - 1}")
        await pg.wait_for_timeout(300)
        check("연습: 답 선택 후 맨 위로 튀지 않음", await pg.evaluate("window.scrollY") > 0)
        await pg.set_viewport_size({"width": 420, "height": 900})
        check("정답 선택 시 A·B만 활성", await pg.is_enabled('.rxb[data-k="B"]') and await pg.is_disabled('.rxb[data-k="C"]'))
        await pg.click('.rxb[data-k="B"]')
        check("B 선택 후 기록 전 다음 불가", await pg.is_disabled("#nextBtn"))
        await pg.fill("#note", "테스트 근거")
        check("기록 후 다음 가능", await pg.is_enabled("#nextBtn"))
        # 3-1. 풀이 화면에서 해설 작성 (2026-09-30)
        await pg.click(".exp-box .linkish")
        await pg.fill("#expEdit", f"테스트 해설 {int(time.time())}\n둘째 줄")   # 매번 달라야 기존 해설과 같아지는 일이 없음
        await pg.click(".exp-btns >> text=저장")
        check("해설 저장 후 화면에 표시", "테스트 해설" in await pg.inner_text(".exp-box"))
        check("작성한 해설 표시(반영 전)", await pg.locator(".exp-mine").count() == 1)
        stored = await pg.evaluate("JSON.parse(localStorage.getItem('hkh.exps.v1'))")
        check("해설이 브라우저에 저장됨", any(v["t"].startswith("테스트 해설") for v in stored.values()))
        await pg.click("#nextBtn")
        ans2 = await pg.evaluate("ROUND_DATA.problems[1].a")
        await pg.click(f".bub >> nth={ans2 % 5}")                 # 일부러 오답
        check("오답 선택 시 C·D만 활성", await pg.is_enabled('.rxb[data-k="C"]') and await pg.is_disabled('.rxb[data-k="A"]'))
        await pg.click('.rxb[data-k="A"]', force=True)
        await pg.click('.rxb[data-k="D"]')
        await pg.fill("#note", "핵심 키워드")
        await pg.click("text=그만하기")
        await pg.wait_for_timeout(300)
        out = await pg.input_value("#out")
        check("기록 텍스트에 B·D 항목", "B |" in out and "D |" in out)
        check("연습 기록에 시간 줄 없음", "시간" not in out.splitlines()[1])

        # 3-2. 해설 파일 받기
        await pg.click("text=처음으로")
        check("홈에 반영 전 해설 개수", "반영 전 해설 1개" in await pg.inner_text("#app"))
        async with pg.expect_download() as dl:
            await pg.click("text=해설 파일 받기")
        d = await dl.value
        import json as _j
        data = _j.loads(open(await d.path(), encoding="utf-8").read())
        check("해설 파일 형식", data.get("type") == "hkh-explanations" and len(data["items"]) == 1
              and data["items"][0]["n"] == 1, str(data)[:120])

        # 4. 이어하기 저장
        await pg.click("text=80분 실전 시작")
        # 4-1. 답 선택 시 스크롤 유지 (2026-09-30 버그: 답을 고르면 맨 위로 이동)
        await pg.set_viewport_size({"width": 420, "height": 500})
        await pg.wait_for_function("(()=>{const i=document.querySelector('.qimg img');return !!i && i.complete})()", timeout=5000)
        await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        y1 = await pg.evaluate("window.scrollY")
        await pg.click(".bub >> nth=0")
        await pg.wait_for_timeout(300)
        y2 = await pg.evaluate("window.scrollY")
        check("실전: 답 선택 후 스크롤 유지", y1 > 0 and abs(y1 - y2) < 5, f"전 {y1} / 후 {y2}")
        await pg.set_viewport_size({"width": 420, "height": 900})
        await pg.reload()
        check("새로고침 후 이어서 풀기 표시", await pg.locator("text=이어서 풀기").count() == 1)
        await pg.click("text=이어서 풀기")
        check("실전 시계 표시", await pg.locator("#clock").count() == 1)
        await pg.click("text=제출")
        await pg.wait_for_timeout(300)
        check("제출 후 번호판 표시", await pg.locator(".sheet .cell").count() == 50)

        check("스크립트 오류 없음", not errs, "; ".join(errs))
        await b.close()
    print(f"\n{sum(results)}/{len(results)} 통과")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
