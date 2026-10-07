# SPDX-License-Identifier: BUSL-1.1
"""平台采集器注册：import 本包即加载全部平台模块（触发 @register）。

加新平台：新建 collectors/<平台码>.py，实现 PlatformCollector 并加 @register，
然后在下面加一行 import。
"""

from studio.hot.base import register  # noqa: F401

# 热榜类
from . import baidu  # noqa: F401
from . import douyin  # noqa: F401
from . import tieba  # noqa: F401
from . import toutiao  # noqa: F401
from . import weibo  # noqa: F401
# 社区类
from . import bilibili  # noqa: F401
from . import csdn  # noqa: F401
from . import juejin  # noqa: F401
# 科技媒体类
from . import ifanr  # noqa: F401
from . import ithome  # noqa: F401
from . import kr36  # noqa: F401
from . import solidot  # noqa: F401
from . import sspai  # noqa: F401
from . import weixin  # noqa: F401 需 WECHAT_RSS_FEEDS
from . import xiaohongshu  # noqa: F401 需 XHS_COOKIE
# 新闻类
from . import douban  # noqa: F401
from . import netease  # noqa: F401
from . import qqnews  # noqa: F401
from . import sina  # noqa: F401
from . import thepaper  # noqa: F401
from . import wallstreetcn  # noqa: F401
# 海外类
from . import github  # noqa: F401
from . import hackernews  # noqa: F401
from . import youtube  # noqa: F401 需 YOUTUBE_API_KEY / yt-dlp / RSS
