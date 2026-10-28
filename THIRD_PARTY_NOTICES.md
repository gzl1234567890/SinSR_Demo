# 第三方代码与素材

## SinSR 论文实现

- 项目：SinSR: Diffusion-Based Image Super-Resolution in a Single Step（CVPR 2024）。
- 原作者：Yufei Wang 等；上游仓库：https://github.com/wyf0912/SinSR。
- 固定版本：`f1735490e980162435391162ddd18c0642327c5b`。
- `vendor/SinSR/` 是该版本未经修改的推理源码子集，不是重新实现或本项目原创算法；原文件的逐项 SHA-256 记录在 `vendor/SinSR/ORIGIN.json`。
- 原始许可为 CC BY-NC-SA 4.0，限非商业学术研究用途；原始许可文字保留在 `LICENSE` 和 `vendor/SinSR/LICENSE`。上游部分代码来自 ResShift，原有文件头和署名保持原样。
- `testdata/` 中的 203 张输入图原样复制自上游测试目录：RealSet65 65 张、RealSR 100 张、RealSet128 目录 38 张。逐文件来源与 SHA-256 在 `testdata/catalog.json` 中，名称中的数字不作为实际文件数量。
- 两个模型文件从 SinSR / ResShift 的官方发布地址下载，来源和下载校验值记录在 `weights/download_manifest.json`。

## 本 Demo 新增内容

`app.py`、`demo_backend.py`、`upstream_compat.py`、`demo_static/`、安装与启动脚本、测试和 README 用于课堂演示与复现。兼容层仅在本 Demo 的 Python 进程中生效，不写入或修改上游源码文件。项目随附原始学术使用许可与署名。

## 字体

界面使用访问者设备的系统字体，不附带或下载 Apple 专有字体。
