---
layout: post
title: "OpenCode 学习：AgentLoop 核心代码模块拆解"
date: 2026-03-16 10:00:00 +0800
---

Sign-off-by: 难易
Assisted-by: OpenClaw:minimax/M2.7

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




# loop 函数核心逻辑讲解
loop 函数是整个 agent 系统的核心，负责协调用户消息、模型调用、工具执行和会话管理等关键流程。以下是其核心逻辑的详细讲解：

## 1. 初始化与会话管理
```
// 解构输入参数
const { sessionID, resume_existing } =
input

// 初始化或恢复会话状态
const abort = resume_existing ? resume
(sessionID) : start(sessionID)

// 如果会话已经在运行中，返回一个 Promise，等待
会话完成
if (!abort) {
  return new Promise<messagev2.withparts>
  ((resolve, reject) => {
  const callbacks = state()[sessionID].
  callbacks
  callbacks.push({ resolve, reject })
  })
}

// 使用 defer 确保会话结束时取消状态
using _ = defer(() => cancel(sessionID))
```
这部分代码负责初始化或恢复会话状态，确保同一时间只有一个实例在运行，并设置资源清理机制。

## 2. 主循环结构
```
let step = 0
const session = await Session.get
(sessionID)

while (true) {
  SessionStatus.set(sessionID, { type: 
  "busy" })
  log.info("loop", { step, sessionID })
  
  if (abort.aborted) break
  let msgs = await MessageV2.
  filterCompacted(MessageV2.stream
  (sessionID))
  
  // 消息处理...
  
  step++
  
  // 核心处理逻辑...
}
```
主循环持续运行，直到满足退出条件，每次循环处理一轮消息和任务。

## 3. 消息处理与任务识别
```
let lastUser: MessageV2.User | 
undefined          // 最后一个用户消息
let lastAssistant: MessageV2.Assistant | 
undefined   // 最后一个助手消息
let lastFinished: MessageV2.Assistant | 
undefined      // 最后一个已完成的助手消息
let tasks: (MessageV2.CompactionPart | 
MessageV2.SubtaskPart)[] = []  // 任务列表

// 从后向前遍历消息，找到相关消息和任务
for (let i = msgs.length - 1; i >= 0; 
i--) {
  const msg = msgs[i]
  // 找到最后一个用户消息
  if (!lastUser && msg.info.role === 
  "user") lastUser = msg.info as 
  MessageV2.User
  // 找到最后一个助手消息
  if (!lastAssistant && msg.info.role === 
  "assistant") lastAssistant = msg.info 
  as MessageV2.Assistant
  // 找到最后一个已完成的助手消息
  if (!lastFinished && msg.info.role === 
  "assistant" && msg.info.finish)
  lastFinished = msg.info as MessageV2.
  Assistant
  // 如果已经找到用户消息和已完成的助手消息，退出
  循环
  if (lastUser && lastFinished) break
  // 收集任务（压缩任务或子任务）
  const task = msg.parts.filter((part) => 
  part.type === "compaction" || part.type 
  === "subtask")
  if (task && !lastFinished) {
  tasks.push(...task)
  }
}
```
这部分代码从消息流中识别关键消息和任务，为后续处理做准备。

## 4. 任务处理
### 4.1 子任务处理
```
if (task?.type === "subtask") {
  // 初始化任务工具
  const taskTool = await TaskTool.init()
  // 获取任务模型
  const taskModel = task.model ? await 
  Provider.getModel(task.model.
  providerID, task.model.modelID) : model
  
  // 创建助手消息和工具部分
  // 执行任务工具
  // 处理任务结果
  // 更新消息状态
  
  continue
}
```
子任务处理负责执行子代理任务，包括初始化工具、创建消息、执行任务、处理结果等步骤。

### 4.2 压缩任务处理
```
if (task?.type === "compaction") {
  const result = await SessionCompaction.
  process({
  messages: msgs,
  parentID: lastUser.id,
  abort,
  sessionID,
  auto: task.auto,
  overflow: task.overflow,
  })
  if (result === "stop") break
  continue
}
```
压缩任务处理负责处理会话消息的压缩，优化消息流。

## 5. 正常处理流程
```
// 正常处理流程
const agent = await Agent.get(lastUser.
agent)
const maxSteps = agent.steps ?? Infinity
const isLastStep = step >= maxSteps

// 插入提醒信息
msgs = await insertReminders({
  messages: msgs,
  agent,
  session,
})

// 创建会话处理器
const processor = SessionProcessor.create
({
  // 配置处理器...
})

// 解析工具
const tools = await resolveTools({
  agent,
  session,
  model,
  tools: lastUser.tools,
  processor,
  bypassAgentCheck,
  messages: msgs,
})

// 构建系统提示
const system = [
  ...(await SystemPrompt.environment
  (model)),
  ...(skills ? [skills] : []),
  ...(await InstructionPrompt.system()),
]

// 处理消息
const result = await processor.process({
  user: lastUser,
  agent,
  abort,
  sessionID,
  system,
  messages: [
  ...MessageV2.toModelMessages(msgs, 
  model),
  ...(isLastStep ? [{ role: "assistant" 
  as const, content: MAX_STEPS }] : []),
  ],
  tools,
  model,
  toolChoice: format.type === 
  "json_schema" ? "required" : undefined,
})
```
正常处理流程是核心部分，包括获取代理信息、解析工具、构建系统提示、调用模型处理消息等步骤。

## 6. 循环退出条件
```
// 检查是否应该退出循环
if (
  lastAssistant?.finish &&
  !["tool-calls", "unknown"].includes
  (lastAssistant.finish) &&
  lastUser.id < lastAssistant.id
) {
  log.info("exiting loop", { sessionID })
  break
}

// 如果捕获到结构化输出，保存并立即退出
if (structuredOutput !== undefined) {
  processor.message.structured = 
  structuredOutput
  processor.message.finish = processor.
  message.finish ?? "stop"
  await Session.updateMessage(processor.
  message)
  break
}

// 检查模型是否完成
const modelFinished = processor.message.
finish && !["tool-calls", "unknown"].
includes(processor.message.finish)

if (modelFinished && !processor.message.
error) {
  if (format.type === "json_schema") {
  // 模型停止但未调用 StructuredOutput 工具
  processor.message.error = new 
  MessageV2.StructuredOutputError({
   message: "Model did not produce 
   structured output",
   retries: 0,
  }).toObject()
  await Session.updateMessage(processor.
  message)
  break
  }
}

// 处理处理器返回的结果
if (result === "stop") break
```
循环退出条件包括：

- 模型已完成且不是工具调用
- 捕获到结构化输出
- 模型完成但未产生结构化输出
- 处理器返回 "stop" 信号
## 7. 清理与返回
```
// 清理会话中的压缩消息
SessionCompaction.prune({ sessionID })

// 找到最后一个助手消息并返回
for await (const item of MessageV2.stream
(sessionID)) {
  if (item.info.role === "user") continue
  const queued = state()[sessionID]?.
  callbacks ?? []
  for (const q of queued) {
  q.resolve(item)
  }
  return item
}
```
最后，清理会话中的压缩消息，并返回最后一个助手消息。

## 核心技术特点
1. 异步处理 ：使用 async/await 处理异步操作，确保代码可读性和可靠性
2. 状态管理 ：通过 state() 函数维护会话状态，确保会话的连续性和一致性
3. 错误处理 ：通过 try/catch 和错误传播机制处理异常情况
4. 工具集成 ：通过 resolveTools 函数集成各种工具，扩展 agent 的能力
5. 权限控制 ：通过 PermissionNext 实现工具调用的权限检查和控制
6. 插件系统 ：通过 Plugin.trigger 集成插件，扩展系统功能
7. 结构化输出 ：支持 JSON schema 格式的结构化输出
8. 会话压缩 ：通过 SessionCompaction 优化消息流，提高系统效率
## 总结
loop 函数是整个 agent 系统的核心，实现了一个完整的循环处理流程，包括消息处理、工具调用、模型交互和会话管理。它通过协调各个组件的工作，确保 agent 能够有效地响应用户请求并执行任务。

这个实现展示了如何构建一个强大的 agent 系统，通过循环处理和状态管理，实现了复杂的任务执行和工具调用功能。它是整个项目的核心部分，为用户提供了智能、高效的交互体验。

# 附录

对这段代码做注释如下

``` language

  /**
   * Agent 核心循环函数
   * 
   * 这是整个 agent 系统的核心函数，负责处理用户消息、调用模型、执行工具、管理会话状态等
   * 循环会持续运行，直到满足退出条件（如模型完成、用户中断等）
   * 
   * @param input - 输入参数，包含会话 ID 和是否恢复现有会话的标志
   * @returns 返回最终的助手消息
   */
  export const loop = fn(LoopInput, async (input) => {
    // 解构输入参数
    const { sessionID, resume_existing } = input

    // 初始化或恢复会话状态
    // 如果是恢复现有会话，则使用 resume 函数
    // 否则，使用 start 函数创建新的会话状态
    const abort = resume_existing ? resume(sessionID) : start(sessionID)
    
    // 如果会话已经在运行中，返回一个 Promise，等待会话完成
    if (!abort) {
      return new Promise<messagev2.withparts>((resolve, reject) => {
        const callbacks = state()[sessionID].callbacks
        callbacks.push({ resolve, reject })
      })
    }

    // 使用 defer 确保会话结束时取消状态
    using _ = defer(() => cancel(sessionID))

    // 结构化输出状态
    // 注意：在会话恢复时，状态会重置，但输出格式会保存在用户消息中
    // 稍后会从 lastUser 中检索
    let structuredOutput: unknown | undefined

    // 步骤计数器，用于跟踪循环执行的次数
    let step = 0
    // 获取会话信息
    const session = await Session.get(sessionID)
    
    // 主循环
    while (true) {
      // 设置会话状态为忙碌
      SessionStatus.set(sessionID, { type: "busy" })
      // 记录循环执行信息
      log.info("loop", { step, sessionID })
      
      // 如果会话被中止，退出循环
      if (abort.aborted) break
      
      // 获取过滤后的消息流（排除已压缩的消息）
      let msgs = await MessageV2.filterCompacted(MessageV2.stream(sessionID))

      // 初始化消息变量
      let lastUser: MessageV2.User | undefined         // 最后一个用户消息
      let lastAssistant: MessageV2.Assistant | undefined   // 最后一个助手消息
      let lastFinished: MessageV2.Assistant | undefined     // 最后一个已完成的助手消息
      let tasks: (MessageV2.CompactionPart | MessageV2.SubtaskPart)[] = []  // 任务列表
      
      // 从后向前遍历消息，找到相关消息和任务
      for (let i = msgs.length - 1; i >= 0; i--) {
        const msg = msgs[i]
        // 找到最后一个用户消息
        if (!lastUser && msg.info.role === "user") lastUser = msg.info as MessageV2.User
        // 找到最后一个助手消息
        if (!lastAssistant && msg.info.role === "assistant") lastAssistant = msg.info as MessageV2.Assistant
        // 找到最后一个已完成的助手消息
        if (!lastFinished && msg.info.role === "assistant" && msg.info.finish)
          lastFinished = msg.info as MessageV2.Assistant
        // 如果已经找到用户消息和已完成的助手消息，退出循环
        if (lastUser && lastFinished) break
        // 收集任务（压缩任务或子任务）
        const task = msg.parts.filter((part) => part.type === "compaction" || part.type === "subtask")
        if (task && !lastFinished) {
          tasks.push(...task)
        }
      }

      // 确保存在用户消息
      if (!lastUser) throw new Error("No user message found in stream. This should never happen.")
      
      // 检查是否应该退出循环
      // 如果最后一个助手消息已完成，且完成原因不是工具调用或未知，且用户消息早于助手消息
      if (
        lastAssistant?.finish &&
        !["tool-calls", "unknown"].includes(lastAssistant.finish) &&
        lastUser.id < lastAssistant.id
      ) {
        log.info("exiting loop", { sessionID })
        break
      }

      // 增加步骤计数
      step++
      
      // 第一步时，确保会话有标题
      if (step === 1)
        ensureTitle({
          session,
          modelID: lastUser.model.modelID,
          providerID: lastUser.model.providerID,
          history: msgs,
        })

      // 获取模型信息
      const model = await Provider.getModel(lastUser.model.providerID, lastUser.model.modelID).catch((e) => {
        // 处理模型未找到的错误
        if (Provider.ModelNotFoundError.isInstance(e)) {
          const hint = e.data.suggestions?.length ? ` Did you mean: ${e.data.suggestions.join(", ")}?` : ""
          Bus.publish(Session.Event.Error, {
            sessionID,
            error: new NamedError.Unknown({
              message: `Model not found: ${e.data.providerID}/${e.data.modelID}.${hint}`,
            }).toObject(),
          })
        }
        throw e
      })
      
      // 取出最后一个任务
      const task = tasks.pop()

      // 处理子任务
      if (task?.type === "subtask") {
        // 初始化任务工具
        const taskTool = await TaskTool.init()
        // 获取任务模型
        const taskModel = task.model ? await Provider.getModel(task.model.providerID, task.model.modelID) : model
        
        // 创建助手消息
        const assistantMessage = (await Session.updateMessage({
          id: MessageID.ascending(),
          role: "assistant",
          parentID: lastUser.id,
          sessionID,
          mode: task.agent,
          agent: task.agent,
          variant: lastUser.variant,
          path: {
            cwd: Instance.directory,
            root: Instance.worktree,
          },
          cost: 0,
          tokens: {
            input: 0,
            output: 0,
            reasoning: 0,
            cache: { read: 0, write: 0 },
          },
          modelID: taskModel.id,
          providerID: taskModel.providerID,
          time: {
            created: Date.now(),
          },
        })) as MessageV2.Assistant
        
        // 创建工具部分
        let part = (await Session.updatePart({
          id: PartID.ascending(),
          messageID: assistantMessage.id,
          sessionID: assistantMessage.sessionID,
          type: "tool",
          callID: ulid(),
          tool: TaskTool.id,
          state: {
            status: "running",
            input: {
              prompt: task.prompt,
              description: task.description,
              subagent_type: task.agent,
              command: task.command,
            },
            time: {
              start: Date.now(),
            },
          },
        })) as MessageV2.ToolPart
        
        // 准备任务参数
        const taskArgs = {
          prompt: task.prompt,
          description: task.description,
          subagent_type: task.agent,
          command: task.command,
        }
        
        // 触发工具执行前的插件钩子
        await Plugin.trigger(
          "tool.execute.before",
          {
            tool: "task",
            sessionID,
            callID: part.id,
          },
          { args: taskArgs },
        )
        
        // 执行任务
        let executionError: Error | undefined
        const taskAgent = await Agent.get(task.agent)
        const taskCtx: Tool.Context = {
          agent: task.agent,
          messageID: assistantMessage.id,
          sessionID: sessionID,
          abort,
          callID: part.callID,
          extra: { bypassAgentCheck: true },
          messages: msgs,
          async metadata(input) {
            part = (await Session.updatePart({
              ...part,
              type: "tool",
              state: {
                ...part.state,
                ...input,
              },
            } satisfies MessageV2.ToolPart)) as MessageV2.ToolPart
          },
          async ask(req) {
            await PermissionNext.ask({
              ...req,
              sessionID: sessionID,
              ruleset: PermissionNext.merge(taskAgent.permission, session.permission ?? []),
            })
          },
        }
        
        // 执行任务工具
        const result = await taskTool.execute(taskArgs, taskCtx).catch((error) => {
          executionError = error
          log.error("subtask execution failed", { error, agent: task.agent, description: task.description })
          return undefined
        })
        
        // 处理任务结果
        const attachments = result?.attachments?.map((attachment) => ({
          ...attachment,
          id: PartID.ascending(),
          sessionID,
          messageID: assistantMessage.id,
        }))
        
        // 触发工具执行后的插件钩子
        await Plugin.trigger(
          "tool.execute.after",
          {
            tool: "task",
            sessionID,
            callID: part.id,
            args: taskArgs,
          },
          result,
        )
        
        // 更新助手消息状态
        assistantMessage.finish = "tool-calls"
        assistantMessage.time.completed = Date.now()
        await Session.updateMessage(assistantMessage)
        
        // 更新工具部分状态
        if (result && part.state.status === "running") {
          await Session.updatePart({
            ...part,
            state: {
              status: "completed",
              input: part.state.input,
              title: result.title,
              metadata: result.metadata,
              output: result.output,
              attachments,
              time: {
                ...part.state.time,
                end: Date.now(),
              },
            },
          } satisfies MessageV2.ToolPart)
        }
        
        // 处理执行失败的情况
        if (!result) {
          await Session.updatePart({
            ...part,
            state: {
              status: "error",
              error: executionError ? `Tool execution failed: ${executionError.message}` : "Tool execution failed",
              time: {
                start: part.state.status === "running" ? part.state.time.start : Date.now(),
                end: Date.now(),
              },
              metadata: "metadata" in part.state ? part.state.metadata : undefined,
              input: part.state.input,
            },
          } satisfies MessageV2.ToolPart)
        }

        // 如果任务包含命令，添加合成用户消息以防止某些推理模型出错
        if (task.command) {
          const summaryUserMsg: MessageV2.User = {
            id: MessageID.ascending(),
            sessionID,
            role: "user",
            time: {
              created: Date.now(),
            },
            agent: lastUser.agent,
            model: lastUser.model,
          }
          await Session.updateMessage(summaryUserMsg)
          await Session.updatePart({
            id: PartID.ascending(),
            messageID: summaryUserMsg.id,
            sessionID,
            type: "text",
            text: "Summarize the task tool output above and continue with your task.",
            synthetic: true,
          } satisfies MessageV2.TextPart)
        }

        // 继续下一次循环
        continue
      }

      // 处理压缩任务
      if (task?.type === "compaction") {
        const result = await SessionCompaction.process({
          messages: msgs,
          parentID: lastUser.id,
          abort,
          sessionID,
          auto: task.auto,
          overflow: task.overflow,
        })
        if (result === "stop") break
        continue
      }

      // 处理上下文溢出，需要压缩
      if (
        lastFinished &&
        lastFinished.summary !== true &&
        (await SessionCompaction.isOverflow({ tokens: lastFinished.tokens, model }))
      ) {
        await SessionCompaction.create({
          sessionID,
          agent: lastUser.agent,
          model: lastUser.model,
          auto: true,
        })
        continue
      }

      // 正常处理流程
      const agent = await Agent.get(lastUser.agent)
      const maxSteps = agent.steps ?? Infinity
      const isLastStep = step >= maxSteps
      
      // 插入提醒信息
      msgs = await insertReminders({
        messages: msgs,
        agent,
        session,
      })

      // 创建会话处理器
      const processor = SessionProcessor.create({
        assistantMessage: (await Session.updateMessage({
          id: MessageID.ascending(),
          parentID: lastUser.id,
          role: "assistant",
          mode: agent.name,
          agent: agent.name,
          variant: lastUser.variant,
          path: {
            cwd: Instance.directory,
            root: Instance.worktree,
          },
          cost: 0,
          tokens: {
            input: 0,
            output: 0,
            reasoning: 0,
            cache: { read: 0, write: 0 },
          },
          modelID: model.id,
          providerID: model.providerID,
          time: {
            created: Date.now(),
          },
          sessionID,
        })) as MessageV2.Assistant,
        sessionID: sessionID,
        model,
        abort,
      })
      
      // 使用 defer 确保指令提示被清除
      using _ = defer(() => InstructionPrompt.clear(processor.message.id))

      // 检查用户是否在本轮明确调用了代理（通过 @ 符号）
      const lastUserMsg = msgs.findLast((m) => m.info.role === "user")
      const bypassAgentCheck = lastUserMsg?.parts.some((p) => p.type === "agent") ?? false

      // 解析工具
      const tools = await resolveTools({
        agent,
        session,
        model,
        tools: lastUser.tools,
        processor,
        bypassAgentCheck,
        messages: msgs,
      })

      // 如果启用了 JSON schema 模式，注入 StructuredOutput 工具
      if (lastUser.format?.type === "json_schema") {
        tools["StructuredOutput"] = createStructuredOutputTool({
          schema: lastUser.format.schema,
          onSuccess(output) {
            structuredOutput = output
          },
        })
      }

      // 第一步时，总结会话
      if (step === 1) {
        SessionSummary.summarize({
          sessionID: sessionID,
          messageID: lastUser.id,
        })
      }

      // 临时包装排队的用户消息，提醒保持专注
      if (step > 1 && lastFinished) {
        for (const msg of msgs) {
          if (msg.info.role !== "user" || msg.info.id <= lastFinished.id) continue
          for (const part of msg.parts) {
            if (part.type !== "text" || part.ignored || part.synthetic) continue
            if (!part.text.trim()) continue
            part.text = [
              "<system-reminder>",
              "The user sent the following message:",
              part.text,
              "",
              "Please address this message and continue with your tasks.",
              "</system-reminder>",
            ].join("\n")
          }
        }
      }

      // 触发消息转换插件钩子
      await Plugin.trigger("experimental.chat.messages.transform", {}, { messages: msgs })

      // 构建系统提示，添加结构化输出指令（如果需要）
      const skills = await SystemPrompt.skills(agent)
      const system = [
        ...(await SystemPrompt.environment(model)),
        ...(skills ? [skills] : []),
        ...(await InstructionPrompt.system()),
      ]
      const format = lastUser.format ?? { type: "text" }
      if (format.type === "json_schema") {
        system.push(STRUCTURED_OUTPUT_SYSTEM_PROMPT)
      }

      // 处理消息
      const result = await processor.process({
        user: lastUser,
        agent,
        abort,
        sessionID,
        system,
        messages: [
          ...MessageV2.toModelMessages(msgs, model),
          ...(isLastStep
            ? [
                {
                  role: "assistant" as const,
                  content: MAX_STEPS,
                },
              ]
            : []),
        ],
        tools,
        model,
        toolChoice: format.type === "json_schema" ? "required" : undefined,
      })

      // 如果捕获到结构化输出，保存并立即退出
      // 这具有优先级，因为 StructuredOutput 工具已成功调用
      if (structuredOutput !== undefined) {
        processor.message.structured = structuredOutput
        processor.message.finish = processor.message.finish ?? "stop"
        await Session.updateMessage(processor.message)
        break
      }

      // 检查模型是否完成（完成原因不是 "tool-calls" 或 "unknown"）
      const modelFinished = processor.message.finish && !["tool-calls", "unknown"].includes(processor.message.finish)

      // 处理模型完成的情况
      if (modelFinished && !processor.message.error) {
        if (format.type === "json_schema") {
          // 模型停止但未调用 StructuredOutput 工具
          processor.message.error = new MessageV2.StructuredOutputError({
            message: "Model did not produce structured output",
            retries: 0,
          }).toObject()
          await Session.updateMessage(processor.message)
          break
        }
      }

      // 处理处理器返回的结果
      if (result === "stop") break
      if (result === "compact") {
        await SessionCompaction.create({
          sessionID: sessionID,
          agent: lastUser.agent,
          model: lastUser.model,
          auto: true,
          overflow: !processor.message.finish,
        })
      }
      continue
    }
    
    // 清理会话中的压缩消息
    SessionCompaction.prune({ sessionID })
    
    // 找到最后一个助手消息并返回
    for await (const item of MessageV2.stream(sessionID)) {
      if (item.info.role === "user") continue
      const queued = state()[sessionID]?.callbacks ?? []
      for (const q of queued) {
        q.resolve(item)
      }
      return item
    }
    throw new Error("Impossible")
  })


```
