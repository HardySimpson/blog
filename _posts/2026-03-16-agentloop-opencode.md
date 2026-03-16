---
layout: post
title: "OpenCode 学习：AgentLoop 核心代码模块拆解"
date: 2026-03-16 10:00:00 +0800
---

OpenCode学习-AgentLoop核心的代码模块学习




# 为什么要研究AgentLoop、和OpenCode的实现？

对于当前比较火的Agent编程来说，其实底层的逻辑相当的直接了当，就是不断的把问题提给LLM大模型，然后获取答案，并且在这个过程中调用一批工具。

研究就是拆解，去魅，让大家能知道这个所谓的Agent编程，并不神秘，核心的代码可能就几百行，但是充分的把大模型的能力发挥出来，用于支撑所有的业务场景。



# 展示一下循环过程的伪代码

先简单用伪代码显示一下整个AgentLoop的循环过程

``` language

// 通用 agent loop 伪代码（文档讲解用，非仓库真实代码）
async function agentLoop(task: string, tools: Tool[]): Promise<string> {
  let context = { task, history: [], step: 0 };
  // 循环直到任务完成/达到最大步数
  while (!isTaskCompleted(context) && context.step < MAX_STEPS) {
    context.step += 1;
    
    // 1. 思考：基于上下文选择下一步行动（核心：LLM 决策）
    const action = await llm.predict({
      prompt: `基于任务${context.task}和历史记录${context.history}，选择行动：调用工具/直接回答`,
      tools: tools.map(t => t.metadata), // 传入工具元信息供 LLM 选择
    });

    // 2. 执行：调用工具或直接输出
    let result: string;
    if (action.type === "tool") {
      const tool = tools.find(t => t.name === action.toolName);
      result = await tool.execute(action.params); // 工具调用
    } else {
      result = action.answer; // 直接回答
    }

    // 3. 反馈：将结果加入上下文
    context.history.push({ action, result });
  }
  return context.history.at(-1)?.result || "任务未完成";
}
```

对于OpenCode这个项目来说，其核心的AgentLoop的代码，在这个位置附近[https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/prompt.ts#L280](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/prompt.ts#L280)

（以下内容保持与你原始文档一致，可以继续补充/编辑）

