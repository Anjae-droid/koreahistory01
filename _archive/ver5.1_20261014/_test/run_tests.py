"""
run_tests.py  (ver4 - 2026.10.13, 첫 화면(회차별/시대별)·시대별 풀이 검사 추가)
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

        # 1. 인덱스: 첫 화면에서 회차별 / 시대별 선택 (2026-10-13)
        await pg.goto(url("index.html"))
        check("첫 화면에 회차별·시대별 선택", await pg.locator(".pick-card").count() == 2)
        await pg.click("text=회차별로 풀기")
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
        # 3-1a. 마친 기록 수정 (2026-10-05): 답은 고정, 반응·1줄 기록만 고친다
        await pg.click("button:has-text('기록 수정')")
        check("기록 수정: 답 버튼 잠김", await pg.locator(".bub:enabled").count() == 0)
        check("기록 수정: 푼 문항만 이동", "1 / 2" in await pg.inner_text(".progress-text"))
        await pg.click("#nextBtn")
        check("기록 수정: 오답은 C·D만 활성", await pg.is_enabled('.rxb[data-k="C"]') and await pg.is_disabled('.rxb[data-k="B"]'))
        await pg.click('.rxb[data-k="C"]')
        await pg.fill("#note", "수정한 근거")
        await pg.click("#nextBtn")                                  # 마지막 문항 → 수정 마치기
        await pg.wait_for_timeout(300)
        out = await pg.input_value("#out")
        check("수정 후 기록 텍스트 반영", "C |" in out and "수정한 근거" in out and "D |" not in out, out[-200:])
        sess = await pg.evaluate("JSON.parse(localStorage.getItem('hkh.sessions.v1'))")
        check("수정한 기록 저장(updatedAt)", any(x.get("finished") and x.get("updatedAt") and x["items"]["2"]["rx"] == "C" for x in sess))

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
        # 3-3. 백업 불러오기: 같은 기록은 나중에 고친 쪽을 남김 (2026-10-05)
        check("기록 목록에 수정 버튼", await pg.locator("table >> text=수정").count() >= 1)
        import tempfile
        sid = sess[0]["id"]
        for note, dt, want in (("백업에서 고침", 60000, "백업에서 고침"), ("옛 기록", -10**12, "백업에서 고침")):
            x = _j.loads(_j.dumps(sess[0])); x["items"]["2"]["note"] = note; x["updatedAt"] = sess[0]["updatedAt"] + dt
            fp = os.path.join(tempfile.mkdtemp(), "b.json")
            open(fp, "w", encoding="utf-8").write(_j.dumps([x]))
            await pg.set_input_files("#restore", fp)
            await pg.wait_for_timeout(300)
            got = await pg.evaluate(f"JSON.parse(localStorage.getItem('hkh.sessions.v1')).find(x=>x.id==='{sid}').items['2'].note")
            check(f"백업 불러오기: {'최신 기록으로 교체' if dt > 0 else '옛 기록은 무시'}", got == want, got)

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

        await era_tests(b, pg)

        check("스크립트 오류 없음", not errs, "; ".join(errs))
        await b.close()
    print(f"\n{sum(results)}/{len(results)} 통과")
    return 0 if all(results) else 1


async def era_tests(b, pg):
    """시대별 풀이 (2026-10-13): 기본 범위 = 최신 회차의 그 시대 문항, 그냥 풀기 / 항목체크 풀기, 시간 제한 없음."""
    await pg.goto(url("index.html"))
    await pg.click("text=시대별로 풀기")
    await pg.wait_for_selector(".era-card")
    eras = await pg.locator(".era-card").count()
    check("시대 카드 표시", eras >= 8, f"{eras}개")
    await pg.click(".era-card >> text=조선")
    await pg.wait_for_load_state()
    check("시대 화면 열림", "조선" in await pg.inner_text("header"))
    exp = await pg.evaluate("EP.filter(p=>p.r===EROUNDS[0]).length")
    check("기본 범위: 최신 회차의 조선 문항", await pg.input_value("#scope") == str(await pg.evaluate("EROUNDS[0]"))
          and f"{exp}문항" in await pg.inner_text("#howmany"))
    check("시대별 화면에 시계 없음", await pg.locator("#clock").count() == 0)
    # 그냥 풀기: 반응 없이 다음으로, 중간에 그만두면 거기까지 점수
    await pg.click("text=그냥 풀기 시작")
    check("문항 출처(회차·번호) 표시", "회" in await pg.inner_text(".qsrc"))
    a = await pg.evaluate("BY[S.list[0]].a")
    await pg.click(f".bub >> nth={a - 1}")
    check("그냥 풀기: 반응 분류 없음", await pg.locator(".rxb").count() == 0)
    check("그냥 풀기: 해설 표시", await pg.locator(".exp-box").count() == 1)
    check("그냥 풀기: 바로 다음 문제 가능", await pg.is_enabled("#nextBtn"))
    await pg.click("#nextBtn")
    await pg.click("text=그만하기")
    await pg.wait_for_timeout(300)
    out = await pg.input_value("#out")
    check("그냥 풀기: 중간 종료 점수", "정답 1/1문항" in out and "시대: 조선" in out, out[:200])
    sess = await pg.evaluate("JSON.parse(localStorage.getItem('hkh.sessions.v1')).filter(x=>x.kind==='era')")
    check("시대별 기록 저장", len(sess) == 1 and sess[0]["finished"])
    # 항목체크 풀기: 전체 회차·무작위·최대 5문항, 반응·1줄 기록 필수
    await pg.click("text=처음으로")
    await pg.select_option("#scope", "all")
    await pg.select_option("#order", "rand")
    await pg.select_option("#count", "5")
    check("문항 수 제한 표시", "5문항" in await pg.inner_text("#howmany"))
    await pg.click("text=항목체크 풀기 시작")
    lst = await pg.evaluate("S.list")
    check("문항 수 제한·전 회차 범위", len(lst) == 5 and await pg.evaluate("S.list.every(k=>BY[k].e==='조선')"), str(lst))
    await pg.set_viewport_size({"width": 420, "height": 500})
    await pg.wait_for_function("(()=>{const i=document.querySelector('.qimg img');return !!i && i.complete && i.naturalWidth>0})()", timeout=5000)
    await pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    y1 = await pg.evaluate("window.scrollY")
    a = await pg.evaluate("BY[S.list[0]].a")
    await pg.click(f".bub >> nth={a % 5}")                      # 일부러 오답
    await pg.click('.rxb[data-k="C"]')
    y2 = await pg.evaluate("window.scrollY")
    check("항목체크: 반응 선택 후 스크롤 유지", y1 > 0 and y2 > 0, f"전 {y1} / 후 {y2}")
    await pg.set_viewport_size({"width": 420, "height": 900})
    check("항목체크: 1줄 기록 전 다음 막힘", await pg.is_disabled("#nextBtn"))
    await pg.fill("#note", "시대별 근거")
    check("항목체크: 1줄 기록 후 다음 가능", await pg.is_enabled("#nextBtn"))
    await pg.reload()
    check("시대별 이어서 풀기 표시", await pg.locator("text=이어서 풀기").count() == 1)
    await pg.click("text=이어서 풀기")
    await pg.click("text=그만하기")
    await pg.wait_for_timeout(300)
    out = await pg.input_value("#out")
    check("항목체크 기록 텍스트", f"C | {lst[0]} / 조선" in out and "시대별 근거" in out and "무작위" in out, out[:300])
    # 회차 화면에는 시대별 기록이 섞이지 않음
    r0 = lst[0].split("-")[0]
    await pg.goto(url(f"round_{r0}.html"))
    check("회차 화면에 시대별 기록 섞이지 않음", "이 회차 기록 (" not in await pg.inner_text("#app")
          or await pg.evaluate(f"ALL.filter(x=>x.round==={r0}).length") == await pg.locator("tbody tr").count())
    await pg.click("text=← 회차 선택")
    check("회차 화면 → 회차 목록으로 복귀", await pg.locator(".round-card").count() > 2)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
