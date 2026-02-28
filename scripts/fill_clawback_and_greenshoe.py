#!/usr/bin/env python3
"""Fill 回拨 and 绿鞋 columns in docs/index.html from local PDFs.

Policy (per user): 宁可留空，不填错。

回拨 (Clawback):
- Source: 配發結果.pdf
- Logic: compare FINAL HK public offer shares vs INITIAL HK offer shares.
  - initial: "香港發售股份數目" / "香港發售股份數目 :" / "香港發售股份數目："
  - final: "公開發售的最終發售股份數目" / variants
- If final > initial => 回拨=是 else 回拨=否

绿鞋 (Greenshoe exercise %):
- Prefer source: 綠鞋悉行.pdf (if present), else 穩價期終.pdf, else 配發結果.pdf.
- Determine exercised shares:
  - If text says "超額配股權未獲行使" => 0%
  - If says "獲悉數行使" => 15% (if we cannot extract shares precisely)
  - Otherwise try to extract exercised share count and compute pct = exercised / base_offer_shares * 100
- base_offer_shares: extract from 配發結果.pdf summary label "全球發售...發售股份數目".

Output:
- Writes back docs/index.html when --apply.
- Writes a JSON report.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, List

from bs4 import BeautifulSoup


def pdftotext(pdf: Path, pages: int = 40, layout: bool = False) -> str:
    cmd = ["pdftotext"]
    if layout:
        cmd.append("-layout")
    cmd += ["-f", "1", "-l", str(pages), "-enc", "UTF-8", str(pdf), "-"]
    try:
        out = subprocess.check_output(cmd, timeout=240, stderr=subprocess.DEVNULL)
        return out.decode("utf-8", "ignore")
    except Exception:
        return ""


def norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


def parse_int(s: str) -> Optional[int]:
    m = re.search(r"([0-9][0-9,]{2,})", s)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except Exception:
        return None


def extract_initial_hk_shares(text: str) -> Optional[int]:
    c = norm(text)

    # Common inline layout
    m = re.search(r"香港發售股份數目[:：]?([0-9][0-9,]{2,})", c)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except Exception:
            return None

    # Some PDFs do not use the '香港發售股份數目' label; they use '香港公開發售項下初步可供認購...'
    m = re.search(r"香港公開發售項下初步可供認購[^0-9]{0,60}([0-9][0-9,]{2,})", c)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except Exception:
            return None

    # GEM wording often uses 公開發售 / 配售
    m = re.search(r"公開發售初步可供認購[^0-9]{0,60}([0-9][0-9,]{2,})", c)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except Exception:
            return None
    # Table layout: label on one line, values a few lines later.
    # Prefer the number that appears after the label (often on a standalone line).
    lines = [ln.strip() for ln in (text or "").splitlines()]
    for i, ln in enumerate(lines):
        if (
            ln == "香港發售股份數目"
            or "香港發售股份數目" in ln
            or "香港公開發售項下初步可供認購" in ln
            or "香港公開發售初步可供認購" in ln
            or "香港公開發 售 項 下 初 步 可 供 認 購" in ln
            or "公開發售初步可供認購" in ln
        ):
            cands = []
            for j in range(i + 1, min(len(lines), i + 60)):
                v = parse_int(lines[j])
                if v and 100_000 <= v <= 500_000_000:
                    cands.append(v)
            if cands:
                # initial is usually the smaller one (final may be larger after clawback)
                return min(cands)
            break

    return None


def extract_final_hk_shares(text: str) -> Optional[int]:
    # try multiple label variants (compact)
    c = norm(text)
    for lab in [
        r"公開發售的最終發售股份數目",
        r"公開發售最終發售股份數目",
        r"公開發售項下最終發售股份數目",
        r"香港公開發售的最終發售股份數目",
        r"香港公開發售最終發售股份數目",
        r"香港公開發售最終發售股份數量",
        r"公開發售最終股份數目",
        r"最終香港公開發售股份數目",
        r"香港公開發售的發售股份的最終數目",
        r"香港公開發售最終發售股份數目\(經重新分配後\)",
        r"公開發售的發售股份最終數量",
        r"公開發售的發售股份最終數目",
        r"公開發售項下發售股份的最終數目\(重新分配後\)",
    ]:
        m = re.search(lab + r"[:：]?([0-9][0-9,]{2,})", c)
        if m:
            try:
                v = int(m.group(1).replace(",", ""))
                if 100_000 <= v <= 500_000_000:
                    return v
            except Exception:
                pass

    # fallback: line window scan (handles spaced/traditional)
    lines = [ln.strip() for ln in (text or "").splitlines()]
    for i, ln in enumerate(lines):
        if (
            re.search(r"公開發售.*最終.*(數目|數量)", ln)
            or re.search(r"香港公開發售.*最終", ln)
            or ("公 開 發 售" in ln and "最 終" in ln)
            or ("香 港 公 開 發 售" in ln and "最 終" in ln)
            or ("最終香港公開發售" in ln)
        ):
            win = lines[i : i + 30]
            for w in win:
                v = parse_int(w)
                if v and 100_000 <= v <= 500_000_000:
                    return v
    return None


def extract_base_offer_shares(text: str) -> Optional[int]:
    c = norm(text)
    m = re.search(r"全球發售(?:項下)?的發售股份數目[:：]?([0-9][0-9,]{2,})", c)
    if not m:
        m = re.search(r"全球發售項下的發售股份數目[:：]?([0-9][0-9,]{2,})", c)
    if m:
        try:
            v = int(m.group(1).replace(",", ""))
            # base offer shares can be >500m for some huge IPOs; keep wide bound
            if 100_000 <= v <= 5_000_000_000:
                return v
        except Exception:
            return None
    return None


def greenshoe_exercised_pct(green_text: str, base_offer_shares: Optional[int]) -> Optional[float]:
    c = norm(green_text)

    # Explicit no exercise
    if re.search(r"超額配股權未獲行使|超额配股权未获行使|Over\-?allotment\s+Option\s+has\s+not\s+been\s+exercised", c, flags=re.I):
        return 0.0

    # Try to extract exercised shares
    # Typical phrases
    share = None
    for pat in [
        r"超額配股權(?:已)?獲(?:部份|部分)?行使[^0-9]{0,20}([0-9][0-9,]{2,})股",
        r"超额配股权(?:已)?获(?:部份|部分)?行使[^0-9]{0,20}([0-9][0-9,]{2,})股",
        r"exercise[^0-9]{0,40}([0-9][0-9,]{2,})\s*(?:Shares|share)",
    ]:
        m = re.search(pat, c, flags=re.I)
        if m:
            try:
                share = int(m.group(1).replace(",", ""))
                break
            except Exception:
                pass

    # Fully exercised without share count
    if share is None and re.search(r"超額配股權獲悉數行使|超额配股权获悉数行使|fully\s+exercised", c, flags=re.I):
        # If base offer shares unknown, we can only safely say 15% by convention; keep None if you prefer strict.
        return 15.0

    if share is None or base_offer_shares is None or base_offer_shares <= 0:
        return None

    pct = share / base_offer_shares * 100.0
    if pct < 0 or pct > 20:
        # sanity: greenshoe pct should be within [0, 15] typically
        return None
    return pct


def fmt_pct(v: float) -> str:
    # show 0% / 15% as integer; others one decimal
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v))}%"
    return f"{v:.1f}%"


@dataclass
class Item:
    code: str
    name: str
    clawback_before: str
    clawback_after: str
    greenshoe_before: str
    greenshoe_after: str
    initial_hk: Optional[int] = None
    final_hk: Optional[int] = None
    base_offer: Optional[int] = None
    greenshoe_pct: Optional[float] = None
    greenshoe_src: Optional[str] = None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pages", type=int, default=40)
    ap.add_argument("--report", type=Path, default=Path("reports/clawback_greenshoe_report.json"))
    args = ap.parse_args()

    index_path = Path("docs/index.html")
    soup = BeautifulSoup(index_path.read_text(encoding="utf-8"), "html.parser")
    ths = [re.sub(r"[↕\s]+$", "", th.get_text(strip=True)).strip() for th in soup.select("table thead th")]
    idx: Dict[str, int] = {h: i for i, h in enumerate(ths)}

    for col in ["代码", "股票名称", "回拨", "绿鞋"]:
        if col not in idx:
            raise SystemExit(f"missing col {col}")

    code_i = idx["代码"]
    name_i = idx["股票名称"]
    claw_i = idx["回拨"]
    green_i = idx["绿鞋"]

    attempted = 0
    updated = 0
    items: List[Item] = []

    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != len(ths):
            continue

        code = tds[code_i].get_text(strip=True)
        name = tds[name_i].get_text(strip=True)
        claw_before = tds[claw_i].get_text(strip=True)
        green_before = tds[green_i].get_text(strip=True)

        ddir = next(iter(Path("docs").glob(code + "*")), None)
        if not ddir or not ddir.is_dir():
            continue

        allot_pdf = ddir / "配發結果.pdf"
        if not allot_pdf.exists():
            continue

        attempted += 1

        allot_text = pdftotext(allot_pdf, pages=args.pages)
        init_hk = extract_initial_hk_shares(allot_text)
        fin_hk = extract_final_hk_shares(allot_text)
        base_offer = extract_base_offer_shares(allot_text)

        claw_after = claw_before
        if init_hk is not None and fin_hk is not None:
            claw_after = "是" if fin_hk > init_hk else "否"
        else:
            # English-only announcements may not expose 'initial HK offer shares' clearly.
            # If we see an explicit statement like "there will be no reallocation", set 回拨=否.
            c0 = norm(allot_text).lower()
            if "noreallocation" in c0 or "therewillbenoreallocation" in c0:
                claw_after = "否"

        # greenshoe
        green_src = None
        green_text = ""
        for cand in [ddir / "綠鞋悉行.pdf", ddir / "穩價期終.pdf", allot_pdf]:
            if cand.exists():
                green_text = pdftotext(cand, pages=max(12, args.pages))
                green_src = str(cand)
                # if file is optional and blank, continue
                if green_text.strip():
                    break

        pct = greenshoe_exercised_pct(green_text, base_offer)
        green_after = green_before
        if pct is not None:
            green_after = fmt_pct(pct)

        changed = (claw_after != claw_before) or (green_after != green_before)
        if changed:
            updated += 1
            if args.apply:
                tds[claw_i].string = claw_after
                # sort: 是=1 否=0
                tds[claw_i]["data-sort-num"] = "1" if claw_after == "是" else ("0" if claw_after == "否" else "")
                tds[claw_i]["data-sort"] = claw_after

                tds[green_i].string = green_after
                # numeric for sorting
                m = re.search(r"([0-9]+(?:\.[0-9]+)?)%", green_after)
                if m:
                    tds[green_i]["data-sort-num"] = m.group(1)
                    tds[green_i]["data-sort"] = green_after

        items.append(
            Item(
                code=code,
                name=name,
                clawback_before=claw_before,
                clawback_after=claw_after,
                greenshoe_before=green_before,
                greenshoe_after=green_after,
                initial_hk=init_hk,
                final_hk=fin_hk,
                base_offer=base_offer,
                greenshoe_pct=pct,
                greenshoe_src=green_src,
            )
        )

    args.report.parent.mkdir(exist_ok=True)
    args.report.write_text(
        json.dumps({"attempted": attempted, "updated": updated, "items": [asdict(x) for x in items]}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )

    if args.apply:
        index_path.write_text(str(soup), encoding="utf-8")

    print(f"attempted={attempted} updated={updated} report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
