#!/usr/bin/env python3
"""將 Word 試題檔 (.docx) 轉換為題庫匯入用 CSV。

適用格式（各校／各出版社「解析卷」常見排版）：
    （　　）題目敘述...①選項一　②選項二　③選項三　④選項四
    答案：②
    解析：...（預設不匯入，可用 --include-explanations 帶入）

輸出欄位對齊題庫匯入範例：
    題目,正確答案,選項一,選項二,選項三,選項四,詳解

用法：
    python3 scripts/exam_docx_to_csv.py 解析卷.docx
    python3 scripts/exam_docx_to_csv.py 解析卷.docx -o 題庫.csv
    python3 scripts/exam_docx_to_csv.py 解析卷.docx --include-explanations

若來源檔沒有「答案：」（例如只有題目卷、沒有解析卷），對應題目的『正確
答案』欄位會留空，並在結尾列出需要人工複核的題目清單。
"""
import argparse
import csv
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

CIRCLED_TO_INDEX = {"①": "1", "②": "2", "③": "3", "④": "4"}
OPTION_MARKERS = ["①", "②", "③", "④"]

STEM_PREFIX_RE = re.compile(r"^[（(]\s*[)）]\s*")
ANSWER_RE = re.compile(r"^答案[：:]\s*([①②③④])")
EXPLANATION_RE = re.compile(r"^解析[：:]\s*")
SECTION_HEADER_RE = re.compile(r"^[一二三四五六七八九十]+、")


def extract_paragraphs(docx_path: Path) -> list[str]:
    with zipfile.ZipFile(docx_path) as z:
        xml_bytes = z.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    return ["".join(t.text or "" for t in p.iter(f"{W_NS}t")) for p in root.iter(f"{W_NS}p")]


def split_question(text: str):
    """回傳 (題幹, [選項1..4])；若不含完整四個選項標記則回傳 None。"""
    positions = [text.find(m) for m in OPTION_MARKERS]
    if any(pos == -1 for pos in positions) or positions != sorted(positions):
        return None

    stem = STEM_PREFIX_RE.sub("", text[: positions[0]]).strip()
    options = []
    for i in range(4):
        start = positions[i] + 1
        end = positions[i + 1] if i < 3 else len(text)
        options.append(text[start:end].strip(" 　"))
    return stem, options


def parse_exam(paragraphs: list[str], include_explanations: bool):
    rows, warnings = [], []
    i, n = 0, len(paragraphs)
    while i < n:
        text = paragraphs[i].strip()
        i += 1
        if not text or SECTION_HEADER_RE.match(text):
            continue
        if ANSWER_RE.match(text) or EXPLANATION_RE.match(text):
            continue  # 落單的答案／解析段落（理論上會在上一題的前瞻視窗內被吃掉）
        parsed = split_question(text)
        if parsed is None:
            continue
        stem, options = parsed

        answer, explanation = "", ""
        j = i
        while j < n and j < i + 4:
            follow = paragraphs[j].strip()
            m = ANSWER_RE.match(follow)
            if m:
                answer = CIRCLED_TO_INDEX[m.group(1)]
                j += 1
                if include_explanations and j < n and EXPLANATION_RE.match(paragraphs[j].strip()):
                    explanation = EXPLANATION_RE.sub("", paragraphs[j].strip(), count=1).strip()
                    j += 1
                break
            if split_question(follow) is not None or SECTION_HEADER_RE.match(follow):
                break  # 已進入下一題，代表這題沒有答案
            j += 1
        if answer:
            i = j

        if not answer:
            warnings.append(f"未找到答案：「{stem[:24]}」，請手動填寫『正確答案』欄位")
        if len(set(options)) < 4:
            warnings.append(f"選項內容有重複（可能是特殊注音字型無法擷取，需人工比對原始docx）：「{stem[:30]}」")

        rows.append([stem, answer, *options, explanation])
    return rows, warnings


def main():
    parser = argparse.ArgumentParser(description="將 Word 試題 (.docx) 轉換為題庫匯入 CSV")
    parser.add_argument("docx", type=Path, help="來源 Word 檔（建議用含答案的「解析卷」）")
    parser.add_argument("-o", "--output", type=Path, help="輸出 CSV 路徑（預設：來源檔同目錄、同檔名.csv）")
    parser.add_argument("--include-explanations", action="store_true", help="把「解析：」內容一併寫入『詳解』欄位（預設不匯入）")
    args = parser.parse_args()

    if not args.docx.exists():
        sys.exit(f"找不到檔案：{args.docx}")

    output = args.output or args.docx.with_suffix(".csv")

    paragraphs = extract_paragraphs(args.docx)
    rows, warnings = parse_exam(paragraphs, args.include_explanations)

    if not rows:
        sys.exit("沒有解析出任何題目，請確認 docx 排版是否為「（　　）題幹①…②…③…④…」格式。")

    header = ["題目", "正確答案", "選項一", "選項二", "選項三", "選項四", "詳解"]
    with open(output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(header)
        writer.writerows(rows)

    print(f"已產生 {len(rows)} 題 -> {output}")
    if warnings:
        print(f"\n⚠ 有 {len(warnings)} 個項目需要人工複核：")
        for w in warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
