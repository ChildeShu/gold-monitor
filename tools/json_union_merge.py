#!/usr/bin/env python3
"""
history.json 的 Git 合并驱动（key 并集）。

服务端(GitHub Actions)与本地(WorkBuddy)都会往 history.json 写入按分钟时间戳
为 key 的行情数据。两个并行写入者在变基/合并时会在文件尾部产生冲突，普通的
文本合并无法理解 JSON。本驱动按 key 做并集：

  - 取 base / ours(%A) / theirs(%B) 三方的并集；
  - 同一 key 冲突时 ours 优先（ours 是当前正在提交的版本：通常是刚采集的
    最新数据，或人工清洗/修复后的版本）；
  - 结果严格按时间戳 key 升序写出，保证 history.json 始终“时间先后”有序，
    不会出现乱序或重复。

Git 调用方式（在 .gitattributes 中配置）：
    history.json merge=jsonunion
并在仓库执行：
    git config merge.jsonunion.name "JSON key-union merge"
    git config merge.jsonunion.driver "python tools/json_union_merge.py %O %A %B"
"""
import json
import sys


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def main():
    if len(sys.argv) < 4:
        # 参数不足：交还给 Git 走常规冲突流程
        sys.exit(1)

    base_path, ours_path, theirs_path = sys.argv[1], sys.argv[2], sys.argv[3]
    base = load(base_path)
    ours = load(ours_path)
    theirs = load(theirs_path)

    merged = {}
    # 顺序：base -> theirs -> ours，后者覆盖前者，ours 最终胜出
    for d in (base, theirs, ours):
        merged.update(d)

    # 严格按时间戳 key 升序，保证时间先后有序
    out = {k: merged[k] for k in sorted(merged.keys())}

    with open(ours_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    sys.exit(0)


if __name__ == "__main__":
    main()
