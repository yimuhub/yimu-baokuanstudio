# 贡献指南 (Contributing Guide)

感谢你关注并有意向为 **一幕·YIMU 爆款工作室** 贡献代码！我们欢迎所有社区开发者提出问题、建议与 Pull Request。

---

## 规范与原则

1. **版本号单一真源铁律**：全项目版本号以 [`version.py`](version.py) 中的 `__version__` 为唯一真源，严禁在业务逻辑中硬编码截断或伪造版本号。
2. **影视级配图铁律**：涉及文章配图生成的逻辑，必须坚持“先通读全文、再总结分镜、段落1:1精准回填”的视听语言标准，严禁粗暴盲盒出图。
3. **零敏感信息承诺**：严禁提交任何真实的 API Key、测试 Token、密码、私有数据库或用户隐私数据。
4. **门禁全绿**：任何合并至 `main` 分支的 PR，必须保证 `bash ci.sh` 四道门禁全部通过。

---

## 本地开发流程

### 1. 环境准备
```bash
git clone https://github.com/your-username/yimu-baokuanstudio.git
cd yimu-baokuanstudio

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 本地测试
```bash
# 运行单元测试
pytest

# 运行完整 CI 门禁检查（单元测试、探针、术语扫描、密钥扫描）
bash ci.sh
```

### 3. 提交代码与 Pull Request
- 分支命名建议：`feature/xxx`、`fix/xxx`、`docs/xxx`
- Commit Message 遵循语义化提交规范（如 `feat(...)`, `fix(...)`, `docs(...)`, `chore(...)`）
- 提交前务必运行 `bash ci.sh` 确保 4 步全绿。

---

感谢对开源社区的贡献与支持！
