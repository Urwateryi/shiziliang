#!/usr/bin/env python3
"""Extract 1800 chars (big char + word + sentence per row) from 洪恩识字 PDFs.

Strategy per page (5 rows):
 1. Full-page OCR at dpi 150 and 250 -> word/sentence text + big-char candidates (context helps Vision).
 2. Big char must appear in word (or sentence) to be accepted.
 3. Unresolved rows: OCR the red tracing band (13 copies -> vote) and the big cell at several dpi.
 4. Rows still unresolved are flagged; cell images saved to review/ for manual check.
"""
import sys, os, json
from collections import Counter
import fitz
import Vision, Quartz
from Foundation import NSData

TOP, BOTTOM, NROWS = 0.095, 0.958, 5

def ocr_png_bytes(png_bytes):
    data = NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
    src = Quartz.CGImageSourceCreateWithData(data, None)
    cgimg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(["zh-Hans"])
    req.setUsesLanguageCorrection_(False)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cgimg, None)
    handler.performRequests_error_([req], None)
    out = []
    if req.results():
        for obs in req.results():
            cand = obs.topCandidates_(1)
            if not cand or not len(cand):
                continue
            bb = obs.boundingBox()
            out.append({"text": str(cand[0].string()), "conf": float(cand[0].confidence()),
                        "x": bb.origin.x, "y": bb.origin.y, "w": bb.size.width, "h": bb.size.height})
    return out

def is_cjk(ch):
    return len(ch) == 1 and ('\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf')

def clean_label(s, leading):
    while s and s[0] in leading:
        s = s[1:]
    return s

def row_band(pr, ri):
    rowh = (BOTTOM - TOP) / NROWS
    y0 = pr.height * (TOP + ri * rowh)
    y1 = pr.height * (TOP + (ri + 1) * rowh)
    return y0, y1

def page_pass(page, dpi):
    """Full page OCR -> per-row: char votes, word tokens, sent tokens."""
    pix = page.get_pixmap(dpi=dpi)
    obs = ocr_png_bytes(pix.tobytes("png"))
    rowh = (BOTTOM - TOP) / NROWS
    rows = [{"votes": Counter(), "word": [], "sent": []} for _ in range(NROWS)]
    for o in obs:
        cy = 1.0 - (o["y"] + o["h"] / 2)
        cx = o["x"] + o["w"] / 2
        if cy < TOP or cy > BOTTOM:
            continue
        ri = min(NROWS - 1, max(0, int((cy - TOP) / rowh)))
        frac = ((cy - TOP) % rowh) / rowh
        t = o["text"].strip()
        if cx < 0.17:
            # big char zone
            for ch in t:
                if is_cjk(ch):
                    rows[ri]["votes"][ch] += 3 if o["conf"] >= 0.5 else 1
        elif frac < 0.42:
            if t in ("词", "句", "旬", "甸"):
                continue
            if cx < 0.34:
                rows[ri]["word"].append((o["x"], t))
            else:
                rows[ri]["sent"].append((o["x"], t))
    return rows

def red_band_votes(page, ri):
    pr = page.rect
    y0, y1 = row_band(pr, ri)
    clip = fitz.Rect(pr.width * 0.17, y0 + (y1 - y0) * 0.40, pr.width * 0.99, y0 + (y1 - y0) * 0.74)
    c = Counter()
    for dpi in (200, 300):
        obs = ocr_png_bytes(page.get_pixmap(dpi=dpi, clip=clip).tobytes("png"))
        for o in obs:
            for ch in o["text"]:
                if is_cjk(ch):
                    c[ch] += 1
    return c

def cell_votes(page, ri):
    pr = page.rect
    y0, y1 = row_band(pr, ri)
    clip = fitz.Rect(pr.width * 0.012, y0, pr.width * 0.172, y0 + (y1 - y0) * 0.72)
    c = Counter()
    for dpi in (120, 200, 300):
        obs = ocr_png_bytes(page.get_pixmap(dpi=dpi, clip=clip).tobytes("png"))
        for o in obs:
            t = o["text"].strip()
            if len(t) == 1 and is_cjk(t):
                c[t] += 2 if o["conf"] >= 0.8 else 1
    return c

def save_cell_image(page, ri, out_path):
    pr = page.rect
    y0, y1 = row_band(pr, ri)
    clip = fitz.Rect(pr.width * 0.012, y0, pr.width * 0.172, y0 + (y1 - y0) * 0.72)
    page.get_pixmap(dpi=150, clip=clip).save(out_path)

def resolve_row(page, ri, votes, word, sent):
    """Return (char, method). Char must appear in word (or sentence) when possible."""
    context = word + sent
    def pick(counter):
        in_ctx = [(n, ch) for ch, n in counter.items() if ch in context]
        if in_ctx:
            return max(in_ctx)[1]
        return None
    # 1. page-level votes validated by context
    ch = pick(votes)
    if ch:
        return ch, "page"
    # 2. red tracing band
    rv = red_band_votes(page, ri)
    ch = pick(rv)
    if ch and rv[ch] >= 3:
        return ch, "red"
    # 3. big cell multi-dpi
    cv = cell_votes(page, ri)
    ch = pick(cv)
    if ch:
        return ch, "cell"
    # 4. unvalidated best guess from any source
    allv = votes + rv + cv
    if allv:
        return allv.most_common(1)[0][0], "guess"
    return "", "none"

def process_pdf(path, review_dir):
    doc = fitz.open(path)
    out = []
    for pno in range(doc.page_count):
        page = doc[pno]
        rows150 = page_pass(page, 150)
        rows250 = page_pass(page, 250)
        for ri in range(NROWS):
            votes = rows150[ri]["votes"] + rows250[ri]["votes"]
            wtok = rows150[ri]["word"] if len(rows150[ri]["word"]) >= len(rows250[ri]["word"]) else rows250[ri]["word"]
            stok = rows150[ri]["sent"] if len("".join(t for _, t in rows150[ri]["sent"])) >= len("".join(t for _, t in rows250[ri]["sent"])) else rows250[ri]["sent"]
            word = clean_label("".join(t for _, t in sorted(wtok)), "词司")
            sent = clean_label("".join(t for _, t in sorted(stok)), "句旬甸")
            # empty row (e.g. incomplete last page)
            if not word and not sent and not votes:
                continue
            ch, method = resolve_row(page, ri, votes, word, sent)
            flagged = method in ("guess", "none") or ch == "" or (ch not in word + sent)
            rec = {"pdf": os.path.basename(path), "page": pno + 1, "row": ri + 1,
                   "char": ch, "word": word, "sent": sent, "method": method, "flagged": flagged}
            if flagged:
                img = os.path.join(review_dir, f"{os.path.basename(path)}_p{pno+1}_r{ri+1}.png")
                save_cell_image(page, ri, img)
                rec["img"] = img
            out.append(rec)
        line = " | ".join(f"{r['char']}{'?' if r['flagged'] else ''}" for r in out[-NROWS:])
        print(f"{os.path.basename(path)} p{pno+1}: {line}", file=sys.stderr, flush=True)
    return out

if __name__ == "__main__":
    out_file = sys.argv[1]
    review_dir = os.path.join(os.path.dirname(out_file) or ".", "review")
    os.makedirs(review_dir, exist_ok=True)
    all_rows = []
    for path in sys.argv[2:]:
        all_rows.extend(process_pdf(path, review_dir))
    json.dump(all_rows, open(out_file, "w"), ensure_ascii=False, indent=1)
    n_flag = sum(1 for r in all_rows if r["flagged"])
    chars = [r["char"] for r in all_rows]
    dups = [c for c, n in Counter(chars).items() if n > 1 and c]
    print(f"total rows: {len(all_rows)}, flagged: {n_flag}, dup chars: {dups}", file=sys.stderr)
