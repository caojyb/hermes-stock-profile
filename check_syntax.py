#!/usr/bin/env python3
"""Minimal syntax checker for c5_q_research_coverage_restoration.py"""
import ast
with open('core/research/c5_q_research_coverage_restoration.py') as f:
    src = f.read()
try:
    ast.parse(src)
    print('Syntax OK')
except SyntaxError as e:
    print(f'SyntaxError at line {e.lineno}, col {e.offset}: {e.msg}')
    if e.text:
        print(f'Line: {e.text!r}')
