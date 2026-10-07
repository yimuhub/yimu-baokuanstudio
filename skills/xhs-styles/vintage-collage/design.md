# 风格包 · 复古拼贴 · 静默长文 (vintage-collage)

> 母题:**编辑杂志 × 复古版画拼贴 × 荧光笔标记 × 纸纹**。
> 灵魂一句话:**安静、近黑白、有纸感和拼贴的艺术长文**——不靠撞色,靠纹理 + 一抹荧光 + 一张老版画。
> 拆解来源:@joana_koehl「Spotlight Story Method」(2026-06-24 用户提供)。
> 三套对比:warm-editorial 暖克制 / memphis 多色俏皮 / **本套近单色 + 纸纹 + 拼贴**。

---

## 1. 配色(近黑白 + 一抹荧光)

| token | 值 | 用途 |
|---|---|---|
| `--paper` | `#F1EEE3` | 暖白纸底,**带纸纹颗粒** |
| `--ink` | `#1A1A1A` | 标题 + 正文(近黑) |
| `--lime` | `#D8F24A` | **唯一强调=荧光黄绿**,只做 marker 标记,点 1-2 个词 |
| `--muted` | `#8A857A` | 页脚灰 |
| 插画 | 纯黑白 | 版画 / halftone |

**铁律**:整张近单色。强调色只以"荧光笔划过关键词"的形式出现,**一张最多标 1-2 处**。绝不撞色。

---

## 2. 字体(双字:衬线标题 + 黑体正文)

```
hook 标题:高对比衬线,黑色 → 'WenJin Mincho Plane 0'(文津宋体) / 英文 'Playfair Display'
   稍加粗:-webkit-text-stroke:0.6px var(--ink)。★ 标题不加引号(见 §7),2 行内
正文(长文卡主角):无衬线 → 'Noto Sans SC'(思源黑体) / 英文 'Inter'
强调:英文可斜体;中文斜体丑 → 改用荧光 marker(见 §6)
```
引入:
```html
<link href="https://fontsapi.zeoseven.com/376/main/result.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Noto+Sans+SC:wght@400;500;700&family=Inter:wght@400;600&display=swap" rel="stylesheet">
```

字号(@1080×1440):
- hook 标题:`130–142px` / line-height `1.05`(**2 行内,别挤成 3 行;不加引号**)
- hook 副标:`38–40px` / line-height `1.5`
- 长文正文:`40–44px` / line-height `1.68` / 段间距 `40px`
- 页脚:`24px` / `--muted`

---

## 3. 招牌动作(必须有)

1. **黑白复古版画拼贴** —— 老木刻/版画(鸟、花、手、石膏像…),**白底用 `mix-blend-mode:multiply` 直接吃进纸里**(白消失,只留黑线)= 剪贴感。放 hook 卡右上角。
2. **荧光笔标记** —— 关键词覆一道荧光黄绿色块(`linear-gradient` 背景带,压在文字下半)。
3. **纸纹颗粒底** —— 本套**首次用纹理**(前两套都不用),SVG `feTurbulence` 噪点,低透明 multiply。
4. **高对比衬线大标题**(hook 卡)—— 左对齐,**不加引号**(见 §7),2 行内。

---

## 4. 氛围层(本套唯一靠纹理的)

纸纹 + 版画的木刻颗粒 = 全部艺术感来源。所以纹理**必须有**(和 warm-editorial / memphis 相反)。除纸纹外别再加做旧滤镜。

---

## 5. 版式骨架(1080×1440 · 左对齐 · 两种卡)

**A. hook 钩子卡**
```
                          [黑白版画 · 右上角 · multiply]
[大衬线标题(不加引号)· 2 行 · 左 · 垂直居中]
[无衬线副标 · 关键词带荧光]
[@handle 左 ·········· 栏目名 右]   ← 页脚
```
- 标题 + 副标用 `.main{position:absolute; top:51%; translateY(-50%)}` 垂直居中;插画 `absolute` 右上;页脚 `absolute` 底。

**B. longtext 纯长文卡**
```
[正文 · 无衬线 · 短句分行 · 大留白 · 垂直居中]
   (一处关键词带荧光 / 英文斜体)
[@handle 左 ·········· 栏目名 右]
```
- `body{display:flex; flex-direction:column; justify-content:center}` 正文垂直居中;页脚 absolute 底。

---

## 6. 实现素材

**纸纹(SVG 噪点,body::before):**
```css
body::before{ content:""; position:absolute; inset:0; pointer-events:none;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>");
  opacity:.10; mix-blend-mode:multiply; }
```

**荧光 marker:**
```css
.mark{ background:linear-gradient(var(--lime),var(--lime));
  background-size:100% 48%; background-position:0 74%; background-repeat:no-repeat; padding:0 4px; }
```

**版画拼贴(白底自动消失):**
```css
.illo{ mix-blend-mode:multiply; filter:grayscale(1) contrast(1.06); }
```
插画**用 base64 内嵌**(自包含、不踩相对路径坑)。

**插画来源(重要)**:
- 用户指定 **Heritage Type**(https://www.heritagetype.com/pages/free-vintage-illustrations,100% 免费可商用,按套下载 PNG+矢量)。
- ⚠️ **但 Heritage 的鸟/花多是彩色**;本套要黑白版画 → 要么把彩图 `grayscale(1)` 去色,要么改用纯黑白木刻。
- 纯黑白木刻备选:**Wikimedia Commons 的 Thomas Bewick 木刻鸟**(公共领域,纯线刻白底,multiply 完美)。API:`commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch=Bewick+bird+engraving&gsrnamespace=6&prop=imageinfo&iiprop=url&format=json`。本包样张用的就是 Bewick 黄鹀(`illo-bird-bewick-yellowhammer.png`)。
- **按内容自动选题材**(发声/表达→鸟;成长→植物;关系→手;等),不必每次问。

**渲染**:走 card-layout §8 管线;Chrome 加 `--virtual-time-budget=15000` 等 webfont 加载完。

---

## 7. do / don't

- ✅ 近单色 + 纸纹 + 一张黑白版画 + 1-2 处荧光。
- ✅ 版画用 multiply 吃进纸里;按内容选题材。
- ✅ 长文卡敢留白、短句分行。
- ❌ 不撞色、不加做旧滤镜(纸纹够了)、不让荧光标记超过 2 处、不用彩色插画(去色或换黑白木刻)。
- ❌ **标题不加引号**(中英文双引号 `""` / 中文 `「」` 都不加)——标题作为陈述句直接出现;加引号会显得局促、不自然。即便母题原图带引号,落到我们的标题也去掉。

---

## 8. 适合 / 不适合

适合:**心理 / 情感 / 成长长文、观点、故事、金句钩子** —— emotion-writing / 心灵旷野 量身定做。
不适合:信息密集的教程/清单/分类(那找 memphis)、需要明快活泼的(那找 memphis)。

---

## 9. 页面集(模块)· 9 种已配齐

`hook.html`(封面)+ `longtext.html`(正文/长文)+ `page-concept/data/compare/steps/quote/list/back.html`,各带 `sample-*.png`。通用:纸纹底 + 文津宋衬线标题 + 思源黑正文 + 荧光只点 1 处。本套是**长文主力**:纯长文连发 = hook + longtext×N + quote(高潮句)+ back。数据/对比/步骤也走安静版(serif 数字、细线分隔、不喧闹)。
