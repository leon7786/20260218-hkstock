#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "index.html"
DOCS = ROOT / "docs"


@dataclass
class Extracted:
    hit_rate: Optional[float] = None
    public_oversub: Optional[float] = None
    placing_oversub: Optional[float] = None


def to_text(pdf: Path, *, pages: int = 12) -> str:
    # 只提取前 N 页，避免把 Next Day Disclosure Return 等后续公告混进来
    cp = subprocess.run(
        ["pdftotext", "-f", "1", "-l", str(pages), "-enc", "UTF-8", str(pdf), "-"],
        capture_output=True,
        text=True,
    )
    if cp.returncode != 0:
        return ""
    return cp.stdout or ""


_NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?")


def parse_num(s: str) -> Optional[float]:
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except Exception:
        return None


def pick_last_number(s: str) -> Optional[float]:
    """Pick the last well-formatted number in a snippet.

    Useful when OCR concatenates multiple columns (e.g. 236,078 71,945 2,682.35倍).
    """
    nums = _NUM_RE.findall(s)
    if not nums:
        return None
    return parse_num(nums[-1])


def slice_between(text: str, start_pat: re.Pattern, end_pats: list[re.Pattern]) -> Optional[str]:
    m = start_pat.search(text)
    if not m:
        return None
    start = m.start()
    end = len(text)
    for ep in end_pats:
        m2 = ep.search(text, m.end())
        if m2:
            end = min(end, m2.start())
    return text[start:end]


def extract_hit_rate_one_lot(text: str) -> Optional[float]:
    # 统一做 compact（去空白），以应对 pdftotext 把中文拆字。
    compact = re.sub(r"\s+", "", text)

    def _parse_int(s: str) -> Optional[int]:
        s = s.replace(",", "").strip()
        if not s.isdigit():
            return None
        try:
            return int(s)
        except Exception:
            return None

    # 1) 显式「一手中签率」
    for pat in [
        r"一手(?:中[籤签]率|獲配發比率|配發比率|分配比率|中[签籤]率)?[^\d%]{0,40}([0-9]+(?:\.[0-9]+)?)\s*%",
        r"一手(?:中[籤签]率|獲配發比率|配發比率|分配比率|中[签籤]率)?[^\d%]{0,40}([0-9]+(?:\.[0-9]+)?)%",  # compact
    ]:
        m = re.search(pat, text, flags=re.IGNORECASE) or re.search(pat, compact, flags=re.IGNORECASE)
        if m:
            v = parse_num(m.group(1))
            if v is not None and 0 <= v <= 100:
                return v

    # 2) 甲组表格首档（通常一手）「X名中的Y名獲得Z股」
    sec = slice_between(
        compact,
        re.compile(r"甲組"),
        [re.compile(r"乙組"), re.compile(r"國際"), re.compile(r"国际"), re.compile(r"International", re.I)],
    )
    blob = sec or compact

    # We should take the FIRST valid row after 甲組, not a greedy match that swallows many numbers.
    pat = re.compile(
        r"([0-9]{1,3}(?:,[0-9]{3})*)名中(?:的)?([0-9]{1,3}(?:,[0-9]{3})*)名獲(?:得|配發|發)([0-9]{1,3}(?:,[0-9]{3})*)股"
    )
    for m in pat.finditer(blob):
        total = _parse_int(m.group(1))
        success = _parse_int(m.group(2))
        if total and success is not None and total > 0:
            v = success / total * 100.0
            if 0 <= v <= 100:
                return v

    # 3) 兜底：甲组「概约百分比」列第一项
    m = re.search(r"獲配發股份佔所申請[\s\S]{0,200}?概約百分比[\s\S]{0,400}?([0-9]+(?:\.[0-9]+)?)%", blob)
    if m:
        v = parse_num(m.group(1))
        if v is not None and 0 <= v <= 100:
            return v

    return None


def _extract_section_subscription_level_times(text: str, *, section: str) -> Optional[float]:
    """Extract "Subscription Level ... xx.xx times" within a specific section.

    We intentionally require a nearby 'Subscription Level' label to avoid capturing generic
    narrative thresholds like '15 times ... less than 50 times'.
    """

    # Work on a whitespace-collapsed variant for robustness.
    compact = re.sub(r"\s+", " ", text)

    if section == "hk":
        # STRICT anchor: only start from the allotment-results table.
        start_pat = re.compile(
            r"ALLOTMENT\s*RESULTS\s*DETAILS",
            re.I,
        )
    elif section == "intl":
        # We will first locate ALLOTMENT RESULTS DETAILS, then search within that region for INTERNATIONAL OFFER/OFFERING.
        start_pat = re.compile(r"ALLOTMENT\s*RESULTS\s*DETAILS", re.I)
    else:
        return None

    m = start_pat.search(compact)
    if not m:
        return None

    seg = compact[m.start() : m.start() + 6000]

    # 1) Preferred: explicit "Subscription Level" row
    # We want the subscription level that belongs to THIS section.
    # For HK: the first 'Subscription level' in PUBLIC OFFER table.
    # For Intl: the first 'Subscription Level' after INTERNATIONAL OFFER table label.

    if section == "hk":
        # PUBLIC OFFER table: capture the first times value after the 'Subscription level' label.
        # PUBLIC OFFER table: between the label and the next section marker, take the first times.
        m2 = re.search(
            r"PUBLIC\s*OFFER[\s\S]{0,1200}?Subscription\s*level[\s\S]{0,600}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*times",
            seg,
            flags=re.I,
        )
        if m2:
            # This regex can still jump to the next 'times' (e.g. Intl 2.68). Guard by cutting at INTERNATIONAL OFFER.
            block = seg
            cut = re.search(r"INTERNATIONAL\s*OFFER\b", block, flags=re.I)
            if cut:
                block = block[: cut.start()]
            # take first times in the PUBLIC OFFER block
            nums = re.findall(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*times", block, flags=re.I)
            if nums:
                return pick_last_number(nums[0])

        idx = seg.lower().find("subscription level")
        if idx != -1:
            win = seg[idx : idx + 600]
            nums = re.findall(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*times", win, flags=re.I)
            if nums:
                return pick_last_number(nums[0])

    if section == "intl":
        # Narrow to the International table inside allotment results details.
        mi = re.search(r"INTERNATIONAL\s*OFFER(?:ING)?\b", seg, flags=re.I)
        if not mi:
            return None
        seg2 = seg[mi.start() : mi.start() + 2500]
        idx = seg2.lower().find("subscription level")
        if idx != -1:
            win = seg2[idx : idx + 1200]
            nums = re.findall(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*times", win, flags=re.I)
            if nums:
                return pick_last_number(nums[0])
        return None

    return None

    return None


def extract_from_text(text: str) -> Extracted:
    out = Extracted()

    # 为应对 pdftotext 把中文拆成“香 港 交 易 …”，我们同时对去空白版本做匹配。
    compact = re.sub(r"\s+", "", text)

    # 1) 一手中签率（raw + compact）
    out.hit_rate = extract_hit_rate_one_lot(text)
    if out.hit_rate is None:
        out.hit_rate = extract_hit_rate_one_lot(compact)

    # 2) 香港公开发售超购倍数
    # 只在明确语境（公开发售 + 超额认购/超购/认购水平/over-subscribed）下提取。

    # Prefer anchor on "香港公開發售" (not just "公開發售") to avoid matching other contexts.
    if out.public_oversub is None:
        m = re.search(
            r"香港公開發售[\s\S]{0,240}?(?:超額認購|超额认购|超購|超购|認購水平|认购水平|認購額|认购额)[\s\S]{0,80}?(?:約|约)?([0-9][0-9,]*(?:\.[0-9]+)?)倍",
            compact,
        )
        if m:
            out.public_oversub = pick_last_number(m.group(1))

    # Table-only fallback: anchor on "香港公開發售" then only look after the "認購水平" row.
    if out.public_oversub is None:
        idx = compact.find("香港公開發售")
        if idx != -1:
            seg = compact[idx : idx + 2200]
            j = seg.find("認購水平")
            seg2 = seg[j : j + 600] if j != -1 else seg
            nums = re.findall(r"([0-9][0-9,]*(?:\.[0-9]+)?)倍", seg2)
            if nums:
                out.public_oversub = pick_last_number(nums[-1])

    # Extra fallback for Chinese "香港公開發售...認購水平...倍"
    if out.public_oversub is None:
        pub_m = re.search(
            r"香港公開發售[\s\S]{0,800}?認購水平[\s\S]{0,80}?([0-9][0-9,]*(?:\.[0-9]+)?)倍",
            compact,
        )
        if pub_m:
            out.public_oversub = pick_last_number(pub_m.group(1))

    if out.public_oversub is None:
        m = re.search(
            r"Hong\s*Kong\s*Public\s*Offering[\s\S]{0,400}?over\-?subscribed[\s\S]{0,120}?(?:approximately\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)\s*times",
            text,
            flags=re.IGNORECASE,
        )
        if m:
            out.public_oversub = pick_last_number(m.group(1))

    # 不再使用“全文第一个 xxx倍”兜底：误判风险过高（可能来自别的段落/表格/引用）。

    # 3) 配售超购 = International Offering oversubscription
    if out.placing_oversub is None:
        # Prefer explicit '國際發售 ... 超額認購/認購水平/認購額 ... 倍'
        m = re.search(
            r"(?:國際發售|国际发售|國際配售|国际配售|InternationalOffering)[\s\S]{0,260}?(?:超額認購|超额认购|超購|超购|認購水平|认购水平|認購額|认购额)[\s\S]{0,80}?(?:約|约)?([0-9][0-9,]*(?:\.[0-9]+)?)倍",
            compact,
            flags=re.IGNORECASE,
        )
        if m:
            v = pick_last_number(m.group(1))
            # sanity: international placing oversub is rarely in the thousands; huge values are usually HK public oversub
            if v is not None and v > 500:
                v = None
            out.placing_oversub = v
        else:
            # Table-only fallback: avoid mis-reading HK public oversub within the Intl section.
            # Prefer numbers that appear AFTER the "國際發售" block AND close to the "認購水平" row.
            idx = compact.find("國際發售")
            if idx != -1:
                seg = compact[idx : idx + 2000]
                # If we can anchor on "認購水平" within the International block, only look after it.
                j = seg.find("認購水平")
                if j != -1:
                    seg2 = seg[j : j + 600]
                else:
                    seg2 = seg
                nums = re.findall(r"([0-9][0-9,]*(?:\.[0-9]+)?)倍", seg2)
                if nums:
                    out.placing_oversub = pick_last_number(nums[-1])
            else:
                m = re.search(
                    r"International\s*Offering[\s\S]{0,300}?over\-?subscribed[\s\S]{0,120}?(?:approximately\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)\s*times",
                    text,
                    flags=re.IGNORECASE,
                )
                if m:
                    out.placing_oversub = parse_num(m.group(1))

    # If text clearly states no oversubscription, set placing_oversub=0.0
    if out.placing_oversub is None and re.search(r"並無超額分配|没有超额分配|無超額分配", compact):
        out.placing_oversub = 0.0

    # 4) 英文表格兜底（带语境 + Subscription Level）：
    # - 公开：Hong Kong Public Offering / Subscription Level / xx times
    # - 国际：International Offering / Subscription Level / xx times

    if out.public_oversub is None:
        v = _extract_section_subscription_level_times(text, section="hk")
        if v is not None:
            out.public_oversub = v

    if out.placing_oversub is None:
        v = _extract_section_subscription_level_times(text, section="intl")
        if v is not None:
            out.placing_oversub = v

    # 5) 中文双「認購水平」兜底（带语境）：
    # - 公开：必须出现「香港公開發售 ... 認購水平 ... 倍」
    # - 国际：必须出现「國際發售/International Offering ... 認購水平 ... 倍」

    if out.public_oversub is None:
        m = re.search(r"香港公開發售[\s\S]{0,200}?認購水平[\s\S]{0,60}?([0-9][0-9,]*(?:\.[0-9]+)?)倍", compact)
        if m:
            out.public_oversub = pick_last_number(m.group(1))

    if out.placing_oversub is None:
        m = re.search(
            r"(?:國際發售|国际发售|國際配售|国际配售|InternationalOffering)[\s\S]{0,220}?認購水平[\s\S]{0,60}?([0-9][0-9,]*(?:\.[0-9]+)?)倍",
            compact,
            flags=re.IGNORECASE,
        )
        if m:
            v = pick_last_number(m.group(1))
            if v is not None and v > 500:
                v = None
            out.placing_oversub = v

    return out


def fmt_percent(v: float) -> str:
    # 一手中签率保留 1 位小数
    return f"{v:.1f}%"


def fmt_times(v: float) -> str:
    # keep 1 decimal (user requirement) and avoid absurd OCR numbers
    if v is None:
        return "—"
    if v < 0:
        return "—"
    if v > 100000:
        return "—"
    return f"{v:.1f}倍"


def _parse_cell_number(s: str) -> Optional[float]:
    s = (s or "").strip()
    if not s or s == "—":
        return None
    s = s.replace(",", "")
    s = s.replace("倍", "").replace("%", "").strip()
    try:
        return float(s)
    except Exception:
        return None


def has_missing(td) -> bool:
    """Cell is considered missing if:
    - it's '—'
    - or it contains an obviously invalid value (OCR garbage), so we allow overwrite.
    """

    t = td.get_text(strip=True)
    if t == "—" or t == "":
        return True

    v = _parse_cell_number(t)
    if v is None:
        return True

    if t.endswith("%"):
        return not (0 <= v <= 100)

    if t.endswith("倍"):
        # allow 0.00倍 (explicitly no oversub), but cap upper bound
        return not (0 <= v < 100000)

    # unknown format
    return True


def find_dir_by_code(code: str) -> Optional[Path]:
    ms = sorted([p for p in DOCS.iterdir() if p.is_dir() and p.name.startswith(code + " ")])
    return ms[0] if ms else None


def _code_variants(code: str) -> list[str]:
    c5 = code.strip().zfill(5)
    out: set[str] = {c5}
    try:
        n = int(c5)
        out.add(str(n))
        out.add(str(n).zfill(4))
    except Exception:
        pass
    out.add(c5[-4:])
    return sorted(v for v in out if v)


def _name_keys(name: str) -> list[str]:
    keys: list[str] = []

    zh = "".join(re.findall(r"[\u4e00-\u9fff]", name))
    if len(zh) >= 3:
        keys.append(zh[:3])
    if len(zh) >= 2:
        keys.append(zh[:2])

    # 英文前缀：至少 4 字母
    ascii_words = re.findall(r"[A-Za-z]{4,}", name)
    if ascii_words:
        keys.append(ascii_words[0][:4].upper())
    joined = "".join(re.findall(r"[A-Za-z]", name)).upper()
    if len(joined) >= 4:
        keys.append(joined[:4])

    # 去重保序
    seen = set()
    uniq: list[str] = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def identity_ok(text: str, code: str, name: str) -> tuple[bool, str]:
    code_vars = _code_variants(code)
    name_keys = _name_keys(name)

    for cv in code_vars:
        if re.search(rf"(?<!\d){re.escape(cv)}(?!\d)", text):
            return True, f"code={cv}"

    upper = text.upper()
    for nk in name_keys:
        if nk.isascii():
            if nk in upper:
                return True, f"name={nk}"
        else:
            if nk in text:
                return True, f"name={nk}"

    return False, f"code_vars={code_vars};name_keys={name_keys}"


def count_missing_rows(soup: BeautifulSoup) -> int:
    n = 0
    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        if has_missing(tds[2]) or has_missing(tds[4]) or has_missing(tds[5]):
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="本次最多扫描多少只缺失股票（0=不限）")
    ap.add_argument("--update-limit", type=int, default=0, help="本次最多实际更新多少只（0=不限，用于每10只一批）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", type=Path, default=ROOT / "reports" / "fill_index_from_allotment_pdf_last.txt")
    args = ap.parse_args()

    soup = BeautifulSoup(INDEX.read_text(encoding="utf-8"), "html.parser")
    rows = soup.select("table tbody tr")

    missing_before = count_missing_rows(soup)
    scanned = 0
    touched = 0
    processed_codes: list[str] = []
    missing_codes: list[str] = []
    logs: list[str] = []

    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        code = tds[1].get_text(strip=True).zfill(5)
        name = tds[8].get_text(strip=True) if len(tds) > 8 else ""
        td_hit, td_place, td_public = tds[2], tds[4], tds[5]

        if not (has_missing(td_hit) or has_missing(td_place) or has_missing(td_public)):
            continue

        missing_codes.append(code)

        # scan limit (how many missing rows we examine)
        if args.limit and scanned >= args.limit:
            continue
        scanned += 1

        # update limit (how many rows we actually modify)
        if args.update_limit and touched >= args.update_limit:
            continue

        d = find_dir_by_code(code)
        if not d:
            logs.append(f"{code}: 未找到目录")
            continue
        pdf = d / "配發結果.pdf"
        if not pdf.exists():
            logs.append(f"{code}: 缺少配發結果.pdf")
            continue

        txt = to_text(pdf)
        if not txt.strip():
            logs.append(f"{code}: pdftotext 失败或空文本")
            continue

        ok, why = identity_ok(txt, code, name)
        if not ok:
            logs.append(f"{code}: 身份校验失败，不更新 ({why})")
            continue

        ex = extract_from_text(txt)

        # Sanity checks: drop suspicious values
        if ex.hit_rate is not None:
            if not (0 <= ex.hit_rate <= 100):
                ex.hit_rate = None

        for k in ("public_oversub", "placing_oversub"):
            v = getattr(ex, k)
            if v is None:
                continue
            # oversub times can be 0.0 (explicitly "并无超额分配"), otherwise must be positive.
            if not (0 <= v < 100000):
                setattr(ex, k, None)

        row_changed = False

        if has_missing(td_hit) and ex.hit_rate is not None:
            v = fmt_percent(ex.hit_rate)
            td_hit["data-sort"] = v
            td_hit.string = v
            row_changed = True

        if has_missing(td_public) and ex.public_oversub is not None:
            v = fmt_times(ex.public_oversub)
            td_public["data-sort"] = v
            td_public.string = v
            row_changed = True

        if has_missing(td_place) and ex.placing_oversub is not None:
            v = fmt_times(ex.placing_oversub)
            td_place["data-sort"] = v
            td_place.string = v
            row_changed = True

        if row_changed:
            touched += 1
            processed_codes.append(code)
            logs.append(
                f"{code}: 命中[{why}] hit={ex.hit_rate} public={ex.public_oversub} placing={ex.placing_oversub}"
            )
        else:
            logs.append(f"{code}: 身份通过[{why}]，但未提取到可用字段")

    missing_after = count_missing_rows(soup)

    if touched and not args.dry_run:
        INDEX.write_text(str(soup), encoding="utf-8")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        "\n".join(
            [
                f"missing_before={missing_before}",
                f"missing_total={len(missing_codes)}",
                f"attempted={scanned}",
                f"updated={touched}",
                f"missing_after={missing_after}",
                f"updated_codes={','.join(processed_codes)}",
                "---",
                *logs,
            ]
        ),
        encoding="utf-8",
    )

    print(
        f"missing_before={missing_before} missing_total={len(missing_codes)} "
        f"attempted={scanned} updated={touched} missing_after={missing_after}"
    )
    if processed_codes:
        print("updated_codes=" + ",".join(processed_codes))
    print(f"report={args.report}")


if __name__ == "__main__":
    main()
