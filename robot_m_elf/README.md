# 岐黄智取：ELFBoard 视觉识别与机器人控制系统

## 模块简介

`robot_m_elf` 是“岐黄智取”系统的边缘计算与机器人控制模块，运行于 ELFBoard 平台。

该模块负责接收 PC 端任务，完成相机采集、药品识别、目标定位，并控制机械臂执行抓取。

## 主要功能

- 接收 PC 端抓取任务
- RealSense 相机图像采集
- RKNN 模型推理
- 药品识别与目标定位
- 机械臂通信与控制
- 抓取状态返回
- HTTP 服务接口

## 运行环境

- ELFBoard
- Linux
- Python 3.x
- RKNN Runtime
- RealSense Camera
- Serial Communication

## 模型文件

药品识别模型位于：

```text
models/
```

例如：

```text
best_fp.rknn
medicine_fp.rknn
```

## 启动

进入 ELFBoard 端目录：

```bash
cd robot_m_elf
```

根据实际运行环境安装依赖后，启动对应机器人服务程序。

## 工作流程

接收 PC 端任务  
↓  
相机采集图像  
↓  
RKNN 模型识别药品  
↓  
目标定位  
↓  
生成抓取任务  
↓  
机械臂执行抓取  
↓  
返回执行状态  

## 相关模块

- `../robot_m_pc/`：PC 端智能问诊与任务调度
- `../dummy-ref-core-fw/`：机械臂 STM32 固件

## 开源协议

MIT License
