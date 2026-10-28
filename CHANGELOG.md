# 版本记录

## v1.0.0 · 2026-10-28

SinSR_Demo 首个公开版本，将单步扩散 4× 超分辨率整理为可直接操作的本地课堂演示。

- iOS 风格中文界面，支持滑动对比、并排视图、局部放大、全屏展示与 PNG 下载。
- 内置 RealSet65、RealSR、RealSet128 共 203 张测试图，支持分组、搜索和分页选择。
- NVIDIA GPU 实时推理，附带四组真实 SinSR 结果，支持 CPU 离线回放。
- 提供 Windows 配置与启动脚本、模型自动下载、15 项自动测试和来源校验。

### 下载与运行

下载本版本附件 **sinsr_demo_source.zip**，解压并按照 [README](https://github.com/gzl1234567890/SinSR_Demo/blob/v1.0.0/README.md) 配置 Python 3.10 环境。

- CPU 回放：`setup_demo.ps1 -CpuOnly`，随后运行 `python app.py`。
- GPU 实时演示：`setup_demo.ps1`，随后运行 `python app.py --prepare` 和 `python app.py`。

源码包包含全部测试图与四组真实回放结果。GPU 模型通过配置说明中的官方地址下载至本地 `weights/`。

算法基于 [SinSR](https://github.com/wyf0912/SinSR)（CVPR 2024），保留项目许可证与第三方署名。
