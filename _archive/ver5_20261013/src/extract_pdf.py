"""
extract_pdf.py  (ver2.1 - 2026.09.30, 단 마지막 문항 아래쪽 잘림 수정)
inbox/ 에 넣은 시험지 PDF(문제지 + 정답표)를 data/<회차>/ 로 추출한다.

  ver2: 텍스트 레이어 없는 문제지(글자가 그림·곡선으로 된 PDF)는 OCR 로 처리한다.
        - 문항 번호 위치: 각 단 왼쪽 여백의 잉크 덩어리를 찾고, 숫자만 OCR 해서 번호를 확인
        - 시대 분류용 텍스트: 문항 영역을 한국어 OCR (오탈자 많음 → 애매하면 검토필요=Y)
        - Tesseract + 한국어 데이터(kor)가 설치된 PC 에서만 동작. 없으면 안내 후 건너뜀
        - 번호를 50개 다 못 찾으면 추출하지 않고 누락 번호를 알려 준다 (사람이 PDF 확인)
  ver2: 정답표가 ①②③ 대신 숫자로 된 경우도 읽는다.
  ver2: 이미 추출된 회차의 PDF 도 done/ 으로 옮긴다.
  ver2: [47~48] 같은 공통 자료를 해당 문항 이미지 위에 붙인다.
  사용: python src/extract_pdf.py [--force] [--only 78] [--images-only]
        --images-only : 이미 추출된 회차의 이미지만 다시 만든다 (문항.csv 의 시대·해설은 건드리지 않음)

  - 파일명에 'NN회' 가 있어야 회차를 인식한다.
  - 파일명에 '문제' 가 있으면 문제지, '정답'/'답지'/'답안' 이 있으면 정답표.
  - 텍스트 레이어가 없는 스캔(이미지) PDF 는 문항 위치를 못 찾으므로 건너뛴다.
  - 이미 data/<회차>/문항.csv 가 있으면 덮어쓰지 않는다 (--force 로 강제).
  - 시대는 키워드로 자동 분류하고, 애매한 문항은 검토필요=Y 로 표시한다.
    엑셀로 문항.csv 를 열어 시대를 확인·수정한 뒤 검토필요 칸을 비우면 된다.

필요 패키지: pip install pymupdf pillow numpy   (+ OCR: Tesseract 프로그램, 한국어 데이터)
"""
import csv
import io
import os
import re
import shutil
import subprocess
import sys

try:
    import pymupdf as fitz
    from PIL import Image
    import numpy as np
except ImportError:
    print("패키지가 없습니다. 먼저 실행하세요:  pip install pymupdf pillow numpy")
    sys.exit(1)

from era_keywords import classify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(ROOT, "inbox")
DONE = os.path.join(INBOX, "done")
DATA = os.path.join(ROOT, "data")

# 페이지 좌표 (pt). 70·71·72·75·76·77회 문제지 기준 (729 x 1032 pt, 2단 편집)
LEFT_COL_END = 374
RIGHT_COL_END = 728
PAGE_BOTTOM = 985
DPI = 200
IMG_WIDTH = 700
JPEG_Q = 72
CIRCLED = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}


def find_problems(doc):
    found = {}
    for pno in range(len(doc)):
        for block in doc[pno].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    m = re.match(r"^(\d{1,2})\.$", span["text"].strip())
                    if m and span["size"] > 12:
                        n = int(m.group(1))
                        if 1 <= n <= 50 and n not in found:
                            found[n] = {"n": n, "page": pno, "x": span["bbox"][0], "y": span["bbox"][1]}
    return [found[k] for k in sorted(found)]


def region(p, allp):
    nxt = [q["y"] for q in allp if q["page"] == p["page"] and abs(q["x"] - p["x"]) < 20 and q["y"] > p["y"]]
    x0 = p["x"] - 8
    x1 = LEFT_COL_END if p["x"] < 200 else RIGHT_COL_END - 5
    y0 = p["y"] - 8
    y1 = (min(nxt) - 3) if nxt else PAGE_BOTTOM      # 글자 bbox 위쪽 여백이 있어 -8 이면 선지 마지막 줄 아래가 잘릴 수 있음 (72회 6번)
    return fitz.Rect(x0, y0, x1, y1)


def parse_answers(path):
    doc = fitz.open(path)
    text = "".join(pg.get_text() for pg in doc)
    doc.close()
    tokens = re.findall(r"[①②③④⑤]|\d+", text)
    ans, pts = {}, {}
    i = 0
    while i < len(tokens) - 2:
        t1, t2, t3 = tokens[i], tokens[i + 1], tokens[i + 2]
        if t2 in CIRCLED and t1 not in CIRCLED and t3 not in CIRCLED:
            n, p = int(t1), int(t3)
            if 1 <= n <= 50 and 1 <= p <= 3 and n not in ans:
                ans[n], pts[n] = CIRCLED[t2], p
                i += 3
                continue
        i += 1
    if len(ans) != 50:
        ans, pts = parse_answers_digits(text)
    return ans, pts


def parse_answers_digits(text):
    """정답이 ①② 가 아니라 숫자로 적힌 정답표 (예: 73회). '배점' 머리글 뒤를 (번호, 정답, 배점) 3개씩 읽는다."""
    body = text[text.rfind("배점") + 2:] if "배점" in text else text
    tokens = [int(t) for t in re.findall(r"\d+", body)]
    ans, pts = {}, {}
    for i in range(0, len(tokens) - 2, 3):
        n, a, p = tokens[i:i + 3]
        if not (1 <= n <= 50 and 1 <= a <= 5 and 1 <= p <= 3) or n in ans:
            break
        ans[n], pts[n] = a, p
    return ans, pts


# ---------------- OCR (텍스트 레이어 없는 문제지) ----------------
OCR_DPI = 200


def tesseract_ok():
    try:
        out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False, "Tesseract 가 설치되어 있지 않습니다"
    if "kor" not in (out.stdout + out.stderr).split():
        return False, "Tesseract 한국어 데이터(kor)가 없습니다"
    return True, ""


def ocr(img, lang, psm, digits=False):
    cmd = ["tesseract", "stdin", "stdout", "-l", lang, "--psm", str(psm)]
    if digits:
        cmd += ["-c", "tessedit_char_whitelist=0123456789."]
    buf = io.BytesIO()
    img.save(buf, "PNG")
    env = dict(os.environ, OMP_THREAD_LIMIT="1")          # 여러 개를 동시에 돌리므로 1스레드씩
    r = subprocess.run(cmd, input=buf.getvalue(), capture_output=True, timeout=120, env=env)
    return r.stdout.decode("utf-8", "ignore")


def gray(page):
    pix = page.get_pixmap(dpi=OCR_DPI, colorspace=fitz.csGRAY)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)


def first_ink(a):
    """단별로, 각 행에서 가장 왼쪽 잉크의 x(px) 목록."""
    h, w = a.shape
    ink = a < 128
    line = ink.mean(axis=0) > 0.3               # 단 구분 세로선(과 번진 가장자리 3px)은 제외
    for x in np.flatnonzero(line):
        ink[:, max(0, x - 3):x + 4] = False
    res = []
    for x0, x1 in ((0, w // 2), (w // 2, w)):
        sub = ink[int(h * 0.13):int(h * 0.95), x0:x1]
        res.append(np.array([x0 + int(np.argmax(r)) for r in sub if r.any() and r.sum() < (x1 - x0) * 0.5]))
    return res


def column_margins(firsts):
    """문항 번호의 x(px). 쪽마다 [왼단, 오른단].
    번호는 모든 쪽에서 같은 x 에 있고 그림 테두리는 그 쪽에만 있다는 점을 이용해,
    같은 홀짝 쪽의 60% 이상에서 15행 이상 나오는 가장 왼쪽 x 를 고른다."""
    out = [[None, None] for _ in firsts]
    for parity in (0, 1):
        pages = [i for i in range(len(firsts)) if i % 2 == parity]
        for c in (0, 1):
            arrs = [firsts[i][c] for i in pages if len(firsts[i][c])]
            if not arrs:
                continue
            for x in range(int(min(a.min() for a in arrs)), int(max(a.max() for a in arrs)) + 1):
                hit = sum(1 for a in arrs if ((a >= x) & (a <= x + 8)).sum() >= 15)
                if hit >= 0.6 * len(arrs):
                    for i in pages:
                        out[i][c] = max(0, x - 2)
                    break
    return out


def page_bottoms(grays):
    """쪽마다 본문 아래 끝(px) = 쪽 번호 상자 바로 위.
    아래쪽 15% 에서 단 구분 세로선을 뺀 잉크 행을 묶었을 때, 맨 아래 덩어리가 폭이 좁으면(쪽 번호 상자)
    그 위까지를 본문으로 본다. (2026-09-30 ver2.1: 홀짝 쪽 공통 행으로 찾던 방식은 본문 행까지 공통으로 잡아
    각 단 마지막 문항의 아래쪽이 잘렸다 → 78회 2번 등)"""
    out = []
    for a in grays:
        h, w = a.shape
        y0 = int(h * 0.85)
        ink = a[y0:] < 128
        line = (a < 128).mean(axis=0) > 0.3
        for x in np.flatnonzero(line):
            ink[:, max(0, x - 3):x + 4] = False
        ys = np.flatnonzero(ink.any(axis=1))
        b = int(h * 0.954)
        if len(ys):
            br = np.flatnonzero(np.diff(ys) > 15)
            top = ys[br[-1] + 1] if len(br) else ys[0]          # 맨 아래 덩어리의 시작 행
            xs = np.flatnonzero(ink[top:].any(axis=0))
            if len(br) and xs[-1] - xs[0] < w * 0.15:
                b = y0 + int(top) - 8
            else:
                b = h - 4                                         # 쪽 번호를 못 찾으면 자르지 않고 끝까지
        out.append(b)
    return out


def number_candidates(a, xm, top=0.05):
    """여백 x 부근 좁은 띠에서 글자 높이만 한 잉크 덩어리(세로 구간)를 찾는다."""
    rows = (a[:, xm:xm + 22] < 128).any(axis=1)
    orig = rows.copy()
    for gap in np.flatnonzero(~orig):           # 글자 속 8px 이하 틈('7' 의 꺾이는 부분 등)은 메움
        if orig[max(0, gap - 8):gap].any() and orig[gap + 1:gap + 9].any():
            rows[gap] = True
    out, y, h = [], int(a.shape[0] * top), a.shape[0]
    while y < h:
        if rows[y]:
            y0 = y
            while y < h and rows[y]:
                y += 1
            if 22 <= y - y0 <= 60:
                out.append((y0, y))
            elif y - y0 > 60:           # 번호 바로 아래 그림·상자가 붙은 경우: 덩어리 윗부분을 후보로 (OCR 로 확인)
                out.append((y0, y0 + 42))
        y += 1
    return out


def find_problems_ocr(doc):
    """[{n, page, x, y, col_end}] (pt 좌표). 번호를 OCR 로 확인한 것만 반환."""
    z = OCR_DPI / 72
    cands = []
    grays = [gray(doc[pno]) for pno in range(len(doc))]
    margins = column_margins([first_ink(a) for a in grays])
    bottoms = page_bottoms(grays)
    for pno in range(len(doc)):
        a = grays[pno]
        for ci, xm in enumerate(margins[pno]):
            if xm is None:
                continue
            for y0, y1 in number_candidates(a, xm, 0.13 if pno == 0 else 0.05):   # 1쪽은 큰 제목 아래부터
                crop = Image.fromarray(a[max(0, y0 - 8):y1 + 8, max(0, xm - 10):xm + 75])
                n = None
                for im in (crop, crop.resize((crop.width * 2, crop.height * 2))):
                    m = re.match(r"\s*(\d{1,2})\.", ocr(im, "eng", 7, digits=True))
                    if m and 1 <= int(m.group(1)) <= 50:
                        n = int(m.group(1))
                        break
                cands.append({"n": n, "page": pno, "x": xm / z, "y": y0 / z, "col": ci,
                              "bottom": bottoms[pno] / z})
    # 여러 쪽의 같은 자리에 반복되는 못 읽은 덩어리는 쪽 머리글(회차 제목 등)이므로 제외
    def repeated(c):
        return sum(1 for o in cands if not o["n"] and o["page"] != c["page"] and o["col"] == c["col"]
                   and abs(o["y"] - c["y"]) < 2) >= 2
    cands = [c for c in cands if c["n"] or not repeated(c)]
    # cands 는 (쪽, 단, 위→아래) 순서. 번호도 이 순서대로 1→50 이어야 한다.
    # 1) 순서와 맞는 번호만 확정 (가장 긴 증가 수열)
    idx = [i for i, c in enumerate(cands) if c["n"]]
    best = {}
    for i in idx:
        prev = [best[j] for j in best if j < i and cands[j]["n"] < cands[i]["n"]]
        best[i] = (max(prev, key=len) + [i]) if prev else [i]
    keep = set(max(best.values(), key=len)) if best else set()
    for i, c in enumerate(cands):
        if i not in keep:
            c["n"] = None
    # 2) 확정 번호 사이 빈 칸 수 = 빠진 번호 수 이면 순서대로 채움 (숫자를 못 읽은 경우, guess 표시)
    anchors = [(-1, 0)] + [(i, cands[i]["n"]) for i in sorted(keep)] + [(len(cands), 51)]
    for (i0, n0), (i1, n1) in zip(anchors, anchors[1:]):
        gap = cands[i0 + 1:i1]
        if gap and n1 - n0 - 1 == len(gap):
            for k, c in enumerate(gap):
                c["n"], c["guess"] = n0 + 1 + k, True
    ok = [c for c in cands if c["n"]]
    # 단 오른쪽 끝: 오른쪽 단은 페이지 끝, 왼쪽 단은 같은 쪽 오른쪽 단 여백 직전
    for p in ok:
        w = doc[p["page"]].rect.width
        right = [q["x"] for q in ok if q["page"] == p["page"] and q["col"] == 1]
        p["col_end"] = (min(right) - 6 if right else w / 2) if p["col"] == 0 else w - 8
    return ok


def region_ocr(p, allp, page):
    nxt = [q["y"] for q in allp if q["page"] == p["page"] and q["col"] == p["col"] and q["y"] > p["y"]]
    y1 = (min(nxt) - 8) if nxt else p["bottom"]
    return fitz.Rect(p["x"] - 8, p["y"] - 8, p["col_end"], y1)


def find_passages(doc, probs, rect_of, use_ocr):
    """[47~48] 처럼 여러 문항이 함께 보는 자료. 단의 첫 문항이 평소 단 시작 위치보다 한참 아래에 있으면
    그 위쪽이 공통 자료다. {문항번호: (쪽, Rect)} 반환. 범위는 [NN~MM] 을 읽고, 못 읽으면 그 단의 첫 2문항."""
    first = {}
    for p in probs:
        key = (p["page"], p.get("col", 0 if p["x"] < doc[p["page"]].rect.width / 2 else 1))
        if key not in first or p["y"] < first[key]["y"]:
            first[key] = p
    tops = sorted(p["y"] for (pg, _), p in first.items() if pg > 0)
    if not tops:
        return {}
    typical = tops[len(tops) // 2]
    res = {}
    for (pg, c), p in first.items():
        ref = min(q["y"] for (pg2, _), q in first.items() if pg2 == pg) if pg == 0 else typical
        if p["y"] - ref < 25:
            continue
        qr = rect_of(p)
        rect = fitz.Rect(qr.x0, ref - 8, qr.x1, p["y"] - 8)
        page = doc[pg]
        if use_ocr:
            pix = page.get_pixmap(clip=fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + 40), dpi=OCR_DPI)
            head = ocr(Image.open(io.BytesIO(pix.tobytes("png"))), "kor+eng", 6)
        else:
            head = page.get_text(clip=rect)
        m = re.search(r"\[\s*(\d{1,2})\s*[~∼～\-]\s*(\d{1,2})\s*\]", head)
        nums = range(int(m.group(1)), int(m.group(2)) + 1) if m else (p["n"], p["n"] + 1)
        for n in nums:
            res[n] = (pg, rect)
    return res


def extract_round(r, qpath, apath, force, images_only=False):
    out = os.path.join(DATA, str(r))
    csv_path = os.path.join(out, "문항.csv")
    if images_only and not os.path.exists(csv_path):
        print(f"  {r}회: --images-only 는 이미 추출된 회차에만 씁니다")
        return False
    if os.path.exists(csv_path) and not force and not images_only:
        print(f"  {r}회: 이미 있음 (data/{r}/문항.csv). 다시 만들려면 --force")
        return "exists"

    ans, pts = parse_answers(apath)
    if len(ans) != 50 or sum(pts.values()) != 100:
        print(f"  {r}회: 정답표 파싱 실패 (정답 {len(ans)}/50, 배점 합 {sum(pts.values())})")
        return False

    doc = fitz.open(qpath)
    probs = find_problems(doc)
    use_ocr = False
    if not probs:
        good, why = tesseract_ok()
        if not good:
            print(f"  {r}회: 텍스트 레이어 없는 PDF 입니다. OCR 필요 - {why}. 건너뜀")
            doc.close()
            return False
        print(f"  {r}회: 텍스트 레이어 없음 → OCR 로 처리합니다 (1~3분 걸림)")
        probs, use_ocr = find_problems_ocr(doc), True
    if len(probs) != 50:
        miss = sorted(set(range(1, 51)) - {p["n"] for p in probs})
        if not probs:
            print(f"  {r}회: 문항 번호를 찾지 못했습니다. 텍스트 레이어 없는 스캔 PDF 로 보입니다 - 자동 추출 불가")
        else:
            print(f"  {r}회: 문항 번호 {len(probs)}/50 만 찾음 (누락 {miss}) - 레이아웃이 다른 시험지일 수 있음")
        doc.close()
        return False

    os.makedirs(os.path.join(out, "img"), exist_ok=True)
    rows, review, imgs = [], [], {}
    rect_of = (lambda q: region_ocr(q, probs, doc[q["page"]])) if use_ocr else (lambda q: region(q, probs))
    passages = find_passages(doc, probs, rect_of, use_ocr)
    if passages:
        print(f"        공통 자료([NN~MM]) 를 붙인 문항: {sorted(passages)}")

    def render(pg, rect):
        pix = doc[pg].get_pixmap(clip=rect, dpi=DPI)
        return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

    for p in probs:
        page = doc[p["page"]]
        rect = rect_of(p)
        img = render(p["page"], rect)
        if p["n"] in passages:          # 공통 자료를 문항 위에 붙인다
            pimg = render(*passages[p["n"]])
            both = Image.new("RGB", (max(img.width, pimg.width), pimg.height + 20 + img.height), "white")
            both.paste(pimg, (0, 0))
            both.paste(img, (0, pimg.height + 20))
            img = both
        if img.width > IMG_WIDTH:
            img = img.resize((IMG_WIDTH, int(img.height * IMG_WIDTH / img.width)), Image.LANCZOS)
        img.save(os.path.join(out, "img", f"q{p['n']:02d}.jpg"), "JPEG", quality=JPEG_Q, optimize=True)
        imgs[p["n"]] = img if use_ocr else page.get_text(clip=rect)
    doc.close()
    if images_only:
        print(f"  {r}회: 이미지 50개만 다시 만들었습니다 (문항.csv 는 그대로)")
        return True
    if use_ocr:     # 한국어 OCR 은 느려서 동시에 여러 개 실행
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max(2, os.cpu_count() or 2)) as ex:
            texts = dict(zip(imgs, ex.map(lambda im: ocr(im, "kor", 6), imgs.values())))
    else:
        texts = imgs
    guessed = [p["n"] for p in probs if p.get("guess")]
    for p in probs:
        era, sure = classify(re.sub(r"\s+", " ", texts[p["n"]]))
        if not sure:
            review.append(p["n"])
        rows.append([p["n"], ans[p["n"]], pts[p["n"]], era, "" if sure else "Y", ""])

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["번호", "정답", "배점", "시대", "검토필요", "해설"])
        w.writerows(rows)

    rounds_csv = os.path.join(DATA, "rounds.csv")
    have = set()
    if os.path.exists(rounds_csv):
        with open(rounds_csv, encoding="utf-8-sig", newline="") as f:
            have = {int(x["회차"]) for x in csv.DictReader(f)}
    if r not in have:
        new = not os.path.exists(rounds_csv)
        with open(rounds_csv, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["회차", "시행일"])
            w.writerow([r, ""])
    print(f"  {r}회: 50문항 추출 완료{' (OCR)' if use_ocr else ''}. 시대 검토필요 {len(review)}문항 {review}")
    if guessed:
        print(f"        번호 숫자를 못 읽어 순서로 추정한 문항: {guessed} - 이미지 확인 권장")
    print(f"        data/rounds.csv 에 {r}회 시행일을 적어 주세요 (비워도 동작함).")
    return True


def main():
    force = "--force" in sys.argv
    images_only = "--images-only" in sys.argv
    only = None
    if "--only" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    os.makedirs(INBOX, exist_ok=True)
    pdfs = [f for f in os.listdir(INBOX) if f.lower().endswith(".pdf")]
    if not pdfs:
        print("inbox 폴더에 PDF 가 없습니다. 문제지와 정답표 PDF 를 넣고 다시 실행하세요.")
        return 0
    groups = {}
    for f in pdfs:
        m = re.search(r"(\d{2,3})\s*회", f)
        if not m:
            print(f"  건너뜀: {f} (파일명에 'NN회' 없음)")
            continue
        r = int(m.group(1))
        g = groups.setdefault(r, {})
        if "문제" in f:
            g["q"] = f
        elif any(k in f for k in ("정답", "답지", "답안")):
            g["a"] = f
        else:
            print(f"  건너뜀: {f} (문제지/정답표 구분 불가 - 파일명에 '문제' 또는 '정답' 을 넣으세요)")
    for r in sorted(groups):
        if only and r not in only:
            continue
        g = groups[r]
        if "q" not in g or "a" not in g:
            print(f"  {r}회: 문제지와 정답표가 둘 다 있어야 합니다 (현재 {list(g.values())})")
            continue
        ok = extract_round(r, os.path.join(INBOX, g["q"]), os.path.join(INBOX, g["a"]), force, images_only)
        if ok:
            os.makedirs(DONE, exist_ok=True)
            for f in (g["q"], g["a"]):
                shutil.move(os.path.join(INBOX, f), os.path.join(DONE, f))
    return 0


if __name__ == "__main__":
    sys.exit(main())
