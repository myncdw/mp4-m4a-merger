"""ui 子包：GUI 相关模块。

对外仅承诺 MediaMergerApp 这一公共接口，theme/app 的实现细节
不被视为公共 API，可按需调整。
"""
from ui.app import MediaMergerApp

__all__ = ["MediaMergerApp"]
