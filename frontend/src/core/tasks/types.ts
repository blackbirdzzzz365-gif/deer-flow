import type { AIMessage } from "@langchain/langgraph-sdk";

export interface Subtask {
  id: string;
  status: "in_progress" | "completed" | "failed";
  subagent_type: string;
  description: string;
  latestMessage?: AIMessage;
  latestText?: string;
  prompt: string;
  result?: string;
  error?: string;
  runtime?: "subagent" | "openhands" | "feynman" | "acp";
  runId?: string;
  artifacts?: string[];
  resultFile?: string;
}
