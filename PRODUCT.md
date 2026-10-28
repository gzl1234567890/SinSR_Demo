# Product

## Platform

web

## Purpose

中文课堂展示 SinSR 四倍图像超分辨率。支持真实 GPU 推理、已保存真实结果回放、普通插值、原图上传及完整本地图库。

## Confirmed requirements

- 用户要求 iOS 风格、减少解释文字、移除底部教学说明区。
- 页尾右侧提供 SinSR 官方 GitHub 源代码地址。
- 自带原项目实际提供的 203 张测试图，其他人运行 Demo 无需访问外层论文仓库。
- 所有代码与资源变更只在 sinsr_demo 中；内置论文推理代码保持未经修改。
- 保留当前 RTX 5060 Laptop 8GB 的性能配置；清楚区分回放与实时结果。
- 新增公开测试图片可随源码包分发，上传的私人图片不进入提交包。

## Evidence

本地输入：RealSet65 65 张、RealSR 100 张、RealSet128 目录 38 张。四组精选回放经过真实模型推理。算法与许可归属见 THIRD_PARTY_NOTICES.md。
