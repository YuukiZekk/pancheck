"""从文件名里抽展示用的标签（反馈 25）：制作组 / 版本属性 / 语言字幕。

只给清单显示用，不参与任何判定和排序。词表都是固定的，命中就出，不猜。
"""
import os
import re

# 常见站点 / 制作组（裸名出现在名字里，按词边界认）；特效字幕组名单（设置里那份）也算
KNOWN_GROUPS = ['HDSky', 'HDHome', 'CMCT', 'CHDBits', 'FRDS', 'OurBits', 'PTer', 'HDChina', 'TTG', 'MTeam', 'M-Team', 'Audies',
                'ADWeb', 'BeyondHD', 'WiKi', 'beAst', 'PTHome', 'PTsbao', 'HDArea', 'HDVideo', 'NCmt', 'BHYS', 'SGNB', 'Blucook',
                'FGT', 'CtrlHD', 'EbP', 'DON', 'HiFi', 'TayTO', 'SiCFoI', 'CHD', 'HDS', 'HDC', 'OB', 'ADE', 'MySiLU', 'QHstudIo']
_AT = re.compile(r'(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{0,15})@([A-Za-z][A-Za-z]{1,12})')       # nn@CHDBits、SGNB@CHD-165187
_TRAIL = re.compile(r'-([A-Za-z][A-Za-z0-9]{1,14})\s*$')                                          # …DTS-HD.MA.5.1-FGT
_NOT_GROUP = {'hd', 'ma', 'dl', 'rip', 'x264', 'x265', 'hevc', 'avc', 'dts', 'remux', 'bluray', 'uhd', 'web', 'hdr', 'sdr', 'dv',
              'atmos', 'truehd', 'ddp', 'aac', 'flac', 'lpcm', 'disc', 'cd', 'iso', 'mkv', 'mp4', 'ac3', 'eac3', 'mpeg', 'vc'}
VERSION = [('官方', re.compile(r'官方')), ('独占', re.compile(r'独占')), ('DIY', re.compile(r'(?i)(?<![a-z])diy(?![a-z])')),
           ('原盘', re.compile(r'原盘')), ('REMUX', re.compile(r'(?i)remux')), ('压制', re.compile(r'(?i)压制|(?<![a-z0-9])x26[45](?![0-9])'))]
LANG = [('国语', re.compile(r'国语|国配')), ('粤语', re.compile(r'粤语|粤配')), ('简繁', re.compile(r'简繁')),
        ('特效字幕', re.compile(r'特效.{0,4}?字幕')), ('双语', re.compile(r'双语')), ('中字', re.compile(r'中字|中文字幕'))]
_EXT = re.compile(r'(?i)\.(iso|mkv|mp4|m2ts|ts|avi|wmv|mov|rmvb|flv)$')


def _groups(name, extra):
    out = []
    for m in _AT.finditer(name):
        out.append('%s@%s' % (m.group(1), m.group(2)))
    stem = re.sub(r'[\[【(（][^\]】)）]*[\]】)）]\s*$', '', _EXT.sub('', name)).strip()      # 末尾的 [91.78GB] 之类先去掉
    m = _TRAIL.search(stem)
    if m and m.group(1).lower() not in _NOT_GROUP and not any(m.group(1) in g for g in out):
        out.append(m.group(1))
    for g in list(extra) + KNOWN_GROUPS:
        if not g or any(g.lower() in x.lower() for x in out):
            continue
        if re.search(r'[A-Za-z]', g):
            if re.search(r'(?i)(?<![A-Za-z0-9])%s(?![A-Za-z0-9])' % re.escape(g), name):
                out.append(g)
        elif g in name and not name.startswith(g):                     # 中文组名（至尊宝、雅典娜）：片名开头的不算
            out.append(g)
    return out[:2]


def tags(path, extra_groups=()):
    """→ ['nn@CHDBits', 'DIY', '国语', …]（顺序：制作组、版本属性、语言字幕）。标签就是组名本身，不加「组」字（反馈 26）。"""
    name = os.path.basename((path or '').rstrip('/'))
    out = list(_groups(name, extra_groups))
    out += [t for t, rx in VERSION if rx.search(name)]
    out += [t for t, rx in LANG if rx.search(name)]
    return out


def listed(tag_list, extra_groups=()):
    """标签里哪些是设置里那份特效字幕组名单上的（清单上用淡色单独标出来，反馈 26）。只做展示。"""
    names = {str(g).strip().lower() for g in extra_groups or () if str(g).strip()}
    return [t for t in tag_list if t.lower() in names]
