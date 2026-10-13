"""
build.py  (ver1 - 2026.09.28)
data/ 의 회차별 문항.csv·이미지를 읽어 dist/ 에 웹앱을 생성한다.

  data/rounds.csv            회차,시행일
  data/<회차>/문항.csv       번호,정답,배점,시대,검토필요,해설
  data/<회차>/img/qNN.jpg    문항 이미지

생성물(dist/)은 직접 수정하지 않는다. 디자인은 src/template_*.html 만 고친다.
"""
import csv
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
DATA = os.path.join(ROOT, "data")
DIST = os.path.join(ROOT, "dist")

ERAS = ["전삼국", "삼국", "남북국", "고려", "조선", "개항기", "일제강점기", "해방이후", "미분류"]


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_round(r):
    """회차 1개 검증 후 문제 목록 반환. 오류가 있으면 (None, 오류목록)."""
    errors, warns = [], []
    path = os.path.join(DATA, str(r), "문항.csv")
    if not os.path.exists(path):
        return None, [f"{r}회: 문항.csv 없음"], warns
    rows = read_csv(path)
    probs = []
    for row in rows:
        try:
            n = int(row["번호"])
            a = int(row["정답"])
            p = int(row["배점"])
        except (ValueError, KeyError):
            errors.append(f"{r}회: 숫자가 아닌 값이 있는 행 {row}")
            continue
        era = (row.get("시대") or "").strip()
        if not 1 <= a <= 5:
            errors.append(f"{r}회 {n}번: 정답 {a} (1~5만 가능)")
        if era not in ERAS:
            errors.append(f"{r}회 {n}번: 시대 '{era}' 는 허용 목록에 없음 {ERAS}")
        img = os.path.join(DATA, str(r), "img", f"q{n:02d}.jpg")
        if not os.path.exists(img):
            errors.append(f"{r}회 {n}번: 이미지 없음 ({img})")
        if (row.get("검토필요") or "").strip():
            warns.append(f"{r}회 {n}번: 검토필요 표시 남아 있음")
        probs.append({"n": n, "a": a, "p": p, "e": era, "x": (row.get("해설") or "").strip()})
    nums = sorted(x["n"] for x in probs)
    if nums != list(range(1, 51)):
        errors.append(f"{r}회: 문항 번호가 1~50 이 아님 (현재 {len(nums)}개)")
    total = sum(x["p"] for x in probs)
    if total != 100:
        errors.append(f"{r}회: 배점 합계 {total} (100 이어야 함)")
    probs.sort(key=lambda x: x["n"])
    return (None if errors else probs), errors, warns


def sync_images(r):
    src = os.path.join(DATA, str(r), "img")
    dst = os.path.join(DIST, "data", str(r), "img")
    os.makedirs(dst, exist_ok=True)
    copied = 0
    for fn in os.listdir(src):
        s, d = os.path.join(src, fn), os.path.join(dst, fn)
        if not os.path.exists(d) or os.path.getmtime(s) > os.path.getmtime(d) or os.path.getsize(s) != os.path.getsize(d):
            shutil.copy2(s, d)
            copied += 1
    return copied


def main():
    rounds_csv = os.path.join(DATA, "rounds.csv")
    if not os.path.exists(rounds_csv):
        print("data/rounds.csv 가 없습니다.")
        return 1
    rounds = read_csv(rounds_csv)
    tpl_round = open(os.path.join(SRC, "template_round.html"), encoding="utf-8").read()
    tpl_index = open(os.path.join(SRC, "template_index.html"), encoding="utf-8").read()
    os.makedirs(os.path.join(DIST, "data"), exist_ok=True)

    built, failed = [], []
    for row in rounds:
        r = int(row["회차"])
        date = (row.get("시행일") or "").strip()
        probs, errors, warns = load_round(r)
        for w in warns:
            print(f"  [주의] {w}")
        if errors:
            failed.append(r)
            for e in errors:
                print(f"  [오류] {e}")
            continue
        payload = {"round": r, "date": date, "problems": probs}
        os.makedirs(os.path.join(DIST, "data", str(r)), exist_ok=True)
        with open(os.path.join(DIST, "data", str(r), "data.js"), "w", encoding="utf-8") as f:
            f.write("window.ROUND_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n")
        copied = sync_images(r)
        with open(os.path.join(DIST, f"round_{r}.html"), "w", encoding="utf-8") as f:
            f.write(tpl_round.replace("__ROUND__", str(r)))
        n_exp = sum(1 for p in probs if p["x"])
        print(f"  {r}회: 50문항 / 해설 {n_exp}개 / 이미지 {copied}개 갱신")
        built.append({"round": r, "date": date})

    with open(os.path.join(DIST, "data", "rounds.js"), "w", encoding="utf-8") as f:
        f.write("window.ROUNDS = " + json.dumps(built, ensure_ascii=False) + ";\n")
    with open(os.path.join(DIST, "index.html"), "w", encoding="utf-8") as f:
        f.write(tpl_index)

    print(f"\n완료: {len(built)}개 회차 생성" + (f" / 실패: {failed}" if failed else ""))
    print(f"열기: {os.path.join(DIST, 'index.html')}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
