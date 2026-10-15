# 双库同步说明（SYNC）

> 本文件在本地部署版与云端部署版两库根目录各放一份，内容相同。修改版本相关内容前，请先阅读 `VERSION_RULES.md`（第零条）。

## 一、双库信息

| | 本地部署版 | 云端部署版 |
|---|---|---|
| Mac 路径 | `/Users/czmj/Documents/yimu-baokuanstudio` | `/Users/czmj/Documents/yimu-baokuanstudio-cloud` |
| GitHub | `https://github.com/yimuhub/yimu-baokuanstudio` | `https://github.com/yimuhub/yimu-baokuanstudio-cloud` |

两库为同一产品的两种部署形态，互相链接、同步演进。

## 二、同步更新要求

任何**非独有功能**的修改，必须在两库**同步进行更新**：

1. 同一次变更内容合入两库；
2. 两库取**相同版本号**；
3. 两库各自打 tag、建 release（代号相同，代号序列只消耗一次）；
4. 提交信息格式：`release(vX.Y.Z): 一句话说明`。

## 三、豁免规则：独有功能

- **云端部署版独有功能**：仅在云端库更新，云端库按 `VERSION_RULES.md` 独立升版并取下一个代号；**本地库不同步、不升版**。
- **本地部署版独有功能**：对称处理——仅在本地库更新，本地库独立升版并取下一个代号；**云端库不同步、不升版**。
- 独有功能发布时，仍需更新本库的 `release-codenames.json`（`current_version`、`next_index`、`history`），另一库的文件不动。两库的 `next_index` 因此可能不再一致，这是正常的。

## 四、判断流程

```
有新变更
 └─ 是某一方独有功能？（看需求归属）
     ├─ 是 → 只更新归属库，按版本规则独立升版+取代号
     └─ 否 → 两库同步更新，取相同版本号，共享同一代号
```
