"""
import_explanations.py  (ver2 - 2026.09.30)
해설을 data/<회차>/문항.csv 의 해설 칸에 넣는다. 두 가지 입력을 받는다.

  1) 풀이 화면에서 작성한 해설 (ver2, 권장)
     웹앱 회차 화면의 "해설 파일 받기" 로 받은 한능검_해설_*.json
     - inbox/해설/ 과 이 PC 의 다운로드 폴더(~/Downloads)에서 자동으로 찾는다
     - 화면에서 직접 고친 것이므로 기존 해설을 덮어쓴다
     - 덮어쓰기 전 문항.csv 를 _archive/해설반영_<날짜시각>/ 에 복사해 둔다
  2) 해설 PDF (ver1) - 아래 규칙

  - 'NN회 NN번' 을 기준으로 해설을 나눈다. 앞의 큰 번호(1), 2) ...)는 무시한다.
  - 해설 칸이 이미 채워진 문항은 건너뛴다 (--force 로 덮어쓰기).
  - a. / i. / 1. 목록 기호는 들여쓰기 불릿으로 바꾼다.
  - 문항.csv 가 없는 회차의 해설은 반영하지 않고 목록만 보여 준다.

필요 패키지: pip install pymupdf
"""
import csv
import datetime
import glob
import json
import os
import re
import shutil
import sys

try:
    import pymupdf as fitz
except ImportError:
    print("패키지가 없습니다. 먼저 실행하세요:  pip install pymupdf")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(ROOT, "inbox", "해설")
DONE = os.path.join(INBOX, "done")
DATA = os.path.join(ROOT, "data")

HEAD = re.compile(r"(\d{2,3})\s*회\s*(\d{1,2})\s*번")
ROMAN = r"(?:i{1,3}|iv|v|vi{1,3}|ix|x)"


def clean_block(raw):
    raw = re.sub(r"\s*\d{1,2}\)\s*$", "", raw.strip())          # 다음 항목의 큰 번호 꼬리 제거
    raw = re.sub(rf"(?<!\n)(?=\b(?:[a-h]|{ROMAN}|\d{{1,2}})[.)]\s)", "\n", raw)  # 붙어 버린 목록 기호 분리
    out = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(rf"^({ROMAN})[.)]\s*(.*)$", s)
        if m:
            out.append("  - " + m.group(2)); continue
        m = re.match(r"^([a-h])[.)]\s*(.*)$", s)
        if m:
            out.append("• " + m.group(2)); continue
        m = re.match(r"^(\d{1,2})[.)]\s*(.*)$", s)
        if m:
            out.append("    · " + m.group(2)); continue
        if out and not s.startswith(("(", "-", "※")) and out[-1] and not out[-1].endswith(":"):
            out[-1] += " " + s                                    # 줄바꿈으로 끊긴 문장 잇기
        else:
            out.append(s)
    return "\n".join(out).strip()


def parse_pdf(path):
    doc = fitz.open(path)
    text = "\n".join(pg.get_text() for pg in doc)
    doc.close()
    marks = list(HEAD.finditer(text))
    items = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end]
        title = ""
        tm = re.match(r"^\s*(\([^)]*\)|-\s*[^\n]*)", body)   # (관등제도) 또는 - 고려시대 문제
        if tm:
            title = tm.group(1).strip("()- ").strip()
            body = body[tm.end():]
        exp = clean_block(body)
        if title:
            exp = f"[{title}]\n{exp}" if exp else title
        items[(int(m.group(1)), int(m.group(2)))] = exp
    return items


def find_json():
    pats = [os.path.join(INBOX, "*.json"), os.path.join(os.path.expanduser("~"), "Downloads", "한능검_해설_*.json")]
    return sorted({f for pat in pats for f in glob.glob(pat)}, key=os.path.getmtime)


def read_json(path):
    """{(회차, 번호): 해설}. 여러 파일이면 나중 파일이 이긴다 (호출 쪽에서 수정시각 순으로 읽음)."""
    with open(path, encoding="utf-8") as fp:
        d = json.load(fp)
    if not isinstance(d, dict) or d.get("type") != "hkh-explanations":
        raise ValueError("한능검 웹앱 해설 파일이 아닙니다")
    return {(int(x["round"]), int(x["n"])): str(x["text"]).strip() for x in d.get("items", [])}


def write_round(r, items, overwrite, stamp):
    path = os.path.join(DATA, str(r), "문항.csv")
    if not os.path.exists(path):
        print(f"  {r}회: 문항.csv 없음 - 반영 안 함 {sorted(items)}")
        return
    with open(path, encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))
    put, skip = [], []
    for row in rows:
        n = int(row["번호"])
        if n in items:
            if (row.get("해설") or "").strip() and not overwrite:
                skip.append(n)
            elif (row.get("해설") or "").strip() != items[n]:
                row["해설"] = items[n]
                put.append(n)
    if put:
        bak = os.path.join(ROOT, "_archive", f"해설반영_{stamp}", "data", str(r))
        os.makedirs(bak, exist_ok=True)
        shutil.copy2(path, os.path.join(bak, "문항.csv"))
        with open(path, "w", encoding="utf-8-sig", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=["번호", "정답", "배점", "시대", "검토필요", "해설"])
            w.writeheader()
            w.writerows(rows)
    print(f"  {r}회: 반영 {len(put)}개 {put}" + (f" / 기존 해설 있어 건너뜀 {skip}" if skip else ""))


def main():
    force = "--force" in sys.argv
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(INBOX, exist_ok=True)
    pdfs = [f for f in os.listdir(INBOX) if f.lower().endswith(".pdf")]
    jsons = find_json()
    if not pdfs and not jsons:
        print("반영할 해설이 없습니다. 웹앱에서 '해설 파일 받기' 를 누르거나, inbox/해설 에 PDF 를 넣으세요.")
        return 0

    # 1) 풀이 화면에서 작성한 해설 (덮어씀)
    found, used = {}, []
    for f in jsons:
        try:
            items = read_json(f)
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            print(f"  건너뜀: {os.path.basename(f)} ({e})")
            continue
        print(f"  {os.path.basename(f)}: 해설 {len(items)}개")
        found.update(items)
        used.append(f)
    by_round = {}
    for (r, n), x in found.items():
        by_round.setdefault(r, {})[n] = x
    for r in sorted(by_round):
        write_round(r, by_round[r], True, stamp)

    # 2) 해설 PDF (기존 해설이 있으면 건너뜀, --force 로 덮어쓰기)
    found = {}
    for f in pdfs:
        items = parse_pdf(os.path.join(INBOX, f))
        print(f"  {f}: 해설 {len(items)}개 인식")
        found.update(items)
    by_round = {}
    for (r, n), x in found.items():
        by_round.setdefault(r, {})[n] = x
    for r in sorted(by_round):
        write_round(r, by_round[r], force, stamp)

    os.makedirs(DONE, exist_ok=True)
    for f in [os.path.join(INBOX, x) for x in pdfs] + used:
        dst = os.path.join(DONE, os.path.basename(f))
        if os.path.exists(dst):
            base, ext = os.path.splitext(dst)
            dst = f"{base}_{stamp}{ext}"
        shutil.move(f, dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
