"""
写真のカメラを、写真の中の点と建物の点の対応から求める（ストリートビューのスクショ用）。

ストリートビューの性質を前提にして、求めるものを減らす:
  - カメラの高さは地面から 2.5m（× ワールドの縮尺）、横の傾き（ロール）は 0
  - 写真の中心が画面の中心
求めるもの: カメラの位置 x, z、向き yaw（Minecraft と同じ: 0=南, -90=東）、pitch（下向き+）、
           焦点距離 f（px）、それと高さの分からない点の高さ（例: 帯の上端）。

座標は Minecraft と同じ（x 東、y 上、z 南）。ブロック (x,y,z) は [x,x+1]×[y,y+1]×[z,z+1] を占める。
"""

import math

import numpy as np
from scipy.optimize import least_squares


def axes(yaw, pitch):
    """視線 f・右 r・上 u（render.py の render_view と同じ向きの決め方）。"""
    yr, pr = math.radians(yaw), math.radians(pitch)
    f = np.array([-math.sin(yr) * math.cos(pr), -math.sin(pr), math.cos(yr) * math.cos(pr)])
    r = np.cross(f, [0, 1, 0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return f, r, u


class Camera:
    def __init__(self, pos, yaw, pitch, focal, size):
        self.pos = np.asarray(pos, dtype=float)
        self.yaw, self.pitch, self.focal = yaw, pitch, focal
        self.w, self.h = size
        self.f, self.r, self.u = axes(yaw, pitch)

    def project(self, pts):
        """世界の点 (N,3) → 画素 (N,2)。カメラの後ろは nan。"""
        d = np.asarray(pts, dtype=float) - self.pos
        zc = d @ self.f
        x = self.w / 2 + self.focal * (d @ self.r) / zc
        y = self.h / 2 - self.focal * (d @ self.u) / zc
        out = np.stack([x, y], axis=-1)
        out[zc <= 0.1] = np.nan
        return out

    def ray(self, px):
        """画素 (u,v) → 視線の向き（単位ベクトル）。"""
        u, v = px
        d = self.f + (u - self.w / 2) / self.focal * self.r - (v - self.h / 2) / self.focal * self.u
        return d / np.linalg.norm(d)

    def on_wall(self, px, a, b):
        """画素 (u,v) が、点 a→b（平面の (x,z)）を通る鉛直な壁の面の上にあるとして、その3D点を返す。"""
        a, b = np.asarray(a, float), np.asarray(b, float)
        n = np.array([-(b[1] - a[1]), 0.0, b[0] - a[0]])
        d = self.ray(px)
        t = n @ (np.array([a[0], 0.0, a[1]]) - self.pos) / (n @ d)
        return self.pos + t * d

    def on_vertical(self, px, xz):
        """画素 (u,v) が、点 xz を通る鉛直線の上にあるとして、その高さ y を返す（角の縦線の上端など）。"""
        d = self.ray(px)
        hor = np.array([d[0], d[2]])
        t = hor @ (np.asarray(xz, float) - self.pos[[0, 2]]) / (hor @ hor)
        return float(self.pos[1] + t * d[1])

    @property
    def vfov(self):
        """縦の視野角（度）。render_view の vfov に渡せる。"""
        return math.degrees(2 * math.atan(self.h / 2 / self.focal))

    def __repr__(self):
        return (f"Camera(pos=({self.pos[0]:.1f}, {self.pos[1]:.1f}, {self.pos[2]:.1f}), yaw={self.yaw:.1f}, "
                f"pitch={self.pitch:.1f}, vfov={self.vfov:.1f})")


def solve(points, size, eye_y, guess, unknown_heights=()):
    """points: [(画素 (u,v), 世界 (x, y または "名前", z))]。y を文字列にすると、その名前の高さも求める。
    eye_y: カメラの目の高さ（ワールドの y）。None なら guess["eye_y"] から一緒に求める。
    guess: dict(x, z, yaw, pitch, vfov, 高さの名前...)。
    戻り値: (Camera, {高さの名前: y}, 画素の誤差の一覧)"""
    names = sorted({p[1][1] for p in points if isinstance(p[1][1], str)} | set(unknown_heights))
    w, h = size

    fit_eye = eye_y is None

    def unpack(v):
        x, z, yaw, pitch, logf = v[:5]
        rest = list(v[5:])
        ey = rest.pop(0) if fit_eye else eye_y
        return Camera((x, ey, z), yaw, pitch, math.exp(logf), size), dict(zip(names, rest))

    def resid(v):
        cam, hs = unpack(v)
        world = np.array([[p[1][0], hs[p[1][1]] if isinstance(p[1][1], str) else p[1][1], p[1][2]] for p in points])
        px = cam.project(world)
        px = np.nan_to_num(px, nan=1e4)
        return (px - np.array([p[0] for p in points], dtype=float)).ravel()

    f0 = h / 2 / math.tan(math.radians(guess.get("vfov", 60)) / 2)
    v0 = [guess["x"], guess["z"], guess["yaw"], guess.get("pitch", 0.0), math.log(f0)]
    v0 += ([guess["eye_y"]] if fit_eye else []) + [guess[n] for n in names]
    res = least_squares(resid, v0, x_scale="jac")
    cam, hs = unpack(res.x)
    err = np.linalg.norm(res.fun.reshape(-1, 2), axis=1)
    return cam, hs, err
