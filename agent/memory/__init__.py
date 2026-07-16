"""Memory Agent — 长期记忆管理

结构:
  agent/memory/
  ├── __init__.py
  ├── extractor.py    — Memory Extractor（每轮结束判断是否保存）
  ├── episodic/       — 情景记忆（具体事件/问题/解决方案）
  │   └── 20260715_login_bug.md
  └── semantic/       — 语义记忆（通用模式/知识）
      └── vue_patterns.md

Memory Extractor:
  输入: trajectory
  判断: 有没有值得保存的知识？
  输出: 保存到 episodic/ 或 semantic/ 的 markdown 文件
"""
