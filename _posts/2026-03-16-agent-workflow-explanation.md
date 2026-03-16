---
layout: post
title: "OpenCode 学习：Agent工作流程通俗解释"
date: 2026-03-16 16:24:00 +0800
---

## 概述：Agent就像你的技术项目经理

想象一下你要装修房子，但你不懂装修技术。这时候你需要一个项目经理来帮你：

- **你（用户）**：提出需求（"我想把客厅刷成蓝色"）
- **项目经理（Agent）**：理解需求、协调资源、监督执行
- **设计师（LLM）**：提供专业方案和建议
- **施工队（工具）**：具体执行工作

## 完整工作流程

### 1. 需求接收阶段

**用户输入**："给登录功能添加验证码"

**Agent的工作**：
- 记录用户需求
- 创建会话（就像开一个项目会议）
- 准备项目背景资料

### 2. 项目分析阶段

**Agent开始调研**：
- 查看项目结构（就像查看户型图）
- 找到相关文件（找到需要装修的房间）
- 分析现有代码（了解当前的装修风格）

### 3. 咨询专家阶段

**Agent找LLM设计师沟通**：
```
"客户需求：给登录功能添加验证码
项目情况：
- 技术栈：React + Node.js
- 登录文件：src/login.tsx
- 现有逻辑：用户名密码验证
- 要求：添加图形验证码，确保安全性"
```

**LLM设计师回复**：
```
"推荐方案：
1. 使用svg-captcha库生成验证码
2. 前端添加验证码输入框
3. 后端验证验证码正确性
4. 具体修改文件：
   - login.tsx：添加验证码UI
   - auth.ts：添加验证逻辑
   - routes/login.ts：更新登录接口"
```

### 4. 执行实施阶段

**Agent协调施工队（工具）**：

1. **准备材料**：安装svg-captcha库
   ```bash
   npm install svg-captcha
   ```

2. **修改前端**：在login.tsx添加验证码输入框
   ```typescript
   // 添加验证码输入框
   <input type="text" placeholder="请输入验证码" />
   <img src="/api/captcha" alt="验证码" />
   ```

3. **修改后端**：在auth.ts添加验证逻辑
   ```typescript
   // 验证验证码
   if (!validateCaptcha(input.captcha, session.captcha)) {
     throw new Error("验证码错误");
   }
   ```

4. **更新接口**：在routes/login.ts添加验证码生成接口

### 5. 质量检查阶段

**Agent进行测试**：
- 检查代码语法是否正确
- 运行测试用例
- 验证功能是否正常

### 6. 交付汇报阶段

**Agent向用户汇报**：
```
"验证码功能已成功添加！

完成的工作：
✅ 安装了svg-captcha库
✅ 修改了login.tsx，添加了验证码UI
✅ 更新了auth.ts，添加了验证逻辑
✅ 创建了验证码生成接口
✅ 所有测试通过

修改了3个文件，新增了25行代码
功能已可正常使用！"
```

## 实际代码示例

### Agent的核心循环逻辑（简化版）

```typescript
// 项目经理的主循环
async function projectManagerLoop(userRequest: string) {
  // 1. 理解用户需求
  const requirement = understandRequirement(userRequest);
  
  // 2. 分析项目现状
  const projectContext = analyzeProject();
  
  // 3. 咨询LLM专家
  const expertAdvice = await consultLLM(requirement, projectContext);
  
  // 4. 制定执行计划
  const plan = createExecutionPlan(expertAdvice);
  
  // 5. 协调工具执行
  const results = await executeWithTools(plan);
  
  // 6. 验证和汇报
  return reportResults(results);
}
```

### 工具调用的比喻

| 工具类型 | 比喻 | 作用 |
|---------|------|------|
| 文件读取工具 | 查看图纸 | 读取代码文件内容 |
| 文件编辑工具 | 施工队 | 修改代码文件 |
| 命令执行工具 | 电动工具 | 运行命令、安装依赖 |
| 测试工具 | 质量检测 | 验证代码正确性 |

## 为什么这个流程有效？

### 分工明确
- **用户**：只需要说"想要什么"（业务需求）
- **Agent**：负责"怎么实现"（技术协调）
- **LLM**：提供"专业建议"（技术方案）
- **工具**：执行"具体操作"（代码修改）

### 风险控制
- Agent会检查每一步是否正确
- 遇到问题及时反馈和调整
- 确保最终结果符合预期

### 效率提升
- 用户不用学习复杂的技术细节
- 自动化执行重复性工作
- 多轮对话确保需求理解准确

## 总结

Agent工作流程的核心思想是：**将人类的高层需求，通过智能协调和工具调用，转化为具体的代码实现**。

就像你不会亲自去刷墙，而是找项目经理来协调一样，你也不需要亲自写代码，而是让Agent来帮你把想法变成现实！

---

*本文档基于 OpenCode 项目的 prompt.ts 文件分析编写*