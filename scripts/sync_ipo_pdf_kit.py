#!/usr/bin/env python3
"""
同步 docs 下每个“5位代码 空格 名称”目录的 IPO 五件套 PDF：
1) 检查现有 PDF 完整性与匹配性（pdftotext 关键字/代码/名称）
2) 对缺失或疑似错档，从 HKEX 披露易标题检索并下载
3) 统一命名到固定 5 个文件名
4) 生成/更新 README.md（文件名、HKEX 直链、抓取时间）

可重复运行（幂等）：已有且通过校验的文件不会重复下载。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests


HKEX_BASE = "https://www1.hkexnews.hk"
TITLESEARCH_PAGE = f"{HKEX_BASE}/search/titlesearch.xhtml?lang=zh&market=SEHK"
STOCK_PARTIAL = f"{HKEX_BASE}/search/partial.do"
TITLE_SERVLET = f"{HKEX_BASE}/search/titleSearchServlet.do"


@dataclass(frozen=True)
class TargetType:
    filename: str
    # 标题匹配优先用于检索
    title_patterns: Tuple[re.Pattern, ...]
    # PDF 文本内容校验
    text_patterns: Tuple[re.Pattern, ...]


TARGETS: Tuple[TargetType, ...] = (
    TargetType(
        filename="配發結果.pdf",
        title_patterns=(
            re.compile(r"配發結果"),
            re.compile(r"分配結果"),
            re.compile(r"結果公告"),
            re.compile(r"Allotment\s*Results", re.I),
            re.compile(r"Results\s*of\s*Allocation", re.I),
        ),
        text_patterns=(
            re.compile(r"配發結果"),
            re.compile(r"分配結果"),
            re.compile(r"香港公開發售"),
            re.compile(r"Allotment\s*Results", re.I),
        ),
    ),
    TargetType(
        filename="正式通告.pdf",
        # HKEX 对 IPO「正式通告」在标题检索里不一定写“正式通告/FORMAL NOTICE”，
        # 很多时候只会出现「全球發售 / Global Offering」等。
        title_patterns=(
            re.compile(r"正式通告"),
            re.compile(r"Formal\s*Notice", re.I),
            re.compile(r"全球發售"),
            re.compile(r"Global\s*Offering", re.I),
            re.compile(r"股份發售"),
            re.compile(r"Share\s*Offer", re.I),
        ),
        # 文本层也可能缺失“正式通告”关键字，因此宽松一些。
        text_patterns=(
            re.compile(r"正式通告"),
            re.compile(r"Formal\s*Notice", re.I),
            re.compile(r"全球發售"),
            re.compile(r"Global\s*Offering", re.I),
            re.compile(r"股份發售"),
            re.compile(r"Share\s*Offer", re.I),
        ),
    ),
    TargetType(
        filename="上市文件.pdf",
        title_patterns=(
            re.compile(r"上市文件"),
            re.compile(r"招股章程"),
            re.compile(r"全球發售"),
            re.compile(r"Prospectus", re.I),
        ),
        text_patterns=(
            re.compile(r"上市文件"),
            re.compile(r"招股章程"),
            re.compile(r"全球發售"),
            re.compile(r"Prospectus", re.I),
        ),
    ),
    TargetType(
        filename="穩價期終.pdf",
        title_patterns=(
            re.compile(r"穩定價格.*期.*結束"),
            re.compile(r"穩定價格行動.*結束"),
            re.compile(r"Stabilization\s*Period", re.I),
            re.compile(r"Stabili[sz]ation", re.I),
        ),
        text_patterns=(
            re.compile(r"穩定價格"),
            re.compile(r"穩定價格行動"),
            re.compile(r"Stabili[sz]ation", re.I),
        ),
    ),
    TargetType(
        filename="綠鞋悉行.pdf",
        title_patterns=(
            re.compile(r"超額配股權.*悉數.*行使"),
            re.compile(r"超額配股權.*行使"),
            re.compile(r"over-?allotment\s*option.*exercise", re.I),
            re.compile(r"over-?allotment", re.I),
        ),
        text_patterns=(
            re.compile(r"超額配股權"),
            re.compile(r"over-?allotment", re.I),
            re.compile(r"悉數行使"),
            re.compile(r"exercise", re.I),
        ),
    ),
)

CANONICAL_NAMES = tuple(t.filename for t in TARGETS)


def now_ts() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def simplify_name(name: str) -> str:
    # 去除常见后缀，便于宽松匹配
    n = name.strip()
    n = re.sub(r"[-－](B|H|W)$", "", n, flags=re.I)
    n = re.sub(r"\s+", "", n)
    return n


def run_pdftotext(pdf: Path, timeout: int = 60, pages: int = 8) -> str:
    """Extract text from first N pages (default 8).

    Many HKEX PDFs are large; for validation we only need the first few pages.
    """
    try:
        p = subprocess.run(
            [
                "pdftotext",
                "-f",
                "1",
                "-l",
                str(pages),
                "-enc",
                "UTF-8",
                str(pdf),
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return ""
    if p.returncode != 0:
        return ""
    txt = p.stdout or ""
    txt = txt.replace("\x00", " ")
    return txt


def has_code(text: str, code5: str) -> bool:
    """Best-effort stock code match.

    HKEX PDFs sometimes show stock code in different forms:
    - 5 digits: 08610
    - stripped: 8610 / 100
    - 4-digit zero-padded: 00470 -> 0470

    Strategy:
    1) try exact 5-digit with word boundary;
    2) try several compact variants against whitespace-stripped text, with digit-boundary guards.
    """

    code5 = str(code5).zfill(5)
    code_no0 = code5.lstrip("0") or code5
    variants = [code5, code_no0]

    # For 5-digit codes that become <=4 digits after stripping, also accept 4-digit zero-padded.
    if len(code_no0) <= 4:
        variants.append(code_no0.zfill(4))

    # 1) exact 5-digit word boundary
    if re.search(rf"\b{re.escape(code5)}\b", text):
        return True

    # 2) compact search
    compact = re.sub(r"\s+", "", text)
    for v in variants:
        if v == code5 and v in compact:
            return True
        # digit-boundary guard: allow non-digit boundaries too (e.g. "StockCode:0470")
        if re.search(rf"(?<!\d){re.escape(v)}(?!\d)", compact):
            return True
        if re.search(rf"(?:^|\D){re.escape(v)}(?:$|\D)", compact):
            return True

    return False


def _is_mostly_ascii(s: str) -> bool:
    if not s:
        return False
    ascii_cnt = sum(1 for ch in s if ord(ch) < 128)
    return ascii_cnt / max(1, len(s)) >= 0.9


def has_name(text: str, *names: str) -> bool:
    """Best-effort issuer name match.

    For Chinese names, allow 2~3-char prefix fallback (简繁/断字).
    For English/ASCII names, 2-char prefix is too weak (false positives like "BB"),
    so require >=4-char prefix fallback.
    """

    t = re.sub(r"\s+", "", text)
    for n in names:
        if not n:
            continue
        s = simplify_name(n)
        if not s:
            continue

        if s in t:
            return True

        if _is_mostly_ascii(s):
            # require stronger prefix
            if len(s) >= 4 and s[:4] in t:
                return True
            if len(s) >= 6 and s[:6] in t:
                return True
        else:
            if len(s) >= 2 and s[:2] in t:
                return True
            if len(s) >= 3 and s[:3] in t:
                return True

    return False


def target_text_match(text: str, target: TargetType) -> bool:
    return any(p.search(text) for p in target.text_patterns)


def filename_hint_score(filename: str, target: TargetType) -> int:
    base = filename.replace(".pdf", "")
    score = 0
    for p in target.title_patterns:
        if p.search(base):
            score += 2
    return score


def safe_jsonp_load(text: str) -> dict:
    m = re.search(r"^[^(]*\((.*)\);?\s*$", text, re.S)
    if not m:
        raise ValueError("invalid jsonp payload")
    return json.loads(m.group(1))


class HkexClient:
    def __init__(self, timeout: int = 30):
        self.s = requests.Session()
        self.timeout = timeout
        self._warmup_done = False

    def warmup(self):
        if self._warmup_done:
            return
        r = self.s.get(TITLESEARCH_PAGE, timeout=self.timeout)
        r.raise_for_status()
        self._warmup_done = True

    def resolve_stock(self, code5: str) -> Optional[dict]:
        self.warmup()
        params = {
            "lang": "ZH",
            "type": "A",
            "name": code5,
            "market": "SEHK",
            "callback": "callback",
        }
        r = self.s.get(STOCK_PARTIAL, params=params, timeout=self.timeout)
        r.raise_for_status()
        payload = safe_jsonp_load(r.text)
        infos = payload.get("stockInfo") or []
        for it in infos:
            if str(it.get("code", "")).zfill(5) == code5:
                return it
        return None

    def search_announcements(self, stock_id: int, row_range: int = 1000) -> List[dict]:
        # 与前端 titlesearch_research.js 参数保持一致
        today = dt.date.today().strftime("%Y%m%d")
        params = {
            "sortDir": "0",
            "sortByOptions": "DateTime",
            "category": "0",
            "market": "SEHK",
            "stockId": str(stock_id),
            "documentType": "-1",
            "fromDate": "19990401",
            "toDate": today,
            "title": "",
            "searchType": "0",
            "t1code": "-2",
            "t2Gcode": "-2",
            "t2code": "-2",
            "rowRange": str(row_range),
            "lang": "zh",
        }
        r = self.s.get(TITLE_SERVLET, params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        raw = data.get("result") or "[]"
        try:
            return json.loads(raw)
        except Exception:
            return []

    def download_pdf(self, url: str, dest: Path):
        r = self.s.get(url, timeout=90)
        r.raise_for_status()
        data = r.content
        if not data.startswith(b"%PDF"):
            raise ValueError(f"not a pdf: {url}")
        dest.write_bytes(data)


def absolutize_hkex_link(link: str) -> str:
    if link.startswith("http://") or link.startswith("https://"):
        return link
    return f"{HKEX_BASE}{link}"


def candidate_score(item: dict, target: TargetType, code5: str, names: List[str]) -> int:
    title = item.get("TITLE") or ""
    short_text = item.get("SHORT_TEXT") or ""
    stock_name = item.get("STOCK_NAME") or ""
    stock_code = str(item.get("STOCK_CODE") or "")
    blob = f"{title} {short_text}"

    score = 0
    for p in target.title_patterns:
        if p.search(title):
            score += 8
        if p.search(blob):
            score += 3

    if stock_code.zfill(5) == code5:
        score += 3
    if has_name(f"{title} {stock_name}", *names):
        score += 2

    # 轻微偏好中文公告（仓库文件多为 _c.pdf）
    file_link = (item.get("FILE_LINK") or "").lower()
    if file_link.endswith("_c.pdf"):
        score += 1

    return score


def pick_best(items: List[dict], target: TargetType, code5: str, names: List[str]) -> Optional[dict]:
    best = None
    best_score = -1
    for it in items:
        s = candidate_score(it, target, code5, names)
        if s > best_score:
            best_score = s
            best = it
    # 分数过低认为未命中
    if best is None or best_score < 8:
        return None
    return best


def classify_local_pdf(pdf: Path) -> Optional[TargetType]:
    text = run_pdftotext(pdf)
    if not text:
        # 退化到文件名猜测
        scores = [(filename_hint_score(pdf.name, t), t) for t in TARGETS]
        score, target = max(scores, key=lambda x: x[0])
        return target if score > 0 else None

    scored: List[Tuple[int, TargetType]] = []
    for t in TARGETS:
        s = 0
        if target_text_match(text, t):
            s += 3
        s += filename_hint_score(pdf.name, t)
        scored.append((s, t))
    score, target = max(scored, key=lambda x: x[0])
    return target if score > 0 else None


def file_md5(p: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def validate_pdf(
    pdf: Path,
    target: TargetType,
    code5: str,
    names: List[str],
    *,
    candidate_title: str = "",
) -> Tuple[bool, str]:
    """Validate a PDF against a target type.

    Notes:
    - Some HKEX PDFs are scanned / text layer is incomplete: keywords like "正式通告" may be missing
      from pdftotext output even when the document is correct.
    - For downloaded candidates, we can additionally trust the HKEX announcement title.
    """

    if not pdf.exists():
        return False, "missing"

    text = run_pdftotext(pdf)
    if not text.strip():
        # if title strongly matches, still treat as suspicious rather than hard-fail
        if candidate_title and any(p.search(candidate_title) for p in target.title_patterns):
            return True, "weak-title-only-pdftotext-empty"
        return False, "pdftotext-empty"

    type_ok = target_text_match(text, target)
    if not type_ok and candidate_title:
        # allow title-based type validation for scanned PDFs
        if any(p.search(candidate_title) for p in target.title_patterns):
            type_ok = True

    if not type_ok:
        return False, "type-keyword-miss"

    code_ok = has_code(text, code5)
    name_ok = has_name(text, *names)

    # Prefer code as anchor. For 配發結果, name-only is acceptable because many documents omit the stock code.
    if code_ok:
        return True, "ok-code"

    if name_ok:
        if target.filename == "配發結果.pdf":
            return True, "ok-name-only-allotment"
        return True, "weak-name-only"

    return False, "code-name-both-miss"


def render_readme(
    code5: str,
    name: str,
    fetched_at: str,
    entries: Dict[str, dict],
) -> str:
    lines = [
        f"# {code5} {name} — IPO PDF 五件套",
        "",
        "来源入口：<https://www.hkexnews.hk/index_c.htm>",
        "",
        "## 文件清单（含 HKEX 直链）",
    ]
    for t in TARGETS:
        e = entries.get(t.filename, {})
        url = e.get("url") or "(未找到)"
        title = e.get("title") or ""
        status = e.get("status") or "unknown"
        reason = e.get("reason") or ""
        md5 = e.get("md5") or ""
        lines.append(f"- `{t.filename}`")
        lines.append(f"  - 状态: {status}")
        if reason:
            lines.append(f"  - 备注: {reason}")
        if md5:
            lines.append(f"  - MD5: {md5}")
        lines.append(f"  - HKEX 直链: {url}")
        if title:
            lines.append(f"  - 匹配标题: {title}")

    lines += [
        "",
        "## 抓取信息",
        f"- 抓取时间: {fetched_at}",
        "- 维护工具: scripts/sync_ipo_pdf_kit.py",
        "",
        "## 说明",
        "- 若文件内容疑似不匹配（例如 PDF 不是该股票的公告），脚本会优先以 HKEX 标题检索结果为准下载替换，并在上方备注原因。",
    ]
    return "\n".join(lines)


def process_one_dir(
    d: Path,
    hkex: HkexClient,
    dry_run: bool = False,
    sleep_sec: float = 0.0,
) -> dict:
    m = re.match(r"^(\d{5})\s+(.+)$", d.name)
    if not m:
        return {"dir": d.name, "skipped": True, "reason": "name-not-match"}

    code5, dir_name = m.group(1), m.group(2).strip()
    result = {
        "dir": d.name,
        "code": code5,
        "name": dir_name,
        "downloaded": 0,
        "replaced": 0,
        "renamed": 0,
        "warnings": [],
        "errors": [],
    }

    stock = hkex.resolve_stock(code5)
    if not stock:
        result["errors"].append("stock-not-found-on-hkex")
        return result

    hkex_name = str(stock.get("name", "")).strip()
    names = [dir_name, hkex_name]

    # 先把目录下非标准命名 PDF 尝试归类并统一命名
    existing = list(d.glob("*.pdf"))
    canonical_set = set(CANONICAL_NAMES)
    for pdf in existing:
        if pdf.name in canonical_set:
            continue
        t = classify_local_pdf(pdf)
        if not t:
            continue
        target_path = d / t.filename
        if target_path.exists():
            continue
        if not dry_run:
            shutil.move(str(pdf), str(target_path))
        result["renamed"] += 1

    announcements = hkex.search_announcements(stock_id=int(stock["stockId"]))

    readme_entries: Dict[str, dict] = {}
    fetched_at = now_ts()

    for target in TARGETS:
        fp = d / target.filename

        candidate = pick_best(announcements, target, code5, names)
        candidate_url = None
        candidate_title = None
        if candidate:
            candidate_url = absolutize_hkex_link(candidate.get("FILE_LINK") or "")
            candidate_title = (candidate.get("TITLE") or "").strip()

        ok, why = validate_pdf(fp, target, code5, names, candidate_title=candidate_title or "")

        # Special case: for GEM listings, many "正式通告" are titled/typed as "股份發售".
        if (not ok) and target.filename == "正式通告.pdf" and (candidate_title or ""):
            if re.search(r"股份發售", candidate_title):
                ok = True
                why = "weak-title-shares-offer"

        status = "ok-local"
        if not ok:
            status = f"need-refresh:{why}"
            if candidate and candidate_url:
                tmp = None
                try:
                    if not dry_run:
                        with tempfile.NamedTemporaryFile(prefix="ipo-pdf-", suffix=".pdf", delete=False) as tf:
                            tmp = Path(tf.name)
                        hkex.download_pdf(candidate_url, tmp)

                        ok2, why2 = validate_pdf(tmp, target, code5, names, candidate_title=candidate_title or "")
                        if not ok2:
                            raise RuntimeError(f"downloaded-file-validate-failed:{why2}")

                        replaced = fp.exists()
                        shutil.move(str(tmp), str(fp))
                        tmp = None
                        result["downloaded"] += 1
                        if replaced:
                            result["replaced"] += 1
                        status = "downloaded"
                    else:
                        status = "would-download"
                except Exception as e:
                    result["errors"].append(f"{target.filename}: {e}")
                finally:
                    if tmp and tmp.exists():
                        tmp.unlink(missing_ok=True)
            else:
                result["warnings"].append(f"{target.filename}: no-candidate-found ({why})")

        md5 = file_md5(fp) if (not dry_run and fp.exists()) else ""
        readme_entries[target.filename] = {
            "status": status,
            "url": candidate_url,
            "title": candidate_title,
            "md5": md5,
        }

        if sleep_sec > 0:
            time.sleep(sleep_sec)

    # 输出 README
    readme_text = render_readme(code5, dir_name, fetched_at, readme_entries)
    if not dry_run:
        (d / "README.md").write_text(readme_text, encoding="utf-8")

    # 汇总最终缺失情况
    missing_now = [fn for fn in CANONICAL_NAMES if not (d / fn).exists()]
    if missing_now:
        result["warnings"].append("missing-after-sync: " + ", ".join(missing_now))

    return result


def list_target_dirs(docs_dir: Path) -> List[Path]:
    out = []
    for p in sorted(docs_dir.iterdir()):
        if p.is_dir() and re.match(r"^\d{5}\s+.+$", p.name):
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="同步 IPO 五件套 PDF")
    ap.add_argument("--repo", type=Path, default=Path.cwd(), help="仓库根目录")
    ap.add_argument("--docs", type=Path, default=None, help="docs 目录路径（默认 <repo>/docs）")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 个目录（调试用）")
    ap.add_argument("--code", type=str, default="", help="仅处理单个股票代码（5位）")
    ap.add_argument("--dry-run", action="store_true", help="只检查/演练，不落盘")
    ap.add_argument("--sleep", type=float, default=0.0, help="每个目标文件处理后 sleep 秒")
    ap.add_argument("--summary-json", type=Path, default=None, help="输出汇总 JSON 路径")
    args = ap.parse_args()

    repo = args.repo.resolve()
    docs_dir = (args.docs.resolve() if args.docs else (repo / "docs"))
    if not docs_dir.exists():
        print(f"docs dir not found: {docs_dir}", file=sys.stderr)
        return 2

    # 依赖检查
    if not shutil.which("pdftotext"):
        print("pdftotext 未安装，无法校验 PDF 文本", file=sys.stderr)
        return 2

    dirs = list_target_dirs(docs_dir)
    if args.code:
        dirs = [d for d in dirs if d.name.startswith(args.code + " ")]
    if args.limit and args.limit > 0:
        dirs = dirs[: args.limit]

    hkex = HkexClient(timeout=35)

    summary = {
        "started_at": now_ts(),
        "repo": str(repo),
        "docs": str(docs_dir),
        "total_dirs": len(dirs),
        "processed": 0,
        "downloaded": 0,
        "replaced": 0,
        "renamed": 0,
        "warnings": 0,
        "errors": 0,
        "items": [],
    }

    for d in dirs:
        r = process_one_dir(d, hkex=hkex, dry_run=args.dry_run, sleep_sec=args.sleep)
        summary["items"].append(r)
        if r.get("skipped"):
            continue
        summary["processed"] += 1
        summary["downloaded"] += r.get("downloaded", 0)
        summary["replaced"] += r.get("replaced", 0)
        summary["renamed"] += r.get("renamed", 0)
        summary["warnings"] += len(r.get("warnings", []))
        summary["errors"] += len(r.get("errors", []))

        if r.get("errors"):
            print(f"[ERR] {d.name}: {'; '.join(r['errors'])}")
        elif r.get("warnings"):
            print(f"[WARN] {d.name}: {'; '.join(r['warnings'])}")
        else:
            print(f"[OK] {d.name}")

    summary["finished_at"] = now_ts()

    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    print(json.dumps({k: v for k, v in summary.items() if k != "items"}, ensure_ascii=False, indent=2))

    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
