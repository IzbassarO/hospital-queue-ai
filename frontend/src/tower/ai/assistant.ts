/**
 * AI assistant layer of the browser: the request goes to the backend proxy (`POST /api/v1/assistant`), which holds
 * the provider key and the system prompt. Nothing here talks to a provider directly.
 */
import type { AssistantRequest } from "../../api/generated";
import { ApiError } from "../../api/client";
import { specialistApi } from "../../api/specialist";

export type { AssistantRequest };
export interface AssistantReply {
  text: string;
  /** false when the server has no provider configured and answered with the stub text */
  connected: boolean;
  provider?: string;
  model?: string;
}

export async function askAssistant(
  request: AssistantRequest,
  stubText: string,
): Promise<AssistantReply> {
  try {
    const reply = await specialistApi.ask(request);
    return {
      text: reply.text,
      connected: true,
      provider: reply.provider,
      model: reply.model,
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 503)
      return { text: stubText, connected: false };
    throw error;
  }
}
