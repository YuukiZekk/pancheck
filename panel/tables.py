"""一轮扫描的中间表（heji_films、cross_units、yuanpan_units…）。

模块之间在内存里传这些表，不再靠 os.chdir 到轮次目录、按文件名去读。为了和以前读 CSV 的口径完全一致，
放进来的每一行都按 csv 写出再读回的样子存：列按表头取、值一律转成字符串（None → ''）。
给了 dump_dir 就顺带把每张表写成 CSV，只当调试输出（读的时候不用它们）。
"""
import csv
import os

# 表名 → 写 CSV 用的编码（沿用以前文件的编码，老工具照样能读）
ENCODING = {'heji_films.csv': 'utf-8-sig', 'cross_units.csv': 'utf-8-sig', 'yuanpan_all.csv': 'utf-8-sig',
            'hidden_all.csv': 'utf-8-sig', 'emby_titles.csv': 'utf-8-sig',
            'yuanpan_units.csv': 'utf-8', 'yuanpan_files.csv': 'utf-8', 'emby_yp.csv': 'utf-8'}


def _s(v):
    return '' if v is None else str(v)


class Tables:
    def __init__(self, dump_dir=None):
        self.dump_dir = dump_dir
        self._t = {}

    def put(self, name, header, rows, enc=None):
        self._t[name] = [{h: _s(r.get(h)) for h in header} for r in rows]
        if self.dump_dir:
            with open(os.path.join(self.dump_dir, name), 'w', newline='', encoding=enc or ENCODING.get(name, 'utf-8')) as f:
                w = csv.DictWriter(f, fieldnames=header)
                w.writeheader()
                w.writerows(rows)

    def load(self, path, name=None):
        """从现成 CSV 读进来（CSV 模式、对账工具用）。"""
        name = name or os.path.basename(path)
        with open(path, encoding='utf-8-sig') as f:          # utf-8-sig 也能读不带 BOM 的
            self._t[name] = list(csv.DictReader(f))
        if self.dump_dir and os.path.abspath(os.path.dirname(path)) != os.path.abspath(self.dump_dir):
            with open(os.path.join(self.dump_dir, name), 'w', newline='', encoding=ENCODING.get(name, 'utf-8')) as f:
                rows = self._t[name]
                if rows:
                    w = csv.DictWriter(f, fieldnames=list(rows[0]))
                    w.writeheader()
                    w.writerows(rows)
        return self._t[name]

    def has(self, name):
        return name in self._t

    def rows(self, name):
        return self._t.get(name, [])

    @classmethod
    def from_dir(cls, d='.'):
        """读一个轮次目录里已有的中间表（老结果复算、对账脚本用）。"""
        t = cls()
        for name in ENCODING:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                t.load(p, name)
        return t


def tables_of(tab):
    """兼容老调用：传的是目录（或什么都没传）就当轮次目录读。"""
    if isinstance(tab, Tables):
        return tab
    return Tables.from_dir(tab or '.')
