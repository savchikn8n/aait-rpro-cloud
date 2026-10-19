# -*- coding: utf-8 -*-
"""
Траектория робота по модели того, что операция оставляет на изделии.

Заказчик моделирует клеевой валик, паяные соединения, сварные швы, болты —
это детали его CAD. По ним же видно, где работает робот: вытянутый кусок
(валик клея, шов герметика) — проход вдоль него, короткий (точка пайки,
сварная точка, головка болта) — точка, где инструмент опускается и ждёт.
Модель разбирается на связные куски (треугольники с общими вершинами), куски
переводятся в систему изделия тем же местом, что и сама деталь в сборке.

Для операции без модели (контроль, испытание) — сканирование: проходы
камерой над изделием по его габариту.

Здесь только геометрия, без R-Pro: строитель передаёт штрихи в hands27.robot_path.
"""

from __future__ import annotations

import math
import struct

MAX_POINTS = 24          # больше — точки сливаются по сетке, иначе пост встанет на минуты
LINE_RATIO = 3.0         # кусок длиннее ширины в столько раз — шов, а не точка
LINE_MIN = 30.0          # и не короче, мм


# --- матрицы (соглашение R-Pro: W, P, R — повороты вокруг X, Y, Z) -------------

def wpr_matrix(x=0.0, y=0.0, z=0.0, w=0.0, p=0.0, r=0.0) -> list[list[float]]:
    """4×4 как wpr_mat в hands27: Rz(r)·Ry(p)·Rx(w), затем сдвиг."""
    cw, sw = math.cos(math.radians(w)), math.sin(math.radians(w))
    cp, sp = math.cos(math.radians(p)), math.sin(math.radians(p))
    cr, sr = math.cos(math.radians(r)), math.sin(math.radians(r))
    rx = [[1, 0, 0], [0, cw, -sw], [0, sw, cw]]
    ry = [[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]]
    rz = [[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]]

    def mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    m = mul(rz, mul(ry, rx))
    return [m[0] + [x], m[1] + [y], m[2] + [z], [0.0, 0.0, 0.0, 1.0]]


def apply(m, v) -> list[float]:
    return [m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] + m[i][3] for i in range(3)]


def box_corners(lo, hi):
    return [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


def transform_box(lo, hi, pos) -> tuple[list[float], list[float]]:
    """Габарит, перенесённый местом pos = [x, y, z, W, P, R]."""
    m = wpr_matrix(*pos)
    pts = [apply(m, c) for c in box_corners(lo, hi)]
    return ([min(p[a] for p in pts) for a in range(3)], [max(p[a] for p in pts) for a in range(3)])


# --- STL --------------------------------------------------------------------

def read_stl(path: str) -> list[tuple]:
    """Треугольники STL (двоичный или текстовый) — кортежи из трёх вершин."""
    with open(path, "rb") as f:
        data = f.read()
    tris = []
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + 50 * n == len(data):
            for i in range(n):
                v = struct.unpack_from("<12f", data, 84 + 50 * i)
                tris.append((tuple(v[3:6]), tuple(v[6:9]), tuple(v[9:12])))
            return tris
    pts = []
    for line in data.decode("utf-8", "replace").splitlines():
        s = line.strip().split()
        if s[:1] == ["vertex"]:
            pts.append(tuple(float(t) for t in s[1:4]))
            if len(pts) == 3:
                tris.append(tuple(pts))
                pts = []
    return tris


def pieces(tris: list[tuple]) -> list[tuple[list[float], list[float], float]]:
    """Связные куски модели (общие вершины): габарит и площадь верха каждого
    (по ней видно, сплошной кусок или рамка — шов по периметру)."""
    parent: dict = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def key(v):
        return (round(v[0], 2), round(v[1], 2), round(v[2], 2))
    for t in tris:
        ks = [key(v) for v in t]
        for k in ks:
            parent.setdefault(k, k)
        for k in ks[1:]:
            ra, rb = find(ks[0]), find(k)
            if ra != rb:
                parent[rb] = ra
    boxes: dict = {}
    for k in parent:
        r = find(k)
        lo, hi, _ = boxes.setdefault(r, ([1e18] * 3, [-1e18] * 3, [0.0]))
        for a in range(3):
            lo[a] = min(lo[a], k[a])
            hi[a] = max(hi[a], k[a])
    for a, b, c in tris:
        # площадь проекции на XY у граней, смотрящих вверх
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if cross > 1e-9:
            boxes[find(key(a))][2][0] += cross / 2.0
    return [(lo, hi, area[0]) for lo, hi, area in boxes.values()]


# --- штрихи -------------------------------------------------------------------

def _strokes_of(boxes, as_points: bool) -> list[list[list[float]]]:
    out = []
    for lo, hi, area in boxes:
        dx, dy = hi[0] - lo[0], hi[1] - lo[1]
        cx, cy, top = (lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, hi[2]
        long_, short = max(dx, dy), max(min(dx, dy), 1e-6)
        fill = area / max(dx * dy, 1e-6)
        if not as_points and short >= LINE_MIN and fill < 0.35:
            # рамка (герметик по фланцу): обход по периметру по середине валика
            w = area / max(2.0 * (dx + dy), 1e-6)
            x0, x1, y0, y1 = lo[0] + w / 2, hi[0] - w / 2, lo[1] + w / 2, hi[1] - w / 2
            out.append([[x0, y0, top], [x1, y0, top], [x1, y1, top], [x0, y1, top], [x0, y0, top]])
        elif not as_points and short >= 2 * LINE_MIN:
            # сплошная площадка (термопаста под модуль): два прохода вдоль
            if dx >= dy:
                out.append([[lo[0] + 15, lo[1] + dy / 4, top], [hi[0] - 15, lo[1] + dy / 4, top],
                            [hi[0] - 15, hi[1] - dy / 4, top], [lo[0] + 15, hi[1] - dy / 4, top]])
            else:
                out.append([[lo[0] + dx / 4, lo[1] + 15, top], [lo[0] + dx / 4, hi[1] - 15, top],
                            [hi[0] - dx / 4, hi[1] - 15, top], [hi[0] - dx / 4, lo[1] + 15, top]])
        elif not as_points and long_ >= LINE_MIN and long_ / short >= LINE_RATIO:
            if dx >= dy:
                out.append([[lo[0] + short / 2, cy, top], [hi[0] - short / 2, cy, top]])
            else:
                out.append([[cx, lo[1] + short / 2, top], [cx, hi[1] - short / 2, top]])
        else:
            out.append([[cx, cy, top]])
    return out


def _cluster(strokes, limit: int):
    """Слишком много точек — слить по сетке (паста на плате: сотни площадок)."""
    pts = [s[0] for s in strokes]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    n = max(1, int(math.ceil(math.sqrt(limit))))
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cells: dict = {}
    for p in pts:
        i = min(n - 1, int((p[0] - x0) / max(x1 - x0, 1e-6) * n))
        j = min(n - 1, int((p[1] - y0) / max(y1 - y0, 1e-6) * n))
        cells.setdefault((i, j), []).append(p)
    return [[[sum(q[a] for q in g) / len(g) for a in range(3)]] for g in cells.values()]


def _order(strokes):
    """Обход без лишних перелётов: ближайший следующий, штрих — с ближнего конца."""
    if not strokes:
        return strokes
    rest = list(strokes)
    rest.sort(key=lambda s: (s[0][0], s[0][1]))
    out = [rest.pop(0)]
    while rest:
        end = out[-1][-1]
        best, flip, bd = 0, False, 1e30
        for i, s in enumerate(rest):
            for f, p in ((False, s[0]), (True, s[-1])):
                d = (p[0] - end[0]) ** 2 + (p[1] - end[1]) ** 2
                if d < bd:
                    best, flip, bd = i, f, d
        s = rest.pop(best)
        out.append(list(reversed(s)) if flip else s)
    return out


def bead_strokes(stl_path: str, pos: list[float], as_points: bool = False,
                 limit: int = MAX_POINTS) -> list[list[list[float]]]:
    """Штрихи робота по модели шва stl_path, стоящей в изделии на месте pos.
    as_points — только точки (пайка, сварка, винты): короткие куски и так точки,
    а вытянутый сварной шов проходится двумя точками по концам."""
    boxes = [transform_box(lo, hi, pos) + (area,) for lo, hi, area in pieces(read_stl(stl_path))]
    strokes = _strokes_of(boxes, as_points)
    if as_points:
        flat = []
        for s in strokes:
            flat += [[p] for p in s]
        strokes = flat
    if len(strokes) > limit:
        strokes = _cluster(strokes, limit)
    return [[[round(v, 1) for v in p] for p in s] for s in _order(strokes)]


def scan_strokes(lo: list[float], hi: list[float], standoff: float = 150.0,
                 passes: int = 3) -> list[list[list[float]]]:
    """Сканирование камерой: проходы вдоль длинной стороны над изделием."""
    z = hi[2] + standoff
    along_x = (hi[0] - lo[0]) >= (hi[1] - lo[1])
    out = []
    for k in range(passes):
        f = (k + 0.5) / passes
        if along_x:
            y = lo[1] + f * (hi[1] - lo[1])
            out.append([[lo[0] + 40.0, y, z], [hi[0] - 40.0, y, z]])
        else:
            x = lo[0] + f * (hi[0] - lo[0])
            out.append([[x, lo[1] + 40.0, z], [x, hi[1] - 40.0, z]])
    return [[[round(v, 1) for v in p] for p in s] for s in _order(out)]
