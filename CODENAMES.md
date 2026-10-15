# 版本代号序列（CODENAMES）

> 代号分配铁律：**新版本号大于 `release-codenames.json` 中的 `current_version`，即取序列下一个代号**。与版本号跳跃幅度无关，不回退、不跳过、不重用。

## 一、分配规则

1. 唯一判定条件：新版本号 > 当前版本（按语义化版本数字比较，`_t("v10.1.1") > _t("v10.1")`）。
2. 严格顺序消耗：取 `sequence[next_index]`，然后 `next_index + 1`，`current_version` 更新为新版本，`history` 追加一条。
3. 跳跃不跳过：v10.1 → v11.0 直接大跳，也只消耗 1 个代号。
4. 新版本 ≤ 当前版本时拒绝分配（重复发布/回滚不消耗序列）。
5. 双库同步发布同一版本号时（如本地/云端同发 v10.1.1），使用同一代号，序列只消耗一次；独有功能独立发布时各自消耗（见 `SYNC.md`）。
6. 序列耗尽：剩余 ≤ 3 个时预警，生成下一批续上；不自动循环重用。

分配逻辑（供工具直接用）：

```python
def _t(v):
    p = [int(x) for x in v.lstrip("v").split(".")]
    return tuple(p + [0] * (3 - len(p)))

def next_codename(state, new_version):
    if _t(new_version) <= _t(state["current_version"]):
        raise ValueError(f"版本号未前进: {new_version} <= {state['current_version']}，不分配代号")
    i = state["next_index"]
    if i >= len(state["sequence"]):
        raise RuntimeError("代号序列已耗尽，请生成下一批后续上")
    c = state["sequence"][i]
    state["history"].append({"version": new_version, "zh": c["zh"], "en": c["en"]})
    state["current_version"] = new_version
    state["current_codename_zh"] = c["zh"]
    state["current_codename_en"] = c["en"]
    state["next_index"] = i + 1
    return c
```

## 二、历史代号统一表（已消耗，不再分配）

| 版本 | 代号 | 英文 | 发布日期 |
|---|---|---|---|
| v9.4.0 | 破阵子 | Storm Breaker | 2026-10-14 |
| v9.4.1 | 沉影吟 | Shadow Rhythm | 2026-10-14 |
| v9.4.2 | 回响曲 | Echo Melody | 2026-10-14 |
| v9.4.3 | 流云赋 | Flowing Clouds | 2026-10-14 |
| v9.4.4 | 澄澈镜 | Pristine Mirror | 2026-10-14 |
| v9.4.5 | 澄音境 | Pristine Rhythm | 2026-10-14 |
| v10 | 鸿蒙始 | Primordial Dawn | 2026-10-14 |
| v10.0.0 | 鸿蒙始 | Primordial Dawn | 2026-10-14 |
| v10.0.1 | 鸿蒙始 | Primordial Dawn | 2026-10-15 |
| v10.0.2 | 鸿蒙始 | Primordial Dawn | 2026-10-15 |
| v10.1 | 鸿蒙始 | Primordial Dawn | 2026-10-15 |

去重结论：以下 66 个新代号经程序校验，内部无重复，且与历史 7 个代号（破阵子/沉影吟/回响曲/流云赋/澄澈镜/澄音境/鸿蒙始）无任何重叠。

## 三、代号序列（66 个，自 v10.1 之后启用）

| # | 中文 | 英文 |
|---|---|---|
| 1 | 曦光序 | Dawnlight Overture |
| 2 | 云汉章 | Milky Way Verse |
| 3 | 星河纪 | Starfall Chronicle |
| 4 | 长风谣 | Longwind Ballad |
| 5 | 沧海吟 | Oceanic Ode |
| 6 | 山岳赋 | Mountain Hymn |
| 7 | 江河曲 | River Rhapsody |
| 8 | 松涛境 | Pinewave Realm |
| 9 | 竹韵篇 | Bamboo Rhythm |
| 10 | 梅雪镜 | Plum-Snow Mirror |
| 11 | 兰心曲 | Orchid Melody |
| 12 | 荷风吟 | Lotus Breeze Chant |
| 13 | 菊秋赋 | Autumn Chrysanthemum Ode |
| 14 | 霜林传 | Frostwood Tale |
| 15 | 雪原纪 | Snowfield Record |
| 16 | 雷火令 | Thunderfire Edict |
| 17 | 虹霓桥 | Rainbow Span |
| 18 | 月华章 | Moonlit Verse |
| 19 | 日曜篇 | Sunblaze Scroll |
| 20 | 乾坤颂 | Cosmos Anthem |
| 21 | 云阙吟 | Cloud Palace Chant |
| 22 | 琼楼赋 | Jade Tower Ode |
| 23 | 碧霄曲 | Azure Sky Melody |
| 24 | 紫微章 | Ziwei Palace Verse |
| 25 | 太微纪 | Supreme Palace Record |
| 26 | 天市谣 | Celestial Market Ballad |
| 27 | 金乌纪 | Golden Crow Chronicle |
| 28 | 玉兔谣 | Jade Rabbit Ballad |
| 29 | 繁星赋 | Myriad Stars Ode |
| 30 | 晓星吟 | Morning Star Chant |
| 31 | 岱宗篇 | Mount Tai Chapter |
| 32 | 华岳章 | Mount Hua Verse |
| 33 | 衡岳纪 | Southern Peak Record |
| 34 | 嵩岳吟 | Mount Song Chant |
| 35 | 瀚海曲 | Vast Expanse Melody |
| 36 | 漓江赋 | Li River Ode |
| 37 | 洞庭镜 | Dongting Lake Mirror |
| 38 | 云梦泽 | Cloud-Dream Marsh |
| 39 | 桃源境 | Peach Blossom Realm |
| 40 | 杏林传 | Apricot Forest Tale |
| 41 | 桂魄章 | Osmanthus Moon Verse |
| 42 | 芙蓉曲 | Hibiscus Melody |
| 43 | 芦荻吟 | Reed Chant |
| 44 | 苔痕篇 | Moss Trace Chapter |
| 45 | 藤萝境 | Wisteria Realm |
| 46 | 霖雨赋 | Timely Rain Ode |
| 47 | 甘露篇 | Sweet Dew Chapter |
| 48 | 霜钟纪 | Frost Bell Record |
| 49 | 雪霁章 | Snow-Clearing Verse |
| 50 | 风雷引 | Wind-Thunder Prelude |
| 51 | 青铜铭 | Bronze Inscription |
| 52 | 瑶琴曲 | Jade Zither Melody |
| 53 | 羌笛吟 | Qiang Flute Chant |
| 54 | 云锦章 | Cloud Brocade Verse |
| 55 | 霓裳序 | Rainbow Skirt Overture |
| 56 | 广陵散 | Guangling Verses |
| 57 | 高山曲 | High Mountain Melody |
| 58 | 阳关谣 | Yangguan Ballad |
| 59 | 梅花引 | Plum Blossom Prelude |
| 60 | 汉宫秋 | Autumn in Han Palace |
| 61 | 龙腾纪 | Dragon Soaring Record |
| 62 | 凤仪章 | Phoenix Bearing Verse |
| 63 | 麟凤篇 | Qilin-Phoenix Chapter |
| 64 | 河清篇 | River Clearing Chapter |
| 65 | 海晏图 | Calm Sea Scroll |
| 66 | 太平令 | Great Peace Edict |

## 四、release 标题格式

`vX.Y.Z - 代号 · English (本版说明)`，例如：`v10.1.1 - 曦光序 · Dawnlight Overture (版本与发布规范落地）`。
