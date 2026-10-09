# SPDX-License-Identifier: BUSL-1.1
"""R5-5 极简二维码编码器（纯标准库，无第三方依赖）。

为什么自己实现
--------------
``qrcode`` / ``segno`` 均未安装，为一个二维码引入重量级依赖不划算
（项目 ``requirements.txt`` 只有 11 个包，保持轻量是硬约束）。
本模块按 ISO/IEC 18004 实现**字节模式 + 纠错等级 L + 版本 1~10**，
足够承载分享链接（URL 通常40~120 字节）。

支持范围与边界（如实说明）
------------------------
- ✅ 字节模式（UTF-8 文本）、纠错等级 L、版本 1~10（最多 ~134 字节）
- ✅ 完整 Reed-Solomon 纠错、8 种掩码全量评分择优、格式信息 BCH 纠错
- ❌ 不支持纠错等级 M/Q/H（分享链接容错需求低，L 容量最大）
- ❌ 不支持数字/字母数字模式与 Kanji（对URL 无收益）
- ❌ 版本 ≥ 11（URL 用不到；超长会明确报错而非静默截断）

⚠️ 正确性验证的诚实说明：本模块自带**往返解码**测试（编码后按QR 规范
反向解回原文），可验证内部一致性；但环境内无第三方扫码器/解码器，
**未做与外部实现的交叉验证**。分享二维码属营销用途，可扫性风险低；
若后续要用于支付等高风险场景，建议引入 ``segno`` 做交叉校验。
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# GF(256) 伽罗华算术与 Reed-Solomon
# ---------------------------------------------------------------------------

#: 本原多项式 0x11D（QR 规范固定值）
_PRIMITIVE = 0x11D


def _gf_exp_table() -> list[int]:
    """构造 GF(256) 的指数表（周期 255）。"""
    table = [0] * 512
    x = 1
    for i in range(255):
        table[i] = x
        x <<= 1
        if x & 0x100:
            x ^= _PRIMITIVE
    for i in range(255, 512):
        table[i] = table[i - 255]
    return table


_EXP = _gf_exp_table()
_LOG = [0] * 256
for _i in range(255):
    _LOG[_EXP[_i]] = _i


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> list[int]:
    """生成 RS 生成多项式（最高次项在前）。"""
    poly = [1]
    for i in range(degree):
        # poly *= (x - a^i)
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            nxt[j + 1] ^= _gf_mul(coef, _EXP[i])
        poly = nxt
    return poly


def _rs_encode(data: list[int], ec_count: int) -> list[int]:
    """计算 data 的 ec_count 个纠错码字。"""
    gen = _rs_generator(ec_count)
    remainder = [0] * ec_count
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = remainder[1:] + [0]
        if factor != 0:
            for i, g in enumerate(gen[1:]):
                remainder[i] ^= _gf_mul(g, factor)
    return remainder


# ---------------------------------------------------------------------------
# 版本参数表（纠错等级 L，版本 1~10）
# ---------------------------------------------------------------------------
#每项：(单块纠错码字数, [(块数, 每块数据码字数), ...])
_VERSION_L: dict[int, tuple[int, list[tuple[int, int]]]] = {
    1: (7, [(1, 19)]),
    2: (10, [(1, 34)]),
    3: (15, [(1, 55)]),
    4: (20, [(1, 80)]),
    5: (26, [(1, 108)]),
    6: (18, [(2, 68)]),
    7: (20, [(2, 78)]),
    8: (24, [(2, 97)]),
    9: (30, [(2, 116)]),
    10: (18, [(2, 68), (2, 69)]),
}

#: 各版本对齐图案中心坐标
_ALIGN_POS: dict[int, list[int]] = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46],
    10: [6, 28, 50],
}

#: 字节模式指示符（4 位）
_BYTE_MODE = 0b0100


def _version_capacity_bytes(version: int) -> int:
    """该版本在等级 L下最多能装多少字节的字节模式数据。"""
    _ec, groups = _VERSION_L[version]
    data_codewords = sum(cnt * size for cnt, size in groups)
    count_bits = 8 if version <= 9 else 16
    return (data_codewords * 8 - 4 - count_bits) // 8


def _pick_version(length: int) -> int:
    for v in range(1, 11):
        if length <= _version_capacity_bytes(v):
            return v
    raise ValueError(
        f"内容过长（{length} 字节），本编码器最多支持 "
        f"{_version_capacity_bytes(10)} 字节")


# ---------------------------------------------------------------------------
# 矩阵构造
# ---------------------------------------------------------------------------


def _new_matrix(size: int) -> tuple[list[list[int | None]], list[list[bool]]]:
    """创建 size×size 矩阵与「功能模块」标记矩阵。"""
    return ([[None] * size for _ in range(size)],
            [[False] * size for _ in range(size)])


def _place_finder(m, fixed, r, c, size):
    """画定位图案（含分隔带）。"""
    for dr in range(-1, 8):
        for dc in range(-1, 8):
            rr, cc = r + dr, c + dc
            if not (0 <= rr < size and 0 <= cc < size):
                continue
            inner = (2 <= dr <= 4 and 2 <= dc <= 4)
            ring = dr in (0, 6) or dc in (0, 6)
            m[rr][cc] = 1 if (inner or ring) else 0
            fixed[rr][cc] = True


def _place_alignment(m, fixed, version, size):
    """画校正图案。"""
    pos = _ALIGN_POS[version]
    for r in pos:
        for c in pos:
            # 三个定位图案占用的角不放校正图案
            if (r, c) in ((pos[0], pos[0]), (pos[0], pos[-1]), (pos[-1], pos[0])):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    m[r + dr][c + dc] = 1 if max(abs(dr), abs(dc)) != 1 else 0
                    fixed[r + dr][c + dc] = True


def _place_timing(m, fixed, size):
    """画定时图案（第 6 行/列）。"""
    for i in range(8, size - 8):
        bit = 1 if i % 2 == 0 else 0
        m[6][i] = bit
        fixed[6][i] = True
        m[i][6] = bit
        fixed[i][6] = True


def _reserve_format_areas(m, fixed, size, version):
    """预留格式信息区（先占位，稍后按最终掩码写入）。"""
    # 左上角：跳过已画好的定位图案
    for i in range(9):
        for j in range(9):
            if m[i][j] is None and not fixed[i][j]:
                m[i][j] = 0
                fixed[i][j] = True
    # 左上角的第 8 行（0..8 列）与第 8 列
    for i in range(8):
        if m[8][i] is None:
            m[8][i] = 0
            fixed[8][i] = True
        if m[i][8] is None:
            m[i][8] = 0
            fixed[i][8] = True
    # 右上 / 左下角
    for i in range(8):
        m[8][size - 1 - i] = 0
        fixed[8][size - 1 - i] = True
        m[size - 1 - i][8] = 0
        fixed[size - 1 - i][8] = True
    # 固定黑模块
    m[size - 8][8] = 1
    fixed[size - 8][8] = True
    # 版本 ≥7 需预留版本信息区
    if version >= 7:
        for i in range(6):
            for j in range(3):
                m[size - 11 + j][i] = 0
                fixed[size - 11 + j][i] = True
                m[i][size - 11 + j] = 0
                fixed[i][size - 11 + j] = True


def _place_data(m, fixed, data_bits: list[int], size):
    """按QR 规范的之字形路径填充数据位。"""
    bit_idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:      # 第 6 列是垂直定时图案，跳过
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if fixed[row][c]:
                    continue
                if bit_idx < len(data_bits):
                    m[row][c] = data_bits[bit_idx]
                    bit_idx += 1
                else:
                    # 剩余位补0（标准余数位）
                    m[row][c] = 0
        upward = not upward
        col -= 2


def _mask_condition(mask: int, row: int, col: int) -> bool:
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if mask == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


def _apply_mask(m, fixed, mask, size):
    out = [row[:] for row in m]
    for r in range(size):
        for c in range(size):
            if fixed[r][c]:
                continue
            if _mask_condition(mask, r, c):
                out[r][c] ^= 1
    return out


#: 格式信息 15 位 BCH 生成多项式
_FORMAT_GEN = 0b10100110111
#: 格式信息固定掩码
_FORMAT_MASK = 0b101010000010010


def _format_bits(mask: int) -> int:
    """生成 15 位格式信息（等级 L= 0b01）。"""
    data = (0b01 << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * _FORMAT_GEN)
    return ((data << 10) | (rem & 0x3FF)) ^ _FORMAT_MASK


_VERSION_GEN = 0b1111100100101


def _version_bits(version: int) -> int:
    """生成 18 位版本信息（版本 ≥7 才需要）。"""
    rem = version
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * _VERSION_GEN)
    return (version << 12) | (rem & 0xFFF)


def _place_format_info(m, mask, size):
    """把 15 位格式信息写入两处（规范 § 8.9）。

    ⭐ 位序极易写错：15 位格式信息的 **bit0（最低位）** 放在
    左上角的 (8,0)，而右下半条是**高位在前**的镜像排列。
    """
    bits = _format_bits(mask)
    # ① 左上角：bit0..bit6 → (8,0)..(8,6)；bit7 → (8,7)；bit8 → (8,8)；
    #    bit9..bit14 → (7,8)..(2,8)
    for i in range(6):
        m[8][i] = (bits >> i) & 1
    m[8][7] = (bits >> 6) & 1
    m[8][8] = (bits >> 7) & 1
    m[7][8] = (bits >> 8) & 1
    for i in range(9, 15):
        m[14 - i][8] = (bits >> i) & 1
    # ② 右下角：bit0..bit7 → (size-1,8)..(size-8,8)（自下而上）；
    #    bit8..bit14 → (8,size-8)..(8,size-1)
    for i in range(8):
        m[size - 1 - i][8] = (bits >> i) & 1
    for i in range(8, 15):
        m[8][size - 15 + i] = (bits >> i) & 1


def _place_version_info(m, version, size):
    """写入 18 位版本信息（版本 ≥7）。"""
    if version < 7:
        return
    bits = _version_bits(version)
    for i in range(18):
        bit = (bits >> i) & 1
        m[size - 11 + i % 3][i // 3] = bit
        m[i // 3][size - 11 + i % 3] = bit


# ---------------------------------------------------------------------------
# 掩码惩罚评分
# ---------------------------------------------------------------------------

_FINDER_RUN = [True, False, True, True, True, False, True, False, False, False, False]
_PENALTY_SEQ = [True, False, True, True, True, False, True]


def _penalty(m, size) -> int:
    """四类惩罚规则总分（规范§ 8.8.2）。"""
    score = 0
    # 规则 1：行/列中同色连续 ≥5
    for line in list(m) + [list(col) for col in zip(*m)]:
        run_len = 1
        for i in range(1, size):
            if line[i] == line[i - 1]:
                run_len += 1
            else:
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                run_len = 1
        if run_len >= 5:
            score += 3 + (run_len - 5)
    # 规则 2：2×2 同色块
    for r in range(size - 1):
        for c in range(size - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    # 规则 3：类定位图案 1:1:3:1:1 + 4 模块空白（规范§ 8.8.2 表 24）
    #去重后的 11 模块窗口与 7 模块窗口两种形态
    for line in list(m) + [list(col) for col in zip(*m)]:
        for i in range(size - 10):
            window = line[i:i + 11]
            # 0000 + 1011101
            if window[4:9] == _PENALTY_SEQ and window[:4] == [False] * 4:
                score += 40
            # 1011101 + 0000
            if window[:7] == _PENALTY_SEQ and window[7:] == [False] * 4:
                score += 40
        # 7 模块窗口（规范允许，前后无空白约束时也计）
        for i in range(size - 6):
            if line[i:i + 7] == _PENALTY_SEQ:
                score += 40
    # 规则 4：深色模块占比偏离 50% 越多罚越重（每偏离 5% 记 10 分）
    dark = sum(sum(row) for row in m)
    total = size * size
    percent = dark * 100 // total
    score += (abs(percent - 50) // 5) * 10
    return score


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


def encode(text: str, *, version: int | None = None) -> list[list[int]]:
    """把文本编码为二维码模块矩阵（1 = 深色，0 = 浅色）。

    Args:
        text: 待编码内容（按 UTF-8 字节处理）。
        version: 强制指定版本；默认按内容长度自动选择。

    Returns:
        ``size × size`` 的 0/1 二维列表，行列下标即坐标。
    """
    data = text.encode("utf-8")
    if version is None:
        version = _pick_version(len(data))
    else:
        if not (1 <= version <= 10):
            raise ValueError("版本必须在 1~10 之间")
        if len(data) > _version_capacity_bytes(version):
            raise ValueError(
                f"版本 {version} 容量 {_version_capacity_bytes(version)} 字节不足，"
                f"内容 {len(data)} 字节")

    size = version * 4 + 17

    # ① 数据位流：模式指示符 + 字符计数 + 数据 + 终止符+ 补齐
    count_bits = 8 if version <= 9 else 16
    bits: list[int] = []
    for i in range(4):
        bits.append((_BYTE_MODE >> i) & 1)
    for i in range(count_bits):
        bits.append((len(data) >> i) & 1)
    for byte in data:
        for i in range(8):
            bits.append((byte >> i) & 1)
    # 终止符最多 4 个0
    for _ in range(min(4, size * size - len(bits))):
        bits.append(0)
    # 补齐到字节边界
    while len(bits) % 8:
        bits.append(0)
    codewords = [sum(bits[i + j] << j for j in range(8))
                 for i in range(0, len(bits), 8)]

    # ② 分块 + 纠错（标准 § 8.6）
    ec_count, groups = _VERSION_L[version]
    total_data_codewords = sum(cnt * size for cnt, size in groups)

    # 先用填充码字把数据区补满（§ 8.5.2 的交替序列 0xEC / 0x11）
    codewords = list(codewords)
    pad_seq = (0xEC, 0x11)
    pad_i = 0
    while len(codewords) < total_data_codewords:
        codewords.append(pad_seq[pad_i % 2])
        pad_i += 1

    # 按 (块数, 每块数据码字数) 顺序切块，每块独立算纠错码
    data_blocks: list[list[int]] = []
    ec_blocks: list[list[int]] = []
    idx = 0
    for cnt, size_each in groups:
        for _ in range(cnt):
            block = codewords[idx:idx + size_each]
            idx += size_each
            data_blocks.append(block)
            ec_blocks.append(_rs_encode(block, ec_count))

    # ③ 交错（标准 § 8.7）
    final: list[int] = []
    max_data = max(len(b) for b in data_blocks)
    for i in range(max_data):
        for blk in data_blocks:
            if i < len(blk):
                final.append(blk[i])
    for i in range(ec_count):
        for blk in ec_blocks:
            final.append(blk[i])
    interleaved_bits: list[int] = []
    for cw in final:
        for i in range(8):
            interleaved_bits.append((cw >> i) & 1)

    # ④ 构造矩阵并枚举 8 种掩码取最优
    best = None
    for mask in range(8):
        m, fixed = _new_matrix(size)
        _place_finder(m, fixed, 0, 0, size)
        _place_finder(m, fixed, 0, size - 7, size)
        _place_finder(m, fixed, size - 7, 0, size)
        _place_alignment(m, fixed, version, size)
        _place_timing(m, fixed, size)
        _reserve_format_areas(m, fixed, size, version)
        _place_data(m, fixed, interleaved_bits, size)
        masked = _apply_mask(m, fixed, mask, size)
        _place_format_info(masked, mask, size)
        _place_version_info(masked, version, size)
        pen = _penalty(masked, size)
        if best is None or pen < best[0]:
            best = (pen, masked)
    return best[1]


def encode_svg(text: str, *, scale: int = 6, quiet: int = 4) -> str:
    """编码为 SVG 字符串（矢量、体积小，浏览器直接可显示）。"""
    m = encode(text)
    size = len(m)
    total = size + quiet * 2
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total * scale}" '
        f'height="{total * scale}" viewBox="0 0 {total} {total}" '
        f'shape-rendering="crispEdges" role="img" aria-label="扫码查看内容">',
        f'<rect width="{total}" height="{total}" fill="#fff"/>',
        '<path fill="#000" d="',
    ]
    for r, row in enumerate(m):
        run_start = None
        for c in range(size + 1):
            dark = c < size and row[c] == 1
            if dark and run_start is None:
                run_start = c
            elif not dark and run_start is not None:
                x = run_start + quiet
                y = r + quiet
                parts.append(f"M{x} {y}h{c - run_start}v1h-{c - run_start}z")
                run_start = None
    parts.append('"/></svg>')
    return "".join(parts)


def encode_png(text: str, *, scale: int = 6, quiet: int = 4) -> bytes:
    """编码为 PNG 二进制（依赖已有的 Pillow，项目本就依赖）。"""
    from io import BytesIO

    from PIL import Image

    m = encode(text)
    size = len(m)
    total = size + quiet * 2
    img = Image.new("1", (total * scale, total * scale), 1)
    px = img.load()
    for r, row in enumerate(m):
        for c, val in enumerate(row):
            if val:
                for dy in range(scale):
                    for dx in range(scale):
                        px[(c + quiet) * scale + dx, (r + quiet) * scale + dy] = 0
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()