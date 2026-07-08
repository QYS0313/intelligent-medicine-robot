# 云岐智药：机械臂控制固件

## 模块简介

`dummy-ref-core-fw` 是“云岐智药”系统的机械臂底层控制固件，负责接收上位机控制指令并完成机械臂运动执行。

## 主要功能

- STM32 底层控制
- 机械臂关节运动控制
- 串口通信
- 控制指令解析
- FreeRTOS 任务调度

## 开发环境

- STM32
- C / C++
- STM32 HAL
- FreeRTOS
- STM32CubeIDE

## 使用方法

1. 使用 STM32 开发环境打开工程
2. 根据目标控制板完成编译配置
3. 编译固件
4. 将固件烧录至机械臂控制板
5. 通过串口与 ELFBoard 端通信

## 烧录参考

STM32 固件烧录操作可参考：

[Bilibili：STM32 代码烧录教程](https://www.bilibili.com/video/BV1vZ421Y77Q/)

> 具体烧录方式请以实际控制板、下载器和接口配置为准。

## 相关模块

- `../robot_m_pc/`：PC 端智能问诊与任务调度
- `../robot_m_elf/`：ELFBoard 视觉识别与机器人控制

## 开源协议

MIT License
