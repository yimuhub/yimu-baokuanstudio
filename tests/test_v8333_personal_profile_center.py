"""V8.3.33 个人中心会员与账本深度整合、套餐卡片点击交互、修改密码端到端质量验证。

验证目标：
1. 版本单一真源 __version__ == '8.3.33'；
2. 侧边栏左下角固定展示版本号卡片/按钮，绑定 checkSystemUpdate(true)；
3. 侧边栏底部的「个人中心」入口保留 side-auth-badge 兼容；
4. 主内容区独立的个人中心面板（#p-profile）深度集成「会员权益与调用账本」（#profile-billing-section）：
   - 包含会员档位与额度统计（#blN-tier, #blN-upgrade）；
   - 包含可点击交互的会员档位卡片（.billing-plan-card，支持 selectBillingPlan）；
   - 包含卡密核销入口（#profile-cdkey-input, redeemProfileKey）；
   - 包含模型调用账本表格与分页（#blN-ledger-tb, #blN-more）；
5. 商业化充值弹窗（#m-billing）中所有套餐卡片（Free / Pro / Studio）均支持点击交互高亮选中；
6. 账号通行证弹窗（#m-login）支持修改密码 Tab（#auth-tab-password），并成功打通后端 POST /api/auth/change_password 接口；
7. 移动端与全站版本号一致性无断层。
"""
from pathlib import Path
import pytest
import version
from fastapi.testclient import TestClient
from web.admin import app


def test_v8333_version_single_source_of_truth():
    """验证单一真源版本号已升级至 9.1.1"""
    assert version.__version__ == "9.2.0"
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")
    mobile_html = Path("web/templates/mobile.html").read_text(encoding="utf-8")
    readme_md = Path("README.md").read_text(encoding="utf-8")
    license_txt = Path("LICENSE").read_text(encoding="utf-8")

    assert "V9.2.0" in index_html
    assert "9.2.0" in index_html
    assert "V9.2.0" in mobile_html
    assert "version-9.2.0" in readme_md
    assert "V9.2.0" in license_txt


def test_v8333_sidebar_profile_and_fixed_version():
    """验证左侧边栏底部的个人中心入口与左下角固定版本号检查更新"""
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")

    # 1. 导航项中具备个人中心
    assert 'data-p="profile"' in index_html
    assert 'id="nav-item-profile"' in index_html
    assert '个人中心' in index_html

    # 2. 侧边栏底部升级个人中心入口，并保留 side-auth-badge 供 updateAuthUI 兼容
    assert 'id="side-user-profile-btn"' in index_html
    assert 'onclick="switchToProfileCenter()"' in index_html
    assert 'id="side-auth-badge"' in index_html

    # 3. 左下角固定版本号卡片与检查更新触发器
    assert 'id="side-version-badge"' in index_html or 'class="side-version-bar"' in index_html
    assert 'onclick="checkSystemUpdate(true)"' in index_html
    assert 'id="side-version-text"' in index_html
    assert "V9.2.0" in index_html


def test_v8333_personal_center_billing_integration():
    """验证会员与账本已成功挪到个人中心，并具备完整 DOM 契约与交互组件"""
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")

    # 1. 控制中心已移除 sp-billing 子标签与子视图
    assert 'id="sp-billing"' not in index_html

    # 2. 个人中心内嵌 profile-billing-section
    assert 'id="profile-billing-section"' in index_html
    assert '会员权益与算力调用账本' in index_html

    # 3. 会员与额度展示关键 ID 保留
    assert 'id="blN-tier"' in index_html
    assert 'id="blN-upgrade"' in index_html
    assert 'id="blN-ledger-tb"' in index_html
    assert 'id="blN-more"' in index_html

    # 4. 账本内包含可点击的会员套餐卡片
    assert 'selectBillingPlan(this, \'free\')' in index_html
    assert 'selectBillingPlan(this, \'pro\')' in index_html
    assert 'selectBillingPlan(this, \'studio\')' in index_html

    # 5. 卡密核销入口
    assert 'id="profile-cdkey-input"' in index_html
    assert 'redeemProfileKey()' in index_html


def test_v8333_billing_modal_plan_clickable():
    """验证算力账本弹窗内套餐卡片支持点击选中与快速操作"""
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")

    assert 'id="m-billing"' in index_html
    assert 'billing-plan-card' in index_html
    assert 'billing-modal-selected-tag' in index_html
    assert 'billing-action-bar' in index_html
    assert 'quickApplySelectedPlan()' in index_html
    assert 'fillBillingCdKey(' in index_html


def test_v8333_auth_change_password_feature():
    """验证账号与口令具备修改账号密码功能（前端弹窗与后端 API）"""
    index_html = Path("web/templates/index.html").read_text(encoding="utf-8")

    # 1. 通行证弹窗包含修改密码 Tab 与表单
    assert 'id="auth-tab-password"' in index_html
    assert 'id="auth-pwd-change-fields"' in index_html
    assert 'id="change-pwd-old"' in index_html
    assert 'id="change-pwd-new"' in index_html
    assert 'id="change-pwd-confirm"' in index_html
    assert 'openChangePasswordModal()' in index_html
    assert 'doChangePassword()' in index_html

    # 2. 后端 API 接口契约与逻辑验证
    client = TestClient(app)
    # 错误旧密码请求应返回 400
    res = client.post(
        "/api/auth/change_password",
        json={
            "username": "admin",
            "old_password": "wrong_password_xyz",
            "new_password": "new_secret_pwd_888",
            "confirm_password": "new_secret_pwd_888",
        },
    )
    assert res.status_code == 400
    assert "原密码" in res.json().get("detail", "") or "旧密码" in res.json().get("detail", "")
