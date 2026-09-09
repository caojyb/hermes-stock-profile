#!/usr/bin/env python3
import sys

with open('core/research/c5_q_research_coverage_restoration.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

depth = 0
for i, line in enumerate(lines, 1):
    in_str = False
    str_char = None
    j = 0
    while j < len(line):
        ch = line[j]
        if in_str:
            if ch == '\\':
                j += 2
                continue
            if ch == str_char:
                in_str = False
        else:
            if ch in ('"', "'"):
                in_str = True
                str_char = ch
            elif ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
        j += 1
    if depth < 0:
        print(f'Negative depth at line {i}: {line.rstrip()}')
        break

print(f'Final depth: {depth}')
