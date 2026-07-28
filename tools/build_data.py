#!/usr/bin/env python3
"""Clean OCR rows and emit game/hanzi-data.js"""
import json, re, sys

rows = json.load(open('data/ocr_all.json'))

# The source book pages 348/349 are swapped in 601-1800.pdf (pdf pages 227/228): restore order
i227 = [i for i, r in enumerate(rows) if r['pdf'] == '601-1800.pdf' and r['page'] == 227]
i228 = [i for i, r in enumerate(rows) if r['pdf'] == '601-1800.pdf' and r['page'] == 228]
assert len(i227) == 5 and len(i228) == 5 and i228[0] == i227[-1] + 1
block = rows[i228[0]:i228[-1] + 1] + rows[i227[0]:i227[-1] + 1]
rows[i227[0]:i228[-1] + 1] = block

# manual fixes keyed by 1-based sequence index: (char, word, sent) — None keeps existing
FIX = {
    1:    ('一', '一个', '一个人。'),
    37:   (None, '孩子', None),
    59:   (None, '多少', None),
    84:   (None, '包子', '爸爸喜欢吃包子。'),
    105:  (None, '画画', None),
    109:  (None, '也是', '天空是蓝色的，大海也是蓝色的。'),
    147:  (None, '身体', None),
    162:  (None, '星星', '夜晚，天空中有很多闪亮的星星。'),
    181:  (None, '七个', None),
    257:  (None, '害虫', None),
    334:  (None, '萝卜', None),
    382:  (None, '行人', '行人要走人行道，汽车要走车行道。'),
    387:  (None, '宇宙', None),
    397:  (None, '司机', '透过车窗能看见司机坐在车里面。'),
    402:  (None, '贝壳', None),
    426:  (None, '宫殿', None),
    464:  (None, '老虎', None),
    577:  (None, '左手', None),
    757:  (None, '树梢', None),
    864:  (None, '一寸', None),
    897:  (None, '虚心', '遇到不懂的问题要虚心请教。'),
    922:  (None, '寻找', None),
    955:  (None, '丢掉', None),
    1017: (None, '明信片', '明信片上写满了我对朋友的祝福。'),
    1036: (None, '重申', None),
    1117: (None, '丰收', None),
    1122: (None, '导弹', '这种导弹的破坏力非常大。'),
    1137: (None, '节省', '为了节省时间，我们打算坐飞机。'),
    1172: (None, '艺术', None),
    1206: (None, None, '他决定下周回北京。'),
    1232: (None, '脖子', None),
    1307: (None, '草帽', None),
    1309: (None, '棉裤', None),
    1332: (None, '灵芝', None),
    1348: (None, None, '祝愿祖国越来越繁荣昌盛。'),
    1455: (None, '裁剪', None),
    1467: (None, '邮寄', None),
    1482: (None, '长亭', None),
    1527: (None, '夜宵', '昨晚我吃了一顿美味的夜宵。'),
    1532: (None, '乞丐', '在故事里，乞丐得到了善良人的帮助。'),
    1557: (None, None, '妈妈用蒸笼蒸了一屉香喷喷的蒸饺。'),
    1577: (None, None, '坏人常常用谎话蒙蔽小朋友，大家一定要小心。'),
    1617: (None, '肃静', None),
    1641: (None, '破晓', None),
    1662: (None, '咦', None),
    1721: (None, '哦', None),
    1746: (None, '减少', None),
    1747: (None, '卡车', None),
}

def clean_sent(s):
    s = re.sub(r'[①②③④\s|｜!！?？]*(?=[\u4e00-\u9fff])', '', s, count=1)  # leading junk
    s = s.replace(' ', '').replace('|', '').replace('｜', '')
    s = re.sub(r'^[^\u4e00-\u9fff]+', '', s)
    return s

out = []
problems = []
for i, r in enumerate(rows, 1):
    ch, w, s = r['char'], r['word'], r['sent']
    if i in FIX:
        fc, fw, fs = FIX[i]
        ch = fc or ch
        w = fw or w
        s = fs or s
    s = clean_sent(s)
    if not ch or ch not in w:
        problems.append((i, ch, w, s))
    out.append({'c': ch, 'w': w, 's': s})

if problems:
    print('REMAINING PROBLEMS:', file=sys.stderr)
    for p in problems:
        print(p, file=sys.stderr)

# uniqueness check
seen = {}
for i, d in enumerate(out, 1):
    if d['c'] in seen:
        print('DUP:', d['c'], seen[d['c']], i, file=sys.stderr)
    seen[d['c']] = i

data = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
with open('game/hanzi-data.js', 'w') as f:
    f.write('/* 洪恩识字字表（按学习顺序，OCR自三个PDF）共%d字 */\n' % len(out))
    f.write('const HANZI=' + data + ';\n')
print('written game/hanzi-data.js with', len(out), 'chars', file=sys.stderr)
