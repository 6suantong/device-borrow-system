# -*- coding: utf-8 -*-
"""
四轮迭代分析报告生成脚本。
从考核模板 docx 出发，按阶段（stage 1-4，对应 V1-V4）填充表格，
用于 git 分版本提交，体现四轮方案的演化过程。

用法：
    python fill_report.py --stage 4                          # 生成最终版
    python fill_report.py --stage 1 --out report_v1.docx     # 生成 V1 阶段版
"""
import argparse
import os

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

import report_content_a as A
import report_content_b as B

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATE = os.path.join(
    os.path.dirname(HERE),
    "..", "软件工程系统开发方向", "软件工程系统开发方向_四轮迭代分析报告.docx",
)


def style_cell(cell, size=10.5):
    for p in cell.paragraphs:
        for run in p.runs:
            run.font.size = Pt(size)
            run.font.name = "Calibri"
            rpr = run._element.get_or_add_rPr()
            rfonts = rpr.find(qn("w:rFonts"))
            if rfonts is None:
                rfonts = rpr.makeelement(qn("w:rFonts"), {})
                rpr.append(rfonts)
            rfonts.set(qn("w:eastAsia"), "宋体")


def set_cell(cell, text):
    cell.text = str(text)
    style_cell(cell)


def fill_single(tables, idx, text):
    set_cell(tables[idx].rows[0].cells[0], text)


def fill_rows(tables, idx, rows, start_col=0):
    """从数据区第一行开始逐行填充；模板行不足时自动追加。"""
    t = tables[idx]
    for r_i, row_data in enumerate(rows, start=1):
        if r_i >= len(t.rows):
            t.add_row()
        for c_i, value in enumerate(row_data):
            set_cell(t.rows[r_i].cells[start_col + c_i], value)


def fill_label_table(tables, idx, rows):
    """左列为预填标签的两列表：仅填充右侧内容列。"""
    t = tables[idx]
    for r_i, row_data in enumerate(rows, start=1):
        if r_i >= len(t.rows):
            t.add_row()
        set_cell(t.rows[r_i].cells[1], row_data[1])


def build(stage, template_path, out_path):
    doc = Document(template_path)
    t = doc.tables

    # 封面：姓名 / 学号
    set_cell(t[0].rows[0].cells[1], A.COVER["姓名"])
    set_cell(t[0].rows[1].cells[0], "学号")
    set_cell(t[0].rows[1].cells[1], A.COVER["学号"])

    # ---------- V1 ----------
    fill_single(t, 1, A.T01)
    fill_rows(t, 2, A.T02)
    fill_rows(t, 3, A.T03)
    fill_rows(t, 4, A.T04)
    fill_single(t, 5, A.T05)
    fill_rows(t, 6, A.T06)
    fill_rows(t, 7, A.T07)
    fill_label_table(t, 8, A.T08)
    fill_rows(t, 9, A.T09)
    fill_single(t, 10, A.T10)

    if stage >= 2:
        # ---------- V2 ----------
        fill_rows(t, 11, A.T11)
        fill_rows(t, 12, A.T12)
        fill_single(t, 13, A.T13)
        fill_rows(t, 14, A.T14)
        fill_label_table(t, 15, A.T15)
        fill_rows(t, 16, A.T16)
        fill_single(t, 17, A.T17)

    if stage >= 3:
        # ---------- V3 ----------
        fill_rows(t, 19, B.T19)
        fill_rows(t, 20, B.T20)
        fill_rows(t, 21, B.T21)
        fill_label_table(t, 22, B.T22)
        fill_rows(t, 23, B.T23)
        fill_single(t, 24, B.T24)

    if stage >= 4:
        # ---------- V4 ----------
        fill_rows(t, 25, B.T25)           # 列0为预填标签，填列1/2
        fill_rows(t, 26, B.T26)
        fill_rows(t, 27, B.T27)
        fill_rows(t, 28, B.T28)
        fill_label_table(t, 29, B.T29)
        fill_single(t, 30, B.T30)
        fill_rows(t, 31, B.T31)
        # 最终反思：问题行已预填，答案写入其下的空行（1/3/5）
        for ans_i, ans in enumerate(B.T32):
            answer = ans.split("\n", 1)[1] if "\n" in ans else ans
            set_cell(t[32].rows[ans_i * 2 + 1].cells[0], answer)

    doc.save(out_path)
    print("已生成 stage=%d -> %s" % (stage, out_path))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, default=4, choices=[1, 2, 3, 4])
    ap.add_argument("--template", default=os.path.abspath(DEFAULT_TEMPLATE))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = args.out or os.path.join(
        HERE, "软件工程系统开发方向_四轮迭代分析报告_刘泽_2025181005000135.docx")
    build(args.stage, args.template, out)
