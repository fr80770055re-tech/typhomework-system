#!/usr/bin/env python3
"""將 Word 試題檔 (.docx) 轉換為題庫匯入用 CSV。

支援兩種常見排版：

1. 標楷體／circled-number 格式（如翰林以外的自編解析卷）：
       （　　）題目敘述...①選項一　②選項二　③選項三　④選項四
       答案：②
       解析：...（預設不匯入，可用 --include-explanations 帶入）

2. 翰林格式（選項無符號標記，用全形空白分隔；答案用 Word 公式欄位
   eq \\o(○,N) 畫出圈圈數字，不是純文字）：
       (   ) 題目敘述...　　選項一　　選項二　　選項三　　選項四。
       答案：<公式欄位，例如 eq \\o(○,3)>
       解析：...（可能跨多個段落）

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
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

CIRCLED_TO_INDEX = {"①": "1", "②": "2", "③": "3", "④": "4"}
OPTION_MARKERS = ["①", "②", "③", "④"]

STEM_PREFIX_RE = re.compile(r"^[（(]\s*[)）]\s*")
HANLIN_PREFIX_RE = re.compile(r"^\(\s*\)\s*")
ANSWER_RE = re.compile(r"^答案[：:]\s*([①②③④])")
ANSWER_EMPTY_RE = re.compile(r"^答案[：:]\s*$")
FIELD_CIRCLE_ANSWER_RE = re.compile(r"eq\s*\\o\(\s*○\s*,\s*([0-9０-９]+)\s*\)", re.IGNORECASE)
EXPLANATION_RE = re.compile(r"^解析[：:]\s*")
SECTION_HEADER_RE = re.compile(r"^[一二三四五六七八九十]+、")
HANLIN_SECTION_RE = re.compile(r"每.*[分].*）\s*$")


def extract_paragraphs(docx_path: Path) -> list[tuple[str, str]]:
    """回傳 [(段落可見文字, 段落內公式欄位instrText), ...]。"""
    with zipfile.ZipFile(docx_path) as z:
        xml_bytes = z.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    paragraphs = []
    for p in root.iter(f"{W_NS}p"):
        text = "".join(t.text or "" for t in p.iter(f"{W_NS}t"))
        instr = "".join(t.text or "" for t in p.iter(f"{W_NS}instrText"))
        paragraphs.append((text, instr))
    return paragraphs


def split_question_circled(text: str):
    """標楷體格式：題幹①選項1②選項2③選項3④選項4。找不到四個標記則回傳 None。"""
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


def split_question_hanlin(text: str):
    """翰林格式：(   )題幹　　選項1　　選項2　　選項3　　選項4（雙全形空白分隔）。"""
    if not HANLIN_PREFIX_RE.match(text):
        return None
    body = HANLIN_PREFIX_RE.sub("", text)
    parts = re.split("　{2,}", body)
    if len(parts) != 5:
        # 部分文件排版不一致，只用單一全形空白分隔選項，退而求其次再試一次
        parts = re.split("　", body)
    if len(parts) != 5:
        return None
    stem = parts[0].replace("　", " ").strip()
    options = [p.replace("　", " ").strip() for p in parts[1:]]
    return stem, options


QUESTION_SPLITTERS = [split_question_circled, split_question_hanlin]


def split_question(text: str):
    for splitter in QUESTION_SPLITTERS:
        result = splitter(text)
        if result is not None:
            return result
    return None


def parse_answer(text: str, instr: str):
    """回傳答案數字字串("1".."4")或 None。"""
    m = ANSWER_RE.match(text)
    if m:
        return CIRCLED_TO_INDEX[m.group(1)]
    if ANSWER_EMPTY_RE.match(text):
        fm = FIELD_CIRCLE_ANSWER_RE.search(instr)
        if fm:
            digit = unicodedata.normalize("NFKC", fm.group(1))
            if digit in "1234":
                return digit
    return None


def is_boundary(text: str) -> bool:
    """判斷此段落是否代表「上一題的解析已結束」的邊界。"""
    if not text:
        return True
    if ANSWER_RE.match(text) or ANSWER_EMPTY_RE.match(text):
        return True
    if SECTION_HEADER_RE.match(text) or HANLIN_SECTION_RE.search(text):
        return True
    if split_question(text) is not None:
        return True
    if HANLIN_PREFIX_RE.match(text) or STEM_PREFIX_RE.match(text):
        return True  # 看起來像下一題的開頭（即使選項解析失敗），仍視為邊界
    return False


def parse_exam(paragraphs: list[tuple[str, str]], include_explanations: bool):
    rows, warnings = [], []
    i, n = 0, len(paragraphs)
    while i < n:
        text, _ = paragraphs[i]
        text = text.strip()
        i += 1
        if not text or SECTION_HEADER_RE.match(text) or HANLIN_SECTION_RE.search(text):
            continue
        if ANSWER_RE.match(text) or ANSWER_EMPTY_RE.match(text) or EXPLANATION_RE.match(text):
            continue  # 落單的答案／解析段落
        parsed = split_question(text)
        if parsed is None:
            if HANLIN_PREFIX_RE.match(text) or STEM_PREFIX_RE.match(text):
                warnings.append(f"偵測到疑似題目但無法解析出4個選項（分隔符可能不一致），請人工處理：「{text[:30]}」")
            continue
        stem, options = parsed

        answer, explanation = "", ""
        j = i
        while j < n and j < i + 4:
            follow_text, follow_instr = paragraphs[j]
            follow_text = follow_text.strip()
            ans = parse_answer(follow_text, follow_instr)
            if ans is not None:
                answer = ans
                j += 1
                if include_explanations and j < n and EXPLANATION_RE.match(paragraphs[j][0].strip()):
                    parts = [EXPLANATION_RE.sub("", paragraphs[j][0].strip(), count=1).strip()]
                    j += 1
                    while j < n and not is_boundary(paragraphs[j][0].strip()):
                        parts.append(paragraphs[j][0].strip())
                        j += 1
                    explanation = " ".join(p for p in parts if p).replace("　", " ")
                break
            if split_question(follow_text) is not None or SECTION_HEADER_RE.match(follow_text) or HANLIN_SECTION_RE.search(follow_text):
                break  # 已進入下一題，代表這題沒有答案
            j += 1
        if answer:
            i = j

        if not answer:
            warnings.append(f"未找到答案：「{stem[:24]}」，請手動填寫『正確答案』欄位")
        if len(set(options)) < 4:
            warnings.append(f"選項內容有重複（可能是特殊注音字型無法擷取，需人工比對原始docx）：「{stem[:30]}」")
        if len(options) != 4:
            warnings.append(f"選項數量不是4個，已略過：「{stem[:30]}」")
            continue

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
        sys.exit("沒有解析出任何題目，請確認 docx 排版是否為支援的格式（見程式檔頭說明）。")

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
