import type { Message } from "@langchain/langgraph-sdk";
import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { useEffect, useMemo } from "react";

import {
  Conversation,
  ConversationContent,
} from "@/components/ai-elements/conversation";
import { useI18n } from "@/core/i18n/hooks";
import {
  extractContentFromMessage,
  extractPresentFilesFromMessage,
  extractTextFromMessage,
  groupMessages,
  hasContent,
  hasPresentFiles,
  hasReasoning,
  hasToolCalls,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import type { Subtask } from "@/core/tasks";
import { useUpdateSubtask } from "@/core/tasks/context";
import type { AgentThreadState } from "@/core/threads";
import { cn } from "@/lib/utils";

import { ArtifactFileList } from "../artifacts/artifact-file-list";
import { StreamingIndicator } from "../streaming-indicator";

import { MarkdownContent } from "./markdown-content";
import { MessageGroup } from "./message-group";
import { MessageListItem } from "./message-list-item";
import { MessageTokenUsageList } from "./message-token-usage";
import { MessageListSkeleton } from "./skeleton";
import { SubtaskCard } from "./subtask-card";

export const MESSAGE_LIST_DEFAULT_PADDING_BOTTOM = 160;
export const MESSAGE_LIST_FOLLOWUPS_EXTRA_PADDING_BOTTOM = 80;

function isDelegatedRuntimeTool(toolName: string) {
  return toolName === "invoke_feynman" || toolName === "invoke_acp_agent";
}

type SubtaskUpdate = Partial<Subtask> & { id: string };

function collectSubtaskUpdates(messages: Message[]) {
  const updates: SubtaskUpdate[] = [];

  groupMessages(messages, (group) => {
    if (group.type !== "assistant:subagent") {
      return null;
    }

    for (const message of group.messages) {
      if (message.type === "ai") {
        for (const toolCall of message.tool_calls ?? []) {
          if (toolCall.name === "task") {
            updates.push({
              id: toolCall.id!,
              subagent_type: toolCall.args.subagent_type,
              description: toolCall.args.description,
              prompt: toolCall.args.prompt,
              status: "in_progress",
              runtime: "subagent",
            });
          } else if (toolCall.name === "invoke_feynman") {
            updates.push({
              id: toolCall.id!,
              subagent_type: "feynman",
              runtime: "feynman",
              description: toolCall.args.description,
              prompt: toolCall.args.prompt,
              status: "in_progress",
            });
          } else if (toolCall.name === "invoke_acp_agent") {
            const runtimeKind =
              toolCall.args.agent === "openhands" ? "openhands" : "acp";
            updates.push({
              id: toolCall.id!,
              subagent_type: runtimeKind,
              runtime: runtimeKind,
              description:
                toolCall.args.description ?? `ACP: ${toolCall.args.agent}`,
              prompt: toolCall.args.prompt,
              status: "in_progress",
            });
          }
        }
      } else if (message.type === "tool") {
        const taskId = message.tool_call_id;
        if (taskId) {
          const result = extractTextFromMessage(message);
          if (result.startsWith("Task Succeeded. Result:")) {
            updates.push({
              id: taskId,
              status: "completed",
              result: result.split("Task Succeeded. Result:")[1]?.trim(),
            });
          } else if (result.startsWith("Task failed.")) {
            updates.push({
              id: taskId,
              status: "failed",
              error: result.split("Task failed.")[1]?.trim(),
            });
          } else if (result.startsWith("Task timed out")) {
            updates.push({
              id: taskId,
              status: "failed",
              error: result,
            });
          } else if (
            result.includes("completed.\n\nSummary:") ||
            result.startsWith("Feynman completed.") ||
            result.startsWith("OpenHands completed.") ||
            result.startsWith("acp completed.")
          ) {
            updates.push({
              id: taskId,
              status: "completed",
              result,
            });
          } else if (
            result.startsWith("Feynman failed.") ||
            result.startsWith("OpenHands failed.") ||
            result.includes(" failed.\n\nReason:")
          ) {
            updates.push({
              id: taskId,
              status: "failed",
              error: result,
            });
          } else {
            updates.push({
              id: taskId,
              status: "in_progress",
            });
          }
        }
      }
    }

    return null;
  });

  return updates;
}

export function MessageList({
  className,
  threadId,
  thread,
  paddingBottom = MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
  tokenUsageEnabled = false,
}: {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  paddingBottom?: number;
  tokenUsageEnabled?: boolean;
}) {
  const { t } = useI18n();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(thread.isLoading);
  const updateSubtask = useUpdateSubtask();
  const messages = thread.messages;
  const subtaskUpdates = useMemo(
    () => collectSubtaskUpdates(messages),
    [messages],
  );

  useEffect(() => {
    for (const update of subtaskUpdates) {
      updateSubtask(update);
    }
  }, [subtaskUpdates, updateSubtask]);

  if (thread.isThreadLoading && messages.length === 0) {
    return <MessageListSkeleton />;
  }
  return (
    <Conversation
      className={cn("flex size-full flex-col justify-center", className)}
    >
      <ConversationContent className="mx-auto w-full max-w-(--container-width-md) gap-8 pt-12">
        {groupMessages(messages, (group) => {
          if (group.type === "human" || group.type === "assistant") {
            return group.messages.map((msg) => {
              return (
                <MessageListItem
                  key={`${group.id}/${msg.id}`}
                  message={msg}
                  isLoading={thread.isLoading}
                  threadId={threadId}
                  tokenUsageEnabled={tokenUsageEnabled}
                />
              );
            });
          } else if (group.type === "assistant:clarification") {
            const message = group.messages[0];
            if (message && hasContent(message)) {
              return (
                <div key={group.id} className="w-full">
                  <MarkdownContent
                    content={extractContentFromMessage(message)}
                    isLoading={thread.isLoading}
                    rehypePlugins={rehypePlugins}
                  />
                  <MessageTokenUsageList
                    enabled={tokenUsageEnabled}
                    isLoading={thread.isLoading}
                    messages={group.messages}
                  />
                </div>
              );
            }
            return null;
          } else if (group.type === "assistant:present-files") {
            const files: string[] = [];
            for (const message of group.messages) {
              if (hasPresentFiles(message)) {
                const presentFiles = extractPresentFilesFromMessage(message);
                files.push(...presentFiles);
              }
            }
            return (
              <div className="w-full" key={group.id}>
                {group.messages[0] && hasContent(group.messages[0]) && (
                  <MarkdownContent
                    content={extractContentFromMessage(group.messages[0])}
                    isLoading={thread.isLoading}
                    rehypePlugins={rehypePlugins}
                    className="mb-4"
                  />
                )}
                <ArtifactFileList files={files} threadId={threadId} />
                <MessageTokenUsageList
                  enabled={tokenUsageEnabled}
                  isLoading={thread.isLoading}
                  messages={group.messages}
                />
              </div>
            );
          } else if (group.type === "assistant:subagent") {
            const tasks = new Set<Subtask>();
            for (const message of group.messages) {
              if (message.type === "ai") {
                for (const toolCall of message.tool_calls ?? []) {
                  if (toolCall.name === "task") {
                    const task: Subtask = {
                      id: toolCall.id!,
                      subagent_type: toolCall.args.subagent_type,
                      description: toolCall.args.description,
                      prompt: toolCall.args.prompt,
                      status: "in_progress",
                      runtime: "subagent",
                    };
                    tasks.add(task);
                  } else if (toolCall.name === "invoke_feynman") {
                    const task: Subtask = {
                      id: toolCall.id!,
                      subagent_type: "feynman",
                      runtime: "feynman",
                      description: toolCall.args.description,
                      prompt: toolCall.args.prompt,
                      status: "in_progress",
                    };
                    tasks.add(task);
                  } else if (toolCall.name === "invoke_acp_agent") {
                    const runtimeKind =
                      toolCall.args.agent === "openhands"
                        ? "openhands"
                        : "acp";
                    const task: Subtask = {
                      id: toolCall.id!,
                      subagent_type: runtimeKind,
                      runtime: runtimeKind,
                      description:
                        toolCall.args.description ??
                        `ACP: ${toolCall.args.agent}`,
                      prompt: toolCall.args.prompt,
                      status: "in_progress",
                    };
                    tasks.add(task);
                  }
                }
              }
            }
            const results: React.ReactNode[] = [];
            for (const message of group.messages.filter(
              (message) => message.type === "ai",
            )) {
              if (hasReasoning(message)) {
                results.push(
                  <MessageGroup
                    key={"thinking-group-" + message.id}
                    messages={[message]}
                    isLoading={thread.isLoading}
                  />,
                );
              }
              results.push(
                <div
                  key="subtask-count"
                  className="text-muted-foreground pt-2 text-sm font-normal"
                >
                  {t.subtasks.executing(tasks.size)}
                </div>,
              );
              const taskIds = message.tool_calls
                ?.filter(
                  (toolCall) =>
                    toolCall.name === "task" ||
                    isDelegatedRuntimeTool(toolCall.name),
                )
                .map((toolCall) => toolCall.id);
              for (const taskId of taskIds ?? []) {
                results.push(
                  <SubtaskCard
                    key={"task-group-" + taskId}
                    taskId={taskId!}
                    isLoading={thread.isLoading}
                  />,
                );
              }
            }
            return (
              <div
                key={"subtask-group-" + group.id}
                className="relative z-1 flex flex-col gap-2"
              >
                {results}
                <MessageTokenUsageList
                  enabled={tokenUsageEnabled}
                  isLoading={thread.isLoading}
                  messages={group.messages}
                />
              </div>
            );
          }
          const tokenUsageMessages = group.messages.filter(
            (message) =>
              message.type === "ai" &&
              (hasToolCalls(message) ? true : !hasContent(message)),
          );
          return (
            <div key={"group-" + group.id} className="w-full">
              <MessageGroup
                messages={group.messages}
                isLoading={thread.isLoading}
              />
              <MessageTokenUsageList
                enabled={tokenUsageEnabled}
                isLoading={thread.isLoading}
                messages={tokenUsageMessages}
              />
            </div>
          );
        })}
        {thread.isLoading && <StreamingIndicator className="my-4" />}
        <div style={{ height: `${paddingBottom}px` }} />
      </ConversationContent>
    </Conversation>
  );
}
